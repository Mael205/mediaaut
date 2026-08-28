"""Formes de sortie pour la selection d'extraits.

Transmises au modele comme schema, donc la reponse est validee avant
d'atteindre le decoupage : un horodatage manquant echoue tout de suite
plutot que de produire un extrait de duree nulle.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SegmentPick(BaseModel):
    """Un passage juge autonome dans une video longue."""

    start: float = Field(description="Debut en secondes depuis le debut de la video")
    end: float = Field(description="Fin en secondes")
    hook: str = Field(
        description=(
            "La premiere phrase reellement prononcee dans l'extrait, recopiee "
            "telle quelle depuis la transcription. Sert a verifier le calage."
        )
    )
    title: str = Field(description="Titre du short, moins de 80 caracteres")
    reason: str = Field(
        description="En une phrase : pourquoi ce passage tient debout tout seul"
    )


class SegmentBatch(BaseModel):
    segments: list[SegmentPick]
