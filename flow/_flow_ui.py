"""High-level UI interaction helpers for Google Flow AI.

Reverse-engineered from live DOM inspection of labs.google/fx/tools/flow.

Key insight: Flow has NO mode tabs. Instead, clicking the model selector
pill ("🍌 Nano Banana 2  crop_16_9  x2") opens a settings panel containing:
  - imageImage / videocamVideo  (mode buttons)
  - crop_16_9Landscape / crop_9_16Portrait  (aspect ratio)
  - x1 / x2 / x3 / x4  (count)
  - 🍌 Nano Banana 2 ▾  (model dropdown)

Prompt input: textarea with placeholder "What do you want to create?"
Submit button: button with text containing "Create" + arrow_forward icon
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ._models import AspectRatio, GenerationMode

log = logging.getLogger(__name__)

# Text found on mode buttons after opening the settings panel
_MODE_BUTTON_TEXT = {
    GenerationMode.IMAGE: ["Image", "imageImage"],
    GenerationMode.VIDEO: ["Video", "videocamVideo"],
    GenerationMode.FRAME_TO_VIDEO: ["Video", "videocamVideo"],  # same mode, image uploaded separately
}

# Aspect ratio button texts in the settings panel
_ASPECT_BUTTON_TEXT = {
    AspectRatio.LANDSCAPE: ["Landscape", "crop_16_9Landscape"],
    AspectRatio.PORTRAIT:  ["Portrait",  "crop_9_16Portrait"],
    AspectRatio.SQUARE:    ["Square",    "crop_1_1Square"],
}

# Count button texts
_COUNT_BUTTON_TEXT = {"1": "x1", "2": "x2", "3": "x3", "4": "x4"}

# The settings panel trigger: the model selector pill
_SETTINGS_PILL_TEXTS = ["Nano Banana", "Veo", "Imagen", "🍌"]


class FlowUI:
    """Knows the exact selector patterns for labs.google/fx/tools/flow."""

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def navigate_to_project(self, page, project_url: str) -> None:
        """Navigate to a specific Flow project URL."""
        if project_url.rstrip("/") in page.url:
            log.debug("Already on project page")
            return
        await page.goto(project_url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(2)

    # ------------------------------------------------------------------
    # Settings panel
    # ------------------------------------------------------------------

    async def open_settings_panel(self, page) -> bool:
        """Click the model selector pill to reveal Image/Video/Aspect/Count controls.

        Returns True if the panel was opened (or was already open).
        """
        # Check if panel already open by looking for the Image/Video buttons
        already_open = await self._settings_visible(page)
        if already_open:
            return True

        # Find and click the settings pill
        for text in _SETTINGS_PILL_TEXTS:
            el = page.get_by_text(text, exact=False).first
            if await el.count() > 0:
                await el.click()
                await asyncio.sleep(0.8)
                if await self._settings_visible(page):
                    log.debug("Settings panel opened via '%s'", text)
                    return True

        # Fallback: look for the pill container button
        pill = page.locator("button").filter(has_text="x2").first
        if await pill.count() == 0:
            pill = page.locator("button").filter(has_text="x1").first
        if await pill.count() > 0:
            await pill.click()
            await asyncio.sleep(0.8)
            return await self._settings_visible(page)

        log.warning("Could not open settings panel")
        return False

    async def _settings_visible(self, page) -> bool:
        """Check if the settings panel is open (mode tabs are visible).

        IMPORTANT: must use [role=tab] not button[has_text=Image] because
        the gallery has 'Generated image' buttons that would false-positive.
        """
        count = await page.evaluate(
            "() => document.querySelectorAll('[role=tab]').length"
        )
        return count > 0

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    async def switch_mode(self, page, mode: GenerationMode) -> bool:
        """Select Image or Video mode via the settings panel.

        Mode options are TABS (role=tab) inside the settings panel.
        Returns True if successfully switched.
        """
        await self.open_settings_panel(page)

        # Tab labels as seen in DOM: "image Image", "videocam Video", "crop_free Frames"
        label_map = {
            GenerationMode.IMAGE:          ["Image", "image Image"],
            GenerationMode.VIDEO:          ["Video", "videocam Video"],
            GenerationMode.FRAME_TO_VIDEO: ["Frames", "crop_free Frames", "Video"],
        }
        for label in label_map.get(mode, []):
            tab = page.get_by_role("tab", name=label, exact=True).first
            if await tab.count() > 0:
                await tab.click()
                await asyncio.sleep(0.4)
                log.debug("Switched mode to %s via tab '%s'", mode.value, label)
                return True
            # Partial match
            tab = page.locator("[role='tab']").filter(has_text=label.split()[-1]).first
            if await tab.count() > 0:
                await tab.click()
                await asyncio.sleep(0.4)
                return True

        log.warning("Could not find mode tab for %s", mode.value)
        return False

    # ------------------------------------------------------------------
    # Aspect ratio
    # ------------------------------------------------------------------

    async def set_aspect_ratio(self, page, ratio: AspectRatio) -> bool:
        """Select aspect ratio via the settings panel.

        Aspect ratio options are TABS (role=tab), not buttons.
        Must open the settings panel first.
        """
        await self.open_settings_panel(page)

        label_map = {
            AspectRatio.LANDSCAPE: ["Landscape", "crop_16_9 Landscape"],
            AspectRatio.PORTRAIT:  ["Portrait",  "crop_9_16 Portrait"],
            AspectRatio.SQUARE:    ["Square",    "crop_1_1 Square"],
        }
        for label in label_map.get(ratio, []):
            # Try tab role first (Flow uses tabs for aspect ratio)
            tab = page.get_by_role("tab", name=label, exact=True).first
            if await tab.count() > 0:
                await tab.click()
                await asyncio.sleep(0.3)
                log.debug("Set aspect ratio to %s via tab '%s'", ratio.value, label)
                return True
            # Try contains-text tab
            tab = page.locator("[role='tab']").filter(has_text=label.split()[-1]).first
            if await tab.count() > 0:
                await tab.click()
                await asyncio.sleep(0.3)
                return True

        # Already set? Check the pill text
        pill_text = await page.locator("button").filter(has_text="Nano Banana").first.text_content()
        ratio_marker = {"9:16": "crop_9_16", "16:9": "crop_16_9", "1:1": "crop_1_1"}.get(ratio.value, "")
        if ratio_marker and ratio_marker in (pill_text or ""):
            log.debug("Aspect ratio %s already set (pill shows %s)", ratio.value, ratio_marker)
            return True

        log.warning("Could not find aspect ratio tab for %s", ratio.value)
        return False

    # ------------------------------------------------------------------
    # Count
    # ------------------------------------------------------------------

    async def set_count(self, page, count: int) -> bool:
        """Set generation count (1-4) via the settings panel.

        Count options are TABS: tab "x1", tab "x2", tab "x3", tab "x4".
        """
        await self.open_settings_panel(page)
        count = max(1, min(4, count))
        label = f"x{count}"

        tab = page.get_by_role("tab", name=label, exact=True).first
        if await tab.count() > 0:
            await tab.click()
            await asyncio.sleep(0.3)
            log.debug("Set count to %d", count)
            return True

        log.warning("Could not set count to %d", count)
        return False

    # ------------------------------------------------------------------
    # Prompt input
    # ------------------------------------------------------------------

    async def fill_prompt(self, page, prompt: str) -> bool:
        """Fill the prompt input ("What do you want to create?").

        Key findings from DOM inspection:
        - The prompt input is a contenteditable DIV (NOT a textarea)
        - The only textarea is a hidden reCAPTCHA element — skip it
        - Must use page.keyboard.type() to trigger React synthetic events
        - execCommand('insertText') doesn't update React state
        - The search bar (input[type=text]) can steal focus — must close it first
        """
        # Close settings panel and any search overlay
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.2)
        except Exception:
            pass

        # Find the visible contenteditable div at the bottom (the prompt input)
        # There is only ONE visible contenteditable div on the project page
        els = page.locator("div[contenteditable]")
        count = await els.count()

        for i in range(count):
            el = els.nth(i)
            visible = await el.evaluate(
                "el => el.offsetWidth > 0 && el.offsetHeight > 0 && el.getBoundingClientRect().y > 100"
            )
            if not visible:
                continue

            # Scroll into view and click to focus
            await el.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)
            await el.click()
            await asyncio.sleep(0.3)

            # Verify focus landed on this contenteditable (not the search bar)
            focused_tag = await page.evaluate(
                "() => document.activeElement.tagName + '|' + document.activeElement.contentEditable"
            )
            if "true" not in focused_tag.lower():
                log.warning("Focus went to %s instead of contenteditable", focused_tag)
                continue

            # Select all and clear, then type via keyboard (triggers React events)
            await page.keyboard.press("Meta+a")
            await page.keyboard.press("Control+a")
            await asyncio.sleep(0.1)
            await page.keyboard.type(prompt, delay=15)
            await asyncio.sleep(0.2)

            # Verify content was inserted
            content = await el.text_content()
            if prompt[:10] in (content or ""):
                log.debug("Filled prompt (%d chars)", len(prompt))
                return True
            log.warning("Prompt content not found after typing, content=%r", (content or "")[:40])

        log.warning("Could not fill prompt input")
        return False

    async def wait_for_generation_complete(
        self,
        page,
        before_count: int,
        timeout_s: int = 300,
        poll_interval: float = 2.0,
    ) -> bool:
        """Wait for generation to complete (media src populated in gallery).

        Two-phase wait:
        1. Wait for gallery item count to increase (generation started → loading card appears)
        2. Wait for a GCS media URL to be available (generation complete)
        """
        import time as _time
        deadline = _time.monotonic() + timeout_s

        # Phase 1: wait for item to appear
        while _time.monotonic() < deadline:
            if await self.check_policy_error(page):
                return False
            count = await self.count_gallery_items(page)
            if count > before_count:
                log.debug("Gallery item appeared (%d → %d)", before_count, count)
                break
            await asyncio.sleep(poll_interval)
        else:
            log.warning("Timed out waiting for gallery item to appear")
            return False

        # Phase 2: wait for GCS src to be populated (item finishes generating)
        while _time.monotonic() < deadline:
            src = await self.get_newest_media_src(page)
            if src:
                log.debug("Media src available: %s", src[:60])
                return True
            await asyncio.sleep(poll_interval)

        log.warning("Timed out waiting for media src")
        return False

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    async def click_submit(self, page) -> bool:
        """Click the generate/submit button.

        In Flow's UI there are two "Create" buttons:
          1. "add_2 Create" — adds a new media block (NOT the submit)
          2. "arrow_forward Create" — the actual generate/submit button
        We target the LAST "Create" button, which is the submit one.
        """
        # JS: find last enabled Create button (the arrow_forward one)
        clicked = await page.evaluate("""
            () => {
                const btns = [...document.querySelectorAll('button')];
                const creates = btns.filter(b => 
                    b.textContent.trim().includes('Create') && !b.disabled
                );
                if (creates.length > 0) {
                    creates[creates.length - 1].click();
                    return true;
                }
                return false;
            }
        """)
        if clicked:
            log.debug("Clicked submit (last Create button) via JS")
            return True

        # Fallback: button containing "arrow_forward" text (Material icon name)
        btn = page.locator("button").filter(has_text="arrow_forward").last
        if await btn.count() > 0:
            await btn.click()
            log.debug("Clicked submit via arrow_forward button")
            return True

        log.warning("Could not find submit button")
        return False

    # ------------------------------------------------------------------
    # Image upload (for Frame-to-Video)
    # ------------------------------------------------------------------

    async def upload_image(self, page, image_path: str) -> bool:
        """Upload a reference image via the Add Media button."""
        # Click "Add Media" button (add icon)
        add_btn = page.locator("button").filter(has_text="Add Media").first
        if await add_btn.count() == 0:
            add_btn = page.get_by_text("Add Media").first
        if await add_btn.count() > 0:
            await add_btn.click()
            await asyncio.sleep(1)

        # Look for file input
        file_input = page.locator("input[type='file']").first
        if await file_input.count() > 0:
            await file_input.set_input_files(image_path)
            await asyncio.sleep(2)
            log.debug("Uploaded image %s", image_path)
            return True

        # Try file chooser dialog
        try:
            async with page.expect_file_chooser(timeout=3000) as fc_info:
                # Click a likely upload zone
                for sel in ["[aria-label*='upload' i]", ".upload-zone", "[class*='upload']"]:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.click()
                        break
            fc = await fc_info.value
            await fc.set_files(image_path)
            await asyncio.sleep(2)
            return True
        except Exception as e:
            log.warning("File chooser upload failed: %s", e)

        return False

    # ------------------------------------------------------------------
    # Gallery & media extraction
    # ------------------------------------------------------------------

    async def count_gallery_items(self, page) -> int:
        """Count completed items in the generation gallery.

        Flow serves images via /api/trpc/media.getMediaUrlRedirect (NOT GCS directly).
        Count img elements with this URL pattern — these are completed generations.
        """
        count = await page.evaluate("""
            () => document.querySelectorAll(
                'img[src*="getMediaUrlRedirect"], video[src*="getMediaUrlRedirect"]'
            ).length
        """)
        return count or 0

    async def check_policy_error(self, page) -> bool:
        """Return True if a content policy error is shown."""
        policy_strings = [
            "violates our policy",
            "content policy",
            "harmful or unsafe",
            "unable to generate",
            "request was flagged",
            "couldn't generate",
        ]
        body = await page.evaluate("() => document.body.innerText")
        body_lower = body.lower()
        return any(s in body_lower for s in policy_strings)

    async def get_newest_media_src(self, page) -> Optional[str]:
        """Extract src URL from the newest generated image or video.

        Flow serves media via /api/trpc/media.getMediaUrlRedirect?name=<uuid>
        This URL requires session cookies to download (use context.request, not aiohttp).
        """
        src = await page.evaluate("""
            () => {
                const imgs = [...document.querySelectorAll('img[src*="getMediaUrlRedirect"]')];
                const vids = [...document.querySelectorAll('video[src*="getMediaUrlRedirect"]')];
                const all = [...imgs, ...vids];
                if (!all.length) return null;
                return all[all.length - 1].src || all[all.length - 1].currentSrc;
            }
        """)
        return src or None

    async def get_all_media_srcs(self, page) -> list[str]:
        """Get all generated media URLs on the current project page."""
        srcs = await page.evaluate("""
            () => {
                const imgs = [...document.querySelectorAll('img[src*="getMediaUrlRedirect"]')];
                const vids = [...document.querySelectorAll('video[src*="getMediaUrlRedirect"]')];
                return [...imgs, ...vids].map(el => el.src || el.currentSrc).filter(Boolean);
            }
        """)
        return srcs or []

    async def click_download_on_newest(self, page) -> bool:
        """Hover over newest item and click its download button."""
        try:
            # Find last generated media element
            items = page.locator("img[src*='storage.googleapis.com'], video[src*='storage.googleapis.com']")
            count = await items.count()
            if count == 0:
                return False
            last = items.nth(count - 1)
            await last.hover()
            await asyncio.sleep(0.5)
            # Look for download button that appears on hover
            dl_btn = page.locator(
                "button[aria-label*='download' i], "
                "button[aria-label*='Download' i], "
                "[title*='download' i]"
            ).last
            if await dl_btn.count() > 0:
                await dl_btn.click()
                log.debug("Clicked download button on newest item")
                return True
        except Exception as e:
            log.debug("click_download_on_newest error: %s", e)
        return False

    async def get_project_url_from_page(self, page) -> Optional[str]:
        """Extract the current project URL if on a project page."""
        url = page.url
        if "/project/" in url:
            return url
        return None
