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
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        video_urls = []
        async def on_resp(resp):
            url = resp.url
            ct = resp.headers.get("content-type", "")
            if "video" in ct or ".mp4" in url or "googlevideo" in url or "videoplayback" in url:
                print("INTERCEPTED VIDEO:", url[:120])
                video_urls.append(url)
        page.on("response", on_resp)

        print("Loading Flow project...")
        await page.goto("https://flow.google.com/project/72cec3a1-1506-4a70-a045-8ae6c0d1b925", wait_until="domcontentloaded")
        await asyncio.sleep(6)

        # Look for video elements already in page
        vids = await page.evaluate("() => Array.from(document.querySelectorAll('video')).map(v => v.src || v.currentSrc)")
        print("DOM video tags:", vids)

        card = await page.query_selector("div.media-card, [role='button'] img, main img")
        if card:
            try:
                await card.click(force=True)
                print("Clicked media card!")
            except Exception as e:
                print("Click error:", e)
            await asyncio.sleep(4)

        # Check for download button or trigger download
        dl_btn = await page.query_selector("button[aria-label*='下载'], button[aria-label*='Download']")
        if dl_btn:
            print("Found download button, clicking...")
            async with page.expect_download(timeout=10000) as dl_info:
                await dl_btn.click()
            dl = await dl_info.value
            await dl.save_as(str(TARGET_FILE))
            print("Saved download directly to:", TARGET_FILE)
            await ctx.close()
            return

        all_urls = [v for v in vids if v] + video_urls
        print("All candidate URLs:", len(all_urls))
        if all_urls:
            final_video = all_urls[-1]
            print("Downloading from:", final_video[:120])
            resp = await page.context.request.get(final_video)
            if resp.status == 200:
                TARGET_FILE.write_bytes(await resp.body())
                print("SUCCESS! Saved video to:", TARGET_FILE, "Size:", TARGET_FILE.stat().st_size)
            else:
                print("Request failed with status:", resp.status)
        else:
            await page.screenshot(path=str(OUTPUT_DIR / "fetch_debug.png"))
            print("No video URL found, screenshot saved.")

        await ctx.close()

if __name__ == '__main__':
    asyncio.run(run())
