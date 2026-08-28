"""Ecriture des idees et des scripts par un modele Claude.

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

from mediaaut.core.config import ChannelConfig, get_settings
from mediaaut.core.logging import get_logger
from mediaaut.script.models import IdeaBatch, IdeaDraft, ScriptDraft

log = get_logger(__name__)

MODEL = "claude-opus-5"

# Mots par minute vises pour la narration. Cale sur la mesure des references
# analysees (214 et 228 mots/minute) ; en dessous, le rythme s'affaisse.
WORDS_PER_MINUTE = 215


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=get_settings().require("anthropic_api_key"))


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

Vary the shape of the topics across the batch. If several would open the same \
way, or resolve the same way, change them."""


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

    response = _client().messages.parse(
        model=MODEL,
        max_tokens=8000,
        system=IDEA_SYSTEM,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": instruction}],
        output_format=IdeaBatch,
    )
    ideas = response.parsed_output.ideas
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

The word budget is a hard constraint, not a target to approach. Going over it \
makes the video longer than the format allows."""


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

    response = _client().messages.parse(
        model=MODEL,
        max_tokens=8000,
        system=SCRIPT_SYSTEM,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": instruction}],
        output_format=ScriptDraft,
    )
    draft = response.parsed_output

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
    return draft
