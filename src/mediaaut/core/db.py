"""Etat persistant : file d'idees et historique de publication.

SQLite plutot qu'un dossier de JSON : ce qu'on demande a cet etat, ce sont
des questions de recoupement — « qu'ai-je deja traite sur cette chaine »,
« quelle idee est la plus ancienne non utilisee » — et les repondre a la
main sur des fichiers revient a reecrire une base en moins fiable.

Le schema evolue via `PRAGMA user_version` : chaque migration est une etape
numerotee, appliquee une fois, dans l'ordre.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from mediaaut.core.logging import get_logger
from mediaaut.core.paths import DB_PATH

log = get_logger(__name__)

# Chaque entree est une migration appliquee une seule fois, dans l'ordre.
_MIGRATIONS: list[str] = [
    """
    CREATE TABLE ideas (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id    TEXT NOT NULL,
        title         TEXT NOT NULL,
        angle         TEXT NOT NULL DEFAULT '',
        hook          TEXT NOT NULL DEFAULT '',
        fingerprint   TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'queued',
        created_at    TEXT NOT NULL,
        used_at       TEXT,
        job_id        TEXT
    );
    CREATE UNIQUE INDEX idx_ideas_fingerprint ON ideas(channel_id, fingerprint);
    CREATE INDEX idx_ideas_status ON ideas(channel_id, status, created_at);

    CREATE TABLE publications (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id        TEXT NOT NULL,
        channel_id    TEXT NOT NULL,
        platform      TEXT NOT NULL,
        video_id      TEXT NOT NULL DEFAULT '',
        url           TEXT NOT NULL DEFAULT '',
        visibility    TEXT NOT NULL DEFAULT '',
        ok            INTEGER NOT NULL DEFAULT 0,
        detail        TEXT NOT NULL DEFAULT '',
        published_at  TEXT NOT NULL
    );
    CREATE INDEX idx_pub_job ON publications(job_id);
    CREATE UNIQUE INDEX idx_pub_once ON publications(job_id, platform);
    """,
]


def _connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, isolation_level=None)
    connection.row_factory = sqlite3.Row
    # WAL : le scheduler peut ecrire pendant qu'une commande interactive lit.
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _migrate(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    for index, statement in enumerate(_MIGRATIONS[version:], start=version):
        log.debug("migration base %d", index + 1)
        connection.executescript(statement)
        connection.execute(f"PRAGMA user_version={index + 1}")


@contextmanager
def db(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Connexion migree, refermee a la sortie du bloc."""
    connection = _connect(path)
    try:
        _migrate(connection)
        yield connection
    finally:
        connection.close()


def now() -> str:
    return datetime.now(UTC).isoformat()


def record_publication(
    *,
    job_id: str,
    channel_id: str,
    platform: str,
    ok: bool,
    video_id: str = "",
    url: str = "",
    visibility: str = "",
    detail: str = "",
) -> None:
    """Journalise une publication.

    L'index unique (job_id, platform) est la garde anti-doublon : republier
    le meme job sur la meme plateforme remplace la ligne au lieu d'en creer
    une seconde, ce qui evite de compter deux fois une re-tentative.
    """
    with db() as connection:
        connection.execute(
            """
            INSERT INTO publications
                (job_id, channel_id, platform, video_id, url, visibility, ok, detail, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, platform) DO UPDATE SET
                video_id=excluded.video_id, url=excluded.url,
                visibility=excluded.visibility, ok=excluded.ok,
                detail=excluded.detail, published_at=excluded.published_at
            """,
            (job_id, channel_id, platform, video_id, url, visibility, int(ok), detail, now()),
        )


def already_published(job_id: str, platform: str) -> bool:
    with db() as connection:
        row = connection.execute(
            "SELECT ok FROM publications WHERE job_id=? AND platform=? AND ok=1",
            (job_id, platform),
        ).fetchone()
    return row is not None
