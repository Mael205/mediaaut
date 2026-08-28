"""Generation de la miniature.

La miniature decide du taux de clic, donc d'une bonne part de l'audience
d'une video longue. Deux regles gouvernent ce rendu :

- **Le texte doit tenir en trois mots et se lire en vignette.** Une miniature
  est vue a environ 210 pixels de large dans les recommandations. Le texte
  est donc dimensionne par mesure, pas au jugé, exactement comme les
  sous-titres.
- **L'image de fond vient de la video elle-meme.** Une image sans rapport
  gagne le clic et perd le spectateur dans les cinq premieres secondes, ce
  que YouTube penalise plus durement que l'absence de clic.
"""

from __future__ import annotations

from pathlib import Path

from mediaaut.assets.fonts import font_file
from mediaaut.core import ffmpeg
from mediaaut.core.logging import get_logger

log = get_logger(__name__)

WIDTH = 1280
HEIGHT = 720

# Taille a laquelle la miniature est reellement vue dans les recommandations.
# Sert de garde : si le texte n'est pas lisible a cette largeur, il ne l'est
# nulle part.
PREVIEW_WIDTH = 210

_MARGIN = 64
_MAX_LINES = 3
# Au-dela, le texte ne se lit plus a la taille d une vignette.
_MAX_WORDS = 4


def _grab_frame(video: Path, out: Path, at: float) -> Path:
    """Extrait une image de la video pour servir de fond."""
    ffmpeg.run(["-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)])
    return out


def _wrap(text: str, font, max_width: int) -> list[str]:
    """Repartit le texte en lignes qui tiennent dans la largeur donnee."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:_MAX_LINES]


def build(
    video: Path,
    out_path: Path,
    text: str,
    *,
    at: float | None = None,
    accent: str = "#FFC24B",
) -> Path:
    """Compose une miniature 1280x720 a partir d'une image de la video."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFont

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Un tiers de la duree : assez loin de l'intro pour montrer le sujet,
    # assez tot pour ne pas divulguer la conclusion.
    moment = at if at is not None else ffmpeg.duration(video) / 3
    frame_path = _grab_frame(video, out_path.with_name("_frame.jpg"), moment)

    frame = Image.open(frame_path).convert("RGB").resize((WIDTH, HEIGHT), Image.LANCZOS)
    # Assombri et desature : le fond doit porter le texte, pas rivaliser
    # avec lui. Sans cela, un plan clair rend le texte illisible en vignette.
    frame = ImageEnhance.Brightness(frame).enhance(0.52)
    frame = ImageEnhance.Color(frame).enhance(0.65)

    draw = ImageDraw.Draw(frame)
    words = text.strip().upper().split()
    if len(words) > _MAX_WORDS:
        # Les modeles rendent volontiers le titre entier malgre la consigne.
        # Sans cette coupe, le dimensionnement automatique retrecit
        # consciencieusement douze mots jusqu'a l'illisible.
        log.info("texte de miniature ramene de %d a %d mots", len(words), _MAX_WORDS)
        words = words[:_MAX_WORDS]
    label = " ".join(words)
    usable = WIDTH - 2 * _MARGIN

    # Cherche la plus grande taille qui tienne en largeur et en hauteur.
    size = 170
    while size > 48:
        font = ImageFont.truetype(str(font_file("Anton")), size)
        lines = _wrap(label, font, usable)
        widest = max((font.getlength(line) for line in lines), default=0)
        total_height = len(lines) * size * 1.12
        if widest <= usable and total_height <= HEIGHT - 2 * _MARGIN:
            break
        size -= 6

    line_height = size * 1.12
    top = (HEIGHT - len(lines) * line_height) / 2

    for index, line in enumerate(lines):
        y = top + index * line_height
        # Contour epais : la miniature est recompressee par YouTube et
        # affichee sur des fonds imprevisibles.
        draw.text(
            (_MARGIN, y), line, font=font, fill="#FFFFFF",
            stroke_width=max(4, size // 22), stroke_fill="#000000",
        )

    # Une barre d'accent ancre la composition a gauche et donne a la
    # miniature une signature reconnaissable d'une video a l'autre.
    bar_top = top - 10
    bar_bottom = top + len(lines) * line_height + 4
    draw.rectangle(
        [(_MARGIN - 26, bar_top), (_MARGIN - 14, bar_bottom)], fill=accent
    )

    frame.save(out_path, "JPEG", quality=92, optimize=True)
    frame_path.unlink(missing_ok=True)

    preview_size = round(size * PREVIEW_WIDTH / WIDTH)
    log.info(
        "miniature : %s, texte a %d px (%d px en vignette), %d ligne(s)",
        out_path.name, size, preview_size, len(lines),
    )
    if preview_size < 11:
        log.warning(
            "texte de miniature illisible en vignette (%d px) : le raccourcir",
            preview_size,
        )
    return out_path
