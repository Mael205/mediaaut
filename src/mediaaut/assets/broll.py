"""Recherche et telechargement de plans de banque libres de droits.

Pexels et Pixabay proposent tous deux une API gratuite, sans quota
journalier bloquant, dont les contenus sont utilisables commercialement
sans attribution obligatoire. Les deux sont interrogeables : si l'un ne
rend rien sur une requete, l'autre prend le relais plutot que de laisser
le rendu sans image.

Les fichiers sont caches sur disque et adresses par empreinte de leur URL,
de sorte qu'un meme plan n'est jamais retelecharge, y compris entre deux
jobs qui partagent un mot-cle.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import httpx

from mediaaut.core.config import get_settings
from mediaaut.core.logging import get_logger
from mediaaut.core.net import download
from mediaaut.core.paths import CACHE

log = get_logger(__name__)

BROLL_DIR = CACHE / "broll"


@dataclass(slots=True)
class BrollClip:
    """Un plan trouve en banque, avant telechargement."""

    url: str
    width: int
    height: int
    duration: float
    source: str
    page_url: str = ""

    @property
    def is_portrait(self) -> bool:
        return self.height >= self.width

    def cache_path(self) -> Path:
        digest = hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:16]
        return BROLL_DIR / f"{self.source}-{digest}.mp4"

    def fetch(self) -> Path:
        return download(self.url, self.cache_path())


class PexelsVideos:
    name = "pexels"
    _ENDPOINT = "https://api.pexels.com/videos/search"

    def search(self, query: str, *, count: int = 8, portrait: bool = True) -> list[BrollClip]:
        key = get_settings().pexels_api_key
        if not key:
            return []

        response = httpx.get(
            self._ENDPOINT,
            headers={"Authorization": key},
            params={
                "query": query,
                "per_page": min(count * 2, 40),
                "orientation": "portrait" if portrait else "landscape",
                "size": "medium",
            },
            timeout=30,
        )
        response.raise_for_status()

        clips: list[BrollClip] = []
        for video in response.json().get("videos", []):
            # `video_files` liste plusieurs rendus ; on prend le plus grand
            # qui reste sous 4K, au-dela le telechargement coute plus qu'il
            # n'apporte a une sortie 1080x1920.
            files = [
                f for f in video.get("video_files", [])
                if f.get("file_type") == "video/mp4" and (f.get("height") or 0) <= 2160
            ]
            if not files:
                continue
            best = max(files, key=lambda f: (f.get("height") or 0))
            clips.append(
                BrollClip(
                    url=best["link"],
                    width=best.get("width") or video.get("width", 0),
                    height=best.get("height") or video.get("height", 0),
                    duration=float(video.get("duration", 0)),
                    source=self.name,
                    page_url=video.get("url", ""),
                )
            )
        return clips


class PixabayVideos:
    name = "pixabay"
    _ENDPOINT = "https://pixabay.com/api/videos/"

    def search(self, query: str, *, count: int = 8, portrait: bool = True) -> list[BrollClip]:
        key = get_settings().pixabay_api_key
        if not key:
            return []

        response = httpx.get(
            self._ENDPOINT,
            params={
                "key": key,
                "q": query,
                "per_page": max(3, min(count * 2, 50)),
                "video_type": "film",
                "safesearch": "true",
            },
            timeout=30,
        )
        response.raise_for_status()

        clips: list[BrollClip] = []
        for hit in response.json().get("hits", []):
            videos = hit.get("videos", {})
            best = videos.get("large") or videos.get("medium") or videos.get("small")
            if not best or not best.get("url"):
                continue
            clips.append(
                BrollClip(
                    url=best["url"],
                    width=best.get("width", 0),
                    height=best.get("height", 0),
                    duration=float(hit.get("duration", 0)),
                    source=self.name,
                    page_url=hit.get("pageURL", ""),
                )
            )
        return clips


PROVIDERS = (PexelsVideos(), PixabayVideos())


def find_broll(
    queries: list[str],
    *,
    count: int = 6,
    portrait: bool = True,
    min_duration: float = 3.0,
) -> list[Path]:
    """Telecharge jusqu'a `count` plans couvrant les mots-cles donnes.

    Les mots-cles sont parcourus a tour de role plutot qu'epuises un par
    un : une video dont tous les plans viennent d'une meme requete montre
    six fois la meme chose.
    """
    BROLL_DIR.mkdir(parents=True, exist_ok=True)

    found: dict[str, list[BrollClip]] = {}
    for query in queries:
        results: list[BrollClip] = []
        for provider in PROVIDERS:
            try:
                results.extend(provider.search(query, count=count, portrait=portrait))
            except httpx.HTTPError as exc:
                log.warning("recherche %s sur %s echouee : %s", query, provider.name, exc)
        found[query] = [c for c in results if c.duration >= min_duration]

    if not any(found.values()):
        log.warning("aucun b-roll trouve pour %s", ", ".join(queries))
        return []

    # Tour de role entre mots-cles, en privilegiant le portrait natif.
    selected: list[BrollClip] = []
    seen: set[str] = set()
    for rank in range(count):
        for query in queries:
            candidates = sorted(
                (c for c in found.get(query, []) if c.url not in seen),
                key=lambda c: (not c.is_portrait, -c.height),
            )
            if rank < len(candidates) and len(selected) < count:
                chosen = candidates[0]
                seen.add(chosen.url)
                selected.append(chosen)

    paths: list[Path] = []
    for clip in selected[:count]:
        try:
            paths.append(clip.fetch())
        except httpx.HTTPError as exc:
            log.warning("telechargement de %s echoue : %s", clip.url, exc)

    log.info("b-roll : %d plan(s) pour %s", len(paths), ", ".join(queries))
    return paths
