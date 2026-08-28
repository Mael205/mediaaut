"""Formes de sortie attendues du modele.

Ces classes ne sont pas de la documentation : elles sont transmises a
`client.messages.parse()` comme schema de sortie, donc la reponse est
validee avant d'arriver au pipeline. Un champ manquant devient une erreur
immediate plutot qu'un `KeyError` trois etapes plus loin.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class IdeaDraft(BaseModel):
    """Un sujet de video, avant ecriture."""

    title: str = Field(description="Titre de travail, court et concret")
    angle: str = Field(
        description="En une phrase : l'affirmation precise et verifiable que la video defend"
    )
    hook: str = Field(description="Premiere phrase prononcee, moins de 12 mots")


class IdeaBatch(BaseModel):
    ideas: list[IdeaDraft]


class ScriptDraft(BaseModel):
    """Un script pret a etre synthetise, et ses metadonnees de publication."""

    narration: str = Field(
        description=(
            "Le texte a lire a voix haute, d'un seul tenant. Pas de didascalies, "
            "pas de noms de locuteur, pas de marqueurs de section : tout ce qui "
            "est ici sera prononce tel quel."
        )
    )
    title: str = Field(description="Titre de la video, 100 caracteres maximum")
    description: str = Field(description="Description, 2 a 4 phrases")
    tags: list[str] = Field(description="5 a 12 mots-cles, sans le caractere #")
    broll_queries: list[str] = Field(
        description=(
            "3 a 6 requetes en anglais pour chercher des plans de banque. "
            "Des scenes filmables et concretes, jamais des concepts abstraits."
        )
    )
