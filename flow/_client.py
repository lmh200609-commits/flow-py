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

# ─────────────────────────────────────────────
#  UI Selectors (resilient multi-strategy sets)
# ─────────────────────────────────────────────

# Mode tab labels as Flow shows them
_MODE_LABELS = {
    GenerationMode.IMAGE: ["Create Image", "Image", "Imagen"],
    GenerationMode.VIDEO: ["Text-to-Video", "Video", "Generate Video"],
    GenerationMode.FRAME_TO_VIDEO: ["Frame-to-Video", "Image-to-Video", "Frame to Video"],
}

# Gallery item selectors
_GALLERY_SELECTORS = [
    "[data-index]",
    ".gallery-item",
    ".result-item",
    "[class*='gallery'] img",
    "[class*='result'] img",
    "img[src*='storage.googleapis.com']",
    "video[src*='storage.googleapis.com']",
]

# Download button selectors
_DOWNLOAD_SELECTORS = [
    "button[aria-label*='download' i]",
    "button[aria-label*='Download' i]",
    "[title*='download' i]",
    "button:has(svg[data-icon*='download'])",
    "a[download]",
]

# Policy / error indicators
_POLICY_TEXTS = [
    "violates our policy",
    "content policy",
    "harmful or unsafe",
    "unable to generate",
    "request was flagged",
]


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
            input()
        except EOFError:
            pass

        # Capture project URL
        current_url = page.url
        if "flow/project/" in current_url:
            project_id = current_url.rstrip("/").split("/")[-1]
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

        # Look for a "New project" or "+" button
        for btn_text in ("New project", "New Project", "Create project", "+", "New"):
            btn = page.get_by_role("button", name=btn_text)
            if await btn.count() > 0:
                await btn.first.click()
                await asyncio.sleep(2)
                break

        # After creation, URL should contain /project/
        current = page.url
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
    # Mode switching
    # ------------------------------------------------------------------

    async def _switch_mode(self, page, mode: GenerationMode) -> None:
        """Click the appropriate mode tab in the Flow UI."""
        labels = _MODE_LABELS[mode]
        for label in labels:
            # Try role=tab first
            el = page.get_by_role("tab", name=label)
            if await el.count() > 0:
                await el.first.click()
                await asyncio.sleep(0.5)
                log.debug("Switched to mode %s via tab '%s'", mode, label)
                return
            # Try role=button
            el = page.get_by_role("button", name=label)
            if await el.count() > 0:
                await el.first.click()
                await asyncio.sleep(0.5)
                log.debug("Switched to mode %s via button '%s'", mode, label)
                return
        log.warning("Could not find mode tab for %s — proceeding anyway", mode)

    # ------------------------------------------------------------------
    # Gallery snapshot helpers
    # ------------------------------------------------------------------

    async def _count_gallery_items(self, page) -> int:
        """Count current gallery items using multiple selector strategies."""
        for sel in _GALLERY_SELECTORS:
            count = await page.locator(sel).count()
            if count > 0:
                return count
        return 0

    async def _wait_for_new_item(
        self,
        page,
        before_count: int,
        timeout_s: int,
        poll_interval: float = 1.5,
    ) -> int:
        """Wait until gallery item count exceeds before_count. Returns new count."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            # Check for policy error
            body_text = await page.evaluate("() => document.body.innerText")
            for policy_str in _POLICY_TEXTS:
                if policy_str.lower() in body_text.lower():
                    raise PolicyError("(prompt)")

            count = await self._count_gallery_items(page)
            if count > before_count:
                log.debug("Gallery grew from %d to %d", before_count, count)
                return count

            await asyncio.sleep(poll_interval)

        raise GenerationTimeout(timeout_s)

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

    async def _download_latest_item(
        self,
        page,
        output_path: Path,
        mode: GenerationMode,
    ) -> Optional[Path]:
        """Try to download the most recently generated item."""
        # Strategy 1: Intercept src URL from the newest gallery element
        media_src = await page.evaluate(f"""
            () => {{
                // Find media elements sorted by their position (last = newest)
                const imgs = [...document.querySelectorAll('img[src*="storage.googleapis.com"]')];
                const vids = [...document.querySelectorAll('video[src*="storage.googleapis.com"]')];
                const els  = [...imgs, ...vids];
                if (!els.length) return null;
                return els[els.length - 1].src || els[els.length - 1].currentSrc;
            }}
        """)

        if media_src:
            # Determine extension from URL or mode
            ext = _ext_for_url(media_src, mode)
            final_path = output_path.with_suffix(ext)
            try:
                return await self._download_media_url(media_src, final_path)
            except Exception as e:
                log.warning("Direct URL download failed: %s", e)

        # Strategy 2: Click download button on last gallery item
        try:
            last_item = page.locator("[data-index]").last
            # Hover to reveal download button
            await last_item.hover()
            await asyncio.sleep(0.5)
            download_btn = last_item.locator("button[aria-label*='download' i]").first
            if await download_btn.count() > 0:
                ext = ".mp4" if mode in (GenerationMode.VIDEO, GenerationMode.FRAME_TO_VIDEO) else ".png"
                final_path = output_path.with_suffix(ext)
                return await self._browser.click_and_download(
                    page, "button[aria-label*='download' i]", final_path
                )
        except Exception as e:
            log.warning("Download button strategy failed: %s", e)

        return None

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

        # Switch mode
        await self._switch_mode(page, mode)
        await asyncio.sleep(0.8)

        # For frame-to-video: upload the source image first
        if mode == GenerationMode.FRAME_TO_VIDEO and frame_image_path:
            await self._upload_frame_image(page, frame_image_path)
            await asyncio.sleep(1)

        # Fill prompt
        await self._browser.fill_textarea(page, prompt)
        await asyncio.sleep(0.3)

        # Snapshot gallery before
        before_count = await self._count_gallery_items(page)

        # Intercept media URLs while generating
        intercepted_urls: list[str] = []

        def on_response(resp):
            url = resp.url
            if (
                "storage.googleapis.com" in url
                and resp.status == 200
                and url not in intercepted_urls
            ):
                intercepted_urls.append(url)

        page.on("response", on_response)

        try:
            # Click generate
            await self._browser.click_generate(page)
            log.info("Generation started: %s… [%s]", prompt[:60], mode.value)

            # Wait for new gallery item
            await self._wait_for_new_item(
                page,
                before_count,
                self._config.generation_timeout_s,
            )

            result.status = GenerationStatus.COMPLETE
            result.elapsed_s = time.monotonic() - t0

            # Collect intercepted URLs
            result.media_urls = list(intercepted_urls)

            # Download
            output_path.parent.mkdir(parents=True, exist_ok=True)
            dl = await self._download_latest_item(page, output_path, mode)
            if dl:
                result.file_paths.append(dl)

        except PolicyError as e:
            result.status = GenerationStatus.POLICY_REJECTED
            result.error = str(e)
            log.warning("Policy rejection for prompt: %s", prompt[:60])
        except GenerationTimeout as e:
            result.status = GenerationStatus.FAILED
            result.error = str(e)
            log.error("Timeout for prompt: %s", prompt[:60])
        except Exception as e:
            result.status = GenerationStatus.FAILED
            result.error = str(e)
            log.error("Generation error: %s", e, exc_info=True)
        finally:
            page.remove_listener("response", on_response)

        result.elapsed_s = result.elapsed_s or (time.monotonic() - t0)
        return result

    async def _upload_frame_image(self, page, image_path: str) -> None:
        """Upload a local image for frame-to-video generation."""
        # Look for file input
        file_input = page.locator("input[type='file']").first
        if await file_input.count() > 0:
            await file_input.set_input_files(image_path)
            await asyncio.sleep(1)
            return

        # Try drag-and-drop zone
        upload_zone_selectors = [
            "[aria-label*='upload' i]",
            "[class*='upload']",
            "[class*='drop']",
        ]
        for sel in upload_zone_selectors:
            zone = page.locator(sel).first
            if await zone.count() > 0:
                await zone.click()
                await asyncio.sleep(0.5)
                # After click, a file chooser should appear
                async with page.expect_file_chooser() as fc_info:
                    await zone.click()
                fc = await fc_info.value
                await fc.set_files(image_path)
                await asyncio.sleep(1)
                return

        log.warning("Could not find upload element for frame image")

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
