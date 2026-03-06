"""Core FlowClient — high-level interface combining browser auth + direct REST API."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import AsyncIterator, Optional

from ._browser import BrowserManager, FLOW_BASE_URL
from ._api import (
    FlowAPI,
    GeneratedImage,
    VideoJob,
    VideoStatus,
    Credits,
    Workflow,
    IMAGE_MODEL_NARWHAL,
    IMAGE_AR_PORTRAIT,
    IMAGE_AR_LANDSCAPE,
    IMAGE_AR_SQUARE,
    VIDEO_MODEL_VEO31_FAST,
    VIDEO_MODEL_VEO31_I2V,
    VIDEO_AR_LANDSCAPE,
    VIDEO_AR_PORTRAIT,
)
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

# Aspect ratio mapping
_AR_MAP = {
    AspectRatio.LANDSCAPE: (IMAGE_AR_LANDSCAPE, VIDEO_AR_LANDSCAPE),
    AspectRatio.PORTRAIT:  (IMAGE_AR_PORTRAIT,  VIDEO_AR_PORTRAIT),
    AspectRatio.SQUARE:    (IMAGE_AR_SQUARE,     VIDEO_AR_LANDSCAPE),  # square only for images
}


class FlowClient:
    """Async client for Google Flow AI.

    Combines Playwright browser (for auth + recaptcha) with direct REST API calls.

    Quick start::

        async with await FlowClient.create() as client:
            # Text → Image
            images = await client.generate_image("Golden Buddha, 8K")
            print(images[0].file_paths)

            # Text → Video (Veo 3.1)
            job, status = await client.generate_video_and_wait("Sunrise over lotus lake")
            print(job.file_path)

            # Image → Video (upload first)
            job, status = await client.image_to_video("source.png", "slow zoom with golden light")
    """

    def __init__(self, browser: BrowserManager, config: FlowConfig, project_id: str = ""):
        self._browser    = browser
        self._config     = config
        self._project_id = project_id

        # Direct REST API client
        self._api = FlowAPI(
            browser_manager  = browser,
            project_id       = project_id,
            poll_interval_s  = 5.0,
            default_timeout_s = config.generation_timeout_s,
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    async def create(
        cls,
        headless:  Optional[bool]        = None,
        config:    Optional[FlowConfig]  = None,
        project_id: Optional[str]        = None,
    ) -> "FlowClient":
        """Create and start a FlowClient."""
        cfg    = config or load_config()
        hless  = headless if headless is not None else cfg.headless
        browser = BrowserManager(headless=hless)
        await browser.start()

        pid = project_id or get_active_project()[0] or ""
        client = cls(browser, cfg, pid)
        await client._api._ensure_project_page()
        return client

    async def close(self):
        await self._browser.stop()

    async def __aenter__(self) -> "FlowClient":
        return self

    async def __aexit__(self, *_):
        await self.close()

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def login(self) -> None:
        """Interactive Google login in a visible browser window."""
        log.info("Opening browser for interactive login …")
        await self._browser.stop()
        self._browser.headless = False
        await self._browser.start()

        page = await self._browser.navigate_to_flow()
        print("🌐 Browser opened. Please sign in to Google and navigate to Flow.")
        print("   When the Flow project page is visible, press ENTER to continue.")
        try:
            await asyncio.get_running_loop().run_in_executor(None, input)
        except EOFError:
            pass

        current_url = page.url
        m = re.search(r"/project/([^/?#]+)", current_url)
        if m:
            project_id = m.group(1)
            self._project_id = project_id
            self._api.project_id = project_id
            set_active_project(project_id, current_url)
            add_project(project_id, "Default", current_url)
            print(f"✅ Logged in. Active project: {project_id}")
        else:
            print("✅ Logged in (no project URL detected; use `flow projects use <id>` later).")

        await self._browser.stop()
        self._browser.headless = self._config.headless
        await self._browser.start()

    # ── Project management ────────────────────────────────────────────────────

    @property
    def project_id(self) -> str:
        return self._project_id

    @project_id.setter
    def project_id(self, pid: str):
        self._project_id       = pid
        self._api.project_id   = pid
        self._api._project_page_url = f"https://labs.google/fx/tools/flow/project/{pid}"

    async def _ensure_project(self):
        if not self._project_id:
            raise NoProjectError()
        await self._api._ensure_project_page()

    async def use_project(self, project_id_or_url: str) -> None:
        """Switch active project."""
        if project_id_or_url.startswith("http"):
            url = project_id_or_url
            m   = re.search(r"/project/([^/?#]+)", url)
            pid = m.group(1) if m else project_id_or_url
        else:
            pid = project_id_or_url
            url = f"{FLOW_BASE_URL}/project/{pid}"

        self.project_id = pid
        set_active_project(pid, url)
        add_project(pid, "imported", url)

    async def list_projects(self) -> list[dict]:
        return [{"id": pid, **info} for pid, info in load_projects().items()]

    # ── Credits ───────────────────────────────────────────────────────────────

    async def get_credits(self) -> Credits:
        await self._ensure_project()
        return await self._api.get_credits()

    # ── Workflows ─────────────────────────────────────────────────────────────

    async def list_workflows(self) -> list[Workflow]:
        await self._ensure_project()
        return await self._api.list_workflows()

    # ── Image generation ──────────────────────────────────────────────────────

    async def generate_image(
        self,
        prompt: str,
        output_dir: str | Path = ".",
        *,
        aspect_ratio: AspectRatio    = AspectRatio.PORTRAIT,
        model:        str            = IMAGE_MODEL_NARWHAL,
        count:        int            = 4,
        seed:         Optional[int]  = None,
        download:     bool           = True,
    ) -> list[GeneratedImage]:
        """
        Generate images from a text prompt.

        Args:
            prompt:       Text description.
            output_dir:   Where to save images (if download=True).
            aspect_ratio: PORTRAIT (9:16), LANDSCAPE (16:9), or SQUARE.
            model:        Image model (default: NARWHAL = Nano Banana 2).
            count:        Number of images to generate (1–4).
            seed:         Reproducibility seed.
            download:     Auto-download images to output_dir.

        Returns:
            List of GeneratedImage objects.
        """
        await self._ensure_project()
        img_ar, _ = _AR_MAP.get(aspect_ratio, (IMAGE_AR_PORTRAIT, VIDEO_AR_LANDSCAPE))
        images = await self._api.generate_image(
            prompt, model=model, aspect_ratio=img_ar, count=count, seed=seed,
        )
        if download and images:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            for img in images:
                if img.fife_url:
                    await self._api.download_image(img, output_dir)
        return images

    # ── Video generation ──────────────────────────────────────────────────────

    async def generate_video(
        self,
        prompt: str,
        *,
        model:        str           = VIDEO_MODEL_VEO31_FAST,
        aspect_ratio: AspectRatio   = AspectRatio.LANDSCAPE,
        seed:         Optional[int] = None,
    ) -> VideoJob:
        """Submit a text-to-video job (returns immediately, PENDING)."""
        await self._ensure_project()
        _, vid_ar = _AR_MAP.get(aspect_ratio, (IMAGE_AR_LANDSCAPE, VIDEO_AR_LANDSCAPE))
        return await self._api.generate_video(
            prompt, model=model, aspect_ratio=vid_ar, seed=seed,
        )

    async def generate_video_and_wait(
        self,
        prompt: str,
        output_dir: str | Path = ".",
        *,
        model:        str           = VIDEO_MODEL_VEO31_FAST,
        aspect_ratio: AspectRatio   = AspectRatio.LANDSCAPE,
        seed:         Optional[int] = None,
        timeout_s:    int           = 0,
        download:     bool          = True,
        on_poll=None,
    ) -> tuple[VideoJob, VideoStatus]:
        """
        Generate a video and wait for it to finish.

        Args:
            prompt:       Text prompt.
            output_dir:   Download directory.
            model:        Veo model key.
            aspect_ratio: Video aspect ratio.
            seed:         Reproducibility seed.
            timeout_s:    Max wait seconds (0 = default 300s).
            download:     Auto-download when complete.
            on_poll:      Progress callback(status, elapsed).

        Returns:
            (VideoJob, VideoStatus) — job.file_path set if download=True.
        """
        await self._ensure_project()
        _, vid_ar = _AR_MAP.get(aspect_ratio, (IMAGE_AR_LANDSCAPE, VIDEO_AR_LANDSCAPE))
        job, status = await self._api.generate_video_and_wait(
            prompt, model=model, aspect_ratio=vid_ar, seed=seed,
            timeout_s=timeout_s, on_poll=on_poll,
        )
        if download and status.fife_url:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            job.fife_url = status.fife_url
            await self._api.download_video(job, output_dir)
        return job, status

    async def image_to_video(
        self,
        image_path: str | Path,
        prompt: str,
        output_dir: str | Path = ".",
        *,
        model:       str           = VIDEO_MODEL_VEO31_I2V,
        aspect_ratio: AspectRatio  = AspectRatio.PORTRAIT,
        seed:         Optional[int] = None,
        timeout_s:    int           = 0,
        download:     bool          = True,
        on_poll=None,
    ) -> tuple[VideoJob, VideoStatus]:
        """
        Animate a local image (Frames mode).

        Uploads the image, generates a video from it, and downloads the result.
        """
        await self._ensure_project()
        _, vid_ar = _AR_MAP.get(aspect_ratio, (IMAGE_AR_PORTRAIT, VIDEO_AR_PORTRAIT))

        media_name = await self._api.upload_image(image_path)
        job = await self._api.generate_video_from_image(
            prompt, media_name, model=model, aspect_ratio=vid_ar, seed=seed,
        )
        status = await self._api.wait_for_video(job, timeout_s=timeout_s, on_poll=on_poll)

        if download and status.fife_url:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            job.fife_url = status.fife_url
            await self._api.download_video(job, output_dir)

        return job, status

    async def extend_video(
        self,
        media_name_or_job: str | VideoJob,
        prompt: str = "",
        output_dir: str | Path = ".",
        *,
        n: int   = 1,
        aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE,
        timeout_s: int  = 0,
        download:  bool = True,
    ) -> list[tuple[VideoJob, VideoStatus]]:
        """
        Extend a video N times (chain extensions for longer videos).

        Args:
            media_name_or_job: Media name (UUID) or VideoJob of the video to extend.
            prompt:            Continuation prompt (empty = auto-continue).
            output_dir:        Download directory for each segment.
            n:                 Number of extensions (default 1).
            aspect_ratio:      Should match the original video.
            timeout_s:         Per-extension timeout.
            download:          Auto-download each segment.

        Returns:
            List of (VideoJob, VideoStatus) for each extension.
        """
        await self._ensure_project()
        if isinstance(media_name_or_job, VideoJob):
            media_name = media_name_or_job.media_name
        else:
            media_name = media_name_or_job

        _, vid_ar = _AR_MAP.get(aspect_ratio, (IMAGE_AR_LANDSCAPE, VIDEO_AR_LANDSCAPE))

        results = await self._api.extend_video_loop(
            media_name, n, prompt=prompt,
            output_dir=output_dir, aspect_ratio=vid_ar, timeout_s=timeout_s,
        )

        if download:
            for job, status in results:
                if status.fife_url and not job.file_path:
                    job.fife_url = status.fife_url
                    output_dir = Path(output_dir)
                    await self._api.download_video(job, output_dir)

        return results

    # ── Batch operations ──────────────────────────────────────────────────────

    async def batch_images(
        self,
        prompts: list[str],
        output_dir: str | Path = ".",
        *,
        aspect_ratio: AspectRatio = AspectRatio.PORTRAIT,
        count:        int         = 1,
        delay_s:      float       = 1.0,
    ) -> list[list[GeneratedImage]]:
        """Generate images for multiple prompts."""
        await self._ensure_project()
        img_ar, _ = _AR_MAP.get(aspect_ratio, (IMAGE_AR_PORTRAIT, VIDEO_AR_LANDSCAPE))
        return await self._api.batch_generate_images(
            prompts, output_dir, aspect_ratio=img_ar, count=count, delay_s=delay_s,
        )

    async def batch_videos(
        self,
        prompts: list[str],
        output_dir: str | Path = ".",
        *,
        aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE,
        concurrency:  int         = 3,
        timeout_s:    int         = 0,
    ) -> list[tuple[VideoJob, VideoStatus]]:
        """Generate videos for multiple prompts concurrently."""
        await self._ensure_project()
        _, vid_ar = _AR_MAP.get(aspect_ratio, (IMAGE_AR_LANDSCAPE, VIDEO_AR_LANDSCAPE))
        return await self._api.batch_generate_videos(
            prompts, output_dir, aspect_ratio=vid_ar,
            concurrency=concurrency, timeout_s=timeout_s,
        )

    # ── Config ────────────────────────────────────────────────────────────────

    def get_config(self) -> FlowConfig:
        return self._config

    def update_config(self, **kwargs) -> FlowConfig:
        for k, v in kwargs.items():
            if hasattr(self._config, k):
                setattr(self._config, k, v)
        save_config(self._config)
        return self._config

    # ── Direct API access ─────────────────────────────────────────────────────

    @property
    def api(self) -> FlowAPI:
        """Direct access to the low-level FlowAPI client."""
        return self._api
