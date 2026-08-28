"""Interface en ligne de commande.

Point d'entree unique du projet, y compris pour le Planificateur de taches
Windows : une tache planifiee appelle la meme commande qu'un test manuel.
"""

from __future__ import annotations

from pathlib import Path

import typer

from mediaaut.core.logging import console, get_logger
from mediaaut.core.paths import ensure_dirs

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Pipeline automatise de creation et publication de videos.",
)
log = get_logger(__name__)


@app.callback()
def _bootstrap() -> None:
    ensure_dirs()


@app.command()
def doctor() -> None:
    """Verifie que l'environnement est complet et utilisable."""
    from rich.table import Table

    from mediaaut.core import ffmpeg
    from mediaaut.core.config import get_settings, load_channels
    from mediaaut.core.gpu import has_nvidia_gpu, whisper_device

    table = Table("Composant", "Etat", "Detail", title="Diagnostic mediaaut")

    try:
        table.add_row("ffmpeg", "[green]ok[/green]", ffmpeg.resolve("ffmpeg"))
        table.add_row(
            "encodeur",
            "[green]nvenc[/green]" if ffmpeg.has_nvenc() else "[yellow]x264[/yellow]",
            "materiel" if ffmpeg.has_nvenc() else "logiciel, plus lent",
        )
    except RuntimeError as exc:
        table.add_row("ffmpeg", "[red]absent[/red]", str(exc)[:60])

    device, compute = whisper_device()
    table.add_row(
        "whisper",
        "[green]gpu[/green]" if device == "cuda" else "[yellow]cpu[/yellow]",
        f"{device}/{compute}" + ("" if has_nvidia_gpu() else " (pas de GPU NVIDIA)"),
    )

    channels = load_channels()
    active = [c.id for c in channels.values() if c.enabled]
    table.add_row("chaines", "[green]ok[/green]", f"{len(active)} active(s) : {', '.join(active)}")

    settings = get_settings()
    for label, value in (
        ("cle Anthropic", settings.anthropic_api_key),
        ("cle Pexels", settings.pexels_api_key),
        ("cle Pixabay", settings.pixabay_api_key),
    ):
        table.add_row(
            label,
            "[green]ok[/green]" if value else "[yellow]absente[/yellow]",
            "" if value else "a renseigner dans .env",
        )

    console.print(table)


@app.command()
def voices(
    lang: str = typer.Option(None, "--lang", "-l", help="Filtrer par langue (en, fr, es...)"),
    provider: str = typer.Option("kokoro", "--provider", "-p"),
) -> None:
    """Liste les voix disponibles."""
    from mediaaut.voice.base import get_provider

    available = get_provider(provider).list_voices(lang)
    console.print(f"[bold]{len(available)}[/bold] voix ({provider}"
                  + (f", {lang}" if lang else "") + ") :")
    for name in available:
        console.print(f"  {name}")


@app.command()
def make(
    channel: str = typer.Argument(..., help="Identifiant de chaine (cf. config/channels.yaml)"),
    script: str = typer.Option(None, "--script", "-s", help="Texte du script"),
    script_file: Path = typer.Option(None, "--script-file", "-f", exists=True),
    template: str = typer.Option(None, "--template", "-t", help="Force un template"),
    broll: list[Path] = typer.Option(None, "--broll", "-b", help="Fichiers de b-roll"),
    music: Path = typer.Option(None, "--music", "-m", exists=True),
    whisper_model: str = typer.Option("small", "--whisper", help="small | medium | large-v3"),
) -> None:
    """Genere un short a partir d'un script."""
    from mediaaut.pipeline import make_short

    if not script and not script_file:
        raise typer.BadParameter("fournir --script ou --script-file")
    text = script or script_file.read_text(encoding="utf-8")

    result = make_short(
        channel,
        text,
        template_name=template,
        broll=list(broll) if broll else None,
        music=music,
        whisper_model=whisper_model,
    )
    console.print(f"\n[bold green]{result.video_path}[/bold green]")


@app.command()
def channels() -> None:
    """Affiche les chaines configurees."""
    from rich.table import Table

    from mediaaut.core.config import load_channels

    table = Table("id", "langue", "voix", "templates", "plateformes", "actif")
    for channel in load_channels().values():
        table.add_row(
            channel.id,
            channel.language,
            f"{channel.voice.provider}:{channel.voice.voice_id}",
            ", ".join(channel.render.templates),
            ", ".join(channel.platforms),
            "oui" if channel.enabled else "non",
        )
    console.print(table)


if __name__ == "__main__":
    app()
