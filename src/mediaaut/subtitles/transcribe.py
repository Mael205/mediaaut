"""Transcription datee au mot via faster-whisper.

Sert deux usages :
  - pipeline faceless : caler les sous-titres sur la voix Kokoro, dont on
    connait deja le texte exact (d'ou `align_to_script`) ;
  - pipeline clipping : transcrire une video longue pour y reperer les
    passages a decouper.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from mediaaut.core.gpu import whisper_device
from mediaaut.core.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class Word:
    text: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(slots=True)
class Segment:
    text: str
    start: float
    end: float
    words: list[Word]


@dataclass(slots=True)
class Transcript:
    words: list[Word]
    segments: list[Segment]
    language: str
    duration: float

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@lru_cache(maxsize=2)
def _model(size: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    log.info("chargement de Whisper %s sur %s", size, device)
    return WhisperModel(size, device=device, compute_type=compute_type)


def transcribe(
    audio_path: str | Path,
    *,
    language: str | None = None,
    model_size: str = "small",
    vad: bool = True,
) -> Transcript:
    """Transcrit un fichier audio ou video en datant chaque mot.

    `model_size` : `small` suffit pour caler des sous-titres sur une voix de
    synthese propre. Preferer `large-v3` pour de la parole reelle bruitee
    (pipeline clipping), ou le GPU rend le surcout negligeable.
    """
    device, compute_type = whisper_device()
    model = _model(model_size, device, compute_type)

    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        word_timestamps=True,
        vad_filter=vad,
    )

    segments: list[Segment] = []
    words: list[Word] = []
    for seg in segments_iter:
        seg_words = [
            Word(w.word.strip(), w.start, w.end) for w in (seg.words or []) if w.word.strip()
        ]
        words.extend(seg_words)
        segments.append(Segment(seg.text.strip(), seg.start, seg.end, seg_words))

    duration = words[-1].end if words else 0.0
    log.info(
        "transcription : %d mots, %d segments, langue=%s, %.1fs",
        len(words), len(segments), info.language, duration,
    )
    return Transcript(words, segments, info.language, duration)


def _normalize(token: str) -> str:
    """Forme comparable d'un mot : minuscules, sans ponctuation."""
    return re.sub(r"[^\w']", "", token.lower())


def align_to_script(words: list[Word], script: str) -> list[Word]:
    """Remplace le texte transcrit par celui du script, en gardant les timings.

    Whisper normalise ce qu'il entend : « 2026 » devient « twenty twenty-six »,
    la ponctuation est reinventee, la casse est perdue. Comme le script exact
    est connu, on projette les mots d'origine sur les timings mesures. Les
    mots du script qu'aucun mot transcrit ne recouvre heritent d'un partage
    proportionnel de la plage temporelle concernee, ce qui evite les sauts.
    """
    script_words = re.findall(r"\S+", script)
    if not words or not script_words:
        return words

    matcher = difflib.SequenceMatcher(
        a=[_normalize(w.text) for w in words],
        b=[_normalize(w) for w in script_words],
        autojunk=False,
    )

    aligned: list[Word] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            aligned.extend(
                Word(script_words[j], words[i].start, words[i].end)
                for i, j in zip(range(i1, i2), range(j1, j2), strict=True)
            )
            continue
        if j1 == j2:
            continue  # mots entendus mais absents du script : on les jette

        # Plage temporelle a repartir sur les mots du script non apparies.
        start = words[i1].start if i1 < len(words) else (aligned[-1].end if aligned else 0.0)
        end = words[i2 - 1].end if i2 - 1 < len(words) and i2 > i1 else start
        if end <= start:
            end = start + 0.24 * (j2 - j1)

        step = (end - start) / (j2 - j1)
        aligned.extend(
            Word(script_words[j], start + k * step, start + (k + 1) * step)
            for k, j in enumerate(range(j1, j2))
        )

    ratio = sum(1 for _ in matcher.get_matching_blocks())
    log.debug("alignement script : %d mots -> %d (blocs %d)", len(words), len(aligned), ratio)
    return aligned
