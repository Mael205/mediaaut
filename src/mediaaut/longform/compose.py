"""Assemblage d'une video longue horizontale.

Chaque section est rendue separement, puis les sections sont concatenees.
Un unique graphe de filtres couvrant huit sections et vingt-quatre plans
serait ingerable, et surtout un echec en fin de parcours obligerait a tout
refaire : ici, les sections deja rendues sont conservees.

Le format est 1920x1080, contrairement au reste du projet : le long-form se
regarde sur grand ecran, et YouTube ne pousse le format vertical que vers
l'onglet Shorts, ou le temps de visionnage ne compte pas pour la
monetisation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mediaaut.assets.fonts import ensure_fonts
from mediaaut.core import ffmpeg
from mediaaut.core.logging import get_logger
from mediaaut.render.compose import escape_path
from mediaaut.subtitles.ass_writer import write_ass
from mediaaut.subtitles.transcribe import Word

log = get_logger(__name__)

WIDTH = 1920
HEIGHT = 1080
FPS = 30

# Duree d'un plan en video longue. Plus tenu qu'en short : sur huit minutes,
# un plan qui dure fige l'image, un plan qui saute epuise.
SHOT_SECONDS = 5.5


@dataclass(slots=True)
class Chapter:
    """Un chapitre YouTube : un horodatage et un titre."""

    start: float
    title: str

    def formatted(self) -> str:
        minutes, seconds = divmod(int(self.start), 60)
        hours, minutes = divmod(minutes, 60)
        stamp = (
            f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
        )
        return f"{stamp} {self.title}"


def _encoder() -> list[str]:
    if ffmpeg.has_nvenc():
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "22", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "21"]


def render_section(
    out_path: Path,
    voice_path: Path,
    duration: float,
    clips: list[Path],
    *,
    words: list[Word] | None = None,
    subtitle_style: str = "clean",
) -> Path:
    """Rend une section : b-roll enchaine, voix, sous-titres optionnels."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shots = max(1, min(len(clips) or 1, round(duration / SHOT_SECONDS)))
    per_shot = duration / shots

    inputs: list[str] = []
    graph: list[str] = []

    if clips:
        for index in range(shots):
            source = clips[index % len(clips)]
            available = ffmpeg.duration(source)
            start = min(0.5, max(0.0, available - per_shot))
            inputs += [
                "-ss", f"{start:.3f}",
                "-t", f"{min(per_shot, available - start):.3f}",
                "-i", str(source),
            ]
            graph.append(
                f"[{index}:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS},format=yuv420p,"
                f"setpts=PTS-STARTPTS[v{index}]"
            )
        graph.append(
            "".join(f"[v{i}]" for i in range(shots))
            + f"concat=n={shots}:v=1:a=0[vcat]"
        )
        video_count = shots
    else:
        inputs += [
            "-f", "lavfi",
            "-i", f"gradients=s={WIDTH}x{HEIGHT}:c0=0x0F1117:c1=0x1B3B5F"
                  f":d={duration:.3f}:speed=0.01:r={FPS}",
        ]
        graph.append("[0:v]format=yuv420p,setpts=PTS-STARTPTS[vcat]")
        video_count = 1

    stage = "vcat"
    if words:
        subtitles = write_ass(
            words, out_path.with_suffix(".ass"),
            style=subtitle_style, width=WIDTH, height=HEIGHT,
            safe_bottom=0.08, max_chars=42,
        )
        graph.append(
            f"[{stage}]subtitles=filename='{escape_path(subtitles)}'"
            f":fontsdir='{escape_path(ensure_fonts())}'[vout]"
        )
    else:
        graph.append(f"[{stage}]null[vout]")

    inputs += ["-i", str(voice_path)]
    graph.append(f"[{video_count}:a]aresample=48000[aout]")

    ffmpeg.run(
        [
            *inputs,
            "-filter_complex", ";".join(graph),
            "-map", "[vout]", "-map", "[aout]",
            "-t", f"{duration:.3f}",
            *_encoder(),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            str(out_path),
        ]
    )
    return out_path


def concat_sections(sections: list[Path], out_path: Path, music: Path | None = None) -> Path:
    """Recolle les sections et normalise l'audio de l'ensemble.

    La normalisation est faite ici, pas section par section : `loudnorm`
    mesure sur ce qu'on lui donne, donc l'appliquer par morceau alignerait
    chaque section sur elle-meme et produirait des sauts de niveau audibles
    aux jonctions.
    """
    listing = out_path.with_name("sections.txt")
    listing.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in sections) + "\n",
        encoding="utf-8",
    )

    args = ["-f", "concat", "-safe", "0", "-i", str(listing)]
    if music is not None:
        args += ["-stream_loop", "-1", "-i", str(music)]
        filters = (
            "[0:a]aresample=48000[a0];"
            "[1:a]volume=-24dB,aresample=48000[a1];"
            "[a0][a1]amix=inputs=2:duration=first:normalize=0[amix];"
            "[amix]loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.95:level=disabled[aout]"
        )
    else:
        filters = (
            "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,alimiter=limit=0.95:level=disabled[aout]"
        )

    ffmpeg.run(
        [
            *args,
            "-filter_complex", filters,
            "-map", "0:v", "-map", "[aout]",
            # La video est recopiee telle quelle : les sections sont deja
            # encodees aux memes parametres, la reencoder n'apporterait
            # qu'une perte et plusieurs minutes de calcul.
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            str(out_path),
        ]
    )
    listing.unlink(missing_ok=True)
    log.info("video longue assemblee : %s (%.1f Mo)", out_path.name, out_path.stat().st_size / 1e6)
    return out_path


def build_chapters(titles: list[str], durations: list[float]) -> list[Chapter]:
    """Chapitres YouTube a partir des sections.

    Le premier chapitre doit commencer a zero, sinon YouTube ignore toute
    la liste. Il porte donc le titre d'introduction plutot que celui de la
    premiere section.
    """
    chapters: list[Chapter] = []
    elapsed = 0.0
    for index, (title, duration) in enumerate(zip(titles, durations, strict=True)):
        chapters.append(Chapter(0.0 if index == 0 else elapsed, title))
        elapsed += duration
    return chapters
