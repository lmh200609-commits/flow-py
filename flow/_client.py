"""Core async FlowClient — high-level API for Google Flow AI automation."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import AsyncIterator, Optional
from urllib.parse import urlparse

import aiohttp
import aiofiles

from ._browser import BrowserManager, FLOW_BASE_URL
from ._exceptions import (
    AuthError,
    GenerationError,
    GenerationTimeout,
    NoProjectError,
    PolicyError,
    UIError,
)
from ._flow_ui import FlowUI
from ._models import (
    AspectRatio,
    BatchResult,
    FlowConfig,
    GenerationMode,
    GenerationResult,
    GenerationStatus,
    ParsedPrompt,
    parse_prompt_file,
)
from ._storage import (
    get_active_project,
    load_config,
    save_config,
    set_active_project,
    add_project,
    load_projects,
    save_projects,
)

log = logging.getLogger(__name__)


class FlowClient:
    """Async client for Google Flow AI.

    Usage (async context manager)::

        async with await FlowClient.create() as client:
            result = await client.generate_image("golden Buddha, celestial clouds")
            print(result.file_paths)

    Or for longer pipelines::

        client = await FlowClient.create()
        try:
            batch = await client.batch_generate("prompts.txt", mode=GenerationMode.IMAGE)
        finally:
            await client.close()
    """

    def __init__(self, browser: BrowserManager, config: FlowConfig):
        self._browser = browser
        self._config = config
        self._flow_ui = FlowUI()

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def create(
        cls,
        headless: Optional[bool] = None,
        config: Optional[FlowConfig] = None,
    ) -> "FlowClient":
        """Create and start a FlowClient (starts the browser)."""
        cfg = config or load_config()
        hless = headless if headless is not None else cfg.headless
        browser = BrowserManager(headless=hless)
        await browser.start()
        return cls(browser, cfg)

    async def close(self):
        await self._browser.stop()

    async def __aenter__(self) -> "FlowClient":
        return self

    async def __aexit__(self, *_):
        await self.close()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def login(self) -> None:
        """Open a visible browser window for interactive Google login.

        After the user completes sign-in the session is persisted to
        ``~/.flow-py/browser-profile/`` and future calls can run headless.
        """
        log.info("Opening browser for interactive login …")
        # Temporarily go non-headless
        await self._browser.stop()
        self._browser.headless = False
        await self._browser.start()

        page = await self._browser.navigate_to_flow()
        print("🌐 Browser opened. Please sign in to Google and navigate to Flow.")
        print("   When the Flow project page is visible, press ENTER here to continue.")
        try:
            await asyncio.get_running_loop().run_in_executor(None, input)
        except EOFError:
            pass

        # Auto-detect project URL: poll page.url for up to 30s
        project_id = None
        current_url = page.url
        if "/project/" not in current_url:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                current_url = page.url
                if "/project/" in current_url:
                    break
                await asyncio.sleep(1)

        m = re.search(r"/project/([^/?#]+)", current_url)
        if m:
            project_id = m.group(1)
            set_active_project(project_id, current_url)
            add_project(project_id, "Default", current_url)
            print(f"✅ Logged in. Active project: {project_id}")
        else:
            print("✅ Logged in (no project URL detected; run `flow projects use <id>` later).")

        # Restart headless
        await self._browser.stop()
        self._browser.headless = self._config.headless
        await self._browser.start()

    # ------------------------------------------------------------------
    # Project management
    # ------------------------------------------------------------------

    async def _ensure_project_page(self) -> str:
        """Return the project URL, navigating there if needed."""
        project_id, project_url = get_active_project()
        if not project_url:
            raise NoProjectError()
        page = await self._browser.ensure_authenticated()
        if project_url.rstrip("/") not in page.url.rstrip("/"):
            await self._browser.navigate_to_flow(project_url)
        return project_url

    async def list_projects(self) -> list[dict]:
        """Return list of known projects from local registry."""
        return [
            {"id": pid, **info}
            for pid, info in load_projects().items()
        ]

    async def create_project(self, name: str = "flow-py") -> str:
        """Create a new Flow project via the UI and return its ID."""
        page = await self._browser.ensure_authenticated()
        await self._browser.navigate_to_flow()
        await asyncio.sleep(2)

        # Click "New project" link/button
        new_btn = page.get_by_text("New project").first
        if await new_btn.count() > 0:
            await new_btn.click()
        else:
            # Fallback: try other button texts
            for btn_text in ("New Project", "Create project", "+", "New"):
                btn = page.get_by_role("button", name=btn_text)
                if await btn.count() > 0:
                    await btn.first.click()
                    break

        # Wait for URL to contain /project/
        deadline = time.monotonic() + 15
        current = page.url
        while time.monotonic() < deadline:
            current = page.url
            if "/project/" in current:
                break
            await asyncio.sleep(1)

        m = re.search(r"/project/([^/?#]+)", current)
        if not m:
            raise UIError("Could not detect new project URL after creation")

        project_id = m.group(1)
        set_active_project(project_id, current)
        add_project(project_id, name, current)
        log.info("Created project %s", project_id)
        return project_id

    async def use_project(self, project_id_or_url: str) -> None:
        """Switch the active project by ID or full URL."""
        if project_id_or_url.startswith("http"):
            url = project_id_or_url
            m = re.search(r"/project/([^/?#]+)", url)
            project_id = m.group(1) if m else project_id_or_url
        else:
            project_id = project_id_or_url
            url = f"{FLOW_BASE_URL}/project/{project_id}"

        set_active_project(project_id, url)
        add_project(project_id, "imported", url)
        log.info("Active project set to %s", project_id)

    # ------------------------------------------------------------------
    # Download helpers
    # ------------------------------------------------------------------

    async def _download_media_url(self, url: str, output_path: Path) -> Path:
        """Download a media file directly via aiohttp."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                resp.raise_for_status()
                async with aiofiles.open(output_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(65536):
                        await f.write(chunk)
        log.debug("Saved media to %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Core generation: single prompt
    # ------------------------------------------------------------------

    async def _generate_single(
        self,
        prompt: str,
        mode: GenerationMode,
        output_path: Path,
        aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE,
        count: int = 1,
        video_duration: str = "8s",
        frame_image_path: Optional[str] = None,
    ) -> GenerationResult:
        """Generate one prompt and download the result(s)."""
        t0 = time.monotonic()
        result = GenerationResult(prompt=prompt, mode=mode, status=GenerationStatus.GENERATING)

        page = await self._browser.page()

        # Intercept GCS media URLs
        intercepted: list[str] = []

        def on_response(resp):
            if "storage.googleapis.com" in resp.url and resp.status == 200:
                if resp.url not in intercepted:
                    intercepted.append(resp.url)

        page.on("response", on_response)

        try:
            # For frame-to-video: upload image first, then switch to Video mode
            if mode == GenerationMode.FRAME_TO_VIDEO and frame_image_path:
                await self._flow_ui.upload_image(page, frame_image_path)
                await asyncio.sleep(1)

            # Open settings and configure
            await self._flow_ui.open_settings_panel(page)
            await self._flow_ui.switch_mode(page, mode)
            await self._flow_ui.set_aspect_ratio(page, aspect_ratio)
            if count > 1:
                await self._flow_ui.set_count(page, count)

            # Snapshot gallery count before
            before_count = await self._flow_ui.count_gallery_items(page)

            # Fill and submit
            await self._flow_ui.fill_prompt(page, prompt)
            await asyncio.sleep(0.3)
            await self._flow_ui.click_submit(page)

            log.info("Submitted prompt: %s [%s]", prompt[:60], mode.value)

            # Wait for new gallery item
            timeout = self._config.generation_timeout_s
            deadline = time.monotonic() + timeout
            new_count = before_count
            while time.monotonic() < deadline:
                if await self._flow_ui.check_policy_error(page):
                    raise PolicyError(prompt)
                new_count = await self._flow_ui.count_gallery_items(page)
                if new_count > before_count:
                    break
                await asyncio.sleep(2)
            else:
                raise GenerationTimeout(timeout)

            result.status = GenerationStatus.COMPLETE
            result.elapsed_s = time.monotonic() - t0
            result.media_urls = list(intercepted)

            # Download
            output_path.parent.mkdir(parents=True, exist_ok=True)
            src = await self._flow_ui.get_newest_media_src(page)
            if src:
                ext = _ext_for_url(src, mode)
                dl_path = output_path.with_suffix(ext)
                try:
                    await self._download_media_url(src, dl_path)
                    result.file_paths.append(dl_path)
                    log.info("Downloaded to %s", dl_path)
                except Exception as e:
                    log.warning("Direct download failed: %s", e)
                    # Fallback: click download button
                    await self._flow_ui.click_download_on_newest(page)

        except PolicyError:
            result.status = GenerationStatus.POLICY_REJECTED
            result.error = "Content policy rejection"
        except GenerationTimeout as e:
            result.status = GenerationStatus.FAILED
            result.error = str(e)
        except Exception as e:
            result.status = GenerationStatus.FAILED
            result.error = str(e)
            log.error("Generation error: %s", e, exc_info=True)
        finally:
            page.remove_listener("response", on_response)
            result.elapsed_s = result.elapsed_s or (time.monotonic() - t0)

        return result

    # ------------------------------------------------------------------
    # Public generation APIs
    # ------------------------------------------------------------------

    async def generate_image(
        self,
        prompt: str,
        output_dir: str | Path = ".",
        filename: Optional[str] = None,
        aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE,
        count: int = 1,
    ) -> GenerationResult:
        """Generate an image from a text prompt.

        Args:
            prompt: Text description of the image to generate.
            output_dir: Directory to save downloaded images.
            filename: Override filename (without extension).
            aspect_ratio: Landscape, portrait, or square.
            count: Number of images to generate (Flow generates multiple).

        Returns:
            GenerationResult with file_paths populated on success.
        """
        await self._ensure_project_page()
        output_dir = Path(output_dir)
        fname = filename or _safe_filename(prompt)
        output_path = output_dir / fname

        return await self._generate_single(
            prompt=prompt,
            mode=GenerationMode.IMAGE,
            output_path=output_path,
            aspect_ratio=aspect_ratio,
            count=count,
        )

    async def generate_video(
        self,
        prompt: str,
        output_dir: str | Path = ".",
        filename: Optional[str] = None,
        aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE,
        duration: str = "8s",
    ) -> GenerationResult:
        """Generate a video from a text prompt (Veo).

        Args:
            prompt: Text description of the video.
            output_dir: Directory to save downloaded video.
            filename: Override filename (without extension).
            aspect_ratio: Landscape or portrait.
            duration: "5s" or "8s".

        Returns:
            GenerationResult with file_paths populated on success.
        """
        await self._ensure_project_page()
        output_dir = Path(output_dir)
        fname = filename or _safe_filename(prompt)
        output_path = output_dir / fname

        return await self._generate_single(
            prompt=prompt,
            mode=GenerationMode.VIDEO,
            output_path=output_path,
            aspect_ratio=aspect_ratio,
            video_duration=duration,
        )

    async def generate_frame_to_video(
        self,
        image_path: str | Path,
        prompt: str,
        output_dir: str | Path = ".",
        filename: Optional[str] = None,
        duration: str = "8s",
    ) -> GenerationResult:
        """Animate a static image with a motion prompt (Frame-to-Video / Veo).

        Args:
            image_path: Path to the source image (PNG/JPEG).
            prompt: Motion/camera description (e.g., "slow zoom with golden particles").
            output_dir: Directory to save downloaded video.
            filename: Override filename.
            duration: "5s" or "8s".

        Returns:
            GenerationResult with file_paths populated on success.
        """
        await self._ensure_project_page()
        image_path = str(Path(image_path).resolve())
        output_dir = Path(output_dir)
        fname = filename or _safe_filename(prompt)
        output_path = output_dir / fname

        return await self._generate_single(
            prompt=prompt,
            mode=GenerationMode.FRAME_TO_VIDEO,
            output_path=output_path,
            frame_image_path=image_path,
            video_duration=duration,
        )

    # ------------------------------------------------------------------
    # Batch generation
    # ------------------------------------------------------------------

    async def batch_generate(
        self,
        prompts: str | Path | list[str] | list[ParsedPrompt],
        mode: GenerationMode = GenerationMode.IMAGE,
        output_dir: str | Path = ".",
        aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE,
        delay_s: Optional[float] = None,
        on_result=None,
    ) -> BatchResult:
        """Process a batch of prompts sequentially.

        Args:
            prompts: Path to prompts file, list of prompt strings, or
                     list of ParsedPrompt objects.
            mode: IMAGE, VIDEO, or FRAME_TO_VIDEO.
            output_dir: Output directory for all generated files.
            aspect_ratio: Aspect ratio for all generations.
            delay_s: Pause between prompts (default from config).
            on_result: Optional callback(result, index, total) for progress.

        Returns:
            BatchResult summarising the run.
        """
        await self._ensure_project_page()

        # Normalise input
        parsed: list[ParsedPrompt]
        if isinstance(prompts, (str, Path)):
            parsed = parse_prompt_file(prompts)
        elif prompts and isinstance(prompts[0], str):
            from ._models import ParsedPrompt as _PP
            parsed = [_PP(text=p) for p in prompts]
        else:
            parsed = prompts  # type: ignore

        delay = delay_s if delay_s is not None else self._config.inter_prompt_delay_s
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        batch = BatchResult(mode=mode, total=len(parsed))

        for idx, pp in enumerate(parsed):
            log.info("[%d/%d] %s", idx + 1, len(parsed), pp.text[:70])

            # Determine mode per-prompt (pipeline mode overrides)
            effective_mode = mode
            if pp.video_prompt:
                # Phase 1: generate image, Phase 2: animate it
                img_result = await self._generate_single(
                    prompt=pp.text,
                    mode=GenerationMode.IMAGE,
                    output_path=output_dir / f"frame_{idx:04d}",
                    aspect_ratio=aspect_ratio,
                )
                batch.add(img_result)
                if on_result:
                    on_result(img_result, idx * 2, len(parsed) * 2)

                if img_result.succeeded and img_result.primary_file:
                    vid_result = await self._generate_single(
                        prompt=pp.video_prompt,
                        mode=GenerationMode.FRAME_TO_VIDEO,
                        output_path=output_dir / f"video_{idx:04d}",
                        frame_image_path=str(img_result.primary_file),
                    )
                    batch.add(vid_result)
                    if on_result:
                        on_result(vid_result, idx * 2 + 1, len(parsed) * 2)
                else:
                    # Skip video if image failed
                    skip = GenerationResult(
                        prompt=pp.video_prompt,
                        mode=GenerationMode.FRAME_TO_VIDEO,
                        status=GenerationStatus.SKIPPED,
                        error="Source image failed",
                    )
                    batch.add(skip)
            else:
                tag = pp.tag or f"{idx:04d}"
                result = await self._generate_single(
                    prompt=pp.text,
                    mode=effective_mode,
                    output_path=output_dir / tag,
                    aspect_ratio=aspect_ratio,
                )
                batch.add(result)
                if on_result:
                    on_result(result, idx, len(parsed))

            if idx < len(parsed) - 1:
                await asyncio.sleep(delay)

        batch.finished_at = time.time()
        return batch

    # ------------------------------------------------------------------
    # Streaming batch (async generator for progress UX)
    # ------------------------------------------------------------------

    async def stream_batch(
        self,
        prompts: str | Path | list[str] | list[ParsedPrompt],
        mode: GenerationMode = GenerationMode.IMAGE,
        output_dir: str | Path = ".",
        aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE,
        delay_s: Optional[float] = None,
    ) -> AsyncIterator[GenerationResult]:
        """Like batch_generate but yields each result as it completes."""
        await self._ensure_project_page()

        if isinstance(prompts, (str, Path)):
            parsed = parse_prompt_file(prompts)
        elif prompts and isinstance(prompts[0], str):
            from ._models import ParsedPrompt as _PP
            parsed = [_PP(text=p) for p in prompts]
        else:
            parsed = prompts  # type: ignore

        delay = delay_s if delay_s is not None else self._config.inter_prompt_delay_s
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        for idx, pp in enumerate(parsed):
            result = await self._generate_single(
                prompt=pp.text,
                mode=mode,
                output_path=output_dir / (pp.tag or f"{idx:04d}"),
                aspect_ratio=aspect_ratio,
            )
            yield result
            if idx < len(parsed) - 1:
                await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # Config management
    # ------------------------------------------------------------------

    def get_config(self) -> FlowConfig:
        return self._config

    def update_config(self, **kwargs) -> FlowConfig:
        for k, v in kwargs.items():
            if hasattr(self._config, k):
                setattr(self._config, k, v)
        save_config(self._config)
        return self._config


# ─────────────────────────────────────────────
#  Utilities
# ─────────────────────────────────────────────

def _safe_filename(text: str, max_len: int = 50) -> str:
    """Convert a prompt to a safe filename stem."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "_", slug).strip("_")
    return slug[:max_len] or "output"


def _ext_for_url(url: str, mode: GenerationMode) -> str:
    """Guess file extension from URL or generation mode."""
    path = urlparse(url).path.lower()
    for ext in (".mp4", ".webm", ".gif", ".png", ".jpg", ".jpeg"):
        if path.endswith(ext):
            return ext
    if mode in (GenerationMode.VIDEO, GenerationMode.FRAME_TO_VIDEO):
        return ".mp4"
    return ".png"
