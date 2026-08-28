"""Publication sur YouTube via la Data API v3.

Points structurants, valables en 2026 :

- Depuis le 1er juin 2026, `videos.insert` ne pese plus 1600 unites sur le
  quota general mais 1 unite sur un compteur dedie de 100 appels par jour.
  Le plafond pratique est donc passe d'environ 6 uploads quotidiens a 100.

- Un projet API non audite voit toutes ses videos verrouillees en prive,
  definitivement, quelle que soit la valeur de `privacyStatus` envoyee.
  L'audit se demande par formulaire et il est gratuit. Tant qu'il n'est pas
  accorde, ce module refuse de pretendre qu'une video est publique : il
  relit l'etat reel apres upload et le remonte tel quel.

- L'upload est repris par morceaux. Une coupure reseau sur un fichier de
  plusieurs dizaines de mega-octets ne doit pas obliger a tout refaire.
"""

from __future__ import annotations

import json
import random
import time
from datetime import UTC
from pathlib import Path

from mediaaut.core.config import get_settings
from mediaaut.core.logging import get_logger
from mediaaut.core.paths import ROOT, SECRETS
from mediaaut.publish.base import PublishResult, VideoMeta, truncate

log = get_logger(__name__)

# `youtube.upload` suffit a televerser ; `youtube.readonly` permet de relire
# la video apres coup pour constater sa visibilite reelle.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
TOKEN_PATH = SECRETS / "youtube_token.json"

TITLE_LIMIT = 100
DESCRIPTION_LIMIT = 5000
TAGS_LIMIT = 500          # somme des caracteres de tous les tags

# Erreurs transitoires : on retente avec un recul exponentiel plutot que de
# perdre un upload deja engage.
_RETRIABLE_STATUS = frozenset({500, 502, 503, 504})
_MAX_ATTEMPTS = 5


class YouTubePublisher:
    name = "youtube"

    # -- authentification ------------------------------------------------
    def _client_secrets(self) -> Path:
        path = Path(get_settings().youtube_client_secrets)
        if not path.is_absolute():
            path = ROOT / path
        return path

    def _credentials(self, *, interactive: bool = True):
        """Charge le jeton, le rafraichit, ou lance le consentement OAuth."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None
        if TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save(creds)
                return creds
            except Exception as exc:
                log.warning("rafraichissement du jeton echoue (%s), reconsentement", exc)

        if not interactive:
            raise RuntimeError("jeton YouTube absent ou expire ; lancer `mediaaut auth youtube`")

        secrets_path = self._client_secrets()
        if not secrets_path.exists():
            raise RuntimeError(
                f"fichier client OAuth introuvable : {secrets_path}\n"
                "Le telecharger depuis Google Cloud Console > API et services > "
                "Identifiants > ID client OAuth (type « Application de bureau »)."
            )

        flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
        # `port=0` laisse l'OS choisir un port libre pour la redirection.
        creds = flow.run_local_server(port=0, prompt="consent")
        self._save(creds)
        return creds

    def _save(self, creds) -> None:
        SECRETS.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        log.info("jeton YouTube enregistre dans %s", TOKEN_PATH)

    def _service(self, *, interactive: bool = True):
        from googleapiclient.discovery import build

        return build(
            "youtube", "v3", credentials=self._credentials(interactive=interactive),
            cache_discovery=False,
        )

    def authorize(self) -> tuple[bool, str]:
        """Declenche le consentement OAuth et confirme la chaine ciblee."""
        service = self._service(interactive=True)
        response = service.channels().list(part="snippet", mine=True).execute()
        items = response.get("items", [])
        if not items:
            return False, "authentifie, mais aucune chaine YouTube sur ce compte Google"
        title = items[0]["snippet"]["title"]
        return True, f"connecte a la chaine « {title} » ({items[0]['id']})"

    def check_auth(self) -> tuple[bool, str]:
        if not self._client_secrets().exists():
            return False, f"client OAuth manquant : {self._client_secrets()}"
        if not TOKEN_PATH.exists():
            return False, "pas encore autorise ; lancer `mediaaut auth youtube`"
        try:
            service = self._service(interactive=False)
            items = service.channels().list(part="snippet", mine=True).execute().get("items", [])
        except Exception as exc:
            return False, f"jeton inutilisable : {exc}"
        if not items:
            return False, "aucune chaine sur ce compte"
        return True, f"chaine « {items[0]['snippet']['title']} »"

    # -- publication -----------------------------------------------------
    def _body(self, meta: VideoMeta) -> dict:
        tags: list[str] = []
        budget = TAGS_LIMIT
        for tag in meta.tags:
            if len(tag) + 1 > budget:
                break
            tags.append(tag)
            budget -= len(tag) + 1

        status: dict[str, object] = {
            "privacyStatus": "private" if meta.publish_at else "public",
            "selfDeclaredMadeForKids": meta.made_for_kids,
            "containsSyntheticMedia": meta.synthetic,
        }
        if meta.publish_at:
            moment = meta.publish_at
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            status["publishAt"] = moment.astimezone(UTC).isoformat().replace("+00:00", "Z")

        return {
            "snippet": {
                "title": truncate(meta.title, TITLE_LIMIT),
                "description": truncate(meta.description, DESCRIPTION_LIMIT),
                "tags": tags,
                "categoryId": meta.category_id,
                "defaultLanguage": meta.language,
                "defaultAudioLanguage": meta.language,
            },
            "status": status,
        }

    def publish(self, video: Path, meta: VideoMeta) -> PublishResult:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        if not video.exists():
            return PublishResult(self.name, False, detail=f"fichier introuvable : {video}")

        service = self._service()
        media = MediaFileUpload(
            str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True
        )
        request = service.videos().insert(
            part="snippet,status", body=self._body(meta), media_body=media
        )

        log.info("upload YouTube : %s (%.1f Mo)", video.name, video.stat().st_size / 1e6)
        response = None
        attempt = 0
        last_progress = -10

        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    percent = int(status.progress() * 100)
                    if percent >= last_progress + 10:
                        log.info("  %d%%", percent)
                        last_progress = percent
                attempt = 0
            except HttpError as exc:
                if exc.resp.status not in _RETRIABLE_STATUS:
                    return PublishResult(self.name, False, detail=self._explain(exc))
                attempt += 1
                if attempt >= _MAX_ATTEMPTS:
                    return PublishResult(
                        self.name, False, detail=f"abandon apres {attempt} tentatives : {exc}"
                    )
                delay = min(60, 2**attempt) + random.random()
                log.warning("erreur %s, nouvelle tentative dans %.1fs", exc.resp.status, delay)
                time.sleep(delay)
            except OSError as exc:
                attempt += 1
                if attempt >= _MAX_ATTEMPTS:
                    return PublishResult(self.name, False, detail=f"reseau : {exc}")
                time.sleep(min(60, 2**attempt))

        video_id = response["id"]
        visibility = self._actual_visibility(service, video_id) or response.get(
            "status", {}
        ).get("privacyStatus", "")

        result = PublishResult(
            platform=self.name,
            ok=True,
            video_id=video_id,
            url=f"https://youtu.be/{video_id}",
            visibility=visibility,
            detail="",
        )

        wanted = "private" if meta.publish_at else "public"
        if visibility == "private" and wanted == "public":
            # Symptome caracteristique d'un projet API non audite.
            result.detail = (
                "video verrouillee en prive : le projet API n'est pas audite. "
                "Remplir « YouTube API Services - Audit and Quota Extension Form » "
                "pour lever la restriction. Les videos deja uploadees restent privees."
            )
            log.warning(result.detail)

        log.info("publie : %s (visibilite %s)", result.url, visibility or "inconnue")
        return result

    def _actual_visibility(self, service, video_id: str) -> str:
        """Relit la visibilite reelle apres upload.

        La reponse d'insertion reflete ce qui a ete demande, pas ce que
        YouTube a applique. Sur un projet non audite, l'ecart entre les deux
        est precisement l'information utile.
        """
        try:
            items = (
                service.videos().list(part="status", id=video_id).execute().get("items", [])
            )
            return items[0]["status"]["privacyStatus"] if items else ""
        except Exception as exc:
            log.debug("relecture de la visibilite impossible : %s", exc)
            return ""

    def _explain(self, error) -> str:
        """Traduit une erreur d'API en message actionnable."""
        try:
            payload = json.loads(error.content.decode("utf-8"))
            reason = payload["error"]["errors"][0].get("reason", "")
            message = payload["error"].get("message", str(error))
        except Exception:
            return str(error)

        hints = {
            "quotaExceeded":
                "quota journalier epuise ; il repart a minuit heure du Pacifique.",
            "uploadLimitExceeded":
                "plafond d'uploads du compte atteint pour aujourd'hui.",
            "forbidden":
                "la chaine n'a pas le droit de televerser ; verifier la validation du compte.",
            "youtubeSignupRequired":
                "le compte Google n'a pas de chaine YouTube associee.",
            "invalidCategoryId":
                "categoryId invalide pour cette region.",
            "failedPrecondition":
                "la chaine doit etre verifiee pour televerser des videos longues.",
        }
        return f"{reason or 'erreur'} : {hints.get(reason, message)}"
