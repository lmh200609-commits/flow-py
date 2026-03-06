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
        """Check if Image/Video selector buttons are visible."""
        img_btn = page.get_by_role("button", name="Image", exact=True)
        vid_btn = page.get_by_role("button", name="Video", exact=True)
        img_vis = await img_btn.count() > 0
        vid_vis = await vid_btn.count() > 0
        if not img_vis:
            # Try with icon prefix in text
            img_vis = await page.locator("button").filter(has_text="Image").count() > 0
        return img_vis or vid_vis

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    async def switch_mode(self, page, mode: GenerationMode) -> bool:
        """Select Image or Video mode via the settings panel.

        Returns True if successfully switched.
        """
        await self.open_settings_panel(page)

        target_texts = _MODE_BUTTON_TEXT[mode]
        for text in target_texts:
            # Try exact role button
            btn = page.get_by_role("button", name=text, exact=True).first
            if await btn.count() > 0:
                await btn.click()
                await asyncio.sleep(0.4)
                log.debug("Switched mode to %s via button '%s'", mode.value, text)
                return True
            # Try contains text
            btn = page.locator("button").filter(has_text=text).first
            if await btn.count() > 0:
                await btn.click()
                await asyncio.sleep(0.4)
                log.debug("Switched mode to %s via contains '%s'", mode.value, text)
                return True

        log.warning("Could not find mode button for %s", mode.value)
        return False

    # ------------------------------------------------------------------
    # Aspect ratio
    # ------------------------------------------------------------------

    async def set_aspect_ratio(self, page, ratio: AspectRatio) -> bool:
        """Select aspect ratio via the settings panel."""
        await self.open_settings_panel(page)

        target_texts = _ASPECT_BUTTON_TEXT[ratio]
        for text in target_texts:
            btn = page.get_by_role("button", name=text, exact=True).first
            if await btn.count() > 0:
                await btn.click()
                await asyncio.sleep(0.3)
                log.debug("Set aspect ratio to %s", ratio.value)
                return True
            btn = page.locator("button").filter(has_text=text.split()[-1]).first
            if await btn.count() > 0:
                await btn.click()
                await asyncio.sleep(0.3)
                return True

        log.warning("Could not find aspect ratio button for %s", ratio.value)
        return False

    # ------------------------------------------------------------------
    # Count
    # ------------------------------------------------------------------

    async def set_count(self, page, count: int) -> bool:
        """Set generation count (1-4) via the settings panel."""
        await self.open_settings_panel(page)
        count = max(1, min(4, count))
        text = _COUNT_BUTTON_TEXT[str(count)]

        btn = page.locator("button").filter(has_text=text).first
        if await btn.count() > 0:
            await btn.click()
            await asyncio.sleep(0.3)
            log.debug("Set count to %d", count)
            return True
        log.warning("Could not set count to %d", count)
        return False

    # ------------------------------------------------------------------
    # Prompt input
    # ------------------------------------------------------------------

    async def fill_prompt(self, page, prompt: str) -> bool:
        """Fill the prompt textarea ("What do you want to create?")."""
        # Click elsewhere first to close any open panel
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
        except Exception:
            pass

        selectors = [
            "textarea[placeholder*='create' i]",
            "textarea[placeholder*='What' i]",
            "textarea",
            "[contenteditable='true']",
            "div[role='textbox']",
        ]
        for sel in selectors:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                await el.press("Control+a")
                await el.press("Meta+a")
                await el.fill(prompt)
                log.debug("Filled prompt (%d chars) via '%s'", len(prompt), sel)
                return True

        log.warning("Could not find prompt textarea")
        return False

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    async def click_submit(self, page) -> bool:
        """Click the generate/submit button (arrow_forward Create)."""
        # The submit button contains "Create" text with an arrow icon
        # It's different from the "add_2Create" (add media) button
        # Strategy: find button with "Create" that has aria or is the rightmost
        candidates = [
            page.get_by_role("button", name="Create", exact=True),
            page.locator("button").filter(has_text="arrow_forward"),
            page.locator("button[type='submit']"),
        ]
        for locator in candidates:
            if await locator.count() > 0:
                # If multiple, use last (the submit one, not the "add media" one)
                count = await locator.count()
                btn = locator.nth(count - 1)
                await btn.click()
                log.debug("Clicked submit button")
                return True

        # JS fallback: find button with Create text that is NOT the add media button
        clicked = await page.evaluate("""
            () => {
                const btns = [...document.querySelectorAll('button')];
                // Find the rightmost/last Create button (the submit one)
                const creates = btns.filter(b => {
                    const txt = b.textContent.trim();
                    return txt.includes('Create') && !b.disabled;
                });
                if (creates.length > 0) {
                    creates[creates.length - 1].click();
                    return true;
                }
                return false;
            }
        """)
        if clicked:
            log.debug("Clicked submit via JS fallback")
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
        """Count items in the generation gallery."""
        selectors = [
            "img[src*='storage.googleapis.com']",
            "video[src*='storage.googleapis.com']",
            "[data-index]",
            "[class*='generated']",
            "[class*='result']",
            "[class*='gallery'] img",
        ]
        max_count = 0
        for sel in selectors:
            count = await page.locator(sel).count()
            if count > max_count:
                max_count = count
        return max_count

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
        """Extract src URL from the newest generated image or video."""
        src = await page.evaluate("""
            () => {
                // GCS hosted images
                const imgs = [...document.querySelectorAll('img[src*="storage.googleapis.com"]')];
                const vids = [...document.querySelectorAll('video[src*="storage.googleapis.com"]')];
                const all = [...imgs, ...vids];
                if (!all.length) return null;
                const el = all[all.length - 1];
                return el.src || el.currentSrc || el.getAttribute('src');
            }
        """)
        return src or None

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
