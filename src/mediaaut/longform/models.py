"""Formes de sortie pour la production longue.

Deux principes, tous deux tires de ce qui a rate en essayant plus simple :

- **Le script n'est pas demande d'un bloc.** Un modele local peine deja a
  tenir un budget de cent trente mots ; lui en reclamer treize cents produit
  un texte tronque. On demande donc un plan, puis chaque section separement.

- **Les schemas restent plats.** Un schema melangeant champs libres et liste
  d'objets fait decrocher un modele de huit milliards de parametres : il a
  rendu une seule section et une description hors sujet. Le plan est donc
  obtenu en deux appels, chacun portant une seule forme.

Les frontieres de section deviennent au passage les chapitres YouTube.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VideoBrief(BaseModel):
    """L'identite de la video : tout sauf le decoupage en sections."""

    title: str = Field(description="Titre de la video, moins de 90 caracteres")
    hook: str = Field(
        description=(
            "Les deux premieres phrases prononcees. Elles posent la question a "
            "laquelle la video repond, sans annoncer le plan."
        )
    )
    description: str = Field(description="Description YouTube, 3 a 5 phrases")
    tags: list[str] = Field(description="8 a 15 mots-cles, sans le caractere #")
    thumbnail_text: str = Field(
        description="2 a 4 mots pour la miniature, tres lisibles en vignette"
    )


class SectionPlan(BaseModel):
    """Une section du plan, avant redaction."""

    title: str = Field(description="Titre de chapitre, moins de 50 caracteres")
    covers: str = Field(
        description="En une phrase : ce que cette section etablit, et rien d'autre"
    )


class SectionList(BaseModel):
    sections: list[SectionPlan]


class SectionScript(BaseModel):
    """Le texte prononce d'une section."""

    narration: str = Field(
        description=(
            "Plusieurs paragraphes de prose continue, a lire a voix haute. "
            "Ce n'est ni un titre ni un resume : c'est le texte integral que "
            "la voix prononcera pour cette section."
        )
    )
    # `min_length` devient `minItems` dans le schema JSON, que le decodage
    # contraint d'Ollama respecte. Sans cette borne le modele rend une liste
    # vide, et la section entiere tombe sur le fond uni sans rien signaler.
    broll_queries: list[str] = Field(
        min_length=2,
        max_length=4,
        description=(
            "2 a 4 requetes de recherche en anglais, de deux a quatre mots "
            "chacune, decrivant une scene qu'une camera pourrait filmer."
        ),
    )
