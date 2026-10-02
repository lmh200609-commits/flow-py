import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

CHROME_PATH = r"D:/BettaFish/playwright-browsers/chromium-1243/chrome-win64/chrome.exe"
OUTPUT_DIR = Path(r"D:\chatgpt聊天记录1\日常\flow-py\output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TARGET_FILE = OUTPUT_DIR / "high_school_romance_latest.mp4"

async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            r"C:\Users\liu200609\.flow-py\browser-profile",
            executable_path=CHROME_PATH,
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        captured = []
        async def on_resp(resp):
            url = resp.url
            ct = resp.headers.get("content-type", "")
            if "video" in ct or "googlevideo" in url or ".mp4" in url or "videoplayback" in url:
                print("CAPTURED:", url[:120])
                captured.append(url)
        page.on("response", on_resp)

        print("Navigating to project...")
        await page.goto("https://flow.google.com/project/72cec3a1-1506-4a70-a045-8ae6c0d1b925", wait_until="domcontentloaded")
        await asyncio.sleep(6)

        # Check progress
        progress = await page.evaluate("""() => {
            const m = (document.body ? document.body.innerText : '').match(/(\\d{1,3})%/);
            return m ? m[1] : null;
        }""")
        print("Initial Progress:", progress)

        # Wait if still rendering
        for _ in range(20):
            progress = await page.evaluate("""() => {
                const m = (document.body ? document.body.innerText : '').match(/(\\d{1,3})%/);
                return m ? m[1] : null;
            }""")
            if not progress:
                print("Rendering seems 100% finished!")
                break
            print(f"Still rendering: {progress}%...")
            await asyncio.sleep(4)

        await page.screenshot(path=str(OUTPUT_DIR / "check_render_state.png"))

        # Click top-left / recent video card
        # Let's find all video elements or buttons
        card = await page.query_selector("main div[role='button'], div.media-card, main img")
        if card:
            await card.click()
            await asyncio.sleep(2)
            await card.click()
            await asyncio.sleep(3)

        # Look for download button
        dl_btn = await page.query_selector("button[aria-label*='下载'], button[aria-label*='Download'], button:has-text('下载')")
        if dl_btn:
            print("Found download button, triggering download...")
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

        # Check video src
        vsrc = await page.evaluate("() => { const v = document.querySelector('video'); return v ? (v.src || v.currentSrc) : null; }")
        print("DOM vsrc:", vsrc)

        stream = vsrc or (captured[-1] if captured else None)
        if stream:
            print("Downloading stream from:", stream[:100])
            data = await page.evaluate("""async (url) => {
                const res = await fetch(url);
                const buf = await res.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }""", stream)
            with open(TARGET_FILE, "wb") as f:
                f.write(bytes(data))
            print("Saved stream to:", TARGET_FILE)
        else:
            print("No video stream found.")

        await ctx.close()

if __name__ == '__main__':
    asyncio.run(main())
