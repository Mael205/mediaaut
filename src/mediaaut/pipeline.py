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
from mediaaut.publish.base import VideoMeta
from mediaaut.render.compose import Clip, plan_clips, render_short
from mediaaut.render.templates import Template, get_template, pick_from, pick_template
from mediaaut.subtitles.ass_writer import write_ass
from mediaaut.subtitles.transcribe import align_to_script, transcribe
from mediaaut.visuals.build import build_clips
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
    broll_queries: list[str] | None = None,
    music: Path | None = None,
    whisper_model: str = "small",
    meta: VideoMeta | None = None,
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
    # Le sel decorrele le tirage de la voix de celui du template : sans lui
    # les deux changeraient ensemble et la chaine n'aurait que deux visages
    # au lieu de quatre.
    voice_id = pick_from(channel.voice.voices(), seed=job_id, salt="voice")
    step("job", id=job_id, chaine=channel_id, template=template.name, voix=voice_id)

    # 1. Voix ------------------------------------------------------------
    start = time.perf_counter()
    voice = get_provider(channel.voice.provider).synthesize(
        script,
        job / "voice.wav",
        voice_id=voice_id,
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

    # 3. B-roll ------------------------------------------------------------
    if not broll and broll_queries:
        from mediaaut.assets.photos import find_photos

        # Un plan par tranche de `shot_seconds`, plus un de marge : mieux
        # vaut un plan inutilise qu'un plan reboucle deux fois de suite.
        wanted = int(voice.duration // template.shot_seconds) + 1
        # Le vocabulaire curate de la chaine passe en tete. Pexels ne rend
        # jamais « aucun resultat » : sur une requete sans correspondance il
        # sert du contenu vaguement apparente, ce qui a donne des maillots de
        # bain sur un script traitant de memoire GPU. Les requetes du modele
        # ne viennent donc qu'en complement d'une base sure.
        queries = [*channel.broll_vocabulary[:3], *broll_queries]
        # Photos plutot que videos : sur « server room racks », la
        # recherche video de Pexels rend des gens faisant l'inventaire,
        # la recherche photo rend des baies de serveurs. Le fonds video
        # est petit et mal indexe, et depourvu de metadonnees, donc
        # impossible a filtrer.
        broll = find_photos(queries, count=max(3, wanted))

    # 4. Rendu ------------------------------------------------------------
    start = time.perf_counter()
    # Le directeur visuel place les cartes de code aux instants ou la
    # narration nomme un artefact technique, et rend le reste au b-roll.
    # Sans artefact reconnu, le resultat est celui d'avant : du b-roll
    # simplement reparti.
    clips: list[Clip] = build_clips(
        words, broll or [], job,
        width=channel.render.width,
        height=channel.render.height,
        shot_seconds=template.shot_seconds,
    )
    if not clips and broll:
        clips = plan_clips(broll, voice.duration, min_shot=template.shot_seconds)
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
    if meta is not None:
        (job / "meta.json").write_text(
            json.dumps(asdict(meta), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
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
