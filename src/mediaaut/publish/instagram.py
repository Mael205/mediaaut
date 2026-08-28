"""Publication de Reels via l'API Graph d'Instagram.

Seule plateforme des trois ou l'automatisation complete est possible tout de
suite : une application Meta en mode Developpement, plus le role « Instagram
Tester » accorde a son propre compte, suffit a publier. La revue d'application
ne concerne que les comptes qu'on ne possede pas.

La publication se fait en trois temps, imposes par l'API :

1. creation d'un conteneur, en demandant explicitement `upload_type=resumable`
   pour pouvoir envoyer un fichier local. Sans cela l'API exige une URL
   publique, ce qui obligerait a heberger les videos quelque part ;
2. envoi du binaire sur `rupload.facebook.com`, un hote distinct du reste de
   l'API ;
3. attente de la fin du transcodage, puis publication. L'etape d'attente n'est
   pas optionnelle : publier un conteneur encore en cours echoue.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from mediaaut.core.config import get_settings
from mediaaut.core.logging import get_logger
from mediaaut.publish.base import PublishResult, VideoMeta, truncate

log = get_logger(__name__)

API_VERSION = "v23.0"
GRAPH = f"https://graph.facebook.com/{API_VERSION}"
RUPLOAD = f"https://rupload.facebook.com/ig-api-upload/{API_VERSION}"

CAPTION_LIMIT = 2200
# Instagram compte les hashtags de la legende ; au-dela de 30 le post est refuse.
HASHTAG_LIMIT = 30

# Le transcodage prend de quelques secondes a plus d'une minute selon la duree.
_POLL_INTERVAL = 4.0
_POLL_TIMEOUT = 300.0


class InstagramPublisher:
    name = "instagram"

    def __init__(self, channel_id: str | None = None) -> None:
        self.channel_id = channel_id
        settings = get_settings()
        self.user_id = settings.ig_user_id
        self.token = settings.ig_access_token

    # -- authentification ------------------------------------------------
    def check_auth(self) -> tuple[bool, str]:
        if not self.user_id or not self.token:
            return False, "IG_USER_ID ou IG_ACCESS_TOKEN absent de .env"
        try:
            response = httpx.get(
                f"{GRAPH}/{self.user_id}",
                params={"fields": "username,media_count", "access_token": self.token},
                timeout=20,
            )
        except httpx.HTTPError as exc:
            return False, f"reseau : {exc}"

        if response.status_code != 200:
            return False, self._explain(response)
        data = response.json()
        return True, f"@{data.get('username', '?')} ({data.get('media_count', 0)} publications)"

    # -- publication -----------------------------------------------------
    def _caption(self, meta: VideoMeta) -> str:
        """Assemble la legende : description puis hashtags, dans la limite."""
        tags = [f"#{t.replace(' ', '').replace('#', '')}" for t in meta.tags][:HASHTAG_LIMIT]
        caption = meta.description.strip()
        if tags:
            caption = f"{caption}\n\n{' '.join(tags)}".strip()
        return truncate(caption, CAPTION_LIMIT)

    def _create_container(self, meta: VideoMeta) -> str:
        response = httpx.post(
            f"{GRAPH}/{self.user_id}/media",
            data={
                "media_type": "REELS",
                "upload_type": "resumable",
                "caption": self._caption(meta),
                "share_to_feed": "true",
                "access_token": self.token,
            },
            timeout=60,
        )
        if response.status_code != 200:
            raise RuntimeError(self._explain(response))
        container_id = response.json().get("id")
        if not container_id:
            raise RuntimeError(f"conteneur sans identifiant : {response.text[:200]}")
        return container_id

    def _upload(self, container_id: str, video: Path) -> None:
        size = video.stat().st_size
        log.info("envoi du binaire (%.1f Mo)", size / 1e6)
        response = httpx.post(
            f"{RUPLOAD}/{container_id}",
            headers={
                "Authorization": f"OAuth {self.token}",
                "offset": "0",
                "file_size": str(size),
                "Content-Type": "application/octet-stream",
            },
            content=video.read_bytes(),
            timeout=600,
        )
        if response.status_code != 200:
            raise RuntimeError(f"envoi refuse ({response.status_code}) : {response.text[:200]}")

    def _wait_ready(self, container_id: str) -> None:
        """Attend la fin du transcodage. Publier trop tot echoue."""
        deadline = time.monotonic() + _POLL_TIMEOUT
        while time.monotonic() < deadline:
            response = httpx.get(
                f"{GRAPH}/{container_id}",
                params={"fields": "status_code,status", "access_token": self.token},
                timeout=30,
            )
            status = response.json().get("status_code", "")
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise RuntimeError(
                    f"transcodage echoue : {response.json().get('status', 'sans detail')}"
                )
            log.debug("conteneur %s : %s", container_id, status or "en attente")
            time.sleep(_POLL_INTERVAL)
        raise RuntimeError(f"transcodage toujours en cours apres {_POLL_TIMEOUT:.0f}s")

    def publish(self, video: Path, meta: VideoMeta) -> PublishResult:
        if not video.exists():
            return PublishResult(self.name, False, detail=f"fichier introuvable : {video}")

        ok, message = self.check_auth()
        if not ok:
            return PublishResult(self.name, False, detail=message)

        try:
            container_id = self._create_container(meta)
            log.info("conteneur Instagram %s", container_id)
            self._upload(container_id, video)
            self._wait_ready(container_id)

            response = httpx.post(
                f"{GRAPH}/{self.user_id}/media_publish",
                data={"creation_id": container_id, "access_token": self.token},
                timeout=120,
            )
            if response.status_code != 200:
                return PublishResult(self.name, False, detail=self._explain(response))
        except (RuntimeError, httpx.HTTPError) as exc:
            return PublishResult(self.name, False, detail=str(exc))

        media_id = response.json().get("id", "")
        log.info("Reel publie : %s", media_id)
        return PublishResult(
            platform=self.name,
            ok=True,
            video_id=media_id,
            url=f"https://www.instagram.com/reel/{media_id}/",
            visibility="public",
        )

    def _explain(self, response: httpx.Response) -> str:
        """Traduit une erreur Graph en message actionnable."""
        try:
            error = response.json().get("error", {})
        except ValueError:
            return f"HTTP {response.status_code} : {response.text[:160]}"

        code = error.get("code")
        message = error.get("message", "")
        hints = {
            190: "jeton expire ou revoque ; regenerer un jeton longue duree.",
            10: "permission manquante : verifier instagram_content_publish et le "
                "role « Instagram Tester » sur le compte.",
            100: "parametre invalide, ou le compte n'est pas un compte professionnel "
                 "lie a une Page Facebook.",
            4: "limite de frequence atteinte ; l'API plafonne les publications par 24 h.",
        }
        return f"{code} : {hints.get(code, message)[:200]}"
