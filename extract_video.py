import asyncio
import json
import logging
from pathlib import Path
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("extract")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
window.chrome = { runtime: {} };
"""

async def run():
    profile_dir = Path.home() / ".flow-py" / "browser-profile"
    project_url = "https://flow.google.com/project/72cec3a1-1506-4a70-a045-8ae6c0d1b925"
    chrome_path = "D:/BettaFish/playwright-browsers/chromium-1243/chrome-win64/chrome.exe"

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(profile_dir),
            executable_path=chrome_path,
            headless=True,
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ]
        )
        await ctx.add_init_script(STEALTH_JS)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        log.info("Navigating to project...")
        await page.goto(project_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

        # Let's inspect media and video elements
        res = await page.evaluate("""
            () => {
                const videos = [...document.querySelectorAll('video')].map(v => ({
                    src: v.src,
                    currentSrc: v.currentSrc
                }));
                const imgs = [...document.querySelectorAll('img')].map(i => ({
                    src: i.src.slice(0, 100),
                    alt: i.alt
                }));
                const allLinks = [...document.querySelectorAll('a')].map(a => a.href);
                return { videos, imgs, allLinks };
            }
        """)
        log.info("DOM videos: %s", res["videos"])

        # Also let's click on the video card to see options (download button, share, etc.)
        # The video card is on the canvas or in the right chat
        card = page.locator(".chat-message-content video, .canvas-node, [role='button']:has(img), img").first
        # Let's inspect right click or click on the card
        # Or look for download buttons
        download_btns = await page.query_selector_all("button[aria-label*='下载'], button[aria-label*='Download'], button:has-text('download')")
        log.info("Download buttons found: %d", len(download_btns))

        # Check left sidebar "视频" tab
        video_tab = page.locator("text='视频'")
        if await video_tab.count() > 0:
            await video_tab.first.click()
            await asyncio.sleep(2)
            await page.screenshot(path="D:/chatgpt聊天记录1/日常/flow-py/video_tab.png")
            log.info("Saved video_tab.png")

        await ctx.close()

if __name__ == "__main__":
    asyncio.run(run())
