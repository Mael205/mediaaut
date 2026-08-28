"""Envoi vers TikTok par la Content Posting API, mode brouillon.

TikTok distingue deux voies :

- **Direct Post** publie immediatement, mais exige un audit de l'application
  (2 a 4 semaines, plusieurs allers-retours). Tant qu'il n'est pas obtenu,
  chaque publication est forcee en visibilite privee — et l'API ne le signale
  pas : la reponse indique un succes.
- **Inbox / brouillon** depose la video dans les brouillons du compte. Le
  createur termine la publication depuis l'application, en deux gestes. Cette
  voie ne demande aucun audit.

Ce module utilise la seconde. C'est le seul moyen d'obtenir une video
reellement publique sur TikTok sans attendre l'audit, et le geste restant se
compte en secondes. `DIRECT_POST_SCOPE` documente la bascule le jour ou
l'audit est accorde.
"""

from __future__ import annotations

import math
from pathlib import Path

import httpx

from mediaaut.core.config import get_settings
from mediaaut.core.logging import get_logger
from mediaaut.core.paths import SECRETS
from mediaaut.publish.base import PublishResult, VideoMeta

log = get_logger(__name__)

API = "https://open.tiktokapis.com/v2"
INBOX_INIT = f"{API}/post/publish/inbox/video/init/"
STATUS = f"{API}/post/publish/status/fetch/"

# Scope necessaire au depot en brouillon. Le Direct Post demande en plus
# `video.publish`, qui n'est accorde qu'apres audit.
UPLOAD_SCOPE = "video.upload"
DIRECT_POST_SCOPE = "video.publish"

TOKEN_FILE = SECRETS / "tiktok_token.json"

# TikTok impose des morceaux de 5 Mo minimum, sauf pour le dernier.
CHUNK_SIZE = 10 * 1024 * 1024


class TikTokPublisher:
    name = "tiktok"

    def __init__(self, channel_id: str | None = None) -> None:
        self.channel_id = channel_id
        self.settings = get_settings()

    # -- authentification ------------------------------------------------
    def _access_token(self) -> str | None:
        """Jeton d'acces courant, rafraichi si necessaire."""
        import json

        if not TOKEN_FILE.exists():
            return None
        try:
            data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return data.get("access_token")

    def check_auth(self) -> tuple[bool, str]:
        if not self.settings.tiktok_client_key:
            return False, "TIKTOK_CLIENT_KEY absent de .env"
        token = self._access_token()
        if not token:
            return False, f"pas de jeton ; deposer un access_token dans {TOKEN_FILE}"

        try:
            response = httpx.get(
                f"{API}/user/info/",
                headers={"Authorization": f"Bearer {token}"},
                params={"fields": "open_id,display_name"},
                timeout=20,
            )
        except httpx.HTTPError as exc:
            return False, f"reseau : {exc}"

        if response.status_code != 200:
            return False, self._explain(response)
        user = response.json().get("data", {}).get("user", {})
        return True, f"@{user.get('display_name', '?')}"

    # -- publication -----------------------------------------------------
    def publish(self, video: Path, meta: VideoMeta) -> PublishResult:
        """Depose la video dans les brouillons du compte.

        `meta` n'est pas transmis : l'endpoint brouillon n'accepte ni legende
        ni hashtags, le createur les saisit au moment de publier. Le titre est
        malgre tout journalise pour retrouver la correspondance.
        """
        if not video.exists():
            return PublishResult(self.name, False, detail=f"fichier introuvable : {video}")

        token = self._access_token()
        if not token:
            return PublishResult(self.name, False, detail=self.check_auth()[1])

        size = video.stat().st_size
        chunk_size = min(CHUNK_SIZE, size)
        chunks = max(1, math.ceil(size / chunk_size))

        try:
            init = httpx.post(
                INBOX_INIT,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json={
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": size,
                        "chunk_size": chunk_size,
                        "total_chunk_count": chunks,
                    }
                },
                timeout=60,
            )
            if init.status_code != 200:
                return PublishResult(self.name, False, detail=self._explain(init))

            payload = init.json().get("data", {})
            publish_id = payload.get("publish_id", "")
            upload_url = payload.get("upload_url", "")
            if not upload_url:
                return PublishResult(
                    self.name, False, detail=f"reponse sans upload_url : {init.text[:200]}"
                )

            log.info("envoi vers TikTok : %.1f Mo en %d morceau(x)", size / 1e6, chunks)
            self._upload(upload_url, video, size, chunk_size, chunks)
        except (RuntimeError, httpx.HTTPError) as exc:
            return PublishResult(self.name, False, detail=str(exc))

        log.info("brouillon TikTok depose (%s) — a finaliser dans l'application", publish_id)
        return PublishResult(
            platform=self.name,
            ok=True,
            video_id=publish_id,
            url="https://www.tiktok.com/",
            visibility="brouillon",
            detail=(
                f"depose dans les brouillons TikTok sous « {meta.title} ». "
                "Ouvrir l'application, boite de reception, puis publier."
            ),
        )

    def _upload(
        self, upload_url: str, video: Path, size: int, chunk_size: int, chunks: int
    ) -> None:
        """Televerse le fichier par morceaux.

        TikTok exige un en-tete `Content-Range` exact sur chaque morceau ;
        une borne fausse fait echouer tout le transfert.
        """
        with video.open("rb") as handle:
            for index in range(chunks):
                start = index * chunk_size
                # Le dernier morceau absorbe le reste, meme s'il depasse
                # `chunk_size` : TikTok refuse un morceau final trop petit.
                end = size - 1 if index == chunks - 1 else min(start + chunk_size, size) - 1
                handle.seek(start)
                data = handle.read(end - start + 1)

                response = httpx.put(
                    upload_url,
                    headers={
                        "Content-Range": f"bytes {start}-{end}/{size}",
                        "Content-Length": str(len(data)),
                        "Content-Type": "video/mp4",
                    },
                    content=data,
                    timeout=600,
                )
                if response.status_code not in (200, 201, 206):
                    raise RuntimeError(
                        f"morceau {index + 1}/{chunks} refuse "
                        f"({response.status_code}) : {response.text[:160]}"
                    )
                log.debug("morceau %d/%d envoye", index + 1, chunks)

    def _explain(self, response: httpx.Response) -> str:
        try:
            error = response.json().get("error", {})
        except ValueError:
            return f"HTTP {response.status_code} : {response.text[:160]}"

        code = error.get("code", "")
        hints = {
            "access_token_invalid": "jeton invalide ou expire ; en regenerer un.",
            "scope_not_authorized": f"le scope {UPLOAD_SCOPE} n'est pas accorde a l'application.",
            "rate_limit_exceeded": "limite de frequence atteinte.",
            "spam_risk_too_many_posts": "trop de depots recents sur ce compte.",
            "file_format_check_failed": "format refuse ; verifier que le MP4 est en H.264/AAC.",
        }
        return f"{code} : {hints.get(code, error.get('message', ''))[:200]}"
