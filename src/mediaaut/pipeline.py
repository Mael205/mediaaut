"""Orchestration : d'un script ecrit a un MP4 pret a publier.

Chaque etape ecrit son resultat dans le dossier du job. Cela coute quelques
fichiers intermediaires mais permet d'inspecter un rendu rate etape par
etape, et de reprendre un job sans tout recalculer.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from mediaaut.assets.fonts import ensure_fonts
from mediaaut.core.config import ChannelConfig, get_channel
from mediaaut.core.logging import get_logger, step
from mediaaut.core.paths import job_dir
from mediaaut.render.compose import Clip, plan_clips, render_short
from mediaaut.render.templates import Template, get_template, pick_template
from mediaaut.subtitles.ass_writer import write_ass
from mediaaut.subtitles.transcribe import align_to_script, transcribe
from mediaaut.voice.base import get_provider

log = get_logger(__name__)


@dataclass(slots=True)
class ShortResult:
    job_id: str
    channel_id: str
    video_path: str
    duration: float
    template: str
    voice_id: str
    word_count: int
    timings: dict[str, float] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        payload = asdict(self) | {"created_at": datetime.now(UTC).isoformat()}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _new_job_id(channel_id: str) -> str:
    return f"{channel_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def make_short(
    channel_id: str,
    script: str,
    *,
    job_id: str | None = None,
    template_name: str | None = None,
    broll: list[Path] | None = None,
    music: Path | None = None,
    whisper_model: str = "small",
) -> ShortResult:
    """Produit un short vertical a partir d'un script deja ecrit."""
    script = " ".join(script.split())
    if not script:
        raise ValueError("script vide")

    channel: ChannelConfig = get_channel(channel_id)
    job_id = job_id or _new_job_id(channel_id)
    job = job_dir(job_id)
    timings: dict[str, float] = {}

    template: Template = (
        get_template(template_name)
        if template_name
        else pick_template(channel.render.templates, seed=job_id)
    )
    step("job", id=job_id, chaine=channel_id, template=template.name)

    # 1. Voix ------------------------------------------------------------
    start = time.perf_counter()
    voice = get_provider(channel.voice.provider).synthesize(
        script,
        job / "voice.wav",
        voice_id=channel.voice.voice_id,
        speed=channel.voice.speed,
        lang=channel.language,
    )
    timings["voice"] = time.perf_counter() - start

    # 2. Sous-titres cales sur la voix ------------------------------------
    start = time.perf_counter()
    transcript = transcribe(voice.path, language=channel.language, model_size=whisper_model)
    words = align_to_script(transcript.words, script)
    write_ass(
        words,
        job / "subs.ass",
        style=template.subtitle_style,
        width=channel.render.width,
        height=channel.render.height,
        safe_bottom=template.subtitle_anchor,
        max_chars=template.max_chars,
    )
    timings["subtitles"] = time.perf_counter() - start

    # 3. Rendu ------------------------------------------------------------
    start = time.perf_counter()
    clips: list[Clip] = plan_clips(broll, voice.duration) if broll else []
    render_short(
        out_path=job / "short.mp4",
        voice_path=voice.path,
        duration=voice.duration,
        cfg=channel.render,
        template=template,
        clips=clips,
        subtitles_path=job / "subs.ass",
        fonts_dir=ensure_fonts(),
        music_path=music,
    )
    timings["render"] = time.perf_counter() - start

    (job / "script.txt").write_text(script, encoding="utf-8")
    result = ShortResult(
        job_id=job_id,
        channel_id=channel_id,
        video_path=str(job / "short.mp4"),
        duration=voice.duration,
        template=template.name,
        voice_id=voice.voice_id,
        word_count=len(words),
        timings={k: round(v, 2) for k, v in timings.items()},
    )
    result.save(job / "result.json")
    step(
        "termine",
        duree=f"{voice.duration:.1f}s",
        rendu=f"{sum(timings.values()):.1f}s",
        fichier=job / "short.mp4",
    )
    return result
