"""Generate subcommands for the flow CLI."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from .._client import FlowClient
from .._models import AspectRatio, GenerationMode, GenerationResult, GenerationStatus

console = Console()
err_console = Console(stderr=True)


def _check_auth():
    """Warn if not authenticated (non-fatal)."""
    from .._storage import is_authenticated
    if not is_authenticated():
        console.print("[yellow]Warning: No saved session. If this fails, run `flow login` first.[/yellow]\n")


def _run_async(coro_fn):
    """Run an async function, handling common exceptions."""
    import asyncio
    from .._exceptions import (
        AuthError, FlowError, GenerationTimeout, NoProjectError, PolicyError,
    )
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


def _print_result(result: GenerationResult):
    """Pretty-print a single GenerationResult."""
    if result.succeeded:
        console.print(f"\n[green]Generation complete[/green] ({result.elapsed_s:.1f}s)")
        for fp in result.file_paths:
            console.print(f"   {fp}")
        if result.media_urls and not result.file_paths:
            console.print("[yellow]   (intercepted URLs -- manual download may be needed)[/yellow]")
            for url in result.media_urls[:3]:
                console.print(f"   {url[:100]}")
    elif result.status == GenerationStatus.POLICY_REJECTED:
        console.print("\n[red]Content policy rejection[/red]")
        console.print(f"   Prompt: {result.prompt[:80]}")
    else:
        console.print(f"\n[red]Generation failed[/red]: {result.error}")


# ── Click group ──────────────────────────────

@click.group()
def generate():
    """Generate images or videos from text prompts."""
    pass


# ── generate image ───────────────────────────

@generate.command("image")
@click.argument("prompt")
@click.option("-o", "--output", "output_dir", default=".", show_default=True,
              help="Output directory for downloaded images.")
@click.option("-n", "--count", default=1, show_default=True,
              help="Number of images to generate.")
@click.option("--aspect", "aspect_ratio",
              type=click.Choice(["16:9", "9:16", "1:1"]),
              default="16:9", show_default=True,
              help="Aspect ratio.")
@click.option("--headless/--no-headless", default=None,
              help="Override headless mode.")
@click.option("-f", "--filename", default=None,
              help="Output filename stem (no extension).")
def generate_image(
    prompt: str,
    output_dir: str,
    count: int,
    aspect_ratio: str,
    headless: Optional[bool],
    filename: Optional[str],
):
    """Generate an IMAGE from a text prompt.

    \b
    Examples:
      flow generate image "golden Buddha on lotus throne, divine light"
      flow generate image "cherry blossoms" --aspect 9:16 --output ./photos
      flow generate image "mountain landscape" -n 4
    """
    _check_auth()
    ar = AspectRatio(aspect_ratio)

    async def _run():
        async with await FlowClient.create(headless=headless) as client:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]Generating image..."),
                TimeElapsedColumn(),
                transient=True,
            ) as progress:
                progress.add_task("gen", total=None)
                result = await client.generate_image(
                    prompt=prompt,
                    output_dir=Path(output_dir),
                    filename=filename,
                    aspect_ratio=ar,
                    count=count,
                )
            _print_result(result)

    _run_async(_run)


# ── generate video ───────────────────────────

@generate.command("video")
@click.argument("prompt")
@click.option("-o", "--output", "output_dir", default=".", show_default=True,
              help="Output directory.")
@click.option("--aspect", "aspect_ratio",
              type=click.Choice(["16:9", "9:16"]),
              default="16:9", show_default=True)
@click.option("--duration",
              type=click.Choice(["5s", "8s"]),
              default="8s", show_default=True,
              help="Video duration.")
@click.option("--headless/--no-headless", default=None)
@click.option("-f", "--filename", default=None)
def generate_video(
    prompt: str,
    output_dir: str,
    aspect_ratio: str,
    duration: str,
    headless: Optional[bool],
    filename: Optional[str],
):
    """Generate a VIDEO from a text prompt (Veo).

    \b
    Examples:
      flow generate video "aurora borealis, time-lapse, cinematic"
      flow generate video "temple bells swinging, slow motion" --aspect 9:16
      flow generate video "ocean waves at sunset" --duration 5s -o ./clips
    """
    _check_auth()

    async def _run():
        async with await FlowClient.create(headless=headless) as client:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]Generating video... (this takes 30-90s)"),
                TimeElapsedColumn(),
                transient=True,
            ) as progress:
                progress.add_task("gen", total=None)
                result = await client.generate_video(
                    prompt=prompt,
                    output_dir=Path(output_dir),
                    filename=filename,
                    aspect_ratio=AspectRatio(aspect_ratio),
                    duration=duration,
                )
            _print_result(result)

    _run_async(_run)


# ── generate frame ───────────────────────────

@generate.command("frame")
@click.argument("image_path")
@click.argument("prompt")
@click.option("-o", "--output", "output_dir", default=".", show_default=True)
@click.option("--duration", type=click.Choice(["5s", "8s"]), default="8s")
@click.option("--headless/--no-headless", default=None)
@click.option("-f", "--filename", default=None)
def generate_frame(
    image_path: str,
    prompt: str,
    output_dir: str,
    duration: str,
    headless: Optional[bool],
    filename: Optional[str],
):
    """Animate a static IMAGE with a motion prompt (Frame-to-Video).

    \b
    IMAGE_PATH  Source image (PNG/JPEG)
    PROMPT      Motion/camera description

    \b
    Examples:
      flow generate frame buddha.png "slow zoom-in with golden particles rising"
      flow generate frame slide.jpg "gentle camera pan left, wind in trees" --duration 5s
    """
    _check_auth()
    if not Path(image_path).exists():
        err_console.print(f"[red]Error:[/red] Image not found: {image_path}")
        sys.exit(1)

    async def _run():
        async with await FlowClient.create(headless=headless) as client:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]Animating image... (30-90s)"),
                TimeElapsedColumn(),
                transient=True,
            ) as progress:
                progress.add_task("gen", total=None)
                result = await client.generate_frame_to_video(
                    image_path=image_path,
                    prompt=prompt,
                    output_dir=Path(output_dir),
                    filename=filename,
                    duration=duration,
                )
            _print_result(result)

    _run_async(_run)
