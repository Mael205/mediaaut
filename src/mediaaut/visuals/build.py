"""Traduction d'un plan visuel en suite de plans montables.

Fait la jonction entre le directeur, qui decide quoi montrer et quand, et
le compositeur, qui ne connait que des plans a enchainer. Les cartes sont
rendues ici, dans le dossier du job, pour rester inspectables apres coup.
"""

from __future__ import annotations

from pathlib import Path

from mediaaut.core.logging import get_logger
from mediaaut.render.compose import Clip
from mediaaut.subtitles.transcribe import Word
from mediaaut.visuals import cards
from mediaaut.visuals.director import plan_visuals

log = get_logger(__name__)


def build_clips(
    words: list[Word],
    broll: list[Path],
    job_dir: Path,
    *,
    width: int = 1080,
    height: int = 1920,
    shot_seconds: float = 3.2,
) -> list[Clip]:
    """Compose la suite de plans : cartes aux bons instants, b-roll ailleurs.

    Si aucun artefact technique n'est reconnu, la sortie est identique a ce
    que produisait le pipeline avant les cartes — le b-roll simplement
    reparti sur la duree.
    """
    if not words:
        return []

    plan = plan_visuals(words)
    if not plan:
        return []

    cards_dir = job_dir / "cards"
    clips: list[Clip] = []
    broll_index = 0
    card_index = 0

    for cue in plan:
        if cue.kind == "card":
            card_index += 1
            path = cards.render(
                cue.lines,
                cards_dir / f"card-{card_index:02d}.png",
                width=width,
                height=height,
                title=cue.title,
                highlight=cue.highlight,
            )
            clips.append(Clip(path=path, duration=cue.duration, still=True))
            continue

        if not broll:
            continue

        # Un intervalle de b-roll est redecoupe en plusieurs plans : dix
        # secondes sur une seule image fige la video.
        shots = max(1, round(cue.duration / shot_seconds))
        per_shot = cue.duration / shots
        for _ in range(shots):
            source = broll[broll_index % len(broll)]
            broll_index += 1
            clips.append(Clip(path=source, duration=per_shot, start=0.5))

    log.info(
        "montage : %d plan(s) dont %d carte(s)",
        len(clips), sum(1 for c in clips if c.still),
    )
    return clips
