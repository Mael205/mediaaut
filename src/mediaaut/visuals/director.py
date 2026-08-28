"""Choix du visuel a montrer, phrase par phrase.

Le defaut du b-roll de banque n'est pas la pertinence des requetes : c'est
que le fonds n'existe pas. Aucune banque n'a d'image d'un code de statut
HTTP. Quand la narration nomme un artefact technique, la bonne illustration
est cet artefact lui-meme, rendu comme une carte.

Le reperage est deterministe, pas confie au modele : les artefacts se
reconnaissent a leur forme (`videos.insert`, `200 OK`, `--dry-run`), et une
expression reguliere ne derive pas, la ou un modele local a deja rendu des
questions entieres comme requetes de recherche.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mediaaut.core.logging import get_logger
from mediaaut.subtitles.transcribe import Word

log = get_logger(__name__)


@dataclass(slots=True)
class VisualCue:
    """Un visuel et la fenetre temporelle qu'il occupe."""

    start: float
    end: float
    kind: str                        # "card" ou "broll"
    lines: list[str] = field(default_factory=list)
    title: str = ""
    highlight: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


# Formes d'artefacts techniques. L'ordre compte : le premier motif qui
# reconnait un mot gagne, donc les formes les plus specifiques d'abord.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # « 200 OK », « 403 Forbidden », « a two hundred status code »
    ("status", re.compile(r"\b([1-5]\d{2})\s*(OK|Forbidden|Not Found|Created)?\b")),
    # « videos.insert », « media_publish », « object.method() »
    ("call", re.compile(r"\b([a-z][a-zA-Z0-9]*(?:[._][a-zA-Z0-9]+)+)\(?\)?")),
    # « --dry-run », « -p youtube »
    ("flag", re.compile(r"(?<!\w)(--[a-z][a-z0-9-]+)")),
    # « privacyStatus », « containsSyntheticMedia »
    ("field", re.compile(r"\b([a-z]+(?:[A-Z][a-z0-9]+){1,})\b")),
]

# Entites techniques nommees : elles ne ressemblent pas a du code, mais une
# carte les illustre bien mieux qu'une photo de banque. Sans elles, un script
# entierement conceptuel — « la memoire GPU limite la taille de lot » — ne
# declenchait aucune carte et retombait sur du b-roll hors sujet.
_ENTITIES = {
    "pytorch": ("import torch", "torch.cuda.memory_allocated()"),
    "tensorflow": ("import tensorflow as tf", "tf.config.list_physical_devices()"),
    "cuda": ("$ nvidia-smi", "  memory: 11264MiB / 12282MiB"),
    "docker": ("$ docker run --gpus all", "  container started"),
    "kubernetes": ("$ kubectl get pods", "  3 running, 1 pending"),
    "ffmpeg": ("$ ffmpeg -i in.mp4 out.mp4", "  frame= 1024 fps=240"),
    "whisper": ("$ whisper audio.wav", "  detected language: en"),
    "git": ("$ git push origin main", "  main -> main"),
    "npm": ("$ npm install", "  added 214 packages"),
    "sql": ("SELECT * FROM users", "  1204 rows"),
}

# Mots qui ressemblent a du code sans en etre. Sans cette liste, « YouTube »
# et « TikTok » sont pris pour des noms de champ par le motif camelCase.
_NOT_CODE = frozenset(
    """
    youtube tiktok instagram javascript typescript github gitlab openai
    iphone android macos ios chatgpt powershell postgresql mysql
    """.split()
)


def find_artifacts(text: str) -> list[tuple[str, str]]:
    """Artefacts techniques nommes dans un texte, dans l'ordre d'apparition."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    lowered = text.lower()
    for entity in _ENTITIES:
        if re.search(r"\b" + re.escape(entity) + r"\b", lowered):
            found.append(("entity", entity))
            seen.add(entity)

    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            token = match.group(1)
            if token.lower() in _NOT_CODE or token.lower() in seen:
                continue
            # Un mot camelCase isole de moins de huit lettres est plus
            # souvent un nom propre qu'un champ.
            if kind == "field" and len(token) < 8:
                continue
            seen.add(token.lower())
            found.append((kind, token))
    return found


def _card_for(kind: str, token: str) -> tuple[list[str], str, str]:
    """Compose le contenu d'une carte a partir d'un artefact.

    Trois lignes au maximum, et aucune ligne vide. Le panneau partage le
    cadre avec les sous-titres : chaque ligne de plus le fait descendre
    jusqu'a passer sous le texte, qui recouvre alors le code a lire.
    """
    if kind == "status":
        return (
            [f"HTTP/1.1 {token}", '{ "status": "accepted" }'],
            "response",
            token,
        )
    if kind == "call":
        path = token.replace(".", "/")
        return (
            [f"$ POST {path}", "202 Accepted", "  state: pending"],
            "request",
            path,
        )
    if kind == "entity":
        lines = list(_ENTITIES[token])
        return (lines, token, lines[0].split()[-1] if len(lines[0].split()) > 1 else token)
    if kind == "flag":
        return (
            [f"$ mediaaut publish {token}", "  rien televerse"],
            "bash",
            token,
        )
    return (
        ["{", f'  "{token}": true', "}"],
        "payload",
        f'"{token}"',
    )


def plan_visuals(
    words: list[Word],
    *,
    min_card: float = 2.5,
    max_card: float = 5.0,
    spacing: float = 6.0,
) -> list[VisualCue]:
    """Repartit cartes et b-roll sur la duree de la narration.

    `spacing` impose un intervalle minimal entre deux cartes : les
    enchainer transformerait la video en diaporama de code, alors qu'elles
    valent par le contraste avec les plans qui les entourent.
    """
    if not words:
        return []

    total = words[-1].end
    cues: list[VisualCue] = []
    last_card_end = -spacing

    for word in words:
        artifacts = find_artifacts(word.text)
        if not artifacts:
            continue
        if word.start - last_card_end < spacing:
            continue

        kind, token = artifacts[0]
        lines, title, highlight = _card_for(kind, token)
        # La carte s'ouvre un peu avant le mot : elle doit etre a l'ecran
        # quand il est prononce, pas apparaitre dessus.
        start = max(0.0, word.start - 0.4)
        end = min(total, start + max_card)
        if end - start < min_card:
            continue

        cues.append(
            VisualCue(start=start, end=end, kind="card", lines=lines,
                      title=title, highlight=highlight)
        )
        last_card_end = end

    # Les intervalles laisses libres reviennent au b-roll.
    filled: list[VisualCue] = []
    cursor = 0.0
    for cue in cues:
        if cue.start - cursor > 1.0:
            filled.append(VisualCue(start=cursor, end=cue.start, kind="broll"))
        filled.append(cue)
        cursor = cue.end
    if total - cursor > 1.0:
        filled.append(VisualCue(start=cursor, end=total, kind="broll"))

    cards = sum(1 for c in filled if c.kind == "card")
    log.info(
        "plan visuel : %d carte(s), %d plan(s) de b-roll", cards, len(filled) - cards
    )
    return filled
