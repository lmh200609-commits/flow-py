"""Playwright browser lifecycle manager for Google Flow AI."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Download,
    Page,
    Playwright,
    Response,
)

from ._storage import PROFILE_DIR, ensure_dirs
from ._exceptions import AuthError, UIError

log = logging.getLogger(__name__)

FLOW_BASE_URL   = "https://labs.google/fx/tools/flow"
FLOW_PROJECT_RE = r"https://labs\.google/fx/tools/flow/project/[^/?#]+"

# Chrome user-agent to avoid bot detection
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


class BrowserManager:
    """Manages a Playwright persistent browser context.

    Uses ``launch_persistent_context`` so Google session cookies survive
    across CLI invocations (no re-login needed after initial ``flow login``).

    Can also be created from an existing CDP endpoint (e.g., OpenClaw's
    headless Chrome) via ``BrowserManager.from_cdp()``.
    """

    def __init__(
        self,
        headless: bool = True,
        profile_dir: Optional[Path] = None,
        slow_mo: int = 0,
        *,
        cdp_url: Optional[str] = None,   # e.g. "http://127.0.0.1:9222"
    ):
        self.headless = headless
        self.profile_dir = profile_dir or PROFILE_DIR
        self.slow_mo = slow_mo
        self.cdp_url = cdp_url           # if set, connect to existing Chrome via CDP
        self._pw: Optional[Playwright] = None
        self._ctx: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._cdp_browser = None         # CDP-connected browser handle
        # Collected download paths during this session
        self._downloads: list[Path] = []

    @classmethod
    def from_cdp(cls, cdp_url: str = "http://127.0.0.1:9222") -> "BrowserManager":
        """Create a BrowserManager that connects to an existing Chrome instance via CDP.

        This is useful when running inside OpenClaw where a Chrome session with
        Google login cookies is already open (port 9222 by default).

        Example::

            bm = BrowserManager.from_cdp("http://127.0.0.1:9222")
            await bm.start()
            api = FlowAPI(bm, project_id)
            credits = await api.get_credits()
        """
        return cls(cdp_url=cdp_url)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> "BrowserManager":
        ensure_dirs()
        self._pw = await async_playwright().start()

        if self.cdp_url:
            # Connect to an already-running Chrome with existing session cookies
            log.info("Connecting to existing Chrome via CDP: %s", self.cdp_url)
            self._cdp_browser = await self._pw.chromium.connect_over_cdp(self.cdp_url)
            contexts = self._cdp_browser.contexts
            if not contexts:
                raise AuthError(
                    f"No browser contexts found at {self.cdp_url}. "
                    "Make sure Chrome is running with --remote-debugging-port=9222."
                )
            self._ctx = contexts[0]
            log.info("CDP connected: %d existing pages", len(self._ctx.pages))
        else:
            # Normal persistent profile launch
            self._ctx = await self._pw.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=self.headless,
                slow_mo=self.slow_mo,
                viewport={"width": 1440, "height": 900},
                user_agent=_USER_AGENT,
                accept_downloads=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                ],
            )
            await self._ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
        return self

    async def stop(self):
        if self.cdp_url:
            # For CDP connections: just disconnect, don't close the remote browser
            if self._cdp_browser:
                await self._cdp_browser.close()  # closes connection, not the browser
        else:
            if self._ctx:
                await self._ctx.close()
        if self._pw:
            await self._pw.stop()
        self._cdp_browser = None
        self._ctx = None
        self._pw = None
        self._page = None

    async def __aenter__(self) -> "BrowserManager":
        return await self.start()

    async def __aexit__(self, *_):
        await self.stop()

    # ------------------------------------------------------------------
    # Page access
    # ------------------------------------------------------------------

    @property
    def context(self) -> BrowserContext:
        if not self._ctx:
            raise RuntimeError("BrowserManager not started. Use async with / await start()")
        return self._ctx

    async def page(self) -> Page:
        """Return the active page.

        In CDP mode: prefers a page already on labs.google/fx (which has
        reCAPTCHA loaded and Google session cookies active).
        In normal mode: creates a new page if none exists.
        """
        if self._page is not None and not self._page.is_closed():
            return self._page

        pages = self._ctx.pages
        if self.cdp_url and pages:
            # In CDP mode, prefer an existing Flow page (reCAPTCHA already loaded)
            for p in pages:
                if "labs.google" in p.url:
                    self._page = p
                    log.debug("CDP page: using existing Flow tab %s", p.url[:60])
                    return self._page
            # Fall back to first non-blank page
            for p in pages:
                if p.url not in ("", "about:blank", "chrome://newtab/"):
                    self._page = p
                    return self._page

        if pages:
            self._page = pages[0]
        else:
            self._page = await self._ctx.new_page()
        return self._page

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    async def navigate_to_flow(self, project_url: Optional[str] = None) -> Page:
        """Navigate to Flow, optionally to a specific project URL."""
        page = await self.page()
        target = project_url or FLOW_BASE_URL

        current = page.url
        if current.startswith(target.rstrip("/")):
            log.debug("Already on %s, skipping navigation", target)
            return page

        log.debug("Navigating to %s", target)
        await page.goto(target, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(1.5)  # let JS settle
        return page

    async def ensure_authenticated(self) -> Page:
        """Navigate to Flow and raise AuthError if a login wall is detected."""
        page = await self.navigate_to_flow()
        # Google login wall: URL contains accounts.google.com
        if "accounts.google.com" in page.url:
            raise AuthError(
                "Not logged in. Run `flow login` to authenticate interactively."
            )
        return page

    # ------------------------------------------------------------------
    # Download handling
    # ------------------------------------------------------------------

    async def click_and_download(
        self,
        page: Page,
        trigger_selector: str,
        output_path: Path,
        timeout_ms: int = 30_000,
    ) -> Path:
        """Click an element and capture the resulting browser download."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        async with page.expect_download(timeout=timeout_ms) as dl_info:
            await page.click(trigger_selector)
        download: Download = await dl_info.value
        await download.save_as(str(output_path))
        log.debug("Downloaded to %s", output_path)
        self._downloads.append(output_path)
        return output_path

    # ------------------------------------------------------------------
    # URL interception helpers
    # ------------------------------------------------------------------

    async def intercept_media_url(
        self,
        page: Page,
        trigger_fn,
        media_extensions: tuple[str, ...] = (".mp4", ".webm", ".png", ".jpg", ".jpeg", ".gif"),
        timeout_s: float = 60.0,
    ) -> str | None:
        """Execute trigger_fn, then capture the first media response URL."""
        captured: list[str] = []

        def on_response(response: Response):
            url = response.url
            if any(url.lower().endswith(ext) for ext in media_extensions):
                if response.status == 200:
                    captured.append(url)
            # Also catch GCS signed URLs which have ?X-Goog-Signature=
            if "storage.googleapis.com" in url and response.status == 200:
                captured.append(url)

        page.on("response", on_response)
        try:
            await trigger_fn()
            deadline = asyncio.get_running_loop().time() + timeout_s
            while not captured and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.3)
        finally:
            page.remove_listener("response", on_response)

        return captured[0] if captured else None

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    async def wait_for_selector_any(
        self,
        page: Page,
        selectors: list[str],
        timeout_ms: int = 15_000,
        state: str = "visible",
    ):
        """Try each selector in order, return the first that resolves."""
        tasks = [
            asyncio.create_task(
                page.wait_for_selector(sel, timeout=timeout_ms, state=state)
            )
            for sel in selectors
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        # Suppress cancellation errors
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        if not done:
            raise UIError(
                f"None of the selectors became visible within {timeout_ms}ms",
                str(selectors),
            )
        result_task = next(iter(done))
        return result_task.result()

    async def fill_textarea(self, page: Page, text: str) -> None:
        """Find Flow's prompt textarea and fill it (clears first)."""
        # Try multiple selector strategies
        selectors = [
            "textarea[placeholder]",
            "textarea",
            "[contenteditable='true']",
            "div[role='textbox']",
        ]
        el = await self.wait_for_selector_any(page, selectors)
        await el.click()
        # Select all and replace
        await el.press("Control+a")
        await el.press("Meta+a")
        await el.fill(text)
        log.debug("Filled textarea with %d chars", len(text))

    async def click_generate(self, page: Page) -> None:
        """Click the generate/create button."""
        # Try various button texts used by Flow
        for text in ("Create", "Generate", "Run", "Submit"):
            btn = page.get_by_role("button", name=text, exact=True)
            if await btn.count() > 0:
                await btn.click()
                log.debug("Clicked '%s' button", text)
                return
        # Fallback: find any enabled primary button near the textarea
        await page.evaluate("""
            () => {
                const btns = [...document.querySelectorAll('button')];
                const btn = btns.find(b => !b.disabled && 
                    (b.textContent.includes('Create') || 
                     b.textContent.includes('Generate') ||
                     b.getAttribute('aria-label')?.includes('generate')));
                if (btn) btn.click();
            }
        """)
        log.debug("Clicked generate via JS fallback")
