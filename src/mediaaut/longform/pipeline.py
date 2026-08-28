"""Orchestration d'une video longue, du sujet au fichier publiable.

Chaque section est menee jusqu'a son rendu avant de passer a la suivante.
Une video de neuf minutes represente une dizaine de minutes de calcul et
plusieurs centaines de mega-octets de b-roll : un echec en fin de parcours
ne doit pas obliger a tout refaire, donc les sections deja rendues restent
sur le disque.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from mediaaut.core.config import ChannelConfig, get_channel
from mediaaut.core.logging import get_logger, step
from mediaaut.core.paths import job_dir
from mediaaut.longform import thumbnail
from mediaaut.longform.compose import build_chapters, concat_sections, render_section
from mediaaut.longform.models import SectionScript, VideoBrief
from mediaaut.longform.writer import write_long
from mediaaut.publish.base import VideoMeta
from mediaaut.voice.base import get_provider

log = get_logger(__name__)


@dataclass(slots=True)
class LongResult:
    job_id: str
    channel_id: str
    video_path: str
    thumbnail_path: str
    duration: float
    sections: int
    words: int
    chapters: list[str] = field(default_factory=list)


def _description(brief: VideoBrief, chapters: list[str]) -> str:
    """Description YouTube, chapitres inclus.

    Les chapitres ne sont pas un champ d'API : YouTube les deduit de la
    description, a condition que le premier commence a `0:00` et qu'il y en
    ait au moins trois. Les placer en tete les rend aussi visibles au
    spectateur qui deroule.
    """
    body = brief.description.strip()
    if len(chapters) >= 3:
        body = f"{body}\n\n" + "\n".join(chapters)
    return body


def make_long(
    channel_id: str,
    topic: str,
    *,
    minutes: float = 9.0,
    music: Path | None = None,
    burn_subtitles: bool = False,
    whisper_model: str = "small",
) -> LongResult:
    """Produit une video longue horizontale sur `topic`.

    `burn_subtitles` est faux par defaut : en long-form, YouTube genere ses
    propres sous-titres et le spectateur regarde souvent avec le son. Les
    incruster coute une transcription par section sans benefice evident.
    """
    channel: ChannelConfig = get_channel(channel_id)
    job_id = f"long-{channel_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    job = job_dir(job_id)

    step("sujet", titre=topic, duree=f"{minutes:.0f}min")
    brief, section_plans, scripts = write_long(channel, topic, minutes=minutes)

    voice = get_provider(channel.voice.provider)
    rendered: list[Path] = []
    first_clip: Path | None = None
    durations: list[float] = []

    for index, (plan_section, script) in enumerate(
        zip(section_plans, scripts, strict=True), start=1
    ):
        section_path = job / f"section-{index:02d}.mp4"
        if section_path.exists():
            log.info("section %d deja rendue, conservee", index)
            rendered.append(section_path)
            durations.append(ffmpeg_duration(section_path))
            continue

        step(f"section {index}/{len(scripts)}", titre=plan_section.title)
        result = voice.synthesize(
            script.narration,
            job / f"section-{index:02d}.wav",
            voice_id=channel.voice.voice_id,
            speed=channel.voice.speed,
            lang=channel.language,
        )

        clips = _fetch_broll(script, result.duration, plan_section.title)
        if first_clip is None and clips:
            first_clip = clips[0]
        words = None
        if burn_subtitles:
            from mediaaut.subtitles.transcribe import align_to_script, transcribe

            transcript = transcribe(
                result.path, language=channel.language, model_size=whisper_model
            )
            words = align_to_script(transcript.words, script.narration)

        render_section(
            section_path, result.path, result.duration, clips,
            words=words, subtitle_style="clean",
        )
        rendered.append(section_path)
        durations.append(result.duration)

    video_path = concat_sections(rendered, job / "video.mp4", music=music)
    chapters = [
        c.formatted()
        for c in build_chapters([s.title for s in section_plans], durations)
    ]

    # L image de fond vient d un plan de b-roll brut, pas de la video
    # finale : celle-ci porte les sous-titres incrustes, qui se
    # retrouveraient dans la miniature et la rendraient illisible.
    thumb = thumbnail.build(
        first_clip or video_path, job / "thumbnail.jpg", brief.thumbnail_text
    )

    total_words = sum(len(s.narration.split()) for s in scripts)
    meta = VideoMeta(
        title=brief.title,
        description=_description(brief, chapters),
        tags=brief.tags,
        is_short=False,
        language=channel.language,
    )
    (job / "meta.json").write_text(
        json.dumps(asdict(meta), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (job / "script.txt").write_text(
        "\n\n".join(s.narration for s in scripts), encoding="utf-8"
    )

    result = LongResult(
        job_id=job_id,
        channel_id=channel_id,
        video_path=str(video_path),
        thumbnail_path=str(thumb),
        duration=sum(durations),
        sections=len(scripts),
        words=total_words,
        chapters=chapters,
    )
    (job / "result.json").write_text(
        json.dumps(
            asdict(result) | {"created_at": datetime.now(UTC).isoformat()},
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    step(
        "termine",
        duree=f"{result.duration / 60:.1f}min",
        mots=total_words,
        fichier=video_path,
    )
    return result


def _fetch_broll(script: SectionScript, duration: float, title: str = "") -> list[Path]:
    """Recupere le b-roll d'une section, sans faire echouer le rendu.

    Une section sans image tombe sur le degrade anime ; une section qui
    interrompt toute la video parce qu'une requete a echoue coute bien plus
    cher que quelques secondes de fond uni.

    Le titre de section sert de repli quand le modele n'a rendu aucune
    requete : c'est arrive, et le resultat etait une video entiere en fond
    uni, sans le moindre avertissement.
    """
    from mediaaut.longform.compose import SHOT_SECONDS

    # Le modele rend volontiers la question de la section a la place d'une
    # scene filmable (« what is the difference between a successful API
    # response and a completed action? »). Une banque de video ne repond pas
    # a des questions : ces requetes ramenent n'importe quoi.
    queries = [
        q.strip() for q in script.broll_queries
        if q.strip() and not q.strip().endswith("?") and len(q.split()) <= 5
    ]
    if not queries and title:
        log.warning("aucune requete de b-roll exploitable, repli sur « %s »", title)
        # Le titre est ramene a quatre mots : au-dela, une banque de video
        # ne trouve plus rien de pertinent.
        queries = [" ".join(w for w in title.split() if w.isalnum() or w.isalpha())[:60]]
        queries = [" ".join(queries[0].split()[:4])]
    if not queries:
        return []
    try:
        from mediaaut.assets.broll import find_broll

        wanted = max(2, round(duration / SHOT_SECONDS))
        return find_broll(queries, count=wanted, portrait=False)
    except Exception as exc:
        log.warning("b-roll indisponible pour cette section (%s), fond uni", exc)
        return []


def ffmpeg_duration(path: Path) -> float:
    from mediaaut.core import ffmpeg

    return ffmpeg.duration(path)
