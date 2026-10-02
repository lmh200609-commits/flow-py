import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

CHROME_PATH = "D:/BettaFish/playwright-browsers/chromium-1243/chrome-win64/chrome.exe"
OUTPUT_DIR = Path("D:/chatgpt聊天记录1/日常/flow-py/output")
TARGET_FILE = OUTPUT_DIR / "space_exploration.mp4"
SCREENSHOT_FILE = OUTPUT_DIR / "space_render_status.png"

async def run():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            "C:/Users/liu200609/.flow-py/browser-profile",
            executable_path=CHROME_PATH,
            headless=True,
            viewport={"width": 1440, "height": 900},
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        video_stream_urls = []
        async def on_resp(resp):
            url = resp.url
            ct = resp.headers.get("content-type", "")
            if "video" in ct or ".mp4" in url or "googlevideo" in url or "videoplayback" in url:
                print("FOUND STREAM URL:", url[:120])
                video_stream_urls.append(url)
        page.on("response", on_resp)

        print("Navigating to Flow project...")
        await page.goto("https://flow.google.com/project/72cec3a1-1506-4a70-a045-8ae6c0d1b925", wait_until="domcontentloaded")
        await asyncio.sleep(6)

        # Check for rendering progress if still in progress
        for _ in range(30):
            progress = await page.evaluate("""() => {
                const m = (document.body ? document.body.innerText : '').match(/(\\d{1,3})%/);
                return m ? m[1] : null;
            }""")
            if not progress:
                print("Rendering complete!")
                break
            print(f"Still rendering: {progress}%...")
            await asyncio.sleep(4)

        await page.screenshot(path=str(SCREENSHOT_FILE))
        print("Saved status screenshot:", SCREENSHOT_FILE)

        # Look for video cards or images on canvas
        # Click upper-left / latest card
        await page.mouse.click(440, 350)
        await asyncio.sleep(2)
        await page.mouse.click(440, 350)
        await asyncio.sleep(3)

        # Also find all video elements
        v_info = await page.evaluate("() => Array.from(document.querySelectorAll('video')).map(v => v.src || v.currentSrc)")
        print("DOM video srcs:", v_info)

        # Try to find download button
        dl_btn = await page.query_selector("button[aria-label*='下载'], button[aria-label*='Download'], button:has-text('下载')")
        if dl_btn:
            print("Found download button!")
            try:
                async with page.expect_download(timeout=8000) as dl_info:
                    await dl_btn.click()
                dl = await dl_info.value
                await dl.save_as(str(TARGET_FILE))
                print("Downloaded via button to:", TARGET_FILE)
                await ctx.close()
                return
            except Exception as e:
                print("Download button click failed:", e)

        # If we have captured stream URLs
        all_vids = [v for v in v_info if v] + video_stream_urls
        # Filter out landing page preview videos if any
        all_vids = [v for v in all_vids if "landing" not in v]
        if all_vids:
            dl_url = all_vids[-1]
            print("Downloading video stream:", dl_url[:120])
            resp = await page.context.request.get(dl_url)
            if resp.status == 200:
                body = await resp.body()
                TARGET_FILE.write_bytes(body)
                print("SUCCESSFULLY DOWNLOADED VIDEO! Size:", len(body), "bytes at", TARGET_FILE)
        else:
            print("No new video URL intercepted yet.")

        await ctx.close()

if __name__ == '__main__':
    asyncio.run(run())
