"""flow CLI — command-line interface for Google Flow AI automation.

Entry point: `flow` (configured in pyproject.toml [project.scripts]).

Commands
--------
flow login                          # Interactive Google auth
flow generate image   <prompt>      # Text -> image
flow generate video   <prompt>      # Text -> video (Veo)
flow generate frame   <img> <prompt># Image -> video (Frame-to-Video)
flow batch            <file>        # Process a prompts file
flow projects list                  # List known projects
flow projects create  [name]        # Create a new project
flow projects use     <id|url>      # Switch active project
flow config show                    # Show current config
flow config set KEY VALUE           # Set a config value
flow status                         # Check auth + active project
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from .._client import FlowClient
from .._exceptions import (
    AuthError,
    FlowError,
    NoProjectError,
    PolicyError,
    GenerationTimeout,
)
from .._models import (
    AspectRatio,
    BatchResult,
    GenerationMode,
    GenerationResult,
    GenerationStatus,
    parse_prompt_file,
)
from .._storage import (
    get_active_project,
    is_authenticated,
    load_config,
    load_projects,
    save_config,
)
from ._generate import generate

console = Console()
err_console = Console(stderr=True)

# ──────────────────────────────────────────────
#  CLI root
# ──────────────────────────────────────────────

@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="flow-py", prog_name="flow")
@click.option("--debug", is_flag=True, hidden=True)
def cli(debug: bool):
    """flow -- Google Flow AI automation CLI.

    Automate image and video generation on labs.google/fx from the command line.

    \b
    Quick start:
      flow login                          # Authenticate (one-time)
      flow generate image "a red panda"   # Generate an image
      flow generate video "aurora borealis, cinematic" --output ./videos
      flow batch prompts.txt --mode video # Process a batch
    """
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)


# Register the generate group from _generate.py
cli.add_command(generate)


# ──────────────────────────────────────────────
#  flow login
# ──────────────────────────────────────────────

@cli.command()
def login():
    """Authenticate with Google (opens browser window).

    After sign-in the session is saved to ~/.flow-py/browser-profile/
    and future commands run headless automatically.
    """
    async def _run():
        cfg = load_config()
        cfg.headless = False  # force visible for login
        client = await FlowClient.create(headless=False, config=cfg)
        try:
            await client.login()
        finally:
            await client.close()

    _run_async(_run)


# ──────────────────────────────────────────────
#  flow batch
# ──────────────────────────────────────────────

@cli.command()
@click.argument("prompts_file", type=click.Path(exists=True))
@click.option("--mode", "mode_str",
              type=click.Choice(["image", "video", "frame"]),
              default="image", show_default=True,
              help="Generation mode for all prompts (overridden by ||| syntax).")
@click.option("-o", "--output-dir", default="./batch-output", show_default=True)
@click.option("--aspect", "aspect_ratio",
              type=click.Choice(["16:9", "9:16", "1:1"]),
              default="16:9", show_default=True)
@click.option("--delay", default=None, type=float,
              help="Seconds to pause between prompts (default: from config).")
@click.option("--headless/--no-headless", default=None)
def batch(
    prompts_file: str,
    mode_str: str,
    output_dir: str,
    aspect_ratio: str,
    delay: Optional[float],
    headless: Optional[bool],
):
    """Process a PROMPTS_FILE in batch mode.

    \b
    File formats supported:
      - Plain text (one prompt per line)
      - Tagged blocks ([TAG] prompt, blank-line separated)
      - Pipeline (image_prompt ||| video_prompt for image->video)

    \b
    Examples:
      flow batch prompts.txt
      flow batch prompts.txt --mode video --output-dir ./videos
      flow batch pipeline.txt --mode image  # ||| syntax auto-detects pipeline

    \b
    Prompts file example:
      [V1-S1] Golden Buddha on lotus throne, divine rays

      [V1-S2] Subhuti meditating, white hair, golden particles

      [V1-S3] Grand temple exterior, cherry blossoms, dusk light
    """
    _check_auth()
    mode_map = {"image": GenerationMode.IMAGE, "video": GenerationMode.VIDEO,
                "frame": GenerationMode.FRAME_TO_VIDEO}
    mode = mode_map[mode_str]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    parsed = parse_prompt_file(prompts_file)
    console.print(f"[cyan]Loaded {len(parsed)} prompt(s) from {prompts_file}[/cyan]")

    async def _run():
        async with await FlowClient.create(headless=headless) as client:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Generating...", total=len(parsed))
                completed = [0]

                def on_result(result: GenerationResult, idx: int, total: int):
                    completed[0] += 1
                    status_icon = "OK" if result.succeeded else "FAIL"
                    progress.update(
                        task,
                        advance=1,
                        description=f"{status_icon} [{completed[0]}/{total}] {result.prompt[:50]}...",
                    )

                batch_result = await client.batch_generate(
                    prompts=parsed,
                    mode=mode,
                    output_dir=out,
                    aspect_ratio=AspectRatio(aspect_ratio),
                    delay_s=delay,
                    on_result=on_result,
                )

        _print_batch_result(batch_result, out)

    _run_async(_run)


# ──────────────────────────────────────────────
#  flow projects
# ──────────────────────────────────────────────

@cli.group()
def projects():
    """Manage Google Flow projects."""
    pass


@projects.command("list")
def projects_list():
    """List all known projects."""
    known = load_projects()
    active_id, _ = get_active_project()
    if not known:
        console.print("[yellow]No projects found. Run `flow projects create` or `flow login`.[/yellow]")
        return
    table = Table("ID", "Name", "Active", "URL", title="Flow Projects")
    for pid, info in known.items():
        active = "YES" if pid == active_id else ""
        table.add_row(pid[:16] + "...", info.get("name", ""), active, info.get("url", "")[:60] + "...")
    console.print(table)


@projects.command("create")
@click.argument("name", default="flow-py")
@click.option("--headless/--no-headless", default=None)
def projects_create(name: str, headless: Optional[bool]):
    """Create a new Flow project."""
    async def _run():
        async with await FlowClient.create(headless=headless) as client:
            with console.status("Creating project..."):
                pid = await client.create_project(name)
            console.print(f"[green]Created project:[/green] {pid}")

    _run_async(_run)


@projects.command("use")
@click.argument("project_id_or_url")
def projects_use(project_id_or_url: str):
    """Switch the active project by ID or full URL."""
    async def _run():
        async with await FlowClient.create() as client:
            await client.use_project(project_id_or_url)
        console.print(f"[green]Active project:[/green] {project_id_or_url}")

    _run_async(_run)


# ──────────────────────────────────────────────
#  flow config
# ──────────────────────────────────────────────

@cli.group()
def config():
    """View and edit configuration."""
    pass


@config.command("show")
def config_show():
    """Show current configuration."""
    cfg = load_config()
    table = Table("Key", "Value", title="flow-py Config (~/.flow-py/config.json)")
    for k, v in cfg.__dict__.items():
        table.add_row(k, str(v))
    console.print(table)


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """Set a configuration value.

    \b
    Keys:
      headless              true/false (default: true)
      default_output_dir    path (default: .)
      default_aspect_ratio  16:9 / 9:16 / 1:1
      default_image_count   integer (default: 4)
      generation_timeout_s  integer seconds (default: 300)
      inter_prompt_delay_s  float seconds (default: 2.0)
    """
    cfg = load_config()
    if not hasattr(cfg, key):
        err_console.print(f"[red]Unknown config key:[/red] {key}")
        sys.exit(1)

    # Type coerce
    current = getattr(cfg, key)
    try:
        if isinstance(current, bool):
            coerced = value.lower() in ("true", "1", "yes")
        elif isinstance(current, int):
            coerced = int(value)
        elif isinstance(current, float):
            coerced = float(value)
        else:
            coerced = value
    except ValueError:
        err_console.print(f"[red]Invalid value for {key}:[/red] {value}")
        sys.exit(1)

    setattr(cfg, key, coerced)
    save_config(cfg)
    console.print(f"[green]Set {key} = {coerced}[/green]")


# ──────────────────────────────────────────────
#  flow status
# ──────────────────────────────────────────────

@cli.command()
def status():
    """Show auth status and active project."""
    authed = is_authenticated()
    pid, purl = get_active_project()
    cfg = load_config()

    console.print("\n[bold]flow-py status[/bold]")
    console.print(f"  Auth:           {'[green]Logged in[/green]' if authed else '[red]Not authenticated[/red]'}")
    console.print(f"  Active project: {pid or '[yellow]none[/yellow]'}")
    if purl:
        console.print(f"  Project URL:    {purl}")
    console.print(f"  Headless:       {cfg.headless}")
    console.print(f"  Output dir:     {cfg.default_output_dir}")
    console.print(f"  Profile dir:    ~/.flow-py/browser-profile/")
    if not authed:
        console.print("\n  [yellow]Run `flow login` to authenticate.[/yellow]")


# ──────────────────────────────────────────────
#  Internal helpers
# ──────────────────────────────────────────────

def _run_async(coro_fn):
    """Run an async function, handling common exceptions."""
    try:
        asyncio.run(coro_fn())
    except AuthError as e:
        err_console.print(f"\n[red]Auth error:[/red] {e}")
        err_console.print("[yellow]Run `flow login` to authenticate.[/yellow]")
        sys.exit(1)
    except NoProjectError:
        err_console.print("\n[red]No active project.[/red] Run `flow projects create` or `flow projects use <id>`.")
        sys.exit(1)
    except PolicyError as e:
        err_console.print(f"\n[red]Content policy rejection:[/red] {e}")
        sys.exit(2)
    except GenerationTimeout as e:
        err_console.print(f"\n[red]Timeout:[/red] {e}")
        sys.exit(3)
    except FlowError as e:
        err_console.print(f"\n[red]Flow error:[/red] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(130)


def _check_auth():
    """Warn if not authenticated (non-fatal -- browser will redirect)."""
    if not is_authenticated():
        console.print("[yellow]Warning: No saved session found. If this fails, run `flow login` first.[/yellow]\n")


def _print_batch_result(batch_obj: BatchResult, output_dir: Path):
    """Pretty-print batch summary."""
    elapsed = batch_obj.elapsed_s
    elapsed_str = f"{elapsed:.0f}s" if elapsed else "?"

    console.print(f"\n[bold]Batch complete[/bold] ({elapsed_str})")
    console.print(f"  Total:     {batch_obj.total}")
    console.print(f"  Success:   [green]{batch_obj.completed}[/green]")
    console.print(f"  Failed:    [red]{batch_obj.failed}[/red]")
    if batch_obj.skipped:
        console.print(f"  Skipped:   {batch_obj.skipped}")
    console.print(f"  Output:    {output_dir.resolve()}")

    if batch_obj.failed > 0:
        console.print("\n[yellow]Failed prompts:[/yellow]")
        for r in batch_obj.results:
            if not r.succeeded and r.status != GenerationStatus.SKIPPED:
                console.print(f"  - {r.prompt[:70]} -> {r.status.value}: {r.error}")
