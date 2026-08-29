"""Construit la page hebergee a partir de la source de l'artifact.

Une seule source de verite, `site/index.html`, deux destinations qui n'ont
pas les memes contraintes :

- **L'artifact** enveloppe lui-meme le fichier dans un document complet, et
  sa politique de securite bloque tout script tiers. La source ne porte donc
  ni doctype ni balise `head`.
- **GitHub Pages** sert le fichier tel quel : il lui faut un document
  complet, et il accepte le script de mesure d'audience que l'artifact
  refuserait.

Recopier a la main les divergerait au premier changement, d'ou ce script.

    py site/build.py
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "site" / "index.html"
TARGET = ROOT / "docs" / "product" / "index.html"

# Le compteur d'audience. Laisse vide, aucun script tiers n'est emis — on ne
# charge pas un traceur qui repondrait 404, et on n'en impose pas un au
# visiteur tant que le compte n'existe pas.
#
# GoatCounter est gratuit, sans cookie, et ne demande donc pas de banniere.
# Creer le compte, puis remplacer par le code obtenu.
GOATCOUNTER_CODE = ""

DESCRIPTION = (
    "Write, voice, subtitle, illustrate and publish short and long-form video "
    "entirely on your own machine. No credits, no queue, nothing uploaded."
)


def analytics() -> str:
    if not GOATCOUNTER_CODE:
        return "  <!-- Audience : renseigner GOATCOUNTER_CODE dans site/build.py -->"
    return (
        f'  <script data-goatcounter="https://{GOATCOUNTER_CODE}.goatcounter.com/count"\n'
        f'          async src="//gc.zgo.at/count.js"></script>'
    )


def build() -> Path:
    body = SOURCE.read_text(encoding="utf-8")

    # Le titre vit dans la source, sous forme de balise isolee que
    # l'enveloppe de l'artifact remonte dans son `head`. Ici il faut l'en
    # retirer pour ne pas le voir s'afficher dans le corps de la page.
    title_match = re.search(r"<title>(.*?)</title>", body, re.S)
    title = title_match.group(1).strip() if title_match else "mediaaut"
    body = body.replace(title_match.group(0), "", 1) if title_match else body

    # Idem pour les liens de polices : ils appartiennent au `head`.
    head_links = re.findall(r'^\s*<link [^>]*>\s*$', body, re.M)
    for link in head_links:
        body = body.replace(link, "", 1)

    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{DESCRIPTION}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{DESCRIPTION}">
<meta property="og:type" content="website">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#151a20">
{"".join(link.strip() + chr(10) for link in head_links)}{analytics()}
<style>
  /* L'enveloppe de l'artifact fournit cette remise a zero ; en hebergement
     direct il faut la poser soi-meme, sans quoi la page herite des marges
     par defaut du navigateur. */
  html, body {{ margin: 0; }}
  img {{ max-width: 100%; }}
  [hidden] {{ display: none !important; }}
</style>
</head>
<body>
{body.strip()}
</body>
</html>
"""

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(document, encoding="utf-8")
    return TARGET


if __name__ == "__main__":
    out = build()
    size = out.stat().st_size / 1024
    print(f"ecrit : {out.relative_to(ROOT)} ({size:.1f} Ko)")
    if not GOATCOUNTER_CODE:
        print("audience : aucun compteur emis (GOATCOUNTER_CODE vide)")
    if shutil.which("git"):
        print("publier : git add docs/product && git commit && git push")
