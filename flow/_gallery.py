"""Gallery state tracker for Google Flow AI."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

# Multiple selector strategies for finding gallery items
_GALLERY_ITEM_SELECTORS = [
    "[data-index]",
    ".gallery-item",
    ".result-item",
    "[class*='gallery'] img",
    "[class*='result'] img",
    "img[src*='storage.googleapis.com']",
    "video[src*='storage.googleapis.com']",
]


class GalleryWatcher:
    """Watches the Flow gallery DOM for new generated items."""

    async def snapshot(self, page) -> list[dict]:
        """Take a snapshot of current gallery items.

        Returns:
            List of dicts with keys: src, type, index.
        """
        items = await page.evaluate("""
            () => {
                const results = [];

                // Strategy 1: data-index elements
                const indexed = document.querySelectorAll('[data-index]');
                indexed.forEach((el, i) => {
                    const img = el.querySelector('img');
                    const vid = el.querySelector('video');
                    const media = vid || img;
                    results.push({
                        src: media ? (media.src || media.currentSrc || '') : '',
                        type: vid ? 'video' : 'image',
                        index: parseInt(el.getAttribute('data-index') || i),
                    });
                });

                if (results.length > 0) return results;

                // Strategy 2: GCS media elements directly
                const imgs = document.querySelectorAll('img[src*="storage.googleapis.com"]');
                imgs.forEach((el, i) => {
                    results.push({ src: el.src || '', type: 'image', index: i });
                });

                const vids = document.querySelectorAll('video[src*="storage.googleapis.com"]');
                vids.forEach((el, i) => {
                    results.push({
                        src: el.src || el.currentSrc || '',
                        type: 'video',
                        index: results.length,
                    });
                });

                return results;
            }
        """)
        return items

    async def wait_for_new(
        self,
        page,
        before: list[dict],
        timeout_s: int = 300,
        poll_interval: float = 1.5,
    ) -> list[dict]:
        """Wait until new items appear in the gallery beyond `before`.

        Args:
            page: Playwright Page.
            before: Previous snapshot to compare against.
            timeout_s: How long to wait before giving up.
            poll_interval: Seconds between polls.

        Returns:
            List of new items (items in current snapshot but not in before).
        """
        before_srcs = {item.get("src", "") for item in before if item.get("src")}
        before_count = len(before)
        deadline = time.monotonic() + timeout_s

        while time.monotonic() < deadline:
            current = await self.snapshot(page)

            # Check by count first (most reliable)
            if len(current) > before_count:
                new_items = []
                for item in current:
                    src = item.get("src", "")
                    if src and src not in before_srcs:
                        new_items.append(item)
                if new_items:
                    log.debug("Gallery: %d new items detected", len(new_items))
                    return new_items

            await asyncio.sleep(poll_interval)

        return []

    async def get_latest_media_src(self, page) -> Optional[str]:
        """Get the src URL of the most recently added media element.

        Returns:
            URL string or None.
        """
        src = await page.evaluate("""
            () => {
                // Check videos first (they're usually the latest in Flow)
                const vids = [...document.querySelectorAll('video[src*="storage.googleapis.com"]')];
                if (vids.length > 0) {
                    const last = vids[vids.length - 1];
                    return last.src || last.currentSrc || null;
                }

                const srcs = [...document.querySelectorAll('source[src*="storage.googleapis.com"]')];
                if (srcs.length > 0) {
                    return srcs[srcs.length - 1].src || null;
                }

                const imgs = [...document.querySelectorAll('img[src*="storage.googleapis.com"]')];
                if (imgs.length > 0) {
                    return imgs[imgs.length - 1].src || null;
                }

                // Fallback: any media with data-index
                const indexed = [...document.querySelectorAll('[data-index]')];
                if (indexed.length > 0) {
                    const last = indexed[indexed.length - 1];
                    const media = last.querySelector('video') || last.querySelector('img');
                    if (media) return media.src || media.currentSrc || null;
                }

                return null;
            }
        """)
        return src
