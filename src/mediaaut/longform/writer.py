"""Ecriture d'une video longue, section par section.

Trois contraintes, toutes mesurees sur qwen3:8b plutot que supposees :

- **Le script n'est pas ecrit d'un bloc.** Le modele ne tient deja pas un
  budget de cent trente mots. On demande donc un plan, puis chaque section
  separement avec son propre budget.

- **Les schemas restent plats.** Demander en un appel le titre, la
  description, les tags et la liste des sections a produit une seule
  section et une description hors sujet. Le plan est obtenu en deux appels.

- **Ce que le modele rend est verifie, pas suppose.** Un plan d'une seule
  section et une narration de douze mots sont deux resultats qu'il faut
  detecter et redemander, pas laisser passer jusqu'au rendu.

Le debit vise est plus lent qu'en short : 160 mots par minute contre 215.
Un rythme de short tenu huit minutes devient epuisant.
"""

from __future__ import annotations

import re

from mediaaut.core.config import ChannelConfig
from mediaaut.core.logging import get_logger
from mediaaut.longform.models import SectionList, SectionPlan, SectionScript, VideoBrief
from mediaaut.script.backends import generate
from mediaaut.script.writer import _FABRICATED_FIGURE, _channel_brief

log = get_logger(__name__)

WORDS_PER_MINUTE = 160

MIN_SECTIONS = 3
MAX_SECTIONS = 8
MIN_SECTION_WORDS = 90
# Une narration sous ce seuil n'est pas une section : c'est un titre que le
# modele a rendu a la place du texte. Cas observe, et invisible jusqu'au
# rendu final si on ne le teste pas.
NOT_A_SECTION = 25

_MIN_RATIO = 0.7
_RETRIES = 2


BRIEF_SYSTEM = """You name and frame long-form videos: eight to twelve minutes \
of narration over stock footage.

Open on the question the video answers, not on a greeting and not on an \
announcement of what will be covered. Viewers who are told what is coming \
decide they already know it.

Stay on the topic you are given. Do not substitute a neighbouring topic you \
know more about.

Never invent a statistic. No percentages, speed multipliers or benchmark \
figures unless they were given to you.

The thumbnail text is not the title. It is two to four words that make someone \
stop scrolling — a tension, a claim, something they doubt. More than four \
words cannot be read at thumbnail size."""


SECTIONS_SYSTEM = """You break a video topic into sections. Output nothing but \
the sections.

Each section answers one question and hands the next a reason to exist. \
Sections that merely list things ("other considerations", "additional tips") \
are where viewers leave.

Stay on the topic you are given, and make the sections progress: a plan whose \
sections could be read in any order is not a plan."""


SECTION_SYSTEM = """You write one section of a long-form video narration. The \
text is fed to a speech synthesiser and spoken verbatim.

Write continuous prose — several paragraphs of full sentences. You are not \
writing a title, a summary, a bullet list or an outline. If your output is one \
sentence long, you have misunderstood the task.

Write only what should be heard. No section title, no "in this part", no stage \
directions, no markdown, no emoji.

You are given what came before. Continue from it: do not restate it, do not \
recap, do not announce what you are about to say. Start on the substance.

Never invent a statistic. No percentages, speed multipliers, benchmark results \
or dated facts unless they appear in what you were given.

Reaching the word budget matters as much as not exceeding it: a section well \
under budget leaves its point half-made."""


def plan(channel: ChannelConfig, topic: str, *, minutes: float = 9.0) -> tuple[
    VideoBrief, list[SectionPlan]
]:
    """Etablit le plan en deux appels : l'identite, puis le decoupage."""
    wanted = max(MIN_SECTIONS, min(MAX_SECTIONS, round(minutes / 1.6)))
    brief_instruction = (
        f"{_channel_brief(channel)}\n\n"
        f"Topic: {topic}\n\n"
        f"Frame a video of roughly {minutes:.0f} minutes on exactly this topic. "
        f"Write in {channel.language}."
    )
    brief = generate(BRIEF_SYSTEM, brief_instruction, VideoBrief)

    sections_instruction = (
        f"{_channel_brief(channel)}\n\n"
        f"Topic: {topic}\n"
        f"Video title: {brief.title}\n\n"
        f"Break this into exactly {wanted} sections, in reading order. "
        f"Write in {channel.language}."
    )
    sections = generate(SECTIONS_SYSTEM, sections_instruction, SectionList).sections

    for attempt in range(_RETRIES):
        if len(sections) >= MIN_SECTIONS:
            break
        log.info(
            "plan trop maigre (%d section(s)), nouvelle tentative %d/%d",
            len(sections), attempt + 1, _RETRIES,
        )
        sections = generate(
            SECTIONS_SYSTEM,
            f"{sections_instruction}\n\n"
            f"A previous attempt returned only {len(sections)} section(s). "
            f"Return {wanted} distinct sections, each with its own title and "
            f"its own question to answer.",
            SectionList,
        ).sections

    if len(sections) < MIN_SECTIONS:
        raise RuntimeError(
            f"le modele n'a rendu que {len(sections)} section(s) apres "
            f"{_RETRIES} tentatives ; essayer un modele plus grand ou "
            f"SCRIPT_BACKEND=anthropic"
        )

    sections = sections[:MAX_SECTIONS]
    log.info("plan : « %s » en %d section(s)", brief.title, len(sections))
    return brief, sections


def write_section(
    channel: ChannelConfig,
    brief: VideoBrief,
    section: SectionPlan,
    *,
    index: int,
    total: int,
    words: int,
    previous: str = "",
) -> SectionScript:
    """Redige une section, dans la continuite de ce qui precede."""
    context = (
        f"Video title: {brief.title}\n"
        f"Section {index + 1} of {total}: {section.title}\n"
        f"This section must establish: {section.covers}\n\n"
    )
    if index == 0:
        context += f"Open with this hook, rewritten if you can do better:\n{brief.hook}\n\n"
    else:
        # Seule la fin du precedent est transmise : le modele a besoin du
        # point de raccord, pas de tout l'historique, qui noierait la
        # consigne dans plusieurs milliers de mots.
        context += f"The previous section ended with:\n...{previous[-500:]}\n\n"

    instruction = (
        f"{_channel_brief(channel)}\n\n{context}"
        f"Write this section in {channel.language}. "
        f"Word budget: {words} words of continuous prose. "
        f"Stay within {words - 20} to {words} words."
    )
    script = generate(SECTION_SYSTEM, instruction, SectionScript)

    for attempt in range(_RETRIES):
        spoken = len(script.narration.split())
        if spoken >= words * _MIN_RATIO:
            break
        # En dessous de `NOT_A_SECTION`, le modele a rendu un titre : le lui
        # dire explicitement corrige mieux qu'une simple demande de rallonge.
        complaint = (
            "returned a single line, which is a title rather than narration"
            if spoken < NOT_A_SECTION
            else f"produced only {spoken} words against a {words}-word budget"
        )
        log.info(
            "section %d : %d mots, nouvelle tentative %d/%d",
            index + 1, spoken, attempt + 1, _RETRIES,
        )
        script = generate(
            SECTION_SYSTEM,
            f"{instruction}\n\nA previous attempt {complaint}. Write the full "
            f"spoken text: several paragraphs of continuous sentences reaching "
            f"{words} words. Develop the point — a concrete detail, a "
            f"consequence, a case where it does not hold.",
            SectionScript,
        )

    invented = _FABRICATED_FIGURE.findall(script.narration)
    if invented:
        script.narration = re.sub(
            r"\s{2,}", " ", _FABRICATED_FIGURE.sub("", script.narration)
        ).strip()
        log.warning(
            "section %d : chiffre(s) non verifie(s) retire(s) — %s",
            index + 1, ", ".join(sorted(set(invented))),
        )
    return script


def write_long(
    channel: ChannelConfig,
    topic: str,
    *,
    minutes: float = 9.0,
) -> tuple[VideoBrief, list[SectionPlan], list[SectionScript]]:
    """Produit le plan et le texte complet d'une video longue."""
    brief, sections = plan(channel, topic, minutes=minutes)
    total_words = round(minutes * WORDS_PER_MINUTE)
    per_section = max(MIN_SECTION_WORDS, total_words // len(sections))

    scripts: list[SectionScript] = []
    previous = ""
    for index, section in enumerate(sections):
        script = write_section(
            channel, brief, section,
            index=index, total=len(sections), words=per_section, previous=previous,
        )
        scripts.append(script)
        previous = script.narration
        log.info(
            "section %d/%d « %s » : %d mots",
            index + 1, len(sections), section.title, len(script.narration.split()),
        )

    spoken = sum(len(s.narration.split()) for s in scripts)
    log.info(
        "script long : %d mots, ~%.1f min (cible %.0f min)",
        spoken, spoken / WORDS_PER_MINUTE, minutes,
    )
    if spoken < total_words * _MIN_RATIO:
        log.warning(
            "script global court : %d mots pour %d vises", spoken, total_words
        )
    return brief, sections, scripts
