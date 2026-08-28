"""Telechargements caches sur disque, avec reprise visible."""

from __future__ import annotations

from pathlib import Path

import httpx

from mediaaut.core.logging import get_logger

log = get_logger(__name__)


def download(url: str, dest: Path, *, force: bool = False, timeout: float = 120.0) -> Path:
    """Telecharge `url` vers `dest` si absent. Retourne le chemin local.

    Ecrit d'abord dans un fichier temporaire pour qu'une interruption ne
    laisse jamais un fichier tronque passer pour un telechargement valide.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force and dest.stat().st_size > 0:
        return dest

    tmp = dest.with_suffix(dest.suffix + ".part")
    log.info("telechargement %s", dest.name)
    with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_bytes(chunk_size=1 << 20):
                handle.write(chunk)
    tmp.replace(dest)
    log.info("%s pret (%.1f Mo)", dest.name, dest.stat().st_size / 1e6)
    return dest
