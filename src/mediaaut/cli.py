"""Interface en ligne de commande.

Point d'entree unique du projet, y compris pour le Planificateur de taches
Windows : une tache planifiee appelle la meme commande qu'un test manuel.
"""

from __future__ import annotations

from pathlib import Path

import typer

from mediaaut.core.logging import console, get_logger, step
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

    from mediaaut.script.backends import check_backend

    ok, message = check_backend()
    table.add_row("ecriture", "[green]ok[/green]" if ok else "[red]non[/red]", message)

    settings = get_settings()
    for label, value in (
        ("cle Pexels", settings.pexels_api_key),
        ("cle Pixabay", settings.pixabay_api_key),
    ):
        table.add_row(
            label,
            "[green]ok[/green]" if value else "[yellow]absente[/yellow]",
            "" if value else "a renseigner dans .env",
        )

    for platform in ("youtube", "instagram", "tiktok"):
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

    from mediaaut.core.db import already_published, record_publication
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

        if channel_id and already_published(job_root.name, name):
            console.print(f"  [yellow]deja publie sur {name}, ignore[/yellow]")
            continue

        result = publisher.publish(video, meta)
        record_publication(
            job_id=job_root.name,
            channel_id=channel_id or "",
            platform=name,
            ok=result.ok,
            video_id=result.video_id,
            url=result.url,
            visibility=result.visibility,
            detail=result.detail,
        )
        if result.ok:
            console.print(f"  [green]{result.url}[/green]  visibilite={result.visibility}")
            if result.detail:
                console.print(f"  [yellow]{result.detail}[/yellow]")
        else:
            console.print(f"  [red]echec : {result.detail}[/red]")


ideas_app = typer.Typer(no_args_is_help=True, help="File d'idees par chaine.")
app.add_typer(ideas_app, name="ideas")


@ideas_app.command("generate")
def ideas_generate(
    channel: str = typer.Argument(..., help="Identifiant de chaine"),
    count: int = typer.Option(8, "--count", "-n", help="Nombre d'idees a proposer"),
    steer: str = typer.Option("", "--steer", help="Direction supplementaire donnee au modele"),
) -> None:
    """Fait proposer de nouveaux sujets, en evitant ceux deja couverts."""
    from mediaaut.core.config import get_channel
    from mediaaut.ideas.store import add_ideas, recent_titles
    from mediaaut.script.writer import generate_ideas

    channel_config = get_channel(channel)
    drafts = generate_ideas(channel_config, count, avoid=recent_titles(channel), steer=steer)
    added, skipped = add_ideas(channel, [d.model_dump() for d in drafts])

    console.print(f"[bold]{added}[/bold] idee(s) ajoutee(s), {skipped} ecartee(s)")
    for draft in drafts:
        console.print(f"  [cyan]{draft.title}[/cyan]")
        console.print(f"    [dim]{draft.angle}[/dim]")


@ideas_app.command("list")
def ideas_list(
    channel: str = typer.Argument(...),
    status: str = typer.Option(None, "--status", help="queued | used"),
) -> None:
    """Affiche les idees d'une chaine."""
    from rich.table import Table

    from mediaaut.ideas.store import counts, list_ideas

    table = Table("id", "statut", "titre", "angle")
    for idea in list_ideas(channel, status):
        table.add_row(str(idea.id), idea.status, idea.title, idea.angle[:60])
    console.print(table)
    console.print(f"[dim]{counts(channel)}[/dim]")


@app.command()
def auto(
    channel: str = typer.Argument(..., help="Identifiant de chaine"),
    seconds: float = typer.Option(38.0, "--seconds", help="Duree de narration visee"),
    template: str = typer.Option(None, "--template", "-t"),
    publish_now: bool = typer.Option(False, "--publish", help="Publier apres le rendu"),
    private: bool = typer.Option(False, "--private", help="Si publie, rester en prive"),
    whisper_model: str = typer.Option("small", "--whisper"),
) -> None:
    """Chaine complete : idee suivante, script, b-roll, rendu, publication.

    C'est la commande destinee au planificateur de taches. Elle consomme une
    idee de la file ; si la file est vide elle s'arrete plutot que d'inventer
    un sujet, pour qu'un stock epuise se voie au lieu de degrader le contenu.
    """
    from mediaaut.core.config import get_channel
    from mediaaut.ideas.store import counts, mark_used, next_idea
    from mediaaut.pipeline import make_short
    from mediaaut.publish.base import VideoMeta
    from mediaaut.script.models import IdeaDraft
    from mediaaut.script.writer import write_script

    channel_config = get_channel(channel)
    idea = next_idea(channel)
    if idea is None:
        console.print(
            f"[yellow]aucune idee en attente pour {channel}[/yellow] — lancer "
            f"`mediaaut ideas generate {channel}`"
        )
        raise typer.Exit(1)

    step("idee", titre=idea.title)
    draft = write_script(
        channel_config,
        IdeaDraft(title=idea.title, angle=idea.angle, hook=idea.hook),
        seconds=seconds,
    )

    meta = VideoMeta(
        title=draft.title,
        description=draft.description,
        tags=draft.tags,
        language=channel_config.language,
    )
    result = make_short(
        channel,
        draft.narration,
        template_name=template,
        broll_queries=draft.broll_queries,
        whisper_model=whisper_model,
        meta=meta,
    )
    mark_used(idea.id, result.job_id)
    console.print(f"[bold green]{result.video_path}[/bold green]")
    console.print(f"[dim]file restante : {counts(channel)}[/dim]")

    if publish_now:
        publish(result.job_id, platform=["youtube"], title=None, private=private, dry_run=False)


@app.command()
def batch(
    channel: str = typer.Argument(..., help="Identifiant de chaine"),
    count: int = typer.Option(7, "--count", "-n", help="Nombre de videos a produire"),
    seconds: float = typer.Option(38.0, "--seconds"),
    whisper_model: str = typer.Option("small", "--whisper"),
) -> None:
    """Produit plusieurs videos d'affilee, sans rien publier.

    Tant que la mise en ligne YouTube reste manuelle, produire par lots est
    ce qui change le rythme reel : une seance hebdomadaire de quelques
    minutes remplace un geste quotidien.

    Un echec sur une video n'interrompt pas le lot — le sujet reste dans la
    file et sera repris au prochain passage.
    """
    from mediaaut.core.config import get_channel
    from mediaaut.ideas.store import counts, mark_used, next_idea
    from mediaaut.pipeline import make_short
    from mediaaut.publish.base import VideoMeta
    from mediaaut.script.models import IdeaDraft
    from mediaaut.script.writer import write_script

    channel_config = get_channel(channel)
    produced: list[str] = []

    for index in range(count):
        idea = next_idea(channel)
        if idea is None:
            console.print(
                f"[yellow]file d'idees epuisee apres {len(produced)} video(s)[/yellow] — "
                f"lancer `mediaaut ideas generate {channel}`"
            )
            break

        step(f"video {index + 1}/{count}", titre=idea.title)
        try:
            draft = write_script(
                channel_config,
                IdeaDraft(title=idea.title, angle=idea.angle, hook=idea.hook),
                seconds=seconds,
            )
            result = make_short(
                channel,
                draft.narration,
                broll_queries=draft.broll_queries,
                whisper_model=whisper_model,
                meta=VideoMeta(
                    title=draft.title,
                    description=draft.description,
                    tags=draft.tags,
                    language=channel_config.language,
                ),
            )
        except Exception as exc:
            # L'idee n'est pas marquee utilisee : elle repassera au prochain lot.
            log.exception("echec sur « %s »", idea.title)
            console.print(f"  [red]echec : {exc}[/red] — sujet remis dans la file")
            continue

        mark_used(idea.id, result.job_id)
        produced.append(result.job_id)

    console.print(
        f"\n[bold green]{len(produced)} video(s) produite(s)[/bold green]"
        f"  [dim]file : {counts(channel)}[/dim]"
    )
    if produced:
        console.print("[dim]Mettre en ligne : `mediaaut studio`[/dim]")


@app.command()
def studio(
    channel: str = typer.Option(None, "--channel", "-c", help="Limiter a une chaine"),
    port: int = typer.Option(8765, "--port"),
    no_browser: bool = typer.Option(False, "--no-browser"),
) -> None:
    """Ouvre la console locale de mise en ligne.

    Affiche les videos pretes et pas encore publiees, avec leurs
    metadonnees a un clic du presse-papiers. Le televersement reste fait a
    la main sur youtube.com : tant que l'audit de l'API n'est pas accorde,
    c'est la seule voie qui produit une video publique.
    """
    from mediaaut.studio.server import serve

    serve(port=port, channel_id=channel, open_browser=not no_browser)


@app.command()
def clip(
    source: str = typer.Argument(..., help="Fichier local, ou URL de video longue"),
    channel: str = typer.Option(..., "--channel", "-c", help="Identifiant de chaine"),
    count: int = typer.Option(6, "--count", "-n", help="Nombre d'extraits vises"),
    topic: str = typer.Option("", "--topic", help="Sujet de la video, aide la selection"),
    reframe: str = typer.Option(
        "blur", "--reframe", help="blur (garde toute l'image) | crop (plein cadre)"
    ),
    template: str = typer.Option(None, "--template", "-t"),
    whisper_model: str = typer.Option("large-v3", "--whisper"),
    language: str = typer.Option(None, "--language", help="Force la langue de la source"),
) -> None:
    """Decoupe une video longue en plusieurs shorts verticaux.

    Produit du volume sans consommer d'idees : six extraits d'une meme video
    sont six sujets distincts. Et comme le contenu vient d'un enregistrement
    reel, il echappe a la question du contenu fabrique.
    """
    from mediaaut.clip.pipeline import clip_video

    if reframe not in ("blur", "crop"):
        raise typer.BadParameter("--reframe attend blur ou crop")

    try:
        result = clip_video(
            source,
            channel,
            count=count,
            topic=topic,
            reframe=reframe,
            template_name=template,
            whisper_model=whisper_model,
            language=language,
        )
    except (RuntimeError, FileNotFoundError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(f"\n[bold green]{len(result.clips)} extrait(s)[/bold green]")
    for entry in result.clips:
        console.print(
            f"  [cyan]{entry['title']}[/cyan]  "
            f"[dim]{entry['start']:.0f}s, {entry['duration']:.0f}s[/dim]"
        )


@app.command()
def longform(
    channel: str = typer.Argument(..., help="Identifiant de chaine"),
    topic: str = typer.Option(..., "--topic", "-T", help="Sujet de la video"),
    minutes: float = typer.Option(9.0, "--minutes", "-m", help="Duree visee"),
    music: Path = typer.Option(None, "--music", exists=True),
    subtitles: bool = typer.Option(False, "--subtitles", help="Incruster les sous-titres"),
) -> None:
    """Produit une video longue horizontale, chapitree, avec sa miniature.

    Le long-form est la seule source de revenu publicitaire reelle : les
    Shorts rapportent 0,03 a 0,08 dollar pour mille vues, le long-form 8 a
    20. C'est aussi la seule voie vers les heures de visionnage exigees par
    le programme partenaire.
    """
    from mediaaut.longform.pipeline import make_long

    try:
        result = make_long(
            channel, topic, minutes=minutes, music=music, burn_subtitles=subtitles
        )
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(f"\n[bold green]{result.video_path}[/bold green]")
    console.print(f"[dim]miniature : {result.thumbnail_path}[/dim]")
    console.print(
        f"[dim]{result.sections} sections, {result.words} mots, "
        f"{result.duration / 60:.1f} min[/dim]"
    )
    for chapter in result.chapters:
        console.print(f"  [cyan]{chapter}[/cyan]")


if __name__ == "__main__":
    app()
