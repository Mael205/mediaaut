"""Polices embarquees dans le projet.

libass resout les polices par nom via les polices installees sur le systeme.
On ne veut pas dependre de ce qui est installe sur la machine : les polices
sont telechargees dans `data/assets/fonts` et le dossier est passe a ffmpeg
via l'option `fontsdir` du filtre `subtitles`. Le rendu est ainsi identique
sur n'importe quel poste, et une tache planifiee ne depend d'aucun profil
utilisateur.

Montserrat est volontairement absente : le depot Google Fonts ne la publie
plus qu'en police variable, que libass instancie au poids par defaut
(Regular). Le texte sortirait fin la ou on attend un ExtraBold.
"""

from __future__ import annotations

from pathlib import Path

from mediaaut.core.net import download
from mediaaut.core.paths import ASSETS

FONTS_DIR = ASSETS / "fonts"
_GF = "https://raw.githubusercontent.com/google/fonts/main/"

# Nom de famille tel que libass le resoudra -> chemin de telechargement.
CATALOG: dict[str, str] = {
    "Anton": "ofl/anton/Anton-Regular.ttf",
    "Bebas Neue": "ofl/bebasneue/BebasNeue-Regular.ttf",
    "Poppins ExtraBold": "ofl/poppins/Poppins-ExtraBold.ttf",
    # Monospace pour les cartes de code et de terminal. Statique, pas
    # variable : libass et Pillow instancient une police variable au poids
    # par defaut, ce qui donne un rendu plus fin que demande.
    "IBM Plex Mono": "ofl/ibmplexmono/IBMPlexMono-Regular.ttf",
    "IBM Plex Mono SemiBold": "ofl/ibmplexmono/IBMPlexMono-SemiBold.ttf",
}


def font_file(name: str) -> Path:
    """Chemin du .ttf d'une famille, telecharge si besoin.

    Necessaire pour mesurer la largeur reelle d'un texte avant rendu : sans
    les metriques de la police, on ne peut que deviner la taille a appliquer.
    """
    if name not in CATALOG:
        raise KeyError(f"police inconnue : {name} ({', '.join(CATALOG)})")
    filename = CATALOG[name].rsplit("/", 1)[-1]
    return download(_GF + CATALOG[name], FONTS_DIR / filename)


def ensure_fonts(names: list[str] | None = None) -> Path:
    """Telecharge les polices manquantes et retourne le dossier a passer a libass."""
    for name in names or list(CATALOG):
        if name not in CATALOG:
            raise KeyError(f"police inconnue : {name} ({', '.join(CATALOG)})")
        filename = CATALOG[name].rsplit("/", 1)[-1]
        download(_GF + CATALOG[name], FONTS_DIR / filename)
    return FONTS_DIR
