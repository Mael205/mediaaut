"""Logging console lisible + trace fichier persistante."""

from __future__ import annotations

import logging
from typing import Any

from rich.console import Console
from rich.logging import RichHandler

from mediaaut.core.paths import DATA

console = Console()
_CONFIGURED = False


def setup_logging(level: int | str = logging.INFO) -> None:
    """Installe les handlers. Sans effet si deja appele."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    DATA.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(DATA / "mediaaut.log", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            RichHandler(console=console, rich_tracebacks=True, show_path=False),
            file_handler,
        ],
    )
    # Ces librairies loguent chaque requete HTTP en INFO, ce qui noie le reste.
    for noisy in ("httpx", "httpcore", "urllib3", "googleapiclient.discovery_cache"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


def step(message: str, **fields: Any) -> None:
    """Marqueur d'etape du pipeline, visuellement distinct des logs courants."""
    suffix = "  " + "  ".join(f"[dim]{k}=[/dim]{v}" for k, v in fields.items()) if fields else ""
    console.print(f"[bold cyan]>[/bold cyan] {message}{suffix}")
