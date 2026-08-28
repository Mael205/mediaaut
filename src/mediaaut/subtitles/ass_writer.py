"""Generation de sous-titres ASS animes mot par mot.

Le format ASS rendu par libass (integre a ffmpeg) suffit largement pour du
karaoke short-form, pour un cout de rendu sans commune mesure avec une
composition navigateur type Remotion : pas de Chromium, pas de capture
image par image, le texte est incruste pendant l'encodage.

Technique : une cue affiche N mots ; on emet une ligne Dialogue par mot
actif, couvrant sa fenetre temporelle, ou seul ce mot porte la couleur
d'accent. libass superpose les lignes, l'oeil voit un surlignage qui suit
la voix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from mediaaut.subtitles.transcribe import Word


def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    """ASS encode les couleurs en &HAABBGGRR : bleu et rouge sont inverses
    par rapport a l'hexa web, d'ou la conversion explicite."""
    h = hex_rgb.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}"


@dataclass(slots=True)
class SubtitleStyle:
    """Apparence d'un preset de sous-titres."""

    font: str = "Anton"
    size: int = 140              # taille de repli si la mesure echoue
    primary: str = "FFFFFF"      # couleur du texte au repos
    accent: str = "FFE14D"       # couleur du mot en cours
    outline_color: str = "000000"
    outline: float = 9.0
    shadow: float = 3.0
    border_style: int = 1        # 1 = contour, 3 = boite opaque
    back_color: str = "000000"
    back_alpha: int = 0x80
    uppercase: bool = True
    accent_scale: int = 112      # agrandissement du mot actif, en pourcent
    alignment: int = 2           # 2 = bas-centre (pave numerique ASS)

    # Chaque cue est redimensionnee pour occuper cette fraction de la
    # largeur du cadre. Une taille fixe donne des lignes courtes minuscules
    # et des lignes longues qui debordent ; l'ajustement par cue est ce qui
    # produit le rendu « plein cadre » attendu en short-form.
    # Palette parcourue d'une cue a l'autre. Quand elle est definie, c'est
    # la cue entiere qui prend la couleur et le mot actif ne se distingue
    # plus que par son agrandissement. C'est le parti pris des chaines
    # narratives a forte audience : la couleur rythme le recit au lieu de
    # pointer un mot.
    cue_palette: tuple[str, ...] = ()

    fit_width: float = 0.82
    # Hauteur des capitales visee, en fraction de la hauteur du cadre. Borne
    # les cues d'un ou deux mots courts, que l'ajustement en largeur seul
    # ferait grimper a des tailles absurdes.
    fit_height: float = 0.105
    min_size: int = 96
    max_size: int = 330


PRESETS: dict[str, SubtitleStyle] = {
    # Gros mots jaunes surlignes : le standard des shorts a forte retention.
    "pop": SubtitleStyle(),
    # Blanc sobre : convient au long-form et aux langues a mots longs.
    "clean": SubtitleStyle(
        font="Poppins ExtraBold", accent="FFFFFF", outline=5.0, uppercase=False,
        accent_scale=100, fit_width=0.76, fit_height=0.062, min_size=64, max_size=190,
    ),
    # Legende courte et coloree posee sous l'image, calquee sur la mise en
    # page mesuree des chaines narratives generalistes : texte nettement
    # plus petit que le standard « short IA », contour noir marque.
    "story": SubtitleStyle(
        font="Poppins ExtraBold", accent_scale=106, uppercase=False,
        outline=7.0, shadow=0.0,
        cue_palette=("FFFFFF", "FF3B30", "FFE14D", "34C759", "FFFFFF", "FF2D95", "0A84FF"),
        fit_width=0.46, fit_height=0.032, min_size=44, max_size=104,
    ),
    # Boite opaque : lisible sur n'importe quel b-roll clair.
    "boxed": SubtitleStyle(
        font="Poppins ExtraBold", accent="FFE14D", border_style=3, outline=3.0,
        shadow=0.0, uppercase=False, fit_width=0.74, fit_height=0.056, min_size=60,
        max_size=170,
    ),
}


@dataclass(slots=True)
class Cue:
    words: list[Word] = field(default_factory=list)

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end

    def text(self, uppercase: bool) -> str:
        joined = " ".join(w.text for w in self.words)
        return joined.upper() if uppercase else joined


def group_words(
    words: list[Word],
    *,
    max_chars: int = 22,
    max_words: int = 5,
    max_gap: float = 0.55,
    max_duration: float = 3.0,
) -> list[Cue]:
    """Regroupe les mots en cues courtes.

    Une cue se ferme sur la premiere condition atteinte : trop de caracteres,
    trop de mots, fin de phrase, silence marque, ou duree trop longue. Le
    silence compte parce qu'une cue qui enjambe une pause parait desynchronisee
    meme quand les timings sont justes.
    """
    cues: list[Cue] = []
    current = Cue()
    chars = 0

    for word in words:
        gap = word.start - current.words[-1].end if current.words else 0.0
        would_be = chars + len(word.text) + (1 if current.words else 0)
        overflow = current.words and (
            would_be > max_chars
            or len(current.words) >= max_words
            or gap > max_gap
            or word.end - current.start > max_duration
        )
        if overflow:
            cues.append(current)
            current, chars = Cue(), 0
            would_be = len(word.text)

        current.words.append(word)
        chars = would_be

        # Une fin de phrase ferme la cue : on ne melange pas deux idees.
        if re.search(r"[.!?…]$", word.text):
            cues.append(current)
            current, chars = Cue(), 0

    if current.words:
        cues.append(current)
    return cues


def _fit_size(text: str, style: SubtitleStyle, width: int, height: int) -> int:
    """Taille de police pour que `text` remplisse le cadre sans deborder."""
    from mediaaut.subtitles.metrics import fit_size

    # Marge de 3% : le mot accentue est agrandi a `accent_scale` et depasse
    # legerement la largeur mesuree sur le texte au repos.
    return fit_size(
        text,
        style.font,
        width * style.fit_width * 0.97,
        target_height=height * style.fit_height,
        fallback=style.size,
        minimum=style.min_size,
        maximum=style.max_size,
    )


def _style_line(name: str, style: SubtitleStyle, margin_v: int, margin_h: int) -> str:
    return (
        f"Style: {name},{style.font},{style.size},"
        f"{_ass_color(style.primary)},{_ass_color(style.accent)},"
        f"{_ass_color(style.outline_color)},{_ass_color(style.back_color, style.back_alpha)},"
        f"-1,0,0,0,100,100,0,0,{style.border_style},{style.outline},{style.shadow},"
        f"{style.alignment},{margin_h},{margin_h},{margin_v},1"
    )


def build_ass(
    words: list[Word],
    *,
    style: SubtitleStyle | str = "pop",
    width: int = 1080,
    height: int = 1920,
    safe_bottom: float = 0.20,
    max_chars: int = 22,
    hold: float = 0.9,
) -> str:
    """Construit le contenu d'un fichier .ass a partir de mots dates.

    `hold` : duree maximale pendant laquelle une cue reste affichee apres
    son dernier mot, pour couvrir les respirations. Sans ce maintien, chaque
    micro-pause de la voix vide l'ecran, ce qui saccade la lecture bien plus
    que ne le ferait un sous-titre tenu un peu trop longtemps.
    """
    if isinstance(style, str):
        if style not in PRESETS:
            raise ValueError(f"style de sous-titres inconnu : {style} ({', '.join(PRESETS)})")
        style = PRESETS[style]

    margin_v = int(height * safe_bottom)
    margin_h = int(width * 0.06)

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",              # pas de retour a la ligne automatique
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,"
        " BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,"
        " BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        _style_line("Main", style, margin_v, margin_h),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    cues = group_words(words, max_chars=max_chars)
    events: list[str] = []

    for cue_index, cue in enumerate(cues):
        size = _fit_size(cue.text(style.uppercase), style, width, height)

        if style.cue_palette:
            # Toute la cue prend la meme couleur ; le mot actif ne se
            # distingue que par la taille.
            primary = _ass_color(style.cue_palette[cue_index % len(style.cue_palette)])
            accent = primary
        else:
            primary = _ass_color(style.primary)
            accent = _ass_color(style.accent)

        # La cue tient jusqu'a la suivante tant que le silence reste bref.
        next_start = cues[cue_index + 1].start if cue_index + 1 < len(cues) else None
        cue_end = cue.end if next_start is None else min(next_start, cue.end + hold)

        # La couleur de repos est posee en tete de ligne. Sans cela, les mots
        # situes avant le mot actif ne portent aucune balise et retombent sur
        # la couleur du style, ce qui bicolore la cue a chaque image.
        prefix = "{" + f"\\fs{size}\\c{primary}" + "}"

        for index, active in enumerate(cue.words):
            parts = []
            for position, word in enumerate(cue.words):
                text = word.text.upper() if style.uppercase else word.text
                if position == index:
                    parts.append(
                        "{"
                        f"\\c{accent}\\fscx{style.accent_scale}\\fscy{style.accent_scale}"
                        "}" + text + "{"
                        f"\\c{primary}\\fscx100\\fscy100"
                        "}"
                    )
                else:
                    parts.append(text)

            last = index == len(cue.words) - 1
            end = cue_end if last else cue.words[index + 1].start
            # Borne l'affichage au debut de la cue suivante : des timings
            # Whisker qui se chevauchent feraient sinon coexister deux cues
            # sur la meme ligne, avec deux couleurs.
            stop = max(end, active.end)
            if next_start is not None:
                stop = min(stop, next_start)
            events.append(
                f"Dialogue: 0,{_ass_time(active.start)},{_ass_time(stop)},"
                f"Main,,0,0,0,,{prefix}{' '.join(parts)}"
            )

    return "\n".join(header + events) + "\n"


def write_ass(words: list[Word], out_path: Path, **kwargs) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_ass(words, **kwargs), encoding="utf-8")
    return out_path
