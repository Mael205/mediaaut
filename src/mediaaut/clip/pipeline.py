"""Orchestration du decoupage : une video longue devient plusieurs shorts.

Ce pipeline a deux avantages sur la production de shorts de toutes pieces,
et tous deux comptent :

- **Le volume ne consomme pas d'idees.** Six extraits d'une meme video sont
  six sujets distincts sans avoir eu a en trouver six.
- **Rien n'est fabrique.** Le contenu vient d'un enregistrement reel, ce qui
  le place hors d'atteinte de la politique « Inauthentic Content ».
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from mediaaut.clip.extract import ClipResult, extract
from mediaaut.clip.segments import select
from mediaaut.core.config import get_channel
from mediaaut.core.logging import get_logger, step
from mediaaut.core.net import download
from mediaaut.core.paths import CACHE, job_dir
from mediaaut.render.templates import get_template, pick_template
from mediaaut.subtitles.transcribe import transcribe

log = get_logger(__name__)

SOURCES = CACHE / "sources"


@dataclass(slots=True)
class ClipJobResult:
    job_id: str
    channel_id: str
    source: str
    clips: list[dict] = field(default_factory=list)


def fetch_source(target: str) -> Path:
    """Resout une source : fichier local, URL directe, ou lien a telecharger."""
    local = Path(target)
    if local.exists():
        return local

    SOURCES.mkdir(parents=True, exist_ok=True)
    if not target.startswith(("http://", "https://")):
        raise FileNotFoundError(f"ni fichier ni URL : {target}")

    # Un lien de plateforme demande yt-dlp ; une URL de fichier suffit seule.
    if target.rstrip("/").split("/")[-1].lower().endswith((".mp4", ".mov", ".mkv", ".webm")):
        return download(target, SOURCES / target.rstrip("/").split("/")[-1])

    import subprocess

    output = SOURCES / "%(id)s.%(ext)s"
    log.info("telechargement de la source via yt-dlp")
    proc = subprocess.run(
        [
            "yt-dlp", "--no-warnings", "--no-playlist",
            "-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4",
            "--print", "after_move:filepath", "-o", str(output), target,
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp a echoue : {(proc.stderr or '').strip()[-300:]}")

    path = Path(proc.stdout.strip().splitlines()[-1])
    if not path.exists():
        raise RuntimeError(f"yt-dlp n'a pas produit le fichier annonce : {path}")
    return path


def clip_video(
    target: str,
    channel_id: str,
    *,
    count: int = 6,
    topic: str = "",
    reframe: str = "blur",
    template_name: str | None = None,
    whisper_model: str = "large-v3",
    language: str | None = None,
) -> ClipJobResult:
    """Decoupe une video longue en plusieurs shorts verticaux.

    `whisper_model` vaut `large-v3` par defaut, contrairement au pipeline
    faceless : la parole reelle est bruitee, accentuee, coupee de silences,
    la ou une voix de synthese est propre. Sur GPU le surcout est modeste
    et un mauvais horodatage decale tous les extraits.
    """
    channel = get_channel(channel_id)
    source = fetch_source(target)
    job_id = f"clip-{channel_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    job = job_dir(job_id)

    step("source", fichier=source.name)
    transcript = transcribe(
        source, language=language or channel.language, model_size=whisper_model
    )
    if not transcript.words:
        raise RuntimeError("aucune parole detectee dans la source")

    (job / "transcript.txt").write_text(transcript.text, encoding="utf-8")
    step("transcription", mots=len(transcript.words), duree=f"{transcript.duration / 60:.0f}min")

    segments = select(transcript, count=count, topic=topic)
    if not segments:
        raise RuntimeError("aucun passage autonome retenu dans cette video")

    clips: list[ClipResult] = []
    for index, segment in enumerate(segments, start=1):
        template = (
            get_template(template_name)
            if template_name
            else pick_template(channel.render.templates, seed=f"{job_id}-{index}")
        )
        clips.append(
            extract(
                source,
                segment,
                job / f"clip-{index:02d}.mp4",
                cfg=channel.render,
                template=template,
                reframe=reframe,
            )
        )

    result = ClipJobResult(
        job_id=job_id,
        channel_id=channel_id,
        source=str(source),
        clips=[asdict(c) | {"path": str(c.path)} for c in clips],
    )
    (job / "result.json").write_text(
        json.dumps(
            asdict(result) | {"created_at": datetime.now(UTC).isoformat()},
            indent=2, ensure_ascii=False, default=str,
        ),
        encoding="utf-8",
    )
    step("termine", extraits=len(clips), dossier=job)
    return result
