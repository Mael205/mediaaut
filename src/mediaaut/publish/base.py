"""Interface commune aux plateformes de publication.

Chaque plateforme impose ses propres contraintes (longueur de titre, nombre
de hashtags, formats acceptes) mais le pipeline ne doit pas les connaitre.
Il produit une `VideoMeta` neutre ; chaque `Publisher` la traduit et signale
ce qu'il a du tronquer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class VideoMeta:
    """Metadonnees independantes de la plateforme."""

    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    # Reserve aux videos verticales courtes ; certaines plateformes s'en
    # servent pour router la video vers le bon onglet.
    is_short: bool = True
    # Declaration « contenu altere ou synthetique ». Vraie des qu'une voix
    # de synthese ou des images generees interviennent : la declarer coute
    # zero portee, l'omettre expose a une sanction retroactive.
    synthetic: bool = True
    made_for_kids: bool = False
    # Publication differee. Impose une visibilite privee jusqu'a l'echeance.
    publish_at: datetime | None = None
    language: str = "en"
    category_id: str = "28"      # YouTube : « Science & Technology »


@dataclass(slots=True)
class PublishResult:
    platform: str
    ok: bool
    video_id: str = ""
    url: str = ""
    # Etat reel apres publication : une plateforme peut imposer le prive
    # sans le signaler autrement (projet API non audite chez YouTube,
    # application non auditee chez TikTok).
    visibility: str = ""
    detail: str = ""


@runtime_checkable
class Publisher(Protocol):
    name: str

    def publish(self, video: Path, meta: VideoMeta) -> PublishResult: ...

    def check_auth(self) -> tuple[bool, str]:
        """(authentifie, message lisible). Ne declenche aucune publication."""
        ...


def get_publisher(name: str, channel_id: str | None = None) -> Publisher:
    """Instancie un publieur par nom, en important a la demande.

    Chaque plateforme traine ses propres dependances lourdes ; on ne veut
    pas que l'absence du SDK Google empeche de publier sur TikTok.
    """
    if name == "youtube":
        from mediaaut.publish.youtube import YouTubePublisher

        return YouTubePublisher(channel_id)
    if name == "instagram":
        from mediaaut.publish.instagram import InstagramPublisher

        return InstagramPublisher(channel_id)
    if name == "tiktok":
        from mediaaut.publish.tiktok import TikTokPublisher

        return TikTokPublisher(channel_id)
    raise ValueError(f"plateforme inconnue : {name} (youtube, instagram, tiktok)")


def truncate(text: str, limit: int) -> str:
    """Tronque sur une frontiere de mot, en signalant la coupe."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return f"{cut}…"
