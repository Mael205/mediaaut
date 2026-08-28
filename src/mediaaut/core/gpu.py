"""Activation du GPU pour CTranslate2 (faster-whisper) sous Windows.

Les DLL CUDA/cuDNN livrees par les paquets pip `nvidia-*` ne sont dans
aucun chemin de recherche par defaut. `os.add_dll_directory` ne suffit
pas : CTranslate2 charge cublas depuis du code natif, qui utilise l'ordre
de recherche Windows standard et consulte donc le PATH. On fait les deux,
et imperativement avant le premier import de faster_whisper.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from mediaaut.core.logging import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def enable_cuda_dlls() -> list[str]:
    """Rend les DLL CUDA pip-installees visibles. Retourne les dossiers ajoutes."""
    try:
        import nvidia
    except ImportError:
        return []

    bins = [
        str(sub / "bin")
        for root in map(Path, nvidia.__path__)
        for sub in sorted(root.iterdir())
        if (sub / "bin").is_dir()
    ]
    if not bins:
        return []

    os.environ["PATH"] = os.pathsep.join(bins) + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        for path in bins:
            os.add_dll_directory(path)
    log.debug("DLL CUDA exposees : %s", ", ".join(Path(b).parent.name for b in bins))
    return bins


@lru_cache(maxsize=1)
def has_nvidia_gpu() -> bool:
    if not shutil.which("nvidia-smi"):
        return False
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
        )
        return proc.returncode == 0 and bool(proc.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        return False


@lru_cache(maxsize=1)
def whisper_device() -> tuple[str, str]:
    """Meilleur couple (device, compute_type) disponible pour faster-whisper."""
    if has_nvidia_gpu() and enable_cuda_dlls():
        return "cuda", "float16"
    return "cpu", "int8"
