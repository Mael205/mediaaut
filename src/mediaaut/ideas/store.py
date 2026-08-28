"""File d'idees par chaine, avec garde anti-repetition.

L'anti-repetition n'est pas un confort : la politique « Inauthentic Content »
de YouTube vise le contenu repetitif, et deux videos qui disent la meme chose
sous deux titres differents comptent comme telles. La garde travaille a deux
niveaux — une empreinte lexicale qui bloque les quasi-doublons a l'insertion,
et l'historique recent passe au modele pour qu'il evite de les proposer.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime

from mediaaut.core.db import db, now
from mediaaut.core.logging import get_logger

log = get_logger(__name__)

# Mots trop frequents pour porter du sens dans une empreinte de titre.
_STOPWORDS = frozenset(
    """
    a an the this that these those and or but of for to in on at by with from as is are was
    were be been being it its your you my our their how what why when who which do does did
    not no yes if then than so such very just really le la les un une des du de et ou mais
    pour dans sur avec sans par est sont etre ete ce cet cette ces mon ton son notre votre
    leur qui que quoi comment pourquoi quand ne pas plus moins tres vraiment
    """.split()
)


@dataclass(slots=True)
class Idea:
    id: int
    channel_id: str
    title: str
    angle: str
    hook: str
    status: str
    created_at: str


# Suffixes retires pour ramener les flexions a une racine commune, du plus
# long au plus court : sans cela « automated » et « automating » restent deux
# mots distincts et deux titres qui disent la meme chose passent la garde.
# « ers » et « er » sont volontairement absents : ils raciniseraient
# « renders » en « rend » alors que « rendering » donne « render », donc ils
# separent justement les formes qu'on cherche a rapprocher.
_SUFFIXES = (
    "ements", "ement", "ations", "ation", "ingly", "edly", "ing", "ies", "ed",
    "ly", "ment", "ance", "ence", "s",
)
_MIN_STEM = 4


def _stem(word: str) -> str:
    """Racinisation grossiere, suffisante pour comparer des titres.

    Volontairement approximative : on ne cherche pas la forme linguistique
    juste, seulement a ce que deux flexions du meme mot se rencontrent.
    """
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM:
            word = word[: -len(suffix)]
            break
    # « running » -> « runn » -> « run » : sans cela la consonne doublee du
    # participe empeche la rencontre avec la forme simple. Le seuil est a 3
    # et non a `_MIN_STEM`, sinon une racine de quatre lettres comme « runn »
    # passe entre les mailles — c'est precisement le cas a traiter.
    if len(word) > 3 and word[-1] == word[-2]:
        word = word[:-1]
    return word


def _tokens(title: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", title.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return {
        _stem(w)
        for w in re.findall(r"[a-z0-9']+", folded)
        if w not in _STOPWORDS and len(w) > 2
    }


def fingerprint(title: str) -> str:
    """Empreinte lexicale d'un titre : racines significatives, triees.

    Sert de garde exacte a l'insertion — elle n'attrape que les titres qui
    portent exactement le meme vocabulaire. Le recouvrement partiel est
    traite separement par `similarity`.
    """
    return " ".join(sorted(_tokens(title)))


def similarity(left: str, right: str) -> float:
    """Recouvrement de Jaccard entre deux titres, entre 0 et 1."""
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# Au-dela de ce recouvrement, deux titres racontent la meme chose meme
# formules differemment. Regle assez bas : une idee ecartee a tort ne coute
# rien, un doublon publie coute une video repetitive de plus sur la chaine.
SIMILARITY_THRESHOLD = 0.55

# Nombre maximal d'idees en attente partageant le meme premier mot. Les
# modeles produisent volontiers six titres commencant par « Why » ; le leur
# interdire dans le prompt ne suffit pas, alors on l'applique ici. Une chaine
# dont tous les titres s'ouvrent pareil affiche sa fabrication en serie.
MAX_SAME_OPENING = 2


def _opening(title: str) -> str:
    words = re.findall(r"[\w']+", title.lower())
    return words[0] if words else ""


def add_ideas(channel_id: str, ideas: list[dict]) -> tuple[int, int]:
    """Insere des idees. Retourne (ajoutees, ignorees car deja couvertes).

    Deux gardes successives : l'empreinte exacte, portee par un index unique
    en base, et le recouvrement partiel avec les titres deja presents. La
    seconde compare aussi les idees du lot entre elles, sans quoi un meme
    appel pourrait inserer deux formulations d'un seul sujet.
    """
    known = recent_titles(channel_id, limit=400)
    openings: dict[str, int] = {}
    for title in (i.title for i in list_ideas(channel_id, status="queued", limit=400)):
        openings[_opening(title)] = openings.get(_opening(title), 0) + 1
    added = skipped = 0

    with db() as connection:
        for idea in ideas:
            title = (idea.get("title") or "").strip()
            if not title:
                continue

            close = max(
                ((similarity(title, other), other) for other in known),
                default=(0.0, ""),
            )
            if close[0] >= SIMILARITY_THRESHOLD:
                log.info(
                    "idee ecartee (%.0f%% de recouvrement avec « %s ») : %s",
                    close[0] * 100, close[1], title,
                )
                skipped += 1
                continue

            opening = _opening(title)
            if openings.get(opening, 0) >= MAX_SAME_OPENING:
                log.info(
                    "idee ecartee (%d titres commencent deja par « %s ») : %s",
                    openings[opening], opening, title,
                )
                skipped += 1
                continue

            cursor = connection.execute(
                """
                INSERT INTO ideas (channel_id, title, angle, hook, fingerprint, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel_id, fingerprint) DO NOTHING
                """,
                (
                    channel_id,
                    title,
                    (idea.get("angle") or "").strip(),
                    (idea.get("hook") or "").strip(),
                    fingerprint(title),
                    now(),
                ),
            )
            if cursor.rowcount:
                added += 1
                known.append(title)      # compare le reste du lot a celle-ci
                openings[opening] = openings.get(opening, 0) + 1
            else:
                skipped += 1

    log.info("%d idee(s) ajoutee(s), %d ecartee(s) comme deja couverte(s)", added, skipped)
    return added, skipped


def _row_to_idea(row) -> Idea:
    return Idea(
        id=row["id"], channel_id=row["channel_id"], title=row["title"],
        angle=row["angle"], hook=row["hook"], status=row["status"],
        created_at=row["created_at"],
    )


def next_idea(channel_id: str) -> Idea | None:
    """Idee en attente la plus ancienne, sans la consommer."""
    with db() as connection:
        row = connection.execute(
            "SELECT * FROM ideas WHERE channel_id=? AND status='queued'"
            " ORDER BY created_at LIMIT 1",
            (channel_id,),
        ).fetchone()
    return _row_to_idea(row) if row else None


def mark_used(idea_id: int, job_id: str) -> None:
    with db() as connection:
        connection.execute(
            "UPDATE ideas SET status='used', used_at=?, job_id=? WHERE id=?",
            (now(), job_id, idea_id),
        )


def list_ideas(channel_id: str, status: str | None = None, limit: int = 50) -> list[Idea]:
    query = "SELECT * FROM ideas WHERE channel_id=?"
    params: list = [channel_id]
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with db() as connection:
        return [_row_to_idea(r) for r in connection.execute(query, params)]


def recent_titles(channel_id: str, limit: int = 60) -> list[str]:
    """Titres deja en base, du plus recent au plus ancien.

    Transmis au modele comme terrain deja couvert. La borne evite de gonfler
    le prompt indefiniment : au-dela de quelques dizaines de titres, le
    modele ne les distingue plus utilement.
    """
    with db() as connection:
        rows = connection.execute(
            "SELECT title FROM ideas WHERE channel_id=? ORDER BY created_at DESC LIMIT ?",
            (channel_id, limit),
        ).fetchall()
    return [r["title"] for r in rows]


def counts(channel_id: str) -> dict[str, int]:
    with db() as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) AS n FROM ideas WHERE channel_id=? GROUP BY status",
            (channel_id,),
        ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def prune_used(channel_id: str, keep_days: int = 365) -> int:
    """Supprime les idees utilisees anciennes, en gardant les recentes.

    Les idees utilisees restent la garde anti-repetition ; on ne les efface
    qu'au-dela d'un an, quand reprendre un sujet redevient legitime.
    """
    cutoff = datetime.now(UTC).timestamp() - keep_days * 86400
    with db() as connection:
        rows = connection.execute(
            "SELECT id, used_at FROM ideas WHERE channel_id=? AND status='used'", (channel_id,)
        ).fetchall()
        stale = [
            r["id"] for r in rows
            if r["used_at"] and datetime.fromisoformat(r["used_at"]).timestamp() < cutoff
        ]
        for idea_id in stale:
            connection.execute("DELETE FROM ideas WHERE id=?", (idea_id,))
    return len(stale)
