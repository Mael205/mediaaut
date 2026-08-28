"""Photographies de banque, avec filtre de pertinence.

Mesure a l'origine de ce module : sur la requete « server room racks », la
recherche video de Pexels rend « une personne prenant un objet dans un bac
de rangement » et « des gens faisant l'inventaire », tandis que la
recherche photo rend six baies de serveurs, cables optiques et armoires
reseau. Le fonds video est petit et mal indexe ; le fonds photo est vaste
et decrit.

Deux consequences exploitees ici :

- **On prend des photos, pas des videos.** Le mouvement vient d'un effet de
  zoom lent applique au montage, technique standard et qui ne ressemble a
  rien de genere puisque l'image est une vraie photographie.
- **On peut filtrer.** Chaque photo porte un texte `alt` descriptif. Une
  image dont la description ne recoupe pas la requete est ecartee, ce qui
  etait impossible sur les videos, depourvues de metadonnees utiles.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from mediaaut.core.config import get_settings
from mediaaut.core.logging import get_logger
from mediaaut.core.net import download
from mediaaut.core.paths import CACHE

log = get_logger(__name__)

PHOTOS_DIR = CACHE / "photos"
_ENDPOINT = "https://api.pexels.com/v1/search"

# Mots trop courants pour porter de la pertinence dans une description.
_STOPWORDS = frozenset(
    """
    a an the of in on at by with and or to for from is are was were be this that
    close up shot view detailed showcasing modern various similar
    """.split()
)

# Recouvrement minimal entre la requete et la description. Regle bas : une
# photo pertinente ne reprend pas forcement les mots exacts de la requete,
# mais une photo hors sujet n'en partage aucun.
MIN_OVERLAP = 0.25


@dataclass(slots=True)
class Photo:
    url: str
    width: int
    height: int
    alt: str
    relevance: float

    def cache_path(self) -> Path:
        digest = hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:16]
        return PHOTOS_DIR / f"pexels-{digest}.jpg"

    def fetch(self) -> Path:
        return download(self.url, self.cache_path())


def _tokens(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z]+", text.lower())
        if w not in _STOPWORDS and len(w) > 2
    }


def relevance(query: str, alt: str) -> float:
    """Part des mots de la requete que la description reprend."""
    wanted = _tokens(query)
    if not wanted:
        return 0.0
    return len(wanted & _tokens(alt)) / len(wanted)


def search(query: str, *, count: int = 8, portrait: bool = True) -> list[Photo]:
    """Photos pertinentes pour une requete, les mieux notees d'abord."""
    key = get_settings().pexels_api_key
    if not key:
        return []

    try:
        response = httpx.get(
            _ENDPOINT,
            headers={"Authorization": key},
            params={
                "query": query,
                # On demande large pour pouvoir jeter : le filtre ecarte
                # souvent plus de la moitie des resultats.
                "per_page": min(count * 5, 60),
                "orientation": "portrait" if portrait else "landscape",
                "size": "large",
            },
            timeout=30,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("recherche photo « %s » echouee : %s", query, exc)
        return []

    scored: list[Photo] = []
    for item in response.json().get("photos", []):
        alt = item.get("alt") or ""
        score = relevance(query, alt)
        if score < MIN_OVERLAP:
            continue
        source = item.get("src", {})
        url = source.get("large2x") or source.get("large") or source.get("original")
        if not url:
            continue
        scored.append(
            Photo(url=url, width=item.get("width", 0), height=item.get("height", 0),
                  alt=alt, relevance=score)
        )

    scored.sort(key=lambda p: -p.relevance)
    log.debug("« %s » : %d photo(s) retenues", query, len(scored))
    return scored[:count]


def find_photos(
    queries: list[str],
    *,
    count: int = 6,
    portrait: bool = True,
) -> list[Path]:
    """Telecharge jusqu'a `count` photos couvrant les mots-cles donnes.

    Les mots-cles sont parcourus a tour de role : epuiser le premier avant
    de passer au suivant donnerait six fois la meme scene.
    """
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    found = {q: search(q, count=count, portrait=portrait) for q in queries}
    if not any(found.values()):
        log.warning("aucune photo pertinente pour %s", ", ".join(queries))
        return []

    selected: list[Photo] = []
    seen: set[str] = set()
    for rank in range(count):
        for query in queries:
            pool = [p for p in found.get(query, []) if p.url not in seen]
            if rank < len(pool) and len(selected) < count:
                chosen = pool[0]
                seen.add(chosen.url)
                selected.append(chosen)

    paths: list[Path] = []
    for photo in selected[:count]:
        try:
            paths.append(photo.fetch())
        except httpx.HTTPError as exc:
            log.warning("telechargement de %s echoue : %s", photo.url, exc)

    if paths:
        average = sum(p.relevance for p in selected[: len(paths)]) / len(paths)
        log.info(
            "photos : %d image(s), pertinence moyenne %.0f%%", len(paths), average * 100
        )
    return paths
