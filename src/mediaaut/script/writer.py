"""Ecriture des idees et des scripts, quel que soit le moteur configure.

Deux contraintes gouvernent ces prompts, toutes deux mesurees plutot que
supposees :

- **Le debit.** L'analyse de deux shorts narratifs a tres forte audience
  donne 214 et 228 mots par minute. C'est nettement au-dessus du debit
  naturel d'une lecture posee ; un script ecrit sans cible de longueur
  produit une video deux fois trop longue pour sa duree visee.

- **La repetition.** La politique « Inauthentic Content » de YouTube vise
  le contenu de modele, sans variation. Les titres deja traites sont donc
  transmis a chaque appel comme terrain a eviter, et l'angle editorial de
  la chaine est impose plutot que suggere.
"""

from __future__ import annotations

import re

from mediaaut.core.config import ChannelConfig
from mediaaut.core.logging import get_logger
from mediaaut.script.backends import generate
from mediaaut.script.models import IdeaBatch, IdeaDraft, ScriptDraft

log = get_logger(__name__)

# Mots par minute vises pour la narration. Cale sur la mesure des references
# analysees (214 et 228 mots/minute) ; en dessous, le rythme s'affaisse.
WORDS_PER_MINUTE = 215

# Un script qui n'atteint pas cette fraction du budget est redemande. Les
# modeles locaux sous-tirent regulierement de 30 a 40 %.
_MIN_LENGTH_RATIO = 0.8
_LENGTH_RETRIES = 2

# Chiffres de performance qu'un modele produit sans les avoir mesures :
# « 4x plus rapide », « 30 % de gain ». Les pourcentages et multiplicateurs
# sont les seuls vises ; une annee ou une taille de fichier restent legitimes.
_FABRICATED_FIGURE = re.compile(
    r"\s*\d+(?:[.,]\d+)?\s*(?:%|percent\b|x\b|times faster|times slower)",
    re.I,
)


def target_words(seconds: float) -> int:
    return max(20, round(seconds * WORDS_PER_MINUTE / 60))


def _channel_brief(channel: ChannelConfig) -> str:
    return (
        f"Channel: {channel.name}\n"
        f"Language: {channel.language}\n"
        f"Niche: {channel.niche}\n"
        f"Editorial angle (binding, not a suggestion):\n{channel.angle.strip()}"
    )


IDEA_SYSTEM = """You generate video topics for a single short-form channel.

Every topic must make one concrete, falsifiable claim — something that could \
be shown to be wrong. Reject anything that reduces to a category label \
("AI is changing everything"), a listicle, or a topic whose whole content is \
its own title.

You will be given the topics this channel has already covered. Treat them as \
exhausted ground. A topic that merely rephrases one of them is a failure, even \
if the wording differs: what matters is whether a viewer would feel they had \
seen it before.

Vary the shape of the topics across the batch. At most two may begin with the \
same word. A batch whose titles all open identically reads as template output.

Never invent a statistic. Do not write percentages, speed multipliers, time \
savings or benchmark figures unless they were given to you. A topic that hinges \
on a number you made up is worse than useless: it will be published as fact and \
it will be wrong. Make the claim qualitative instead — what changes, and why."""


def generate_ideas(
    channel: ChannelConfig,
    count: int = 8,
    *,
    avoid: list[str] | None = None,
    steer: str = "",
) -> list[IdeaDraft]:
    """Propose `count` sujets pour une chaine, en evitant ceux deja traites."""
    covered = "\n".join(f"- {t}" for t in (avoid or [])) or "(nothing yet)"
    instruction = (
        f"{_channel_brief(channel)}\n\n"
        f"Topics already covered on this channel:\n{covered}\n\n"
        f"Propose {count} new topics that do not overlap with the list above."
    )
    if steer:
        instruction += f"\n\nAdditional direction from the operator: {steer}"

    ideas = generate(IDEA_SYSTEM, instruction, IdeaBatch).ideas
    log.info("%d idee(s) proposee(s) pour %s", len(ideas), channel.id)
    return ideas


SCRIPT_SYSTEM = """You write narration for short-form videos. The text you \
produce is fed directly to a speech synthesiser and spoken verbatim.

Because every word is spoken:
- Write only what should be heard. No stage directions, no speaker labels, no \
section headings, no emoji, no markdown, no parentheses containing asides.
- Write numbers, symbols and units the way they are said aloud.
- Prefer short sentences. The listener cannot re-read.

Structure, in order:
1. A first sentence that states the surprising thing directly. Do not warm up, \
do not greet, do not announce what the video will cover.
2. The substance: the specific claim, and the concrete detail that supports it.
3. A last line that lands the point. Never ask for likes, follows or comments.

Never invent a statistic. No percentages, speed multipliers, benchmark results \
or dated facts unless they appear in the material you were given. If a number \
would strengthen the script but you do not have it, write the sentence without \
it. An invented figure is published as fact and is wrong.

The word budget is a hard constraint, not a target to approach. Reaching it \
matters as much as not exceeding it: a script well under budget produces a \
video far shorter than the format intends."""


def write_script(
    channel: ChannelConfig,
    idea: IdeaDraft,
    *,
    seconds: float = 38.0,
) -> ScriptDraft:
    """Redige le script d'une video a partir d'une idee."""
    words = target_words(seconds)
    instruction = (
        f"{_channel_brief(channel)}\n\n"
        f"Topic: {idea.title}\n"
        f"The claim this video defends: {idea.angle}\n"
        f"Suggested opening line (rewrite it if you can do better): {idea.hook}\n\n"
        f"Write the narration in {channel.language}. "
        f"Word budget: {words} words, for roughly {seconds:.0f} seconds of speech. "
        f"Stay within {words - 10} to {words} words.\n\n"
        "Also produce the title, description, tags, and the stock-footage search "
        "queries. The queries are used to find real filmed footage, so each one "
        "must describe something a camera could point at."
    )

    draft = generate(SCRIPT_SYSTEM, instruction, ScriptDraft)

    # Les modeles locaux visent regulierement 60 a 70 % du budget demande, ce
    # qui donne une video nettement plus courte que prevu. Le redire dans le
    # prompt initial n'y change rien ; le reclamer avec l'ecart mesure, si.
    for attempt in range(_LENGTH_RETRIES):
        spoken = len(draft.narration.split())
        if spoken >= words * _MIN_LENGTH_RATIO:
            break
        log.info(
            "script trop court (%d mots pour %d), nouvelle tentative %d/%d",
            spoken, words, attempt + 1, _LENGTH_RETRIES,
        )
        draft = generate(
            SCRIPT_SYSTEM,
            f"{instruction}\n\n"
            f"A previous attempt produced only {spoken} words, which is far short "
            f"of the {words}-word budget and would make the video roughly "
            f"{words / max(spoken, 1):.1f} times shorter than intended. Develop the "
            f"substance further — a second concrete detail, a consequence, a case "
            f"where it does not hold — until the narration reaches {words} words.",
            ScriptDraft,
        )

    # Les chiffres fabriques survivent a l'instruction : les modeles locaux
    # ecrivent « 4x plus rapide » sans rien avoir mesure. On les retire du
    # texte plutot que de les publier comme des faits.
    invented = _FABRICATED_FIGURE.findall(draft.narration)
    if invented:
        draft.narration = _FABRICATED_FIGURE.sub("", draft.narration)
        draft.narration = re.sub(r"\s{2,}", " ", draft.narration).strip()
        log.warning(
            "chiffre(s) non verifie(s) retire(s) du script : %s",
            ", ".join(sorted(set(invented))),
        )

    spoken = len(draft.narration.split())
    log.info(
        "script ecrit : %d mots (cible %d), ~%.0fs, %d requete(s) b-roll",
        spoken, words, spoken / WORDS_PER_MINUTE * 60, len(draft.broll_queries),
    )
    if spoken > words * 1.25:
        log.warning(
            "script %d%% plus long que la cible ; la video depassera la duree visee",
            round((spoken / words - 1) * 100),
        )
    elif spoken < words * _MIN_LENGTH_RATIO:
        log.warning(
            "script encore court apres %d tentatives : %d mots pour %d",
            _LENGTH_RETRIES, spoken, words,
        )
    return draft
