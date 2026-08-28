"""Composition du rendu final via un unique graphe de filtres ffmpeg.

Tout se fait en une passe : mise au format du b-roll, zoom lent, concatenation,
incrustation des sous-titres, mixage voix/musique, encodage. Passer par un
seul appel evite les fichiers intermediaires et laisse ffmpeg paralleliser.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mediaaut.core import ffmpeg
from mediaaut.core.config import RenderConfig
from mediaaut.core.logging import get_logger
from mediaaut.render.templates import Template

log = get_logger(__name__)


@dataclass(slots=True)
class Clip:
    """Un plan de b-roll et la portion de la timeline qu'il occupe."""

    path: Path
    duration: float
    start: float = 0.0     # point d'entree dans le fichier source


def escape_path(path: Path) -> str:
    """Rend un chemin utilisable comme valeur dans un graphe de filtres.

    ffmpeg decoupe les options de filtre sur `:`, ce qui casse net sur
    `C:\\...`. La forme acceptee est `C\\:/chemin/avec/slashs`.
    """
    return str(Path(path).resolve()).replace("\\", "/").replace(":", "\\:")


def _video_encoder() -> list[str]:
    """NVENC si la carte le permet, sinon x264. Le 4070 divise le temps
    d'encodage par ~4 sur ce type de rendu."""
    if ffmpeg.has_nvenc():
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]


def _background_chain(
    index: int, clip: Clip, width: int, video_height: int, fps: int, zoom: float
) -> str:
    """Chaine de filtres amenant un plan source au format cible.

    Le plan est d'abord suréchantillonne a 2x avant le zoom : `zoompan`
    travaille sur une grille de pixels entiers et produit des saccades
    visibles si on le fait operer directement a la resolution de sortie.
    """
    steps = [
        f"scale={width * 2}:{video_height * 2}:force_original_aspect_ratio=increase",
        f"crop={width * 2}:{video_height * 2}",
        "setsar=1",
        f"fps={fps}",
    ]
    if zoom > 1.0:
        # Le zoom suit le numero d'image de sortie (`on`) plutot que de
        # cumuler `zoom` d'une image a l'autre, qui derive sur les plans longs.
        rate = (zoom - 1.0) / max(1.0, clip.duration * fps)
        steps.append(
            f"zoompan=z='min(1+{rate:.8f}*on,{zoom})':d=1"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={width}x{video_height}:fps={fps}"
        )
    else:
        steps.append(f"scale={width}:{video_height}")

    steps += ["format=yuv420p", "setpts=PTS-STARTPTS"]
    return f"[{index}:v]" + ",".join(steps) + f"[v{index}]"


def render_short(
    *,
    out_path: Path,
    voice_path: Path,
    duration: float,
    cfg: RenderConfig,
    template: Template,
    clips: list[Clip] | None = None,
    subtitles_path: Path | None = None,
    fonts_dir: Path | None = None,
    music_path: Path | None = None,
) -> Path:
    """Assemble et encode un short vertical.

    `duration` fixe la longueur finale : le b-roll est coupe ou boucle pour
    s'y conformer, l'audio de voix la determine en amont.
    """
    width, height, fps = cfg.width, cfg.height, cfg.fps
    video_height = int(height * template.video_fraction) // 2 * 2

    inputs: list[str] = []
    graph: list[str] = []
    clips = clips or []

    if clips:
        for index, clip in enumerate(clips):
            inputs += [
                "-ss", f"{clip.start:.3f}",
                "-t", f"{clip.duration:.3f}",
                "-i", str(clip.path),
            ]
            graph.append(_background_chain(index, clip, width, video_height, fps, template.zoom))
        concat_inputs = "".join(f"[v{i}]" for i in range(len(clips)))
        graph.append(f"{concat_inputs}concat=n={len(clips)}:v=1:a=0[vcat]")
        video_count = len(clips)
    else:
        # Repli sans b-roll : degrade anime, pour que le pipeline reste
        # testable de bout en bout sans aucune cle d'API.
        inputs += [
            "-f", "lavfi",
            "-i", (
                f"gradients=s={width}x{video_height}:c0=0x{template.backdrop}"
                f":c1=0x1B3B5F:x0=0:y0=0:x1={width}:y1={video_height}"
                f":d={duration:.3f}:speed=0.015:r={fps}"
            ),
        ]
        graph.append("[0:v]format=yuv420p,setpts=PTS-STARTPTS[vcat]")
        video_count = 1

    stage = "vcat"
    if template.video_fraction < 1.0:
        graph.append(
            f"[{stage}]pad={width}:{height}:0:0:color=0x{template.backdrop}[vpad]"
        )
        stage = "vpad"

    if subtitles_path is not None:
        subs = f"subtitles=filename='{escape_path(subtitles_path)}'"
        if fonts_dir is not None:
            subs += f":fontsdir='{escape_path(fonts_dir)}'"
        graph.append(f"[{stage}]{subs}[vout]")
        stage = "vout"
    else:
        graph.append(f"[{stage}]null[vout]")
        stage = "vout"

    # --- audio ---
    voice_index = video_count
    inputs += ["-i", str(voice_path)]
    graph.append(f"[{voice_index}:a]volume={cfg.voice_gain_db}dB,aresample=48000[a_voice]")

    if music_path is not None:
        music_index = voice_index + 1
        # `-stream_loop -1` boucle une musique plus courte que la voix ;
        # `duration=first` dans amix coupe ensuite sur la voix.
        inputs += ["-stream_loop", "-1", "-i", str(music_path)]
        graph.append(
            f"[{music_index}:a]volume={cfg.music_gain_db}dB,aresample=48000[a_music]"
        )
        graph.append(
            "[a_voice][a_music]amix=inputs=2:duration=first:dropout_transition=0"
            ":normalize=0[a_mix]"
        )
        audio_out = "a_mix"
    else:
        audio_out = "a_voice"

    # Limiteur doux : evite l'ecretage quand voix et musique s'additionnent.
    graph.append(f"[{audio_out}]alimiter=limit=0.95:level=disabled[aout]")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        *inputs,
        "-filter_complex", ";".join(graph),
        "-map", "[vout]", "-map", "[aout]",
        "-t", f"{duration:.3f}",
        *_video_encoder(),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        str(out_path),
    ]
    log.info(
        "rendu %s : %.1fs, template=%s, %d plan(s)",
        out_path.name, duration, template.name, len(clips) or 1,
    )
    ffmpeg.run(args)
    log.info("rendu termine : %s (%.1f Mo)", out_path, out_path.stat().st_size / 1e6)
    return out_path


def plan_clips(clips: list[Path], total: float, *, min_shot: float = 2.2) -> list[Clip]:
    """Repartit une liste de fichiers de b-roll sur la duree voulue.

    Les plans sont boucles si le stock est insuffisant. `min_shot` borne la
    duree d'un plan par le bas : sous ~2 s, l'enchainement devient nerveux
    au point de nuire a la lisibilite des sous-titres.
    """
    if not clips:
        return []

    shots = max(1, min(len(clips), int(total // min_shot)))
    per_shot = total / shots
    planned: list[Clip] = []
    for index in range(shots):
        source = clips[index % len(clips)]
        available = ffmpeg.duration(source)
        # On demarre un peu apres le debut : les premieres images d'un plan
        # de banque sont souvent un fondu ou une image fixe.
        start = min(0.5, max(0.0, available - per_shot))
        planned.append(Clip(source, duration=min(per_shot, available - start), start=start))

    # Corrige l'arrondi cumule pour que la somme colle exactement a `total`.
    drift = total - sum(c.duration for c in planned)
    if planned and abs(drift) > 0.01:
        planned[-1].duration = max(0.5, planned[-1].duration + drift)
    return planned
