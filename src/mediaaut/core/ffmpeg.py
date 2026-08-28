"""Localisation et invocation de ffmpeg / ffprobe.

Windows ne rafraichit pas le PATH des shells deja ouverts apres une
installation, et le PATH d'une tache planifiee differe souvent de celui de
la session interactive. On resout donc le binaire explicitement plutot que
de faire confiance au PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from mediaaut.core.logging import get_logger

log = get_logger(__name__)

# Emplacements d'installation courants sous Windows, testes dans l'ordre.
_WINDOWS_HINTS = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages",
    Path("C:/ProgramData/chocolatey/bin"),
    Path(os.environ.get("USERPROFILE", "")) / "scoop/shims",
    Path("C:/ffmpeg/bin"),
)


@lru_cache(maxsize=4)
def resolve(tool: str = "ffmpeg") -> str:
    """Chemin absolu vers `ffmpeg` ou `ffprobe`. Leve si introuvable."""
    override = os.environ.get(f"MEDIAAUT_{tool.upper()}")
    if override and Path(override).exists():
        return override

    found = shutil.which(tool)
    if found:
        return found

    exe = f"{tool}.exe" if os.name == "nt" else tool
    for hint in _WINDOWS_HINTS:
        if not hint.exists():
            continue
        direct = hint / exe
        if direct.exists():
            return str(direct)
        # WinGet imbrique le binaire sous Packages/<id>/<build>/bin/.
        for candidate in hint.glob(f"**/bin/{exe}"):
            return str(candidate)

    raise RuntimeError(
        f"{tool} introuvable. Installe-le (`winget install Gyan.FFmpeg`) ou "
        f"pointe la variable d'environnement MEDIAAUT_{tool.upper()} vers le binaire."
    )


def run(args: list[str], *, quiet: bool = True) -> subprocess.CompletedProcess[str]:
    """Execute ffmpeg. Leve une erreur explicite en incluant la sortie de ffmpeg."""
    cmd = [resolve("ffmpeg"), "-hide_banner"]
    if quiet:
        cmd += ["-loglevel", "error"]
    cmd += ["-y", *args]

    log.debug("ffmpeg %s", " ".join(args))
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-15:]
        raise RuntimeError("ffmpeg a echoue :\n" + "\n".join(tail))
    return proc


def probe(path: str | Path) -> dict:
    """Metadonnees ffprobe d'un fichier media."""
    proc = subprocess.run(
        [resolve("ffprobe"), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe a echoue sur {path} : {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def duration(path: str | Path) -> float:
    """Duree en secondes d'un fichier media."""
    return float(probe(path)["format"]["duration"])


def has_nvenc() -> bool:
    """Vrai si l'encodeur materiel NVIDIA h264_nvenc est disponible."""
    proc = subprocess.run(
        [resolve("ffmpeg"), "-hide_banner", "-encoders"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return "h264_nvenc" in proc.stdout
