"""Emplacements canoniques du projet.

Tout le pipeline passe par ici pour resoudre un chemin. Aucun module ne
construit de chemin absolu lui-meme, ce qui permet de deplacer le projet
ou de rediriger `data/` sans toucher au reste du code.
"""

from __future__ import annotations

import os
from pathlib import Path

# src/mediaaut/core/paths.py -> remonter 4 niveaux donne la racine du projet.
ROOT = Path(__file__).resolve().parents[3]

def _data_root() -> Path:
    """Racine des donnees, redirigeable vers un dossier partage.

    Lue depuis l'environnement, et a defaut depuis `.env` — ce fichier est
    charge trop tard par pydantic-settings pour servir ici, alors que les
    chemins sont resolus des l'import. Rediriger `MEDIAAUT_DATA` vers un
    dossier synchronise permet de produire sur une machine et de mettre en
    ligne depuis une autre.
    """
    override = os.environ.get("MEDIAAUT_DATA")
    if not override:
        env_file = ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.lstrip().startswith("#"):
                    continue
                key, sep, value = line.partition("=")
                # Une affectation vide ne gagne pas sur une valeur renseignee
                # plus bas : le modele `.env.example` livre la cle vide, et
                # s'arreter dessus ferait silencieusement ignorer le reglage.
                if sep and key.strip() == "MEDIAAUT_DATA" and value.strip().strip("\"'"):
                    override = value.strip().strip("\"'")
    return Path(override).expanduser() if override else ROOT / "data"


DATA = _data_root()
CONFIG = ROOT / "config"
SECRETS = ROOT / "secrets"

OUT = DATA / "out"          # rendus finaux, un sous-dossier par job
CACHE = DATA / "cache"      # telechargements reutilisables (b-roll, audio source)
ASSETS = DATA / "assets"    # polices, musiques, watermarks fournis par l'utilisateur
MODELS = DATA / "models"    # poids Kokoro / Whisper telecharges une fois
DB_PATH = DATA / "state.sqlite"

_WRITABLE = (DATA, OUT, CACHE, ASSETS, MODELS, SECRETS)


def ensure_dirs() -> None:
    """Cree les dossiers de travail. Idempotent, appele au demarrage du CLI."""
    for path in _WRITABLE:
        path.mkdir(parents=True, exist_ok=True)


def job_dir(job_id: str) -> Path:
    """Dossier de travail isole d'un job de rendu."""
    path = OUT / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path
