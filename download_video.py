import asyncio
import os
import time
import urllib.request
from pathlib import Path
from playwright.async_api import async_playwright

CHROME_PATH = r"D:/BettaFish/playwright-browsers/chromium-1243/chrome-win64/chrome.exe"
OUTPUT_DIR = Path(r"D:\chatgpt聊天记录1\日常\flow-py\output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

async def capture_and_download():
    # Kill any dangling chrome to release user-data-dir lock if needed
    os.system("taskkill /f /im chrome.exe >nul 2>&1")
    await asyncio.sleep(1)

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            "C:\\Users\\liu200609\\.flow-py\\browser-profile",
            executable_path=CHROME_PATH,
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        
        captured_video_urls = []
        async def on_response(resp):
            url = resp.url
            ct = resp.headers.get("content-type", "")
            if "video" in ct or "googlevideo" in url or ".mp4" in url or "videoplayback" in url:
                print("Captured video stream URL:", url[:100])
                captured_video_urls.append(url)
        page.on("response", on_response)

        print("Navigating to Flow project...")
        await page.goto("https://flow.google.com/project/72cec3a1-1506-4a70-a045-8ae6c0d1b925", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

        # Wait until progress percentage is gone and video card is ready
        for i in range(25):
            percent = await page.evaluate("""() => {
                const text = document.body ? document.body.innerText : '';
                const m = text.match(/(\\d{1,3})%/);
                return m ? m[1] : null;
            }""")
            print(f"[{i*4}s] Progress percentage: {percent}%")
            if not percent:
                print("No progress percentage detected, video generation should be finished!")
                break
            await asyncio.sleep(4)

        # Click the first media card in gallery to trigger playback / download
        await page.screenshot(path=str(OUTPUT_DIR / "current_workspace.png"))
        
        # Click on the latest generated media card
        print("Clicking first media card to activate video playback...")
        card = await page.query_selector("main div[role='button'], div.media-card, div:has(> video), [aria-label*='媒体'], main img, div:has(> button[aria-label*='Play'])")
        if card:
            await card.click()
            await asyncio.sleep(3)

        # Search for video element in DOM
        video_src = await page.evaluate("""() => {
            const v = document.querySelector('video');
            return v ? v.src : null;
        }""")
        print("DOM video element src:", video_src)

        # Look for download button
        download_btn = await page.query_selector("button[aria-label*='下载'], button[aria-label*='Download'], button:has-text('下载'), [data-tooltip*='下载']")
        if download_btn:
            print("Found download button, triggering download...")
            async with page.expect_download(timeout=10000) as download_info:
                await download_btn.click()
            download = await download_info.value
            target_path = OUTPUT_DIR / "high_school_romance.mp4"
            await download.save_as(str(target_path))
            print("Saved download directly to:", target_path)
            await ctx.close()
            return str(target_path)

        # If video_src exists
        final_url = video_src or (captured_video_urls[-1] if captured_video_urls else None)
        if final_url:
            print("Downloading from direct URL:", final_url[:100])
            target_path = OUTPUT_DIR / "high_school_romance.mp4"
            # Use cookies via page
            # Download via page evaluate fetch
            content_bytes = await page.evaluate("""async (url) => {
                const res = await fetch(url);
                const buf = await res.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }""", final_url)
            with open(target_path, "wb") as f:
                f.write(bytes(content_bytes))
            print("Saved video file to:", target_path)
            await ctx.close()
            return str(target_path)

        await page.screenshot(path=str(OUTPUT_DIR / "debug_finish.png"))
        await ctx.close()
        return None

if __name__ == '__main__':
    asyncio.run(capture_and_download())
