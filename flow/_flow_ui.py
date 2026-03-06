"""High-level UI interaction helpers for Google Flow AI.

Knows the specific selectors/patterns for labs.google/fx/tools/flow.
Uses multiple selector strategies per method since the Flow UI changes frequently.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ._models import AspectRatio, GenerationMode

log = logging.getLogger(__name__)

# Mode tab labels as Flow shows them (multiple alternatives per mode)
_MODE_LABELS: dict[GenerationMode, list[str]] = {
    GenerationMode.IMAGE: ["Create Image", "Image", "Imagen", "Generate Image"],
    GenerationMode.VIDEO: ["Text-to-Video", "Video", "Generate Video", "Create Video"],
    GenerationMode.FRAME_TO_VIDEO: [
        "Frame-to-Video", "Image-to-Video", "Frame to Video", "Animate Image",
    ],
}

# Aspect ratio label mapping
_ASPECT_LABELS: dict[AspectRatio, list[str]] = {
    AspectRatio.LANDSCAPE: ["16:9", "Landscape", "Widescreen"],
    AspectRatio.PORTRAIT: ["9:16", "Portrait", "Vertical"],
    AspectRatio.SQUARE: ["1:1", "Square"],
}

# Policy / error indicator strings
_POLICY_TEXTS = [
    "violates our policy",
    "content policy",
    "harmful or unsafe",
    "unable to generate",
    "request was flagged",
    "couldn't generate",
    "blocked",
]


class FlowUI:
    """Knows the specific selectors/patterns for labs.google/fx/tools/flow."""

    async def navigate_to_project(self, page, project_url: str) -> None:
        """Navigate to a specific Flow project URL."""
        current = page.url
        if project_url.rstrip("/") in current:
            log.debug("Already on project page")
            return
        await page.goto(project_url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(1.5)

    async def switch_mode(self, page, mode: GenerationMode) -> bool:
        """Click the appropriate mode tab in the Flow UI.

        Returns True if a tab was found and clicked, False otherwise.
        """
        labels = _MODE_LABELS[mode]
        for label in labels:
            # Strategy 1: role=tab
            el = page.get_by_role("tab", name=label)
            if await el.count() > 0:
                await el.first.click()
                await asyncio.sleep(0.5)
                log.debug("Switched to %s via tab '%s'", mode.value, label)
                return True

            # Strategy 2: role=button
            el = page.get_by_role("button", name=label)
            if await el.count() > 0:
                await el.first.click()
                await asyncio.sleep(0.5)
                log.debug("Switched to %s via button '%s'", mode.value, label)
                return True

        # Strategy 3: text content match via JS
        clicked = await page.evaluate("""
            (labels) => {
                const candidates = [
                    ...document.querySelectorAll('[role="tab"]'),
                    ...document.querySelectorAll('button'),
                    ...document.querySelectorAll('[class*="tab"]'),
                ];
                for (const label of labels) {
                    for (const el of candidates) {
                        const text = (el.textContent || '').trim();
                        const ariaLabel = el.getAttribute('aria-label') || '';
                        if (text.includes(label) || ariaLabel.includes(label)) {
                            el.click();
                            return true;
                        }
                    }
                }
                return false;
            }
        """, labels)

        if clicked:
            await asyncio.sleep(0.5)
            log.debug("Switched to %s via JS fallback", mode.value)
            return True

        log.warning("Could not find mode tab for %s", mode.value)
        return False

    async def set_aspect_ratio(self, page, ratio: AspectRatio) -> bool:
        """Select the aspect ratio in the UI.

        Returns True if found and clicked.
        """
        labels = _ASPECT_LABELS[ratio]
        for label in labels:
            # Strategy 1: aria-label button
            el = page.locator(f"button[aria-label*='{label}' i]")
            if await el.count() > 0:
                await el.first.click()
                await asyncio.sleep(0.3)
                return True

            # Strategy 2: role=radio or role=option
            for role in ("radio", "option", "button"):
                el = page.get_by_role(role, name=label)
                if await el.count() > 0:
                    await el.first.click()
                    await asyncio.sleep(0.3)
                    return True

        # Strategy 3: text-based click
        clicked = await page.evaluate("""
            (labels) => {
                const els = [
                    ...document.querySelectorAll('button'),
                    ...document.querySelectorAll('[role="radio"]'),
                    ...document.querySelectorAll('[role="option"]'),
                    ...document.querySelectorAll('[class*="aspect"]'),
                ];
                for (const label of labels) {
                    for (const el of els) {
                        if ((el.textContent || '').trim().includes(label)) {
                            el.click();
                            return true;
                        }
                    }
                }
                return false;
            }
        """, labels)

        if clicked:
            await asyncio.sleep(0.3)
            return True

        log.warning("Could not find aspect ratio selector for %s", ratio.value)
        return False

    async def fill_and_submit_prompt(self, page, prompt: str) -> bool:
        """Fill the prompt textarea and click the generate button.

        Returns True if both actions succeeded.
        """
        # Find and fill textarea
        textarea_selectors = [
            "textarea[placeholder]",
            "textarea",
            "[contenteditable='true']",
            "div[role='textbox']",
        ]

        filled = False
        for sel in textarea_selectors:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                await el.press("Control+a")
                await el.press("Meta+a")
                await el.fill(prompt)
                filled = True
                break

        if not filled:
            log.error("Could not find prompt textarea")
            return False

        await asyncio.sleep(0.3)

        # Click generate button
        for text in ("Create", "Generate", "Run", "Submit"):
            btn = page.get_by_role("button", name=text, exact=True)
            if await btn.count() > 0:
                await btn.first.click()
                log.debug("Clicked '%s' button", text)
                return True

        # JS fallback
        clicked = await page.evaluate("""
            () => {
                const btns = [...document.querySelectorAll('button')];
                const btn = btns.find(b => !b.disabled &&
                    (b.textContent.includes('Create') ||
                     b.textContent.includes('Generate') ||
                     (b.getAttribute('aria-label') || '').toLowerCase().includes('generate')));
                if (btn) { btn.click(); return true; }
                return false;
            }
        """)
        return bool(clicked)

    async def upload_image(self, page, image_path: str) -> bool:
        """Upload a local image file for frame-to-video generation.

        Returns True if upload succeeded.
        """
        # Strategy 1: Direct file input
        file_input = page.locator("input[type='file']").first
        if await file_input.count() > 0:
            await file_input.set_input_files(image_path)
            await asyncio.sleep(1)
            return True

        # Strategy 2: Click upload zone, then use file chooser
        upload_selectors = [
            "[aria-label*='upload' i]",
            "[aria-label*='Upload' i]",
            "button:has-text('Upload')",
            "[class*='upload']",
            "[class*='drop']",
            "[data-dropzone]",
        ]
        for sel in upload_selectors:
            zone = page.locator(sel).first
            if await zone.count() > 0:
                try:
                    async with page.expect_file_chooser(timeout=5000) as fc_info:
                        await zone.click()
                    fc = await fc_info.value
                    await fc.set_files(image_path)
                    await asyncio.sleep(1)
                    return True
                except Exception:
                    continue

        log.warning("Could not find upload element for image")
        return False

    async def count_gallery_items(self, page) -> int:
        """Count current gallery items using multiple selector strategies."""
        selectors = [
            "[data-index]",
            ".gallery-item",
            ".result-item",
            "[class*='gallery'] img",
            "[class*='result'] img",
            "img[src*='storage.googleapis.com']",
            "video[src*='storage.googleapis.com']",
        ]
        for sel in selectors:
            count = await page.locator(sel).count()
            if count > 0:
                return count
        return 0

    async def check_policy_error(self, page) -> bool:
        """Check if a content policy error is visible on the page.

        Returns True if a policy error was detected.
        """
        body_text = await page.evaluate("() => document.body.innerText")
        body_lower = body_text.lower()
        return any(txt.lower() in body_lower for txt in _POLICY_TEXTS)

    async def get_newest_media_src(self, page) -> Optional[str]:
        """Get the src URL of the most recently generated media element."""
        return await page.evaluate("""
            () => {
                const vids = [...document.querySelectorAll('video[src*="storage.googleapis.com"]')];
                if (vids.length) return vids[vids.length - 1].src || vids[vids.length - 1].currentSrc;

                const srcs = [...document.querySelectorAll('source[src*="storage.googleapis.com"]')];
                if (srcs.length) return srcs[srcs.length - 1].src;

                const imgs = [...document.querySelectorAll('img[src*="storage.googleapis.com"]')];
                if (imgs.length) return imgs[imgs.length - 1].src;

                const indexed = [...document.querySelectorAll('[data-index]')];
                if (indexed.length) {
                    const last = indexed[indexed.length - 1];
                    const m = last.querySelector('video') || last.querySelector('img');
                    if (m) return m.src || m.currentSrc;
                }

                return null;
            }
        """)

    async def click_download_on_newest(self, page) -> bool:
        """Hover over the newest gallery item and click its download button.

        Returns True if the download button was clicked.
        """
        # Strategy 1: data-index based
        items = page.locator("[data-index]")
        if await items.count() > 0:
            last = items.last
            await last.hover()
            await asyncio.sleep(0.5)

            dl_selectors = [
                "button[aria-label*='download' i]",
                "button[aria-label*='Download']",
                "[title*='download' i]",
                "button:has(svg[data-icon*='download'])",
                "a[download]",
            ]
            for sel in dl_selectors:
                btn = last.locator(sel).first
                if await btn.count() > 0:
                    await btn.click()
                    return True

        # Strategy 2: Page-level download buttons (click the last one)
        for sel in [
            "button[aria-label*='download' i]",
            "button[aria-label*='Download']",
            "a[download]",
        ]:
            btns = page.locator(sel)
            if await btns.count() > 0:
                await btns.last.click()
                return True

        log.warning("Could not find download button")
        return False
