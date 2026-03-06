"""
flow CLI — Google Flow AI — full command-line interface.

All generation commands use UI automation so reCAPTCHA tokens are valid.
Read-only commands (credits, poll, models) use direct REST API (faster).

Quick start:
    flow login                              # Authenticate (opens browser)
    flow credits                            # Check balance
    flow video "golden lotus at dawn"       # Text → Video (Veo 3.1)
    flow image "serene temple pond" -n 4    # Text → Image (x4)
    flow extend <media_id> -w <workflow_id> # Extend a video
    flow extend-loop <media_id> -n 10       # Make a 10× longer video!
    flow upscale <media_id> -w <wid>        # Free 1080p upscale
    flow models                             # List all models + costs
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

import click

from .._browser import BrowserManager
from .._client import FlowClient, CAMERA_MOTIONS, CAMERA_POSITIONS
from .._storage import get_active_project, load_config, save_config, set_active_project
from .._exceptions import (
    AuthError, GenerationError, GenerationTimeout,
    InvalidArgumentError, NotFoundError,
)
from .._api import (
    FlowAPI,
    FLOW_BASE,
    VIDEO_MODEL_VEO31_FAST, VIDEO_MODEL_VEO31_I2V,
    IMAGE_MODEL_NARWHAL,
)

# ── Shared helpers ─────────────────────────────────────────────────────────────

# Global verbosity context (set by CLI root)
_VERBOSE = False
_QUIET = False


def vprint(*args, **kwargs):
    """Print only when --verbose is active."""
    if _VERBOSE:
        click.echo(*args, **kwargs)


def qprint(*args, **kwargs):
    """Print only when NOT --quiet."""
    if not _QUIET:
        click.echo(*args, **kwargs)


def _poll_cb(status, elapsed: float):
    """Progress bar callback for wait operations."""
    if _QUIET:
        return
    bar = "▓" * min(30, int(elapsed / 10)) + "░" * max(0, 30 - int(elapsed / 10))
    click.echo(f"\r  ⏳ {bar} {elapsed:.0f}s  {status.status}", nl=False, err=True)


def _poll_cb_verbose(status, elapsed: float):
    """Verbose progress callback — prints full status line."""
    if _QUIET:
        return
    if _VERBOSE:
        click.echo(f"  [{elapsed:.0f}s] status={status.status}", err=True)
    else:
        _poll_cb(status, elapsed)


def run(coro):
    return asyncio.run(coro)


async def _make_client(
    project_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    headless: bool = True,
    cdp: bool = False,
) -> FlowClient:
    cdp_url = "http://127.0.0.1:9222" if cdp else None
    cfg = load_config()
    pid = project_id or get_active_project()[0] or ""
    if _VERBOSE:
        click.echo(f"  🔌 Connecting browser (cdp={bool(cdp_url)}, headless={headless})", err=True)
    return await FlowClient.create(
        pid, workflow_id, headless=headless, cdp_url=cdp_url,
        timeout_s=cfg.generation_timeout_s,
    )


# ── CLI root ───────────────────────────────────────────────────────────────────

@click.group()
@click.version_option()
@click.option("--debug",   is_flag=True, help="Enable debug logging")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output (extra detail)")
@click.option("--quiet",   "-q", is_flag=True, help="Suppress progress, print only results")
@click.pass_context
def cli(ctx: click.Context, debug: bool, verbose: bool, quiet: bool):
    """🎬 Google Flow AI — video & image generation CLI"""
    global _VERBOSE, _QUIET
    _VERBOSE = verbose
    _QUIET = quiet
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)
    # Store in context for subcommands that want to inspect
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet


# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
def login():
    """Open browser for Google authentication."""
    async def _go():
        bm = BrowserManager(headless=False)
        await bm.start()
        page = await bm.page()
        click.echo("🌐 Opening browser — sign in to Google, then come back...")
        await page.goto(FLOW_BASE, wait_until="domcontentloaded")

        # Wait for labs.google to be loaded and authenticated
        while True:
            url = page.url
            if "labs.google" in url:
                # Check if logged in
                logged_in = await page.evaluate("""
                    () => window.__NEXT_DATA__?.props?.pageProps?.session?.user?.email || null
                """)
                if logged_in:
                    click.echo(f"✅ Logged in as: {logged_in}")
                    break
            await asyncio.sleep(2)
            click.echo("  (waiting for login...)", err=True)

        await bm.stop()
        click.echo("🔐 Session saved. You can now use flow commands.")

    run(_go())


@cli.command()
def logout():
    """Clear saved browser session."""
    from .._storage import PROFILE_DIR
    import shutil
    if PROFILE_DIR.exists():
        shutil.rmtree(PROFILE_DIR)
        click.echo("✅ Session cleared.")
    else:
        click.echo("No session to clear.")


# ══════════════════════════════════════════════════════════════════════════════
# PROJECTS
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.option("--project", "-p", default=None, help="Project ID")
@click.option("--cdp", is_flag=True, help="Connect to existing Chrome CDP")
def projects(project: Optional[str], cdp: bool):
    """List saved projects and their IDs."""
    from .._storage import load_projects
    projs = load_projects()
    pid, _ = get_active_project()
    if not projs:
        click.echo("No saved projects. Use `flow use <project_id>` to add one.")
        return
    click.echo(f"\n  {'':1} {'ID':38} {'Name'}")
    click.echo("  " + "─" * 60)
    for proj_id, info in projs.items():
        marker = "▶" if proj_id == pid else " "
        click.echo(f"  {marker} {proj_id:38} {info.get('name', '')}")


@cli.command("use")
@click.argument("project_id")
def use_project(project_id: str):
    """Set the active project."""
    from .._storage import add_project
    url = f"https://labs.google/fx/tools/flow/project/{project_id}"
    set_active_project(project_id, url)
    add_project(project_id, "imported", url)
    click.echo(f"Active project: {project_id}")


@cli.command()
@click.option("--project", "-p", default=None)
@click.option("--cdp", is_flag=True)
@click.option("-n", "--limit", default=20, show_default=True)
def workflows(project: Optional[str], cdp: bool, limit: int):
    """List workflows (generation sessions) in the active project."""
    async def _go():
        client = await _make_client(project, cdp=cdp)
        try:
            wfs = await client.get_workflows()
            wfs = wfs[-limit:]
            if not wfs:
                click.echo("No workflows found.")
                return
            click.echo(f"\n  {'Workflow ID':38} {'Name':30} {'Media ID'}")
            click.echo("  " + "─" * 90)
            for wf in wfs:
                click.echo(
                    f"  {wf.name:38} "
                    f"{(wf.display_name or '(unnamed)')[:30]:30} "
                    f"{wf.primary_media_id[:16]}..."
                )
        finally:
            await client.close()
    run(_go())


@cli.command()
def config():
    """Show current configuration."""
    cfg = load_config()
    pid, url = get_active_project()
    click.echo(f"Active project: {pid or '(none)'}")
    if url:
        click.echo(f"Project URL:    {url}")
    click.echo(f"Timeout:        {cfg.generation_timeout_s}s")
    click.echo(f"Headless:       {cfg.headless}")
    click.echo(f"Output dir:     {cfg.default_output_dir}")
    click.echo(f"Profile dir:    ~/.flow-py/browser-profile")


@cli.command()
@click.option("--project", "-p", default=None, help="Project ID to check")
@click.option("--cdp", is_flag=True, help="Connect to existing Chrome CDP")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status(project: Optional[str], cdp: bool, as_json: bool):
    """Show current auth, project, credits, and recent workflow status.

    A quick health-check command — tells you everything you need before generating.

    Examples:\n
        flow status\n
        flow status --json
    """
    async def _go():
        from .._storage import load_projects

        pid, url = get_active_project()
        pid = project or pid or ""
        cfg = load_config()
        projects = load_projects()

        info: dict = {
            "auth": "unknown",
            "active_project": pid or None,
            "project_url": url or None,
            "credits": None,
            "tier": None,
            "recent_workflows": [],
            "config": {
                "timeout_s": cfg.generation_timeout_s,
                "headless": cfg.headless,
                "output_dir": str(cfg.default_output_dir),
            },
        }

        if not pid:
            info["auth"] = "no_project"
            if as_json:
                click.echo(json.dumps(info, indent=2))
            else:
                click.echo("⚠️  No active project. Run `flow use <project_id>` first.")
            return

        # Try to connect and fetch live data
        try:
            client = await _make_client(pid, cdp=cdp)
            try:
                # Credits
                credits_obj = await client.get_credits()
                info["credits"] = credits_obj.credits
                info["tier"] = credits_obj.tier
                info["auth"] = "authenticated"

                # Recent workflows
                try:
                    wfs = await client.get_workflows()
                    recent = wfs[-5:] if len(wfs) > 5 else wfs
                    info["recent_workflows"] = [
                        {
                            "id": wf.name,
                            "name": wf.display_name or "(unnamed)",
                            "media_id": wf.primary_media_id[:16] if wf.primary_media_id else "",
                        }
                        for wf in recent
                    ]
                except Exception as wf_err:
                    info["recent_workflows"] = []
                    if _VERBOSE:
                        click.echo(f"  ⚠️ Could not fetch workflows: {wf_err}", err=True)

            finally:
                await client.close()

        except AuthError:
            info["auth"] = "not_logged_in"
        except Exception as e:
            info["auth"] = f"error: {e}"

        if as_json:
            click.echo(json.dumps(info, indent=2))
            return

        # Human-friendly display
        auth_icon = "✅" if info["auth"] == "authenticated" else "❌"
        click.echo(f"\n{'─'*50}")
        click.echo(f"  🎬 flow-py Status")
        click.echo(f"{'─'*50}")
        click.echo(f"  Auth:        {auth_icon} {info['auth']}")
        click.echo(f"  Project:     {pid[:8]}...{pid[-4:] if len(pid)>12 else pid}")
        if info["credits"] is not None:
            credit_icon = "💳" if info["credits"] > 100 else "⚠️"
            click.echo(f"  Credits:     {credit_icon} {info['credits']} ({info['tier']})")
        click.echo(f"  Timeout:     {cfg.generation_timeout_s}s")
        click.echo(f"  Headless:    {cfg.headless}")

        if info["recent_workflows"]:
            click.echo(f"\n  📁 Recent workflows ({len(info['recent_workflows'])}):")
            for wf in info["recent_workflows"]:
                click.echo(f"     {wf['id'][:12]}...  {wf['name'][:30]}")

        click.echo(f"{'─'*50}\n")

    run(_go())


# ══════════════════════════════════════════════════════════════════════════════
# CREDITS & MODELS
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.option("--project", "-p", default=None)
@click.option("--cdp", is_flag=True)
def credits(project: Optional[str], cdp: bool):
    """Show remaining credits."""
    async def _go():
        client = await _make_client(project, cdp=cdp)
        try:
            c = await client.get_credits()
            click.echo(f"\n💳 Credits remaining: {c.credits}")
            click.echo(f"   Tier: {c.tier}")
            click.echo(f"   SKU:  {c.sku}")
        finally:
            await client.close()
    run(_go())


@cli.command()
@click.option("--project", "-p", default=None)
@click.option("--cdp", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def models(project: Optional[str], cdp: bool, as_json: bool):
    """List all available models with costs."""
    async def _go():
        client = await _make_client(project, cdp=cdp)
        try:
            cfg = await client.get_model_config()
            all_models = cfg.get("result", cfg).get("videoModels", cfg.get("videoModels", []))
            if as_json:
                click.echo(json.dumps(all_models, indent=2))
                return

            active = [m for m in all_models if not m.get("deprecated")]
            click.echo(f"\n{'Key':45} {'Cost':6} {'Features'}")
            click.echo("─" * 90)
            for m in sorted(active, key=lambda x: x.get("creditCost", 0)):
                key   = m.get("key", "?")
                cost  = m.get("creditCost", "?")
                feats = ", ".join(m.get("supportedFeatures", []))[:40]
                click.echo(f"{key:45} {str(cost):6} {feats}")
        finally:
            await client.close()
    run(_go())


# ══════════════════════════════════════════════════════════════════════════════
# POLL & DOWNLOAD
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("media_id")
@click.option("--project", "-p", default=None)
@click.option("--cdp", is_flag=True)
@click.option("--wait", is_flag=True, help="Wait until complete")
@click.option("--timeout", default=300, show_default=True, help="Seconds to wait")
def poll(media_id: str, project: Optional[str], cdp: bool, wait: bool, timeout: int):
    """Poll video generation status."""
    async def _go():
        client = await _make_client(project, cdp=cdp)
        try:
            status = await client.poll_video(media_id)
            click.echo(f"Status:   {status.status}")
            click.echo(f"Complete: {status.complete}")
            if status.fife_url:
                click.echo(f"URL:      {status.fife_url[:80]}")

            if wait and not status.complete:
                from .._api import VideoJob
                job = VideoJob.__new__(VideoJob)
                job.media_name = media_id
                job.status = status.status
                job.project_id = ""
                status = await client.wait_for_video(
                    job, on_poll=_poll_cb, timeout_s=timeout
                )
                click.echo(f"\n✅ Done! {status.status}")
                if status.fife_url:
                    click.echo(f"URL: {status.fife_url}")
        finally:
            await client.close()
    run(_go())


@cli.command()
@click.argument("media_id")
@click.option("--output", "-o", default="./flow_output", show_default=True)
@click.option("--project", "-p", default=None)
@click.option("--cdp", is_flag=True)
def download(media_id: str, output: str, project: Optional[str], cdp: bool):
    """Download a generated video or image."""
    async def _go():
        client = await _make_client(project, cdp=cdp)
        try:
            # If output is a directory, auto-name the file
            out = Path(output)
            if out.is_dir() or not out.suffix:
                out.mkdir(parents=True, exist_ok=True)
                out = out / f"{media_id[:8]}.mp4"

            click.echo(f"⬇️  Downloading {media_id[:16]}...")
            path = await client.download(media_id, out)
            click.echo(f"✅ Saved: {path}")
        finally:
            await client.close()
    run(_go())


# ══════════════════════════════════════════════════════════════════════════════
# GENERATION — VIDEO
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("prompt")
@click.option("--project", "-p", default=None, help="Project ID")
@click.option("--workflow", "-w", default=None, help="Workflow ID")
@click.option("--model",  "-m", default="Veo 3.1 - Fast", show_default=True, help="Model display name")
@click.option("--aspect", "-a", default="landscape", type=click.Choice(["landscape", "portrait"]), show_default=True)
@click.option("--count",  "-n", default=1, type=click.IntRange(1, 4), show_default=True)
@click.option("--start",  default=None, help="Image path for I2V (Image-to-Video) mode")
@click.option("--wait/--no-wait", default=True, show_default=True)
@click.option("--output", "-o", default="./flow_output", show_default=True)
@click.option("--headless/--headed", default=True, show_default=True)
@click.option("--cdp", is_flag=True, help="Connect to existing Chrome CDP (port 9222)")
def video(
    prompt, project, workflow, model, aspect, count, start, wait, output, headless, cdp
):
    """Generate video(s) from text (T2V) or image (I2V).

    Examples:\n
        flow video "golden lotus blooming"\n
        flow video "lotus at dawn" --aspect portrait -n 2\n
        flow video "lotus blooms" --start ./frame.jpg  # I2V\n
        flow video "temple sunrise" --model "Veo 2.1"
    """
    async def _go():
        client = await _make_client(project, workflow, headless=headless, cdp=cdp)
        try:
            click.echo(f"🎬 Generating video: \"{prompt[:60]}\"")
            if start:
                click.echo(f"   Mode: Image-to-Video  source: {start}")
            click.echo(f"   Model: {model}  aspect: {aspect}  count: {count}")

            jobs = await client.generate_video(
                prompt, model=model, aspect=aspect, count=count, start_image=start
            )
            click.echo(f"✅ Submitted {len(jobs)} job(s)")
            for j in jobs:
                click.echo(f"   media_id: {j.media_name}")

            if wait:
                out = Path(output)
                out.mkdir(parents=True, exist_ok=True)
                click.echo("\n⏳ Waiting for generation...", err=True)
                for i, job in enumerate(jobs):
                    status = await client.wait_for_video(job, on_poll=_poll_cb)
                    click.echo(f"\n✅ Job {i+1}/{len(jobs)}: {status.status}")
                    if status.fife_url:
                        path = out / f"video_{i+1:03d}_{job.media_name[:8]}.mp4"
                        await client.download(status.fife_url, path)
                        click.echo(f"   💾 {path}")
        except (GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()
    run(_go())


# ══════════════════════════════════════════════════════════════════════════════
# GENERATION — IMAGE
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("prompt")
@click.option("--project", "-p", default=None)
@click.option("--aspect", "-a", default="landscape",
              type=click.Choice(["landscape", "portrait", "square"]), show_default=True)
@click.option("--count",  "-n", default=4, type=click.IntRange(1, 4), show_default=True)
@click.option("--output", "-o", default="./flow_images", show_default=True)
@click.option("--headless/--headed", default=True, show_default=True)
@click.option("--cdp", is_flag=True)
def image(prompt, project, aspect, count, output, headless, cdp):
    """Generate images from text (T2I).

    Examples:\n
        flow image "golden lotus temple" -n 4\n
        flow image "serene pond" --aspect portrait -o ./images
    """
    async def _go():
        client = await _make_client(project, headless=headless, cdp=cdp)
        try:
            click.echo(f"🖼️  Generating {count} image(s): \"{prompt[:60]}\"")
            imgs = await client.generate_image(prompt, aspect=aspect, count=count)
            out = Path(output)
            out.mkdir(parents=True, exist_ok=True)
            click.echo(f"✅ Got {len(imgs)} image(s)")
            for i, img in enumerate(imgs):
                if img.fife_url:
                    path = out / f"image_{i+1:03d}.jpg"
                    await client.download(img.fife_url, path)
                    click.echo(f"   💾 {path}")
                else:
                    click.echo(f"   ⚠️ image {i+1} has no URL")
        except (GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()
    run(_go())


# ══════════════════════════════════════════════════════════════════════════════
# EDIT-PAGE OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("media_id")
@click.option("--workflow", "-w", required=True, help="Workflow ID")
@click.option("--prompt",   "-p", default="", help="Narrative prompt for extension")
@click.option("--project",  default=None)
@click.option("--wait/--no-wait", default=True)
@click.option("--output",   "-o", default=None, help="Save output video here")
@click.option("--headless/--headed", default=True)
@click.option("--cdp", is_flag=True)
def extend(media_id, workflow, prompt, project, wait, output, headless, cdp):
    """Extend a video (make it longer).

    Example:\n
        flow extend abc123 -w wf456 -p "camera slowly pulls back"\n
        flow extend abc123 -w wf456 --output extended.mp4
    """
    async def _go():
        client = await _make_client(project, workflow, headless=headless, cdp=cdp)
        try:
            click.echo(f"⏩ Extending video: {media_id[:16]}...")
            job = await client.extend_video(media_id, workflow, prompt)
            click.echo(f"✅ Submitted → {job.media_name[:20]}")
            if wait:
                click.echo("⏳ Waiting...", err=True)
                status = await client.wait_for_video(job, on_poll=_poll_cb)
                click.echo(f"\n✅ {status.status}")
                if output and status.fife_url:
                    await client.download(status.fife_url, output)
                    click.echo(f"💾 {output}")
                elif status.fife_url:
                    click.echo(f"URL: {status.fife_url}")
        except (GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()
    run(_go())


@cli.command("extend-loop")
@click.argument("media_id")
@click.option("--workflow",   "-w", required=True, help="Workflow ID")
@click.option("--iterations", "-n", default=5, show_default=True, help="Number of extensions")
@click.option("--prompt",     "-p", default="", help="Narrative prompt (same for all extensions)")
@click.option("--output",     "-o", default="./flow_extensions", show_default=True)
@click.option("--project",    default=None)
@click.option("--headless/--headed", default=True)
@click.option("--cdp", is_flag=True)
def extend_loop(media_id, workflow, iterations, prompt, output, project, headless, cdp):
    """Extend a video N times in sequence — create arbitrarily long videos!

    Each extension builds on the previous result.
    A 5× extension of an 8s clip = ~48 seconds of video.

    Examples:\n
        flow extend-loop abc123 -w wf456 -n 10\n
        flow extend-loop abc123 -w wf456 -n 5 -p "calm steady push forward" -o ./out
    """
    async def _go():
        client = await _make_client(project, workflow, headless=headless, cdp=cdp)
        try:
            click.echo(f"🔄 Extend loop: {media_id[:16]} × {iterations}")
            start = time.time()
            jobs = await client.extend_loop(
                media_id, workflow, iterations=iterations,
                prompt=prompt, output_dir=output,
            )
            elapsed = time.time() - start
            click.echo(f"\n✅ All {len(jobs)} extensions complete in {elapsed:.0f}s")
            click.echo(f"   Output: {output}/")
        except (GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()
    run(_go())


@cli.command()
@click.argument("media_id")
@click.option("--workflow", "-w", required=True)
@click.option("--motion",
              type=click.Choice(list(CAMERA_MOTIONS.keys()), case_sensitive=False),
              required=True,
              help="Camera motion type")
@click.option("--project",  default=None)
@click.option("--wait/--no-wait", default=True)
@click.option("--output",   "-o", default=None)
@click.option("--headless/--headed", default=True)
@click.option("--cdp", is_flag=True)
def camera(media_id, workflow, motion, project, wait, output, headless, cdp):
    """Apply camera motion to a video.

    Motion options:\n
        dolly_in / dolly_out\n
        orbit_left / orbit_right / orbit_up / orbit_low\n
        dolly_zoom_in / dolly_zoom_out\n

    Example:\n
        flow camera abc123 -w wf456 --motion dolly_in
    """
    async def _go():
        client = await _make_client(project, workflow, headless=headless, cdp=cdp)
        try:
            click.echo(f"🎥 Camera motion '{motion}' on {media_id[:16]}...")
            job = await client.camera_motion(media_id, motion, workflow)
            click.echo(f"✅ Submitted → {job.media_name[:20]}")
            if wait:
                click.echo("⏳ Waiting...", err=True)
                status = await client.wait_for_video(job, on_poll=_poll_cb)
                click.echo(f"\n✅ {status.status}")
                if output and status.fife_url:
                    await client.download(status.fife_url, output)
                    click.echo(f"💾 {output}")
        except (GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()
    run(_go())


@cli.command("camera-pos")
@click.argument("media_id")
@click.option("--workflow",  "-w", required=True)
@click.option("--position",
              type=click.Choice(list(CAMERA_POSITIONS.keys()), case_sensitive=False),
              required=True)
@click.option("--project",   default=None)
@click.option("--wait/--no-wait", default=True)
@click.option("--output",    "-o", default=None)
@click.option("--headless/--headed", default=True)
@click.option("--cdp", is_flag=True)
def camera_pos(media_id, workflow, position, project, wait, output, headless, cdp):
    """Apply camera position change to a video.

    Positions: center, left, right, high, low, closer, further\n

    Example:\n
        flow camera-pos abc123 -w wf456 --position closer
    """
    async def _go():
        client = await _make_client(project, workflow, headless=headless, cdp=cdp)
        try:
            click.echo(f"📷 Camera position '{position}' on {media_id[:16]}...")
            job = await client.camera_position(media_id, position, workflow)
            click.echo(f"✅ Submitted → {job.media_name[:20]}")
            if wait:
                status = await client.wait_for_video(job, on_poll=_poll_cb)
                click.echo(f"\n✅ {status.status}")
                if output and status.fife_url:
                    await client.download(status.fife_url, output)
        except (GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()
    run(_go())


@cli.command()
@click.argument("media_id")
@click.option("--workflow", "-w", required=True)
@click.option("--text",     "-t", required=True, help="Object description to insert")
@click.option("--project",  default=None)
@click.option("--wait/--no-wait", default=True)
@click.option("--output",   "-o", default=None)
@click.option("--headless/--headed", default=True)
@click.option("--cdp", is_flag=True)
def insert(media_id, workflow, text, project, wait, output, headless, cdp):
    """Insert an object into a video using text description.

    Example:\n
        flow insert abc123 -w wf456 -t "a golden lotus flower"
    """
    async def _go():
        client = await _make_client(project, workflow, headless=headless, cdp=cdp)
        try:
            click.echo(f"➕ Inserting '{text[:40]}' into {media_id[:16]}...")
            job = await client.insert_object(media_id, text, workflow)
            click.echo(f"✅ Submitted → {job.media_name[:20]}")
            if wait:
                status = await client.wait_for_video(job, on_poll=_poll_cb)
                click.echo(f"\n✅ {status.status}")
                if output and status.fife_url:
                    await client.download(status.fife_url, output)
        except (GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()
    run(_go())


@cli.command()
@click.argument("media_id")
@click.option("--workflow", "-w", required=True)
@click.option("--x",   default=0.5, show_default=True, help="Mask center X (0.0-1.0)")
@click.option("--y",   default=0.5, show_default=True, help="Mask center Y (0.0-1.0)")
@click.option("--brush", default=40, show_default=True, help="Brush size (pixels)")
@click.option("--project",  default=None)
@click.option("--wait/--no-wait", default=True)
@click.option("--output",   "-o", default=None)
@click.option("--headless/--headed", default=True)
@click.option("--cdp", is_flag=True)
def remove(media_id, workflow, x, y, brush, project, wait, output, headless, cdp):
    """Remove an object from a video by drawing a mask.

    Example:\n
        flow remove abc123 -w wf456 --x 0.7 --y 0.3 --brush 60
    """
    async def _go():
        client = await _make_client(project, workflow, headless=headless, cdp=cdp)
        try:
            click.echo(f"✂️  Removing object at ({x:.1f},{y:.1f}) from {media_id[:16]}...")
            job = await client.remove_object(media_id, workflow, mask_x=x, mask_y=y, brush_size=brush)
            click.echo(f"✅ Submitted → {job.media_name[:20]}")
            if wait:
                status = await client.wait_for_video(job, on_poll=_poll_cb)
                click.echo(f"\n✅ {status.status}")
                if output and status.fife_url:
                    await client.download(status.fife_url, output)
        except (GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()
    run(_go())


@cli.command()
@click.argument("media_id")
@click.option("--workflow",    "-w", required=True)
@click.option("--resolution",  "-r", default="1080p",
              type=click.Choice(["1080p", "4k"]), show_default=True)
@click.option("--project",     default=None)
@click.option("--wait/--no-wait", default=True)
@click.option("--output",      "-o", default=None)
@click.option("--headless/--headed", default=True)
@click.option("--cdp", is_flag=True)
def upscale(media_id, workflow, resolution, project, wait, output, headless, cdp):
    """Upscale a video to higher resolution. FREE (0 credits)!

    Clicks the Download button then the '1080p Upscaled' option.
    Uses model: veo_3_1_upsampler_1080p (cost=0).

    Example:\n
        flow upscale abc123 -w wf456\n
        flow upscale abc123 -w wf456 -r 4k -o ./4k.mp4
    """
    async def _go():
        client = await _make_client(project, workflow, headless=headless, cdp=cdp)
        try:
            click.echo(f"⬆️  Upscaling {media_id[:16]} to {resolution} (FREE)...")
            job = await client.upscale_video(media_id, workflow, resolution)
            click.echo(f"✅ Submitted → {job.media_name[:20]}")
            if wait:
                click.echo("⏳ Waiting...", err=True)
                status = await client.wait_for_video(job, on_poll=_poll_cb)
                click.echo(f"\n✅ {status.status}")
                if output and status.fife_url:
                    await client.download(status.fife_url, output)
                    click.echo(f"💾 {output}")
                elif status.fife_url:
                    click.echo(f"URL: {status.fife_url[:80]}")
        except (GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()
    run(_go())


# ══════════════════════════════════════════════════════════════════════════════
# BATCH OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

@cli.command("batch-images")
@click.argument("prompts_file", type=click.Path(exists=True))
@click.option("--output",  "-o", default="./batch_images", show_default=True)
@click.option("--count",   "-n", default=2, type=click.IntRange(1, 4), show_default=True)
@click.option("--aspect",  "-a", default="landscape", show_default=True)
@click.option("--project", default=None)
@click.option("--headless/--headed", default=True)
@click.option("--cdp", is_flag=True)
def batch_images(prompts_file, output, count, aspect, project, headless, cdp):
    """Generate images for each prompt in a text file (one per line).

    Example:\n
        flow batch-images prompts.txt -n 4 -o ./gallery
    """
    async def _go():
        prompts = [
            p.strip() for p in Path(prompts_file).read_text().splitlines()
            if p.strip() and not p.startswith("#")
        ]
        click.echo(f"🖼️  Batch: {len(prompts)} prompts × {count} images")
        client = await _make_client(project, headless=headless, cdp=cdp)
        out = Path(output)
        out.mkdir(parents=True, exist_ok=True)
        total = 0
        try:
            for i, prompt in enumerate(prompts):
                click.echo(f"\n[{i+1}/{len(prompts)}] {prompt[:60]}")
                imgs = await client.generate_image(prompt, aspect=aspect, count=count)
                prompt_dir = out / f"prompt_{i+1:03d}"
                prompt_dir.mkdir(exist_ok=True)
                (prompt_dir / "prompt.txt").write_text(prompt)
                for j, img in enumerate(imgs):
                    if img.fife_url:
                        p = prompt_dir / f"img_{j+1:02d}.jpg"
                        await client.download(img.fife_url, p)
                        total += 1
            click.echo(f"\n✅ Generated {total} images → {output}/")
        finally:
            await client.close()
    run(_go())


@cli.command("batch-videos")
@click.argument("prompts_file", type=click.Path(exists=True))
@click.option("--output",      "-o", default="./batch_videos", show_default=True)
@click.option("--aspect",      "-a", default="landscape", show_default=True)
@click.option("--model",       "-m", default="Veo 3.1 - Fast", show_default=True)
@click.option("--concurrency", "-c", default=1, show_default=True, help="Parallel jobs")
@click.option("--project",     default=None)
@click.option("--headless/--headed", default=True)
@click.option("--cdp", is_flag=True)
def batch_videos(prompts_file, output, aspect, model, concurrency, project, headless, cdp):
    """Generate videos for each prompt in a file (one per line).

    Note: concurrency>1 requires multiple browser windows (more RAM).

    Example:\n
        flow batch-videos prompts.txt -c 2 -o ./videos
    """
    async def _go():
        prompts = [
            p.strip() for p in Path(prompts_file).read_text().splitlines()
            if p.strip() and not p.startswith("#")
        ]
        click.echo(f"🎬 Batch: {len(prompts)} videos (concurrency={concurrency})")
        out = Path(output)
        out.mkdir(parents=True, exist_ok=True)

        async def _one(i, prompt):
            c = await _make_client(project, headless=headless, cdp=cdp)
            try:
                click.echo(f"  [{i+1}] {prompt[:50]}")
                jobs = await c.generate_video(prompt, model=model, aspect=aspect)
                for j, job in enumerate(jobs):
                    status = await c.wait_for_video(job, on_poll=_poll_cb)
                    if status.fife_url:
                        p = out / f"video_{i+1:03d}.mp4"
                        await c.download(status.fife_url, p)
                        click.echo(f"\n  ✅ [{i+1}] saved {p}")
            finally:
                await c.close()

        sem = asyncio.Semaphore(concurrency)
        async def _bounded(i, p):
            async with sem:
                await _one(i, p)

        await asyncio.gather(*[_bounded(i, p) for i, p in enumerate(prompts)])
        click.echo(f"\n✅ Batch complete → {output}/")
    run(_go())


# ══════════════════════════════════════════════════════════════════════════════
# FRAMES (Image → Video)
# ══════════════════════════════════════════════════════════════════════════════

@cli.command()
@click.argument("image_path", type=click.Path(exists=True))
@click.option("--prompt",   "-p", default="", help="Motion/style prompt")
@click.option("--project",  default=None)
@click.option("--aspect",   "-a", default="portrait", type=click.Choice(["landscape", "portrait"]))
@click.option("--output",   "-o", default="./flow_output", show_default=True)
@click.option("--wait/--no-wait", default=True)
@click.option("--headless/--headed", default=True)
@click.option("--cdp", is_flag=True)
def frames(image_path, prompt, project, aspect, output, wait, headless, cdp):
    """Animate a static image into video (Image-to-Video / Frames mode).

    Examples:\n
        flow frames ./photo.jpg -p "slow zoom with golden light"\n
        flow frames slide.png --aspect landscape -o ./animated
    """
    async def _go():
        client = await _make_client(project, headless=headless, cdp=cdp)
        try:
            click.echo(f"🎞 Animating {image_path} → video [{aspect}]")
            jobs = await client.generate_video(
                prompt or "gentle camera movement",
                aspect=aspect, start_image=image_path,
            )
            click.echo(f"Submitted {len(jobs)} job(s)")
            if wait and jobs:
                out = Path(output)
                out.mkdir(parents=True, exist_ok=True)
                status = await client.wait_for_video(jobs[0], on_poll=_poll_cb)
                click.echo(f"\nDone: {status.status}")
                if status.fife_url:
                    path = out / f"animated_{jobs[0].media_name[:8]}.mp4"
                    await client.download(status.fife_url, path)
                    click.echo(f"Saved: {path}")
        except (GenerationError, GenerationTimeout) as e:
            click.echo(f"\n{e}", err=True)
            sys.exit(1)
        finally:
            await client.close()
    run(_go())


# ══════════════════════════════════════════════════════════════════════════════
# DOWNLOAD-ALL
# ══════════════════════════════════════════════════════════════════════════════

@cli.command("download-all")
@click.option("--workflow", "-w", default=None, help="Workflow ID (default: all)")
@click.option("--output",   "-o", default="./flow_downloads", show_default=True)
@click.option("--project",  default=None)
@click.option("--cdp", is_flag=True)
def download_all(workflow, output, project, cdp):
    """Download all media from a workflow or project."""
    async def _go():
        client = await _make_client(project, cdp=cdp)
        try:
            click.echo(f"Downloading all media → {output}/")
            paths = await client.download_all(workflow, output)
            click.echo(f"Downloaded {len(paths)} file(s)")
            for p in paths:
                click.echo(f"  {p}")
        finally:
            await client.close()
    run(_go())


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cli()
