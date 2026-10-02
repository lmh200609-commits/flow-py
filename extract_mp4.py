import asyncio
import os
import urllib.request
from pathlib import Path
from playwright.async_api import async_playwright

CHROME_PATH = r"D:/BettaFish/playwright-browsers/chromium-1243/chrome-win64/chrome.exe"
OUTPUT_DIR = Path(r"D:/chatgpt聊天记录1/日常/flow-py/output")
TARGET_FILE = OUTPUT_DIR / "high_school_romance.mp4"

async def extract_mp4():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            "C:\\Users\\liu200609\\.flow-py\\browser-profile",
            executable_path=CHROME_PATH,
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        video_stream_urls = []
        async def on_response(resp):
            url = resp.url
            ct = resp.headers.get("content-type", "")
            if "video" in ct or ".mp4" in url or "googlevideo" in url or "videoplayback" in url:
                print("FOUND VIDEO URL:", url)
                video_stream_urls.append(url)
        page.on("response", on_response)

        await page.goto("https://flow.google.com/project/72cec3a1-1506-4a70-a045-8ae6c0d1b925", wait_until="domcontentloaded")
        await asyncio.sleep(4)

        # Click the play button / first card
        play_btn = await page.query_selector("button[aria-label*='Play'], button[aria-label*='播放'], [aria-label*='Nostalgic High School'], main div.media-card, main img")
        if play_btn:
            print("Clicking play/card...")
            await play_btn.click()
            await asyncio.sleep(3)

        # Also click inside the big video player or double click
        big_card = await page.query_selector("main div[role='button']")
        if big_card:
            await big_card.click()
            await asyncio.sleep(3)

        # Check for <video> tag src or blob
        video_info = await page.evaluate("""() => {
            const v = document.querySelector('video');
            if (!v) return null;
            return { src: v.src, currentSrc: v.currentSrc };
        }""")
        print("Video tag info:", video_info)

        # Look for download button inside menu or toolbar
        menu_btn = await page.query_selector("button[aria-label*='更多'], button[aria-label*='More'], button:has-text('more_vert')")
        if menu_btn:
            await menu_btn.click()
            await asyncio.sleep(1)

        dl_btn = await page.query_selector("button:has-text('下载'), [aria-label*='下载'], [aria-label*='Download'], a[download]")
        if dl_btn:
            print("Found download button, clicking...")
            try:
                async with page.expect_download(timeout=8000) as dl_info:
                    await dl_btn.click()
                dl = await dl_info.value
                await dl.save_as(str(TARGET_FILE))
                print("Saved via download button to:", TARGET_FILE)
                await ctx.close()
                return str(TARGET_FILE)
            except Exception as e:
                print("Download event failed:", e)

        # Fallback to direct download URL
        if video_stream_urls:
            dl_url = video_stream_urls[-1]
            print("Downloading from captured stream URL:", dl_url[:100])
            content = await page.evaluate("""async (url) => {
                const res = await fetch(url);
                const buf = await res.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }""", dl_url)
            with open(TARGET_FILE, "wb") as f:
                f.write(bytes(content))
            print("Saved video from fetch to:", TARGET_FILE)
            await ctx.close()
            return str(TARGET_FILE)

        await page.screenshot(path=str(OUTPUT_DIR / "debug_player.png"))
        await ctx.close()
        return None

if __name__ == '__main__':
    asyncio.run(extract_mp4())
