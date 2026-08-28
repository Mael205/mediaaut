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
    """Un plan et la portion de la timeline qu'il occupe.

    `still` distingue une image fixe — une carte de code — d'un extrait
    video. ffmpeg ne sait pas deduire la duree d'un PNG : il faut la lui
    imposer avec `-loop 1 -t`, faute de quoi le plan dure une image.
    """

    path: Path
    duration: float
    start: float = 0.0     # point d'entree dans le fichier source
    still: bool = False
    # Zoom propre au plan. Une carte de code bouge a peine — elle se lit ;
    # une photo fixe sans mouvement parait figee au milieu d'une video.
    zoom: float = 0.0      # 0 = utiliser celui du template


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


def _crop_chain(
    index: int, clip: Clip, width: int, video_height: int, fps: int, zoom: float
) -> str:
    """Recadre la source pour remplir le cadre, quitte a couper les bords.

    Le plan est d'abord surechantillonne a 2x avant le zoom : `zoompan`
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


def _blur_fill_chain(index: int, width: int, video_height: int, fps: int) -> str:
    """Inscrit la source entiere au centre, sur un fond flouté tire d'elle-meme.

    C'est la reponse standard au materiau horizontal : recadrer un 16:9 en
    9:16 ampute l'action des deux tiers de sa largeur. Le fond assombri
    evite que le flou n'attire l'oeil hors du sujet.
    """
    return (
        f"[{index}:v]fps={fps},setsar=1,setpts=PTS-STARTPTS,split=2[bg{index}][fg{index}];"
        f"[bg{index}]scale={width}:{video_height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{video_height},gblur=sigma=32,eq=brightness=-0.12:saturation=0.8[bb{index}];"
        f"[fg{index}]scale={width}:{video_height}:force_original_aspect_ratio=decrease[ff{index}];"
        f"[bb{index}][ff{index}]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v{index}]"
    )


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
            if clip.still:
                inputs += ["-loop", "1", "-t", f"{clip.duration:.3f}", "-i", str(clip.path)]
            else:
                inputs += [
                    "-ss", f"{clip.start:.3f}",
                    "-t", f"{clip.duration:.3f}",
                    "-i", str(clip.path),
                ]
            if clip.still:
                # Une image fixe est recadree, jamais floutee : le fond
                # floute n'a de sens que pour du materiau video horizontal.
                graph.append(
                    _crop_chain(
                        index, clip, width, video_height, fps,
                        zoom=clip.zoom or 1.04,
                    )
                )
            elif template.fill_mode == "blur":
                graph.append(_blur_fill_chain(index, width, video_height, fps))
            else:
                graph.append(
                    _crop_chain(index, clip, width, video_height, fps, template.zoom)
                )
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

    # Normalisation a -14 LUFS : c'est la cible vers laquelle YouTube,
    # Instagram et TikTok ramenent la lecture. Livrer plus fort ne rend pas
    # plus fort, cela fait seulement ecraser le mix par leur limiteur ;
    # livrer plus faible fait paraitre la video timide dans le fil.
    graph.append(
        f"[{audio_out}]loudnorm=I=-14:TP=-1.5:LRA=11,"
        "alimiter=limit=0.95:level=disabled[aout]"
    )

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


def plan_clips(clips: list[Path], total: float, *, min_shot: float = 3.2) -> list[Clip]:
    """Repartit une liste de fichiers de b-roll sur la duree voulue.

    Les plans sont boucles si le stock est insuffisant. `min_shot` borne la
    duree d'un plan par le bas. La valeur par defaut est deliberement haute :
    les chaines narratives a forte audience tiennent 3 a 7 secondes par plan,
    la coupe toutes les 1,5 s est une signature du format « slideshow » que
    la politique Inauthentic Content vise directement.
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
