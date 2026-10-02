import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

CHROME_PATH = "D:/BettaFish/playwright-browsers/chromium-1243/chrome-win64/chrome.exe"
OUTPUT_DIR = Path("D:/chatgpt聊天记录1/日常/flow-py/output")
TARGET_FILE = OUTPUT_DIR / "high_school_romance.mp4"

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
        await asyncio.sleep(5)

        # First close the account modal by clicking its close button or background
        close_btn = await page.query_selector("button[aria-label='关闭'], .close-button, i:text-is('close')")
        if close_btn:
            try:
                await close_btn.click()
                print("Closed modal via button")
                await asyncio.sleep(1)
            except Exception as e:
                print("Close btn error:", e)
        else:
            # Click background outside modal (e.g. at 200, 200)
            await page.mouse.click(200, 200)
            await asyncio.sleep(1)

        # Now click directly onto the romance video card (center of upper card, approx x=440, y=350)
        print("Clicking top video card...")
        await page.mouse.click(440, 350)
        await asyncio.sleep(2)

        # Double click or play
        await page.mouse.click(440, 350)
        await asyncio.sleep(3)

        # Inspect if video element appeared
        v_info = await page.evaluate("() => Array.from(document.querySelectorAll('video')).map(v => v.src || v.currentSrc)")
        print("DOM video srcs:", v_info)

        # Check for 3-dots or download icon
        buttons = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('button')).map(b => ({
                text: b.innerText.trim(),
                label: b.getAttribute('aria-label'),
                rect: b.getBoundingClientRect()
            })).filter(b => b.rect.width > 0);
        }""")
        print("Visible buttons count:", len(buttons))
        for b in buttons:
            if any(k in str(b) for k in ['下载', 'Download', '更多', 'More', 'more_vert', 'play', 'Play']):
                print("Candidate button:", b)

        await page.screenshot(path=str(OUTPUT_DIR / "clicked_state.png"))

        # Check captured stream URLs
        all_vids = [v for v in v_info if v] + video_stream_urls
        if all_vids:
            dl_url = all_vids[-1]
            print("Downloading video stream:", dl_url[:120])
            resp = await page.context.request.get(dl_url)
            if resp.status == 200:
                body = await resp.body()
                TARGET_FILE.write_bytes(body)
                print("SUCCESSFULLY DOWNLOADED VIDEO! Size:", len(body), "bytes at", TARGET_FILE)
        else:
            print("No video URL intercepted yet.")

        await ctx.close()

if __name__ == '__main__':
    asyncio.run(run())
