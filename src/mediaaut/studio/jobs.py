"""Inventaire des videos rendues et de leur etat de publication.

Sert la console locale. Lit `data/out/` plutot qu'une table dediee : le
dossier de job est deja la source de verite du pipeline, et le derive dans
une seconde structure creerait deux etats a garder d'accord.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from mediaaut.core.db import db
from mediaaut.core.logging import get_logger
from mediaaut.core.paths import OUT

log = get_logger(__name__)

# Plateforme fictive enregistree quand la mise en ligne a ete faite a la
# main sur youtube.com. Distincte de `youtube` (upload par API) pour que
# l'historique dise laquelle des deux voies a servi.
MANUAL_YOUTUBE = "youtube-manual"


@dataclass(slots=True)
class RenderedJob:
    job_id: str
    channel_id: str
    video_path: Path
    duration: float
    template: str
    created_at: str
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    script: str = ""
    published_on: list[str] = field(default_factory=list)

    @property
    def size_mb(self) -> float:
        return self.video_path.stat().st_size / 1e6 if self.video_path.exists() else 0.0

    @property
    def ready(self) -> bool:
        """Une video est prete si le fichier existe et porte un titre."""
        return self.video_path.exists() and bool(self.title)

    @property
    def hashtags(self) -> str:
        return " ".join(f"#{t.replace(' ', '')}" for t in self.tags)


def _published_platforms() -> dict[str, list[str]]:
    with db() as connection:
        rows = connection.execute(
            "SELECT job_id, platform FROM publications WHERE ok=1"
        ).fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row["job_id"], []).append(row["platform"])
    return result


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("%s illisible : %s", path.name, exc)
        return {}


def scan(channel_id: str | None = None) -> list[RenderedJob]:
    """Toutes les videos rendues, la plus recente d'abord."""
    published = _published_platforms()
    jobs: list[RenderedJob] = []

    for folder in sorted(OUT.iterdir(), reverse=True):
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        result = _read_json(folder / "result.json")
        if not result:
            continue
        if channel_id and result.get("channel_id") != channel_id:
            continue

        meta = _read_json(folder / "meta.json")
        script_file = folder / "script.txt"
        jobs.append(
            RenderedJob(
                job_id=result.get("job_id", folder.name),
                channel_id=result.get("channel_id", ""),
                video_path=folder / "short.mp4",
                duration=float(result.get("duration", 0.0)),
                template=result.get("template", ""),
                created_at=result.get("created_at", ""),
                title=meta.get("title", ""),
                description=meta.get("description", ""),
                tags=meta.get("tags", []) or [],
                script=script_file.read_text(encoding="utf-8") if script_file.exists() else "",
                published_on=published.get(folder.name, []),
            )
        )
    return jobs


def pending(channel_id: str | None = None, platform: str = MANUAL_YOUTUBE) -> list[RenderedJob]:
    """Videos pretes et pas encore mises en ligne sur `platform`.

    Les plus anciennes d'abord : une file de mise en ligne se vide dans
    l'ordre de production, sans quoi les premieres videos vieillissent
    pendant qu'on publie les dernieres.
    """
    return [
        job
        for job in reversed(scan(channel_id))
        if job.ready and platform not in job.published_on
    ]
