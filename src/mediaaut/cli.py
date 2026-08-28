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

    for platform in ("youtube",):
        try:
            from mediaaut.publish.base import get_publisher

            ok, message = get_publisher(platform).check_auth()
        except Exception as exc:
            ok, message = False, str(exc)[:70]
        table.add_row(platform, "[green]ok[/green]" if ok else "[yellow]non[/yellow]", message)

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
    broll: list[Path] = typer.Option(None, "--broll", "-b", help="Fichiers de b-roll locaux"),
    broll_query: list[str] = typer.Option(
        None, "--broll-query", "-q", help="Mots-cles de recherche en banque (repetable)"
    ),
    music: Path = typer.Option(None, "--music", "-m", exists=True),
    whisper_model: str = typer.Option("small", "--whisper", help="small | medium | large-v3"),
    title: str = typer.Option(None, "--title", help="Titre pour la publication"),
    description: str = typer.Option("", "--description"),
    tag: list[str] = typer.Option(None, "--tag", help="Tag (repetable)"),
) -> None:
    """Genere un short a partir d'un script."""
    from mediaaut.core.config import get_channel
    from mediaaut.pipeline import make_short
    from mediaaut.publish.base import VideoMeta

    if not script and not script_file:
        raise typer.BadParameter("fournir --script ou --script-file")
    text = script or script_file.read_text(encoding="utf-8")

    meta = None
    if title:
        meta = VideoMeta(
            title=title,
            description=description,
            tags=list(tag) if tag else [],
            language=get_channel(channel).language,
        )

    result = make_short(
        channel,
        text,
        template_name=template,
        broll=list(broll) if broll else None,
        broll_queries=list(broll_query) if broll_query else None,
        music=music,
        whisper_model=whisper_model,
        meta=meta,
    )
    console.print(f"\n[bold green]{result.video_path}[/bold green]")
    if meta is None:
        console.print(
            "[dim]Sans --title, la video ne peut pas etre publiee telle quelle.[/dim]"
        )


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


@app.command()
def auth(
    platform: str = typer.Argument("youtube", help="Plateforme a autoriser"),
    channel: str = typer.Option(
        None, "--channel", "-c", help="Chaine de channels.yaml a rattacher a ce jeton"
    ),
) -> None:
    """Lance le consentement OAuth d'une plateforme.

    Ouvre le navigateur, puis stocke le jeton dans `secrets/`. A refaire
    uniquement si le jeton est revoque, ou pour rattacher une chaine de plus.

    Si le compte Google possede plusieurs chaines YouTube, l'ecran de
    consentement en propose la liste : choisir celle qui correspond a
    `--channel`. Le message final confirme laquelle a ete rattachee.
    """
    if platform != "youtube":
        raise typer.BadParameter(f"pas encore implemente : {platform}")

    from mediaaut.publish.youtube import YouTubePublisher

    try:
        ok, message = YouTubePublisher(channel).authorize()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(("[green]" if ok else "[yellow]") + message + "[/]")
    if ok and channel:
        console.print(f"[dim]jeton rattache a la chaine mediaaut « {channel} »[/dim]")


@app.command()
def publish(
    job: str = typer.Argument(..., help="Identifiant de job, ou chemin d'un .mp4"),
    platform: list[str] = typer.Option(["youtube"], "--platform", "-p"),
    title: str = typer.Option(None, "--title", help="Remplace le titre de meta.json"),
    private: bool = typer.Option(False, "--private", help="Publier en prive"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Verifier sans televerser"),
) -> None:
    """Publie une video deja rendue."""
    import json as _json
    from datetime import UTC, datetime, timedelta

    from mediaaut.core.paths import OUT
    from mediaaut.publish.base import VideoMeta, get_publisher

    source = Path(job)
    direct_file = source.suffix == ".mp4" and source.exists()
    job_root = source.parent if direct_file else OUT / job
    video = source if direct_file else job_root / "short.mp4"
    meta_path = job_root / "meta.json"

    # Le jeton a utiliser depend de la chaine du job, pas de la plateforme :
    # chaque chaine YouTube a son propre consentement.
    result_path = job_root / "result.json"
    channel_id = (
        _json.loads(result_path.read_text(encoding="utf-8")).get("channel_id")
        if result_path.exists()
        else None
    )

    if not video.exists():
        console.print(f"[red]video introuvable : {video}[/red]")
        raise typer.Exit(1)

    if meta_path.exists():
        raw = _json.loads(meta_path.read_text(encoding="utf-8"))
        raw.pop("publish_at", None)
        meta = VideoMeta(**raw)
    elif title:
        meta = VideoMeta(title=title)
    else:
        console.print(f"[red]ni {meta_path} ni --title : impossible de publier[/red]")
        raise typer.Exit(1)

    if title:
        meta.title = title
    if private:
        # Un `publishAt` lointain force la visibilite privee sans avoir a
        # exposer un champ de visibilite distinct dans l'interface.
        meta.publish_at = datetime.now(UTC) + timedelta(days=3650)

    for name in platform:
        publisher = get_publisher(name, channel_id)
        ok, message = publisher.check_auth()
        console.print(f"[bold]{name}[/bold] : {'[green]' if ok else '[red]'}{message}[/]")
        if not ok:
            continue
        if dry_run:
            console.print(f"  [dim]dry-run, rien televerse ({video.name}, "
                          f"titre « {meta.title} »)[/dim]")
            continue

        result = publisher.publish(video, meta)
        if result.ok:
            console.print(f"  [green]{result.url}[/green]  visibilite={result.visibility}")
            if result.detail:
                console.print(f"  [yellow]{result.detail}[/yellow]")
        else:
            console.print(f"  [red]echec : {result.detail}[/red]")


if __name__ == "__main__":
    app()
