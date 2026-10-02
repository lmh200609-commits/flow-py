import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

CHROME_PATH = r"D:/BettaFish/playwright-browsers/chromium-1243/chrome-win64/chrome.exe"
OUTPUT_DIR = Path(r"D:/chatgpt聊讠蒰录1/日常/flow-py/output")
TARGET_FILE = OUTPUT_DIR / "high_school_romance.mp4"

async def run():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            r"C:\Users\liu200609\.flow-py\browser-profile",
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
                print("INTERCEPTED VIDEO:", url)
                video_urls.append(url)
        page.on("response", on_resp)

        print("Loading Flow project...")
        await page.goto("https://flow.google.com/project/72cec3a1-1506-4a70-a045-8ae6c0d1b925", wait_until="domcontentloaded")
        await asyncio.sleep(6)

        v_info = await page.evaluate(""() => {
            const vids = Array.from(document.querySelectorAll('video')).map(v => v.src || v.currentSrc);
            const imgs = Array.from(document.querySelectorAll('img')).map(img => img.src);
            return { vids: vids.filter(Boolean), imgs: imgs.slice(0, 5) };
        }"")
        print("DOM info:", v_info)

        card = await page.query_selector('div.media-card, [role="button"] img')
        if card:
            try:
                await card.click(force=True)
                print('Clicked media card')
            except Exception as e:
                print('Click error:', e)
            await asyncio.sleep(4)

        buttons = await page.evaluate(""() => {
            return Array.from(document.querySelectorAll('button')).map(b => ({
                text: b.innerText,
                label: b.getAttribute('aria-label')
            }));
        }")
        matched = [b for b in buttons if any(k in str(b) for k in ['\exu4ebf\exu8e00', 'Download', 'Play', '\exu621f\exu5ffe;', '\exu675e\exu5e5a', 'More'])]
        print('Matched buttons:', matched)


        await page.screenshot(path=str(OUTPUT_DIR / 'latest_state.png'))


        final_video = None
        if v_info['vids']:
            final_video = v_info['vids'][-1]
        elif video_urls:
            final_video = video_urls[-1]

        if final_video:
            print('Downloading final video:', final_video[:100])
            content = await page.evaluate("""async (url) => {
                const res = await fetch(url);
                const buf = await res.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            }""", final_video)
            with open(TARGET_FILE, 'wb') as f:
                f.write(bytes(content))
            print('Successfully saved video to:', TARGET_FILE)
        else:
            print('No direct video URL detected yet in DOM or network.')

        await ctx.close()

if __name__ == '__main__':
    asyncio.run(run())
