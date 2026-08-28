"""Mises en page des shorts.

Chaque template decrit une disposition visuelle differente. La rotation
entre templates n'est pas cosmetique : la politique YouTube « Inauthentic
Content » vise explicitement le contenu « qui semble fait avec un modele,
avec peu ou pas de variation d'une video a l'autre ». Deux videos
consecutives d'une meme chaine ne doivent donc jamais partager la meme
composition.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(slots=True)
class Template:
    name: str
    subtitle_style: str          # preset de mediaaut.subtitles.ass_writer
    # Position verticale du bloc de sous-titres, en fraction de la hauteur,
    # mesuree depuis le bas. 0.5 = milieu de l'ecran.
    subtitle_anchor: float
    max_chars: int
    # Fraction de la hauteur occupee par le b-roll (1.0 = plein cadre).
    video_fraction: float = 1.0
    # Couleur du fond visible quand le b-roll n'occupe pas tout le cadre.
    backdrop: str = "0F1117"
    zoom: float = 1.0            # zoom lent de bout en bout (1.0 = aucun)


TEMPLATES: dict[str, Template] = {
    # Texte massif au centre : maximise la retention, cache peu de b-roll.
    "bold_center": Template(
        name="bold_center", subtitle_style="pop", subtitle_anchor=0.46,
        max_chars=13, zoom=1.12,
    ),
    # Legende basse classique : laisse respirer l'image.
    "side_caption": Template(
        name="side_caption", subtitle_style="boxed", subtitle_anchor=0.22,
        max_chars=20, zoom=1.06,
    ),
    # B-roll en haut, texte sur aplat en bas : lisible sur images chargees.
    "split_top": Template(
        name="split_top", subtitle_style="clean", subtitle_anchor=0.16,
        max_chars=18, video_fraction=0.62, backdrop="101826", zoom=1.0,
    ),
}


def get_template(name: str) -> Template:
    if name not in TEMPLATES:
        raise KeyError(f"template inconnu : {name} ({', '.join(TEMPLATES)})")
    return TEMPLATES[name]


def pick_template(candidates: list[str], seed: str) -> Template:
    """Choisit un template de facon deterministe a partir d'une graine.

    Deterministe pour qu'un meme job rejoue donne le meme rendu, mais
    reparti sur l'ensemble des candidats d'un job a l'autre. La graine est
    typiquement l'identifiant du job.
    """
    if not candidates:
        raise ValueError("aucun template candidat")
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return get_template(candidates[digest[0] % len(candidates)])
