"""Calibration de la largeur du texte rendu par libass.

Pour dimensionner une cue afin qu'elle remplisse le cadre, il faut predire
la largeur qu'aura le texte une fois rendu. Or la taille de police d'un
sous-titre ASS ne correspond pas a la taille em utilisee par Pillow pour
mesurer : a valeur nominale egale, libass rend nettement plus etroit.

Le rapport entre les deux est une constante par police, mais elle ne se
deduit pas proprement des metriques du fichier (les hypotheses fondees sur
ascent + descent se trompent de 15 a 30 % selon la fonte). On la mesure
donc pour de vrai : un rendu libass d'une chaine temoin, une lecture de la
boite englobante, un rapport, mis en cache sur disque. La calibration se
corrige ainsi d'elle-meme si la police ou la version de libass changent.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from mediaaut.core import ffmpeg
from mediaaut.core.logging import get_logger
from mediaaut.core.paths import MODELS

log = get_logger(__name__)

_CACHE_FILE = MODELS / "libass_metrics.json"
_PROBE_TEXT = "HAMBURGEFONTSIV 0123"
_PROBE_SIZE = 100
_CANVAS = (1920, 400)

# Utilise si la calibration echoue (ffmpeg absent, rendu vide). Moyenne des
# facteurs observes sur les fontes du catalogue : suffisant pour rester
# lisible, insuffisant pour remplir le cadre au pixel pres.
_FALLBACK_WIDTH = 0.57
# Hauteur des capitales rendues, rapportee a la taille nominale ASS.
_FALLBACK_HEIGHT = 0.72


def _load_cache() -> dict[str, float]:
    if not _CACHE_FILE.exists():
        return {}
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict[str, float]) -> None:
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _measure_libass(font_name: str, fonts_dir: Path) -> tuple[int, int] | None:
    """Boite englobante (largeur, hauteur) du texte temoin rendu par libass."""
    import numpy as np
    from PIL import Image

    width, height = _CANVAS
    with tempfile.TemporaryDirectory() as tmp:
        ass_path = Path(tmp) / "probe.ass"
        png_path = Path(tmp) / "probe.png"
        ass_path.write_text(
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {width}\nPlayResY: {height}\n"
            "WrapStyle: 2\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,"
            " BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,"
            " BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: P,{font_name},{_PROBE_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
            "0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            f"Dialogue: 0,0:00:00.00,0:00:01.00,P,,0,0,0,,{_PROBE_TEXT}\n",
            encoding="utf-8",
        )

        from mediaaut.render.compose import escape_path

        result = subprocess.run(
            [
                ffmpeg.resolve("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:d=0.1",
                "-vf",
                f"subtitles=filename='{escape_path(ass_path)}'"
                f":fontsdir='{escape_path(fonts_dir)}'",
                "-frames:v", "1", str(png_path),
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not png_path.exists():
            return None

        pixels = np.array(Image.open(png_path).convert("L"))
        columns = np.where(pixels.max(axis=0) > 40)[0]
        rows = np.where(pixels.max(axis=1) > 40)[0]
        if len(columns) < 2 or len(rows) < 2:
            return None
        return int(columns[-1] - columns[0] + 1), int(rows[-1] - rows[0] + 1)


@lru_cache(maxsize=8)
def factors(font_name: str) -> tuple[float, float]:
    """Couple (facteur_largeur, facteur_hauteur) de la police.

    - facteur largeur : largeur_libass / largeur_Pillow a taille nominale egale ;
    - facteur hauteur : hauteur des capitales rendue, rapportee a la taille
      nominale. Il borne la taille des cues tres courtes, qu'un ajustement
      en largeur seul rendrait demesurement hautes.

    Mis en cache sur disque : la mesure coute un appel ffmpeg, paye une
    seule fois par police et par machine.
    """
    cache = _load_cache()
    if font_name in cache:
        entry = cache[font_name]
        return entry["width"], entry["height"]

    try:
        from PIL import ImageFont

        from mediaaut.assets.fonts import ensure_fonts, font_file

        fonts_dir = ensure_fonts([font_name])
        pil_width = ImageFont.truetype(str(font_file(font_name)), _PROBE_SIZE).getlength(
            _PROBE_TEXT
        )
        measured = _measure_libass(font_name, fonts_dir)
    except Exception as exc:
        log.warning("calibration de %s impossible (%s), valeurs par defaut", font_name, exc)
        return _FALLBACK_WIDTH, _FALLBACK_HEIGHT

    if not measured or pil_width <= 0:
        log.warning("calibration de %s sans resultat, valeurs par defaut", font_name)
        return _FALLBACK_WIDTH, _FALLBACK_HEIGHT

    width_ratio = measured[0] / pil_width
    height_ratio = measured[1] / _PROBE_SIZE
    log.info(
        "police %s calibree : largeur %.4f, hauteur %.4f", font_name, width_ratio, height_ratio
    )
    cache[font_name] = {"width": width_ratio, "height": height_ratio}
    _save_cache(cache)
    return width_ratio, height_ratio


def fit_size(
    text: str,
    font_name: str,
    target_width: float,
    *,
    target_height: float,
    fallback: int,
    minimum: int,
    maximum: int,
) -> int:
    """Taille ASS pour que `text` tienne dans la boite (largeur, hauteur).

    On retient la plus contraignante des deux dimensions. Sans la borne en
    hauteur, une cue d'un seul mot court serait etiree sur toute la largeur
    et occuperait le tiers de l'ecran.
    """
    if not text:
        return fallback
    try:
        from PIL import ImageFont

        from mediaaut.assets.fonts import font_file

        reference = ImageFont.truetype(str(font_file(font_name)), 100).getlength(text)
    except Exception:
        return fallback

    if reference <= 0:
        return fallback

    width_ratio, height_ratio = factors(font_name)
    by_width = target_width / (reference * width_ratio) * 100
    by_height = target_height / height_ratio
    return max(minimum, min(maximum, round(min(by_width, by_height))))
