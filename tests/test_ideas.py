"""Garde anti-repetition.

Ces cas viennent d'erreurs reelles : la premiere version comparait les
titres mot a mot et laissait passer toutes les reformulations. Le seuil et
la liste de suffixes sont regles sur ce jeu, donc le modifier sans relancer
ces tests rouvre la porte aux doublons.
"""

from __future__ import annotations

import pytest

from mediaaut.ideas.store import SIMILARITY_THRESHOLD, _stem, similarity

# (titre A, titre B, doit-etre-considere-comme-le-meme-sujet)
CASES = [
    ("How I automated my YouTube channel",
     "Automating a YouTube channel: how I did it", True),
    ("The real cost of running Whisper locally",
     "What running Whisper locally really costs", True),
    ("Kokoro TTS beats ElevenLabs",
     "Why ElevenLabs loses to Kokoro TTS", True),
    ("Why your ffmpeg renders are slow",
     "The reason ffmpeg rendering is slow", True),
    ("Your GPU renders video 4x faster",
     "Rendering video on the GPU is 4x faster", True),
    ("Whisper on GPU is 12x faster than CPU",
     "ffmpeg NVENC cuts render time by four", False),
    ("Kokoro runs offline on a CPU",
     "Pexels gives free commercial stock footage", False),
    ("YouTube locks API uploads to private",
     "TikTok drafts avoid the audit entirely", False),
]


@pytest.mark.parametrize(("left", "right", "same_topic"), CASES)
def test_similarity_matches_editorial_judgement(left, right, same_topic):
    score = similarity(left, right)
    assert (score >= SIMILARITY_THRESHOLD) is same_topic, (
        f"recouvrement {score:.2f} pour :\n  {left}\n  {right}"
    )


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("renders", "render"),      # « ers » retire de la liste pour ce cas
        ("rendering", "render"),
        ("automated", "automat"),
        ("automating", "automat"),
        ("costs", "cost"),
        ("running", "run"),         # consonne doublee du participe
        ("run", "run"),
    ],
)
def test_stem(word, expected):
    assert _stem(word) == expected


def test_similarity_is_symmetric_and_bounded():
    for left, right, _ in CASES:
        score = similarity(left, right)
        assert 0.0 <= score <= 1.0
        assert score == pytest.approx(similarity(right, left))


def test_empty_title_scores_zero():
    assert similarity("", "anything at all") == 0.0


# --- chiffres fabriques -------------------------------------------------
# Les modeles locaux ecrivent « 4x plus rapide » sans rien avoir mesure. Ces
# cas fixent la frontiere entre un chiffre de performance invente et un
# chiffre legitime (annee, resolution, taille, duree).
FIGURE_CASES = [
    ("it runs 4x faster than before", True),
    ("a 30% gain in throughput", True),
    ("this is 2.5 times faster in practice", True),
    ("cuts it by 40 percent", True),
    ("released in 2024 with 8 GB of RAM", False),
    ("the 8-bit format uses less memory", False),
    ("a 90 second limit applies", False),
    ("x264 encodes it", False),
    ("H.264 at 1080x1920", False),
]


@pytest.mark.parametrize(("text", "is_fabricated"), FIGURE_CASES)
def test_fabricated_figure_detection(text, is_fabricated):
    from mediaaut.script.writer import _FABRICATED_FIGURE

    assert bool(_FABRICATED_FIGURE.search(text)) is is_fabricated
