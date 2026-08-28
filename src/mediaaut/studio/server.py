"""Console locale de mise en ligne.

Tant que l'audit YouTube n'est pas accorde, `videos.insert` verrouille toute
video en prive de facon definitive. La seule voie qui produit une video
publique est la mise en ligne par le site, a la main.

Cette console ne contourne pas cette regle : elle reduit le geste manuel a
son minimum. Le fichier est pret, les metadonnees sont a un clic du
presse-papiers, et l'etat est enregistre pour que la file se vide dans
l'ordre. Le televersement lui-meme reste fait par un humain sur youtube.com.

Le serveur n'ecoute que sur la boucle locale : il lit des chemins du disque
et ouvre l'explorateur de fichiers, deux capacites qui n'ont rien a faire
sur une interface exposee au reseau.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mediaaut.core.db import record_publication
from mediaaut.core.logging import get_logger
from mediaaut.studio.jobs import MANUAL_YOUTUBE, pending

log = get_logger(__name__)

PAGE = Path(__file__).with_name("page.html")
HOST = "127.0.0.1"


def _reveal(path: Path) -> None:
    """Ouvre le dossier contenant `path` dans l'explorateur du systeme."""
    target = path if path.is_dir() else path.parent
    try:
        if os.name == "nt":
            # `explorer /select,` met le fichier en surbrillance ; il renvoie
            # un code non nul meme en cas de succes, d'ou l'absence de check.
            subprocess.run(["explorer", "/select,", str(path)], check=False)
        elif os.uname().sysname == "Darwin":
            subprocess.run(["open", "-R", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(target)], check=False)
    except OSError as exc:
        log.warning("ouverture de %s impossible : %s", target, exc)


class Handler(BaseHTTPRequestHandler):
    channel_id: str | None = None

    # Le journal par defaut ecrit une ligne par requete sur stderr, ce qui
    # noie la sortie du CLI sans rien apporter.
    def log_message(self, *args) -> None:
        return

    # -- helpers ---------------------------------------------------------
    def _send(self, code: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: object, code: int = HTTPStatus.OK) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _jobs(self) -> list:
        return [
            {
                "job_id": job.job_id,
                "channel_id": job.channel_id,
                "title": job.title,
                "description": job.description,
                "tags": job.tags,
                "hashtags": job.hashtags,
                "script": job.script,
                "duration": round(job.duration, 1),
                "template": job.template,
                "size_mb": round(job.size_mb, 1),
                "created_at": job.created_at,
            }
            for job in pending(self.channel_id)
        ]

    def _find(self, job_id: str):
        return next((j for j in pending(self.channel_id) if j.job_id == job_id), None)

    # -- routes ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - impose par BaseHTTPRequestHandler
        route = urlparse(self.path)

        if route.path == "/":
            self._send(HTTPStatus.OK, PAGE.read_bytes(), "text/html; charset=utf-8")
            return

        if route.path == "/api/pending":
            self._json({"jobs": self._jobs()})
            return

        if route.path.startswith("/media/"):
            job = self._find(route.path[len("/media/") :])
            if job is None or not job.video_path.exists():
                self._json({"error": "introuvable"}, HTTPStatus.NOT_FOUND)
                return
            # Lecture integrale : les shorts pesent quelques mega-octets, la
            # gestion des requetes partielles ne se justifie pas ici.
            self._send(HTTPStatus.OK, job.video_path.read_bytes(), "video/mp4")
            return

        self._json({"error": "route inconnue"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - impose par BaseHTTPRequestHandler
        route = urlparse(self.path)
        job_id = parse_qs(route.query).get("job", [""])[0]
        job = self._find(job_id)

        if job is None:
            self._json({"error": f"job inconnu ou deja traite : {job_id}"}, HTTPStatus.NOT_FOUND)
            return

        if route.path == "/api/reveal":
            _reveal(job.video_path)
            self._json({"ok": True})
            return

        if route.path == "/api/mark":
            record_publication(
                job_id=job.job_id,
                channel_id=job.channel_id,
                platform=MANUAL_YOUTUBE,
                ok=True,
                visibility="manuel",
                detail="mise en ligne via youtube.com",
            )
            log.info("marque comme mis en ligne : %s", job.job_id)
            self._json({"ok": True, "remaining": len(self._jobs())})
            return

        self._json({"error": "route inconnue"}, HTTPStatus.NOT_FOUND)


def serve(port: int = 8765, channel_id: str | None = None, open_browser: bool = True) -> None:
    """Demarre la console et bloque jusqu'a interruption."""
    Handler.channel_id = channel_id
    server = ThreadingHTTPServer((HOST, port), Handler)
    url = f"http://{HOST}:{port}/"

    count = len(pending(channel_id))
    log.info("console sur %s — %d video(s) en attente", url, count)
    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("console arretee")
    finally:
        server.server_close()
