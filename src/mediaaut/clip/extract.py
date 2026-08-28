"""Decoupe d'un extrait et remise au format vertical.

Le materiau source est presque toujours horizontal. Deux facons de le
passer en 9:16, choisies selon ce que montre l'image :

- **blur** — la source entiere au centre, sur un fond flouté tire d'elle-meme.
  Rien n'est perdu. C'est le defaut, et le seul choix sur du contenu ou
  l'information est repartie dans la largeur (ecrans, graphiques, deux
  personnes).
- **crop** — recadrage plein cadre sur une bande verticale. Plus immersif,
  mais ampute les deux tiers de la largeur : reserve au sujet unique et
  centre.

Les sous-titres sont regeneres a partir des mots deja dates par Whisper,
donc le calage est exact sans nouvelle transcription.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mediaaut.assets.fonts import ensure_fonts
from mediaaut.clip.segments import Segment
from mediaaut.core import ffmpeg
from mediaaut.core.config import RenderConfig
from mediaaut.core.logging import get_logger
from mediaaut.render.compose import escape_path
from mediaaut.render.templates import Template
from mediaaut.subtitles.ass_writer import write_ass
from mediaaut.subtitles.transcribe import Word

log = get_logger(__name__)


@dataclass(slots=True)
class ClipResult:
    path: Path
    title: str
    start: float
    duration: float


def _rebase(words: list[Word], origin: float) -> list[Word]:
    """Ramene les horodatages a zero au debut de l'extrait."""
    return [Word(w.text, w.start - origin, w.end - origin) for w in words]


def _reframe(width: int, height: int, fps: int, mode: str) -> str:
    """Chaine de filtres amenant la source au format vertical."""
    if mode == "crop":
        return (
            f"[0:v]fps={fps},scale={width}:{height}"
            f":force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,format=yuv420p[vbase]"
        )
    return (
        f"[0:v]fps={fps},setsar=1,split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma=32,eq=brightness=-0.12:saturation=0.8[bb];"
        f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[ff];"
        f"[bb][ff]overlay=(W-w)/2:(H-h)/2,format=yuv420p[vbase]"
    )


def extract(
    source: Path,
    segment: Segment,
    out_path: Path,
    *,
    cfg: RenderConfig,
    template: Template,
    reframe: str = "blur",
) -> ClipResult:
    """Produit un short vertical a partir d'un passage d'une video longue."""
    width, height, fps = cfg.width, cfg.height, cfg.fps
    out_path.parent.mkdir(parents=True, exist_ok=True)

    subtitles = write_ass(
        _rebase(segment.words, segment.start),
        out_path.with_suffix(".ass"),
        style=template.subtitle_style,
        width=width,
        height=height,
        safe_bottom=template.subtitle_anchor,
        max_chars=template.max_chars,
    )

    graph = [
        _reframe(width, height, fps, reframe),
        f"[vbase]subtitles=filename='{escape_path(subtitles)}'"
        f":fontsdir='{escape_path(ensure_fonts())}'[vout]",
        # Normalisation vers la cible commune des plateformes. La source est
        # rarement mixee pour le mobile : sans cela, un extrait sort nettement
        # plus faible que les videos produites par le pipeline faceless.
        "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]",
    ]

    encoder = (
        ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"]
        if ffmpeg.has_nvenc()
        else ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    )

    ffmpeg.run(
        [
            # `-ss` avant `-i` cherche par mots-cles, ce qui est rapide ; la
            # precision a l'image est retablie par `-accurate_seek`.
            "-accurate_seek",
            "-ss", f"{segment.start:.3f}",
            "-t", f"{segment.duration:.3f}",
            "-i", str(source),
            "-filter_complex", ";".join(graph),
            "-map", "[vout]", "-map", "[aout]",
            *encoder,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            str(out_path),
        ]
    )

    log.info(
        "extrait %s : %.0fs a %.0fs (%.0fs), %s",
        out_path.name, segment.start, segment.end, segment.duration, segment.title,
    )
    return ClipResult(
        path=out_path, title=segment.title, start=segment.start, duration=segment.duration
    )
