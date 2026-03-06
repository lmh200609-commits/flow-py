"""Robust media downloader for flow-py."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import aiohttp
import aiofiles

log = logging.getLogger(__name__)


async def download_url(
    url: str,
    output_path: Path,
    session: aiohttp.ClientSession,
    timeout_s: int = 120,
) -> Path:
    """Download a URL to a local file.

    Args:
        url: The media URL to download.
        output_path: Destination file path.
        session: An existing aiohttp session to reuse.
        timeout_s: Total download timeout in seconds.

    Returns:
        The output path on success.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    timeout = aiohttp.ClientTimeout(total=timeout_s)
    async with session.get(url, timeout=timeout) as resp:
        resp.raise_for_status()
        async with aiofiles.open(output_path, "wb") as f:
            async for chunk in resp.content.iter_chunked(65536):
                await f.write(chunk)

    log.debug("Downloaded %s -> %s (%d bytes)", url[:80], output_path, output_path.stat().st_size)
    return output_path


async def download_from_page(
    page,
    output_path: Path,
    mode: str = "image",
) -> Optional[Path]:
    """Try to download the latest generated media from the page DOM.

    Strategy 1: Extract src URL from newest media element and download directly.
    Strategy 2: Intercept response URLs from storage.googleapis.com.

    Args:
        page: Playwright Page object.
        output_path: Base output path (extension will be added).
        mode: "image", "video", or "frame" to determine expected media type.

    Returns:
        Path to downloaded file, or None if download failed.
    """
    # Strategy 1: Extract src from DOM
    media_src = await page.evaluate("""
        () => {
            const imgs = [...document.querySelectorAll('img[src*="storage.googleapis.com"]')];
            const vids = [...document.querySelectorAll('video[src*="storage.googleapis.com"]')];
            const srcs = [...document.querySelectorAll('source[src*="storage.googleapis.com"]')];
            const els = [...imgs, ...vids, ...srcs];
            if (!els.length) return null;
            const last = els[els.length - 1];
            return last.src || last.currentSrc || null;
        }
    """)

    if media_src:
        ext = _guess_extension(media_src, mode)
        final_path = output_path.with_suffix(ext)
        try:
            async with aiohttp.ClientSession() as session:
                return await download_url(media_src, final_path, session)
        except Exception as e:
            log.warning("Direct URL download failed: %s", e)

    # Strategy 2: Look for download links / blob URLs
    download_href = await page.evaluate("""
        () => {
            const link = document.querySelector('a[download]');
            if (link && link.href) return link.href;
            return null;
        }
    """)

    if download_href and download_href.startswith("http"):
        ext = _guess_extension(download_href, mode)
        final_path = output_path.with_suffix(ext)
        try:
            async with aiohttp.ClientSession() as session:
                return await download_url(download_href, final_path, session)
        except Exception as e:
            log.warning("Download link strategy failed: %s", e)

    return None


def _guess_extension(url: str, mode: str) -> str:
    """Guess file extension from URL or generation mode."""
    url_lower = url.lower().split("?")[0]
    for ext in (".mp4", ".webm", ".gif", ".png", ".jpg", ".jpeg"):
        if url_lower.endswith(ext):
            return ext
    if mode in ("video", "frame"):
        return ".mp4"
    return ".png"
