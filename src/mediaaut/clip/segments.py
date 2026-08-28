"""Reperage des passages a extraire d'une video longue.

Le modele choisit les passages, mais ne fixe pas les bornes : ses
horodatages sont approximatifs et couper au milieu d'un mot s'entend
immediatement. On lui demande donc une intention, puis on recale chaque
borne sur les silences et les fins de phrase mesures par Whisper.

C'est aussi ce qui rend ce pipeline plus sur que la production de shorts
de toutes pieces vis-a-vis de la politique « Inauthentic Content » : le
contenu vient d'une video reelle, chaque extrait est different, et rien
n'est fabrique.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mediaaut.clip.models import SegmentBatch, SegmentPick
from mediaaut.core.logging import get_logger
from mediaaut.script.backends import generate
from mediaaut.subtitles.transcribe import Transcript, Word

log = get_logger(__name__)

# Un short en dessous de cette duree n'a pas le temps d'installer une idee ;
# au-dela, il perd l'avantage de format du court.
MIN_SECONDS = 15.0
MAX_SECONDS = 75.0

# Silence a partir duquel on considere tenir une frontiere naturelle.
_PAUSE = 0.35


@dataclass(slots=True)
class Segment:
    start: float
    end: float
    title: str
    reason: str
    words: list[Word]

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


SYSTEM = """You select passages from a long transcript that can stand alone as \
short videos.

A passage qualifies only if a viewer who has seen nothing else understands it. \
It must contain the setup and the payoff. A passage that refers to something \
said earlier ("as I mentioned", "this is why that matters") does not qualify \
unless the referent is inside the passage.

Prefer passages that open on a claim, a number, a contradiction or a question. \
Reject introductions, sign-offs, housekeeping, and anything whose interest \
depends on the surrounding video.

Choose passages spread across the whole recording. Several picks from the same \
few minutes give near-identical videos.

Timestamps may be approximate — they are snapped to sentence boundaries \
afterwards. The hook field must be copied verbatim from the transcript, so \
that a mis-aligned pick can be detected."""


def _transcript_for_prompt(transcript: Transcript, step: float = 10.0) -> str:
    """Transcription horodatee, condensee pour tenir dans le contexte.

    Les mots sont regroupes par tranches d'une dizaine de secondes : le
    modele a besoin de savoir *ou* se trouve un passage, pas de la position
    de chaque mot.
    """
    lines: list[str] = []
    bucket: list[str] = []
    bucket_start = 0.0

    for word in transcript.words:
        if not bucket:
            bucket_start = word.start
        bucket.append(word.text)
        if word.end - bucket_start >= step:
            lines.append(f"[{bucket_start:.0f}s] {' '.join(bucket)}")
            bucket = []
    if bucket:
        lines.append(f"[{bucket_start:.0f}s] {' '.join(bucket)}")
    return "\n".join(lines)


def _anchor(words: list[Word], hook: str) -> int | None:
    """Retrouve la position du hook dans la transcription.

    Les horodatages rendus par le modele derivent : sur une source de deux
    minutes, un extrait annonce a 59 s peut en realite viser un passage
    situe trente secondes plus loin, et le titre ne correspond alors plus
    au contenu. Le hook, lui, est recopie depuis la transcription : le
    chercher dans le texte redonne la position reelle du passage vise.

    Retourne `None` si le hook est introuvable — auquel cas l'horodatage
    reste le seul indice disponible.
    """
    needle = [w for w in re.findall(r"[a-z0-9']+", hook.lower()) if len(w) > 2][:6]
    if len(needle) < 3:
        return None

    normalised = [re.sub(r"[^a-z0-9']", "", w.text.lower()) for w in words]
    best_index, best_score = None, 0.0

    for index in range(len(normalised) - len(needle) + 1):
        window = normalised[index : index + len(needle)]
        score = sum(1 for a, b in zip(needle, window, strict=True) if a == b) / len(needle)
        if score > best_score:
            best_index, best_score = index, score

    # En dessous de la moitie des mots retrouves, la correspondance releve
    # du hasard et suivre cette position serait pire que l'horodatage.
    return best_index if best_score >= 0.5 else None


def _snap(words: list[Word], start: float, end: float) -> tuple[int, int]:
    """Recale les bornes sur des frontieres naturelles.

    Le debut remonte au premier mot suivant une pause ou une fin de phrase,
    la fin descend au dernier mot qui termine une phrase. Sans ce recalage,
    un extrait commence au milieu d'un mot et se termine en suspens.
    """
    if not words:
        return 0, 0

    first = min(range(len(words)), key=lambda i: abs(words[i].start - start))
    last = min(range(len(words)), key=lambda i: abs(words[i].end - end))
    if last <= first:
        last = min(first + 1, len(words) - 1)

    # Remonte vers l'amont jusqu'a une vraie frontiere, sans depasser 4 s.
    index = first
    while index > 0 and words[first].start - words[index].start < 4.0:
        previous = words[index - 1]
        if words[index].start - previous.end >= _PAUSE or previous.text.endswith((".", "!", "?")):
            first = index
            break
        index -= 1

    # Prolonge vers l'aval jusqu'a une fin de phrase, sans depasser 4 s.
    index = last
    while index < len(words) - 1 and words[index].end - words[last].end < 4.0:
        if words[index].text.endswith((".", "!", "?")):
            last = index
            break
        index += 1

    return first, last


def _grow(words: list[Word], first: int, last: int) -> tuple[int, int]:
    """Etire un extrait trop court jusqu'a la duree minimale.

    Un passage juge pertinent mais long de douze secondes ne doit pas etre
    jete pour trois secondes manquantes : on l'etend jusqu'a la frontiere de
    phrase suivante, puis vers l'amont si cela ne suffit pas. Ne rien faire
    reviendrait a perdre la moitie des propositions du modele.
    """
    while words[last].end - words[first].start < MIN_SECONDS:
        grown = False

        # Vers l'aval d'abord : prolonger la fin garde le debut choisi, donc
        # le hook reste celui que le modele avait retenu.
        if last < len(words) - 1:
            index = last + 1
            while index < len(words) - 1 and not words[index].text.endswith((".", "!", "?")):
                index += 1
            last, grown = index, True

        if words[last].end - words[first].start >= MIN_SECONDS:
            break

        if first > 0:
            index = first - 1
            while index > 0 and not words[index - 1].text.endswith((".", "!", "?")):
                index -= 1
            first, grown = index, True

        if not grown:
            break

    return first, last


def select(
    transcript: Transcript,
    *,
    count: int = 6,
    topic: str = "",
) -> list[Segment]:
    """Choisit jusqu'a `count` extraits autonomes dans la transcription."""
    if not transcript.words:
        return []

    instruction = (
        f"Transcript of a {transcript.duration / 60:.0f}-minute recording"
        + (f" about {topic}" if topic else "")
        + f":\n\n{_transcript_for_prompt(transcript)}\n\n"
        f"Select {count} passages, each between {MIN_SECONDS:.0f} and "
        f"{MAX_SECONDS:.0f} seconds."
    )

    picks: list[SegmentPick] = generate(SYSTEM, instruction, SegmentBatch).segments
    log.info("%d passage(s) proposes par le modele", len(picks))

    segments: list[Segment] = []
    for pick in picks:
        start_hint = pick.start
        anchor = _anchor(transcript.words, pick.hook)
        if anchor is not None:
            drift = abs(transcript.words[anchor].start - pick.start)
            if drift > 5.0:
                log.info(
                    "extrait recale de %.0fs sur son hook (%.0fs -> %.0fs) : %s",
                    drift, pick.start, transcript.words[anchor].start, pick.title,
                )
            start_hint = transcript.words[anchor].start

        first, last = _snap(transcript.words, start_hint, pick.end + (start_hint - pick.start))
        first, last = _grow(transcript.words, first, last)
        words = transcript.words[first : last + 1]
        if not words:
            continue

        start, end = words[0].start, words[-1].end
        duration = end - start
        if duration < MIN_SECONDS:
            log.info(
                "extrait ecarte (%.0fs, trop court meme apres extension) : %s",
                duration, pick.title,
            )
            continue
        if duration > MAX_SECONDS:
            log.info("extrait ecarte (%.0fs, trop long) : %s", duration, pick.title)
            continue
        if any(s.start < end and start < s.end for s in segments):
            log.info("extrait ecarte (chevauche un precedent) : %s", pick.title)
            continue

        segments.append(
            Segment(start=start, end=end, title=pick.title, reason=pick.reason, words=words)
        )

    segments.sort(key=lambda s: s.start)
    log.info("%d extrait(s) retenus apres recalage", len(segments))
    return segments
