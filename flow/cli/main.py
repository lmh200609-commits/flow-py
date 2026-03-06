"""
flow CLI — Google Flow AI command-line interface.

Usage:
    flow image "Golden lotus temple" -o ./out -n 4 -a portrait
    flow video "Sunrise over mountains" -o ./out
    flow extend <media_name> <workflow_id> -p "What happens next"
    flow camera <media_name> <workflow_id> --motion dolly_in
    flow insert <media_name> <workflow_id> -t "golden lotus flower"
    flow remove <media_name> <workflow_id>
    flow batch-images prompts.txt -o ./out
    flow batch-videos prompts.txt -o ./out --concurrency 3
    flow credits
    flow workflows
    flow download <fife_url> <output_path>
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

import click

from .._api import (
    FlowAPI,
    CAMERA_PRESETS,
    IMAGE_AR_LANDSCAPE, IMAGE_AR_PORTRAIT, IMAGE_AR_SQUARE,
    IMAGE_MODEL_NARWHAL, IMAGE_MODEL_IMAGEN3,
    VIDEO_AR_LANDSCAPE, VIDEO_AR_PORTRAIT,
    VIDEO_MODEL_VEO31_FAST, VIDEO_MODEL_VEO31_I2V,
    VIDEO_MODEL_EXTEND_L, VIDEO_MODEL_RESHOOT_L,
    VIDEO_MODEL_INSERT, VIDEO_MODEL_REMOVE,
    RESHOOT_FORWARD,
)
from .._browser import BrowserManager
from .._storage import get_active_project, load_config, set_active_project
from .._exceptions import (
    AuthError, GenerationError, GenerationTimeout,
    InvalidArgumentError, NotFoundError, FeatureUnavailableError,
)

# ── Shared helpers ────────────────────────────────────────────────────────────

def _aspect_image(s: str) -> str:
    return {"portrait": IMAGE_AR_PORTRAIT, "landscape": IMAGE_AR_LANDSCAPE, "square": IMAGE_AR_SQUARE}.get(s, IMAGE_AR_PORTRAIT)

def _aspect_video(s: str) -> str:
    return {"landscape": VIDEO_AR_LANDSCAPE, "portrait": VIDEO_AR_PORTRAIT}.get(s, VIDEO_AR_LANDSCAPE)

def _on_poll(status, elapsed):
    bar  = "▓" * int(elapsed / 10) + "░" * max(0, 30 - int(elapsed / 10))
    click.echo(f"\r  ⏳ {bar} {elapsed:.0f}s  {status.status}", nl=False, err=True)

async def _run(coro):
    return await coro

def run(coro):
    return asyncio.run(coro)


async def _make_api(project_id: Optional[str] = None, headless: bool = True) -> tuple[BrowserManager, FlowAPI]:
    cfg = load_config()
    pid = project_id or get_active_project()[0] or ""
    bm  = BrowserManager(headless=headless)
    await bm.start()
    api = FlowAPI(bm, project_id=pid, default_timeout_s=cfg.generation_timeout_s)
    await api._ensure_project_page()
    return bm, api


# ── CLI entry points ──────────────────────────────────────────────────────────

@click.group()
@click.version_option()
def cli():
    """🎬 Google Flow AI — direct REST API client."""
    pass


# ── image ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("prompt")
@click.option("-o", "--output", default=".", help="Output directory")
@click.option("-n", "--count", default=4, show_default=True, help="Number of images (1-4)")
@click.option("-a", "--aspect", default="portrait", show_default=True,
              type=click.Choice(["portrait","landscape","square"]), help="Aspect ratio")
@click.option("-m", "--model", default="narwhal", show_default=True,
              type=click.Choice(["narwhal","imagen3"]), help="Image model")
@click.option("-s", "--seed", default=None, type=int, help="Seed for reproducibility")
@click.option("-p", "--project", default=None, help="Project ID (overrides active project)")
@click.option("--no-download", is_flag=True, help="Skip downloading, just show URLs")
@click.option("--json-out", is_flag=True, help="Output JSON instead of text")
def image(prompt, output, count, aspect, model, seed, project, no_download, json_out):
    """Generate images from a text prompt."""

    async def _go():
        bm, api = await _make_api(project)
        try:
            img_model = IMAGE_MODEL_NARWHAL if model == "narwhal" else IMAGE_MODEL_IMAGEN3
            img_ar    = _aspect_image(aspect)

            click.echo(f"🖼  Generating {count} image(s) [{aspect}]…", err=True)
            t0 = time.monotonic()
            images = await api.generate_image(
                prompt, model=img_model, aspect_ratio=img_ar,
                count=count, seed=seed,
            )
            elapsed = time.monotonic() - t0
            click.echo(f"\n✅ Done in {elapsed:.1f}s — {len(images)} image(s)", err=True)

            results = []
            for i, img in enumerate(images):
                if not no_download and img.fife_url:
                    out_dir = Path(output)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    path = await api.download_image(img, out_dir)
                    click.echo(f"  [{i+1}] 💾 {path}")
                else:
                    click.echo(f"  [{i+1}] 🔗 {img.fife_url}")
                results.append({"media_name": img.media_name, "fife_url": img.fife_url,
                                 "seed": img.seed, "model": img.model,
                                 "file": str(img.file_path) if img.file_path else None})

            if json_out:
                click.echo(json.dumps(results, indent=2))
        finally:
            await bm.stop()

    run(_go())


# ── video ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("prompt")
@click.option("-o", "--output", default=".", help="Output directory")
@click.option("-a", "--aspect", default="landscape", show_default=True,
              type=click.Choice(["landscape","portrait"]))
@click.option("-m", "--model", default="veo31fast", show_default=True,
              type=click.Choice(["veo31fast","veo31","veo21fast"]))
@click.option("-s", "--seed", default=None, type=int)
@click.option("-t", "--timeout", default=300, show_default=True, help="Max wait seconds")
@click.option("-p", "--project", default=None)
@click.option("--no-download", is_flag=True)
@click.option("--json-out", is_flag=True)
def video(prompt, output, aspect, model, seed, timeout, project, no_download, json_out):
    """Generate a video from a text prompt (Veo 3.1)."""
    _model_map = {
        "veo31fast": VIDEO_MODEL_VEO31_FAST,
        "veo31":     "veo_3_1_t2v",
        "veo21fast": "veo_2_1_t2v_fast",
    }

    async def _go():
        bm, api = await _make_api(project)
        try:
            vid_ar = _aspect_video(aspect)
            click.echo(f"🎬 Generating video [{aspect}]…", err=True)

            job, status = await api.generate_video_and_wait(
                prompt, model=_model_map[model], aspect_ratio=vid_ar,
                seed=seed, timeout_s=timeout, on_poll=_on_poll,
            )
            click.echo(f"\n✅ Done in {job.elapsed_s:.1f}s | credits remaining: {job.remaining_credits}", err=True)

            result = {"media_name": job.media_name, "workflow_id": job.workflow_id,
                      "fife_url": status.fife_url, "seed": status.seed,
                      "model": status.model, "elapsed_s": job.elapsed_s}

            if not no_download and status.fife_url:
                path = await api.download_video(job, Path(output))
                click.echo(f"💾 {path}")
                result["file"] = str(path)
            else:
                click.echo(f"🔗 {status.fife_url}")

            if json_out:
                click.echo(json.dumps(result, indent=2))
        finally:
            await bm.stop()

    run(_go())


# ── extend ────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("media_name")
@click.argument("workflow_id")
@click.option("-p", "--prompt", default="", help="Continuation prompt")
@click.option("-n", "--times", default=1, show_default=True, help="Number of extensions")
@click.option("-o", "--output", default=".", help="Output directory")
@click.option("-a", "--aspect", default="landscape", type=click.Choice(["landscape","portrait"]))
@click.option("-t", "--timeout", default=300, show_default=True)
@click.option("--project", default=None)
@click.option("--json-out", is_flag=True)
def extend(media_name, workflow_id, prompt, times, output, aspect, timeout, project, json_out):
    """Extend an existing video N times (chain for infinite video)."""

    async def _go():
        bm, api = await _make_api(project)
        try:
            vid_ar = _aspect_video(aspect)
            click.echo(f"⏩ Extending video x{times}…", err=True)

            if times == 1:
                job, status = await api.extend_and_wait(
                    media_name, workflow_id, prompt,
                    aspect_ratio=vid_ar, timeout_s=timeout, on_poll=_on_poll,
                )
                click.echo(f"\n✅ Done in {job.elapsed_s:.1f}s", err=True)
                path = await api.download_video(job, Path(output)) if status.fife_url else None
                click.echo(f"💾 {path}" if path else f"🔗 {status.fife_url}")
                if json_out:
                    click.echo(json.dumps({"media_name": job.media_name,
                                           "workflow_id": job.workflow_id,
                                           "fife_url": status.fife_url,
                                           "file": str(path)}, indent=2))
            else:
                results = await api.extend_loop(
                    media_name, workflow_id, times,
                    prompt=prompt, output_dir=output,
                    aspect_ratio=vid_ar, timeout_s=timeout,
                    on_progress=lambda i, n, j, s: click.echo(f"\n  [{i}/{n}] ✅ segment_{i-1:03d}.mp4", err=True),
                )
                click.echo(f"\n✅ {len(results)} segments saved to {output}", err=True)
        finally:
            await bm.stop()

    run(_go())


# ── camera ────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("media_name")
@click.argument("workflow_id")
@click.option("--motion", "-m", default="dolly_in", show_default=True,
              type=click.Choice(list(CAMERA_PRESETS.keys())),
              help="Camera motion preset")
@click.option("-o", "--output", default=".", help="Output directory")
@click.option("-a", "--aspect", default="landscape", type=click.Choice(["landscape","portrait"]))
@click.option("-t", "--timeout", default=300, show_default=True)
@click.option("--project", default=None)
@click.option("--json-out", is_flag=True)
def camera(media_name, workflow_id, motion, output, aspect, timeout, project, json_out):
    """Apply a camera motion preset to an existing video (Reshoot).

    \b
    Presets:
      dolly_in / dolly_out          - Forward/backward camera push
      orbit_left / orbit_right      - Horizontal orbit
      orbit_up / orbit_down         - Vertical orbit
      dolly_zoom_in / dolly_zoom_out - Hitchcock effect
      pos_center / pos_left / pos_right / pos_high / pos_low / pos_closer / pos_further
    """

    async def _go():
        bm, api = await _make_api(project)
        try:
            motion_type = CAMERA_PRESETS[motion]
            vid_ar      = _aspect_video(aspect)
            click.echo(f"📷 Camera motion: {motion}…", err=True)

            job, status = await api.reshoot_and_wait(
                media_name, workflow_id, motion_type,
                aspect_ratio=vid_ar, timeout_s=timeout, on_poll=_on_poll,
            )
            click.echo(f"\n✅ Done in {job.elapsed_s:.1f}s", err=True)

            path = await api.download_video(job, Path(output)) if status.fife_url else None
            click.echo(f"💾 {path}" if path else f"🔗 {status.fife_url}")

            if json_out:
                click.echo(json.dumps({"media_name": job.media_name,
                                       "workflow_id": job.workflow_id,
                                       "motion": motion, "fife_url": status.fife_url,
                                       "file": str(path)}, indent=2))
        finally:
            await bm.stop()

    run(_go())


# ── insert ────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("media_name")
@click.argument("workflow_id")
@click.option("-t", "--text", required=True, help="Object description to insert")
@click.option("-o", "--output", default=".", help="Output directory")
@click.option("-a", "--aspect", default="landscape", type=click.Choice(["landscape","portrait"]))
@click.option("--timeout", default=300, show_default=True)
@click.option("--project", default=None)
@click.option("--json-out", is_flag=True)
def insert(media_name, workflow_id, text, output, aspect, timeout, project, json_out):
    """Insert a new object into an existing video via natural language."""

    async def _go():
        bm, api = await _make_api(project)
        try:
            vid_ar = _aspect_video(aspect)
            click.echo(f"➕ Inserting: '{text}'…", err=True)

            job, status = await api.insert_and_wait(
                media_name, workflow_id, text,
                timeout_s=timeout, on_poll=_on_poll,
            )
            click.echo(f"\n✅ Done in {job.elapsed_s:.1f}s", err=True)

            path = await api.download_video(job, Path(output)) if status.fife_url else None
            click.echo(f"💾 {path}" if path else f"🔗 {status.fife_url}")
            if json_out:
                click.echo(json.dumps({"media_name": job.media_name, "fife_url": status.fife_url,
                                       "file": str(path)}, indent=2))
        finally:
            await bm.stop()

    run(_go())


# ── remove ────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("media_name")
@click.argument("workflow_id")
@click.option("-o", "--output", default=".", help="Output directory")
@click.option("-a", "--aspect", default="landscape", type=click.Choice(["landscape","portrait"]))
@click.option("--timeout", default=300, show_default=True)
@click.option("--project", default=None)
@click.option("--json-out", is_flag=True)
def remove(media_name, workflow_id, output, aspect, timeout, project, json_out):
    """Remove an object from an existing video (auto-detects most prominent object)."""

    async def _go():
        bm, api = await _make_api(project)
        try:
            vid_ar = _aspect_video(aspect)
            click.echo("🧹 Removing object…", err=True)

            job, status = await api.remove_and_wait(
                media_name, workflow_id,
                timeout_s=timeout, on_poll=_on_poll,
            )
            click.echo(f"\n✅ Done in {job.elapsed_s:.1f}s", err=True)

            path = await api.download_video(job, Path(output)) if status.fife_url else None
            click.echo(f"💾 {path}" if path else f"🔗 {status.fife_url}")
            if json_out:
                click.echo(json.dumps({"media_name": job.media_name, "fife_url": status.fife_url,
                                       "file": str(path)}, indent=2))
        finally:
            await bm.stop()

    run(_go())


# ── poll ──────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("media_name")
@click.option("-p", "--project", default=None)
@click.option("-t", "--timeout", default=300, show_default=True, help="Max wait seconds (0=infinite)")
@click.option("-o", "--output", default=".", help="Download directory (if complete)")
@click.option("--no-download", is_flag=True, help="Print fife_url but don't download")
@click.option("--json-out", is_flag=True)
def poll(media_name, project, timeout, output, no_download, json_out):
    """Poll a pending video job until it completes and download the result.

    \b
    media_name: The UUID returned by video/extend/camera/insert/remove commands.
    Useful if a previous command timed out or you want to track an existing job.

    \b
    Examples:
      flow poll 101b581f-6083-42f0-a0e6-f43980bc61ba
      flow poll 101b581f... --no-download --json-out
    """

    async def _go():
        bm, api = await _make_api(project)
        try:
            click.echo(f"⏳ Polling {media_name[:8]}…", err=True)
            from .._api import VideoJob
            # Create a minimal VideoJob shell
            job = VideoJob({"media": [{"name": media_name, "projectId": api.project_id}]})

            try:
                status = await api.wait_for_video(
                    job, timeout_s=timeout or 0, on_poll=_on_poll
                )
            except GenerationTimeout:
                click.echo(f"\n⏰ Timed out after {timeout}s. Re-run `flow poll {media_name}` to resume.", err=True)
                raise SystemExit(1)

            click.echo(f"\n✅ Complete — seed={status.seed}", err=True)

            result = {
                "media_name": media_name,
                "status": status.status,
                "fife_url": status.fife_url,
                "seed": status.seed,
                "model": status.model,
            }

            if not no_download and status.fife_url:
                path = await api.download_video(job, Path(output))
                click.echo(f"💾 {path}")
                result["file"] = str(path)
            else:
                click.echo(f"🔗 {status.fife_url}")

            if json_out:
                click.echo(json.dumps(result, indent=2))
        finally:
            await bm.stop()

    run(_go())


# ── frames (image → video) ────────────────────────────────────────────────────

@cli.command()
@click.argument("start_media_or_file")
@click.option("-p", "--prompt", default="", help="Continuation/style prompt")
@click.option("--end", default=None, help="End-frame media UUID (enables start+end mode)")
@click.option("-m", "--model", default="veo31i2v", show_default=True,
              type=click.Choice(["veo31i2v", "veo21i2v", "startend"]),
              help="Image-to-video model")
@click.option("-a", "--aspect", default="portrait", type=click.Choice(["landscape","portrait"]))
@click.option("-o", "--output", default=".", help="Output directory")
@click.option("-t", "--timeout", default=300, show_default=True)
@click.option("--project", default=None)
@click.option("--json-out", is_flag=True)
def frames(start_media_or_file, prompt, end, model, aspect, output, timeout, project, json_out):
    """Generate a video from start (and optional end) frame image(s).

    \b
    start_media_or_file: Media UUID of an uploaded image, OR a local file path
                         (will be uploaded automatically).

    \b
    Examples:
      flow frames abc123...              # UUID of already-uploaded image
      flow frames ./photo.jpg            # auto-upload then animate
      flow frames abc123 --end def456    # start+end frame pinning
    """
    from .._api import VIDEO_MODEL_VEO31_I2V, VIDEO_MODEL_VEO21_I2V, VIDEO_MODEL_VEO21_SE

    _model_map = {
        "veo31i2v": VIDEO_MODEL_VEO31_I2V,
        "veo21i2v": VIDEO_MODEL_VEO21_I2V,
        "startend": VIDEO_MODEL_VEO21_SE,
    }

    async def _go():
        bm, api = await _make_api(project)
        try:
            vid_ar = _aspect_video(aspect)
            vid_model = _model_map[model]

            # Resolve start frame
            import os
            if os.path.exists(start_media_or_file):
                click.echo(f"📤 Uploading {start_media_or_file}…", err=True)
                start_media = await api.upload_image(start_media_or_file)
                click.echo(f"   media_name = {start_media}", err=True)
            else:
                start_media = start_media_or_file

            click.echo(f"🎞  Animating image → video [{aspect}]…", err=True)
            job, status = await api.generate_video_and_wait(
                prompt,
                model=vid_model,
                aspect_ratio=vid_ar,
                timeout_s=timeout,
                on_poll=_on_poll,
                start_media_name=start_media,
                end_media_name=end,
            )
            click.echo(f"\n✅ Done in {job.elapsed_s:.1f}s", err=True)

            result = {"media_name": job.media_name, "workflow_id": job.workflow_id,
                      "fife_url": status.fife_url, "seed": status.seed}

            if status.fife_url:
                path = await api.download_video(job, Path(output))
                click.echo(f"💾 {path}")
                result["file"] = str(path)
            else:
                click.echo(f"🔗 {status.fife_url}")

            if json_out:
                click.echo(json.dumps(result, indent=2))
        finally:
            await bm.stop()

    run(_go())


# ── upscale ────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("media_name")
@click.argument("workflow_id")
@click.option("-o", "--output", default=".", help="Output directory")
@click.option("-t", "--timeout", default=300, show_default=True)
@click.option("--project", default=None)
@click.option("--json-out", is_flag=True)
def upscale(media_name, workflow_id, output, timeout, project, json_out):
    """Upscale a video to higher resolution.

    \b
    ⚠️  NOTE: Direct API upscale returns 404 as of 2026-03-06.
    The feature works via the Flow UI download dialog (Upscale button).
    This command will attempt the API and report the status clearly.
    """

    async def _go():
        bm, api = await _make_api(project)
        try:
            click.echo("⬆️  Upscaling video…", err=True)
            try:
                job = await api.upscale_video(media_name, workflow_id)
                click.echo(f"  Submitted → media={job.media_name[:8]}…", err=True)
                from .._api import VideoJob as _VJ
                status = await api.wait_for_video(job, timeout_s=timeout, on_poll=_on_poll)
                click.echo(f"\n✅ Done", err=True)
                path = await api.download_video(job, Path(output)) if status.fife_url else None
                click.echo(f"💾 {path}" if path else f"🔗 {status.fife_url}")
                if json_out:
                    click.echo(json.dumps({
                        "media_name": job.media_name, "fife_url": status.fife_url,
                        "file": str(path) if path else None,
                    }, indent=2))
            except FeatureUnavailableError as e:
                click.echo(f"\n⚠️  {e}", err=True)
                click.echo("💡 Workaround: Open the video in Flow UI → Download → click Upscale", err=True)
                raise SystemExit(1)
            except (NotFoundError, InvalidArgumentError) as e:
                click.echo(f"\n❌ {e}", err=True)
                raise SystemExit(1)
        finally:
            await bm.stop()

    run(_go())


# ── batch-images ──────────────────────────────────────────────────────────────

@cli.command("batch-images")
@click.argument("prompts_file", type=click.Path(exists=True))
@click.option("-o", "--output", default=".", help="Output directory")
@click.option("-n", "--count", default=1, show_default=True)
@click.option("-a", "--aspect", default="portrait", type=click.Choice(["portrait","landscape","square"]))
@click.option("--delay", default=1.0, show_default=True, help="Delay between prompts (s)")
@click.option("--project", default=None)
def batch_images(prompts_file, output, count, aspect, delay, project):
    """Generate images for every line in a prompts file."""

    async def _go():
        prompts = Path(prompts_file).read_text().splitlines()
        prompts = [p.strip() for p in prompts if p.strip() and not p.startswith("#")]
        click.echo(f"🖼  Batch: {len(prompts)} prompts × {count} images each", err=True)

        bm, api = await _make_api(project)
        try:
            results = await api.batch_generate_images(
                prompts, output, aspect_ratio=_aspect_image(aspect),
                count=count, delay_s=delay,
            )
            total = sum(len(r) for r in results)
            click.echo(f"✅ Generated {total} images → {output}")
        finally:
            await bm.stop()

    run(_go())


# ── batch-videos ──────────────────────────────────────────────────────────────

@cli.command("batch-videos")
@click.argument("prompts_file", type=click.Path(exists=True))
@click.option("-o", "--output", default=".", help="Output directory")
@click.option("-a", "--aspect", default="landscape", type=click.Choice(["landscape","portrait"]))
@click.option("-c", "--concurrency", default=3, show_default=True, help="Max parallel jobs")
@click.option("-t", "--timeout", default=300, show_default=True)
@click.option("--project", default=None)
@click.option("--json-out", is_flag=True)
def batch_videos(prompts_file, output, aspect, concurrency, timeout, project, json_out):
    """Generate videos for every line in a prompts file (concurrent)."""

    async def _go():
        prompts = Path(prompts_file).read_text().splitlines()
        prompts = [p.strip() for p in prompts if p.strip() and not p.startswith("#")]
        click.echo(f"🎬 Batch: {len(prompts)} prompts | concurrency={concurrency}", err=True)

        bm, api = await _make_api(project)
        try:
            results = []

            def on_done(prompt, job, status):
                click.echo(f"\n  ✅ {prompt[:50]} → {job.file_path or status.fife_url[:40]}", err=True)
                results.append({"prompt": prompt, "media_name": job.media_name,
                                 "fife_url": status.fife_url,
                                 "file": str(job.file_path) if job.file_path else None})

            await api.batch_generate_videos(
                prompts, output, aspect_ratio=_aspect_video(aspect),
                concurrency=concurrency, timeout_s=timeout, on_done=on_done,
            )
            click.echo(f"\n✅ {len(results)} videos → {output}")
            if json_out:
                click.echo(json.dumps(results, indent=2))
        finally:
            await bm.stop()

    run(_go())


# ── credits ───────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--project", default=None)
@click.option("--json-out", is_flag=True)
def credits(project, json_out):
    """Show current credit balance and tier."""

    async def _go():
        bm, api = await _make_api(project)
        try:
            c = await api.get_credits()
            if json_out:
                click.echo(json.dumps({"credits": c.credits, "tier": c.tier,
                                       "sku": c.sku, "service_tier": c.service_tier}))
            else:
                click.echo(f"💳 Credits: {c.credits}")
                click.echo(f"   Tier:    {c.tier}")
                click.echo(f"   SKU:     {c.sku}")
        finally:
            await bm.stop()

    run(_go())


# ── workflows ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--project", default=None)
@click.option("-n", "--limit", default=20, show_default=True)
@click.option("--json-out", is_flag=True)
def workflows(project, limit, json_out):
    """List workflows (generation sessions) in the active project."""

    async def _go():
        bm, api = await _make_api(project)
        try:
            wfs = await api.list_workflows()
            wfs = wfs[-limit:]
            if json_out:
                click.echo(json.dumps([{
                    "name": w.name, "display_name": w.display_name,
                    "create_time": w.create_time, "primary_media_id": w.primary_media_id,
                } for w in wfs], indent=2))
            else:
                for w in wfs:
                    click.echo(f"  {w.name[:8]}…  {w.display_name or '(unnamed)':40s}  media={w.primary_media_id[:8]}…")
        finally:
            await bm.stop()

    run(_go())


# ── download ──────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("fife_url")
@click.argument("output_path")
@click.option("--project", default=None)
def download(fife_url, output_path, project):
    """Download a media file from its fife_url."""

    async def _go():
        bm, api = await _make_api(project)
        try:
            path = await api.download(fife_url, output_path)
            click.echo(f"💾 {path}")
        finally:
            await bm.stop()

    run(_go())


# ── projects ──────────────────────────────────────────────────────────────────

@cli.group()
def projects():
    """Manage Flow projects."""
    pass

@projects.command("use")
@click.argument("project_id_or_url")
def projects_use(project_id_or_url):
    """Set the active project."""
    import re
    if "http" in project_id_or_url:
        m   = re.search(r"/project/([^/?#]+)", project_id_or_url)
        pid = m.group(1) if m else project_id_or_url
    else:
        pid = project_id_or_url
    set_active_project(pid, f"https://labs.google/fx/tools/flow/project/{pid}")
    click.echo(f"✅ Active project: {pid}")

@projects.command("list")
def projects_list():
    """List saved projects."""
    from .._storage import load_projects
    for pid, info in load_projects().items():
        active = "▶" if pid == get_active_project()[0] else " "
        click.echo(f"{active} {pid}  {info.get('name','')}")


# ── model list ────────────────────────────────────────────────────────────────

@cli.command("models")
def models():
    """List all known model keys."""
    from .. import _api as a
    click.echo("\n📷 Image models:")
    click.echo(f"  narwhal   = {a.IMAGE_MODEL_NARWHAL}  (Nano Banana 2 / Imagen 3.5)")
    click.echo(f"  imagen3   = {a.IMAGE_MODEL_IMAGEN3}")

    click.echo("\n🎬 Video models (text→video):")
    click.echo(f"  veo31fast = {a.VIDEO_MODEL_VEO31_FAST}")
    click.echo(f"            = {a.VIDEO_MODEL_VEO31_STD}")
    click.echo(f"  veo21fast = {a.VIDEO_MODEL_VEO21_FAST}")

    click.echo("\n🖼→🎬 Image→video models:")
    click.echo(f"  i2v-31    = {a.VIDEO_MODEL_VEO31_I2V}")
    click.echo(f"  i2v-21    = {a.VIDEO_MODEL_VEO21_I2V}")
    click.echo(f"  i2v-se    = {a.VIDEO_MODEL_VEO21_SE}  (start+end frame)")

    click.echo("\n⏩ Extend models:")
    click.echo(f"  extend-l  = {a.VIDEO_MODEL_EXTEND_L}  (landscape)")
    click.echo(f"  extend-p  = {a.VIDEO_MODEL_EXTEND_P}  (portrait)")

    click.echo("\n📷 Camera / Reshoot models:")
    click.echo(f"  reshoot-l = {a.VIDEO_MODEL_RESHOOT_L}")

    click.echo("\n✏️  Editing models:")
    click.echo(f"  insert    = {a.VIDEO_MODEL_INSERT}")
    click.echo(f"  remove    = {a.VIDEO_MODEL_REMOVE}")

    click.echo("\n📷 Camera presets (--motion):")
    for k, v in a.CAMERA_PRESETS.items():
        click.echo(f"  {k:20s} = {v}")


if __name__ == "__main__":
    cli()
