"""Cartes de code et de terminal, rendues comme des images.

Reponse au defaut de fond du b-roll de banque : une video qui explique
qu'une API repond « 200 OK » en verrouillant la video ne peut pas etre
illustree par une photo. Pexels contient des personnes, des lieux et des
objets ; le sujet, lui, est un bout de texte.

On rend donc le sujet lui-meme. Une carte est du vrai texte compose, pas
une image generee : rien ne peut y ressembler a une production d'IA,
puisqu'il n'y a rien de genere. C'est aussi ce que font les chaines
techniques credibles — elles montrent la reponse, pas quelqu'un qui tape
au clavier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from mediaaut.assets.fonts import font_file
from mediaaut.core.logging import get_logger

log = get_logger(__name__)

# Marge interieure de la fenetre, et bornes de corps de texte. Le minimum
# est cale sur la lisibilite en vignette de fil, le maximum evite qu'une
# carte d'une seule ligne courte ne devienne un titre geant.
_PADDING = 36
_MIN_SIZE = 26
_MAX_SIZE = 78


@dataclass(slots=True)
class CardTheme:
    """Apparence d'une carte. Sobre par defaut : elle est un fond, pas un sujet."""

    background: str = "#0C1016"      # fond de l'image entiere
    panel: str = "#161C25"           # fenetre
    border: str = "#252D38"
    chrome: str = "#1D242E"          # barre de titre
    text: str = "#D7DDE5"
    muted: str = "#7A8798"           # commentaires, ponctuation
    string: str = "#8CD98C"
    number: str = "#F0B67A"
    key: str = "#7CB8F0"             # cles JSON, noms de champs
    accent: str = "#FFC24B"          # valeur mise en avant
    radius: int = 22


# Coloration volontairement grossiere : on compose trois lignes de JSON ou
# une commande, pas un editeur. Un analyseur syntaxique complet serait du
# travail perdu a cette taille de texte.
_TOKEN = re.compile(
    r'(?P<string>"[^"]*")'
    r"|(?P<comment>#[^\n]*|//[^\n]*)"
    r"|(?P<number>\b\d+(?:\.\d+)?\b)"
    r"|(?P<punct>[{}\[\],:])"
)


def _colorize(line: str, theme: CardTheme) -> list[tuple[str, str]]:
    """Decoupe une ligne en morceaux (texte, couleur)."""
    pieces: list[tuple[str, str]] = []
    cursor = 0
    for match in _TOKEN.finditer(line):
        if match.start() > cursor:
            pieces.append((line[cursor : match.start()], theme.text))
        kind = match.lastgroup
        text = match.group()
        # Une chaine suivie de « : » est une cle, pas une valeur.
        if kind == "string" and line[match.end() : match.end() + 1] == ":":
            colour = theme.key
        else:
            colour = {
                "string": theme.string,
                "comment": theme.muted,
                "number": theme.number,
                "punct": theme.muted,
            }[kind]
        pieces.append((text, colour))
        cursor = match.end()
    if cursor < len(line):
        pieces.append((line[cursor:], theme.text))
    return pieces


def render(
    lines: list[str],
    out_path: Path,
    *,
    width: int = 1080,
    height: int = 1920,
    title: str = "",
    highlight: str = "",
    anchor: float = 0.30,
    theme: CardTheme | None = None,
) -> Path:
    """Compose une carte de code et l'ecrit en PNG.

    `highlight` met un fragment en avant — le detail dont parle la
    narration a cet instant. C'est ce qui fait la difference entre une
    illustration et une decoration.

    `anchor` fixe le centre du panneau, en fraction de la hauteur depuis le
    haut. Le defaut le place dans le tiers superieur : centre, il passait
    sous les sous-titres, qui recouvraient precisement le code a lire.
    """
    from PIL import Image, ImageDraw, ImageFont

    theme = theme or CardTheme()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", (width, height), theme.background)
    draw = ImageDraw.Draw(image)

    # La fenetre occupe la bande centrale : les sous-titres vivent en bas,
    # et le haut est mange par l'interface des plateformes.
    margin = int(width * 0.07)
    panel_width = width - 2 * margin
    chrome_height = 62

    # Taille tiree d'une mesure, pas d'une estimation sur le nombre de
    # caracteres : une approximation faisait deborder les lignes longues
    # hors de la fenetre.
    mono_path = str(font_file("IBM Plex Mono"))
    longest = max(lines, key=len) if lines else " "
    reference = ImageFont.truetype(mono_path, 100)
    usable = panel_width - 2 * _PADDING
    measured = reference.getlength(longest) or 1
    size = max(_MIN_SIZE, min(_MAX_SIZE, int(usable / measured * 100)))

    # La hauteur doit aussi tenir : au-dela, une carte de dix lignes
    # deborderait verticalement du cadre.
    max_lines_height = height * 0.62 - chrome_height - 2 * _PADDING
    while size > _MIN_SIZE and len(lines) * size * 1.62 > max_lines_height:
        size -= 2

    mono = ImageFont.truetype(mono_path, size)
    mono_bold = ImageFont.truetype(str(font_file("IBM Plex Mono SemiBold")), size)
    chrome_font = ImageFont.truetype(str(font_file("IBM Plex Mono")), 26)

    line_height = int(size * 1.62)
    panel_height = chrome_height + len(lines) * line_height + 2 * _PADDING
    panel_top = max(_PADDING, int(height * anchor) - panel_height // 2)
    panel = (margin, panel_top, margin + panel_width, panel_top + panel_height)

    draw.rounded_rectangle(
        panel, radius=theme.radius, fill=theme.panel, outline=theme.border, width=2
    )
    draw.rounded_rectangle(
        (panel[0], panel[1], panel[2], panel[1] + chrome_height),
        radius=theme.radius, fill=theme.chrome,
    )
    # Le bas de la barre de titre est carre : sans ce rectangle, l'arrondi
    # du haut se repete au milieu de la fenetre.
    draw.rectangle(
        (panel[0], panel[1] + chrome_height - theme.radius, panel[2], panel[1] + chrome_height),
        fill=theme.chrome,
    )

    for index, colour in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
        cx = panel[0] + 30 + index * 26
        cy = panel[1] + chrome_height // 2
        draw.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill=colour)

    if title:
        draw.text(
            (panel[0] + 122, panel[1] + chrome_height // 2),
            title, font=chrome_font, fill=theme.muted, anchor="lm",
        )

    y = panel[1] + chrome_height + _PADDING
    for line in lines:
        x = panel[0] + _PADDING
        for text, colour in _colorize(line, theme):
            # Le fragment mis en avant est peint en gras sur fond d'accent.
            if highlight and highlight in text:
                before, _, after = text.partition(highlight)
                for chunk, chunk_colour, bold in (
                    (before, colour, False),
                    (highlight, theme.accent, True),
                    (after, colour, False),
                ):
                    if not chunk:
                        continue
                    font = mono_bold if bold else mono
                    if bold:
                        span = draw.textlength(chunk, font=font)
                        draw.rounded_rectangle(
                            (x - 6, y - 6, x + span + 6, y + size + 10),
                            radius=6, fill="#2A2113",
                        )
                    draw.text((x, y), chunk, font=font, fill=chunk_colour)
                    x += draw.textlength(chunk, font=font)
            else:
                draw.text((x, y), text, font=mono, fill=colour)
                x += draw.textlength(text, font=mono)
        y += line_height

    image.save(out_path, "PNG", optimize=True)
    log.debug("carte rendue : %s (%d ligne(s), corps %d)", out_path.name, len(lines), size)
    return out_path
