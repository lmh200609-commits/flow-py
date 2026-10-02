import asyncio
import time
from playwright.async_api import async_playwright
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

async def wait_video():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            "C:\\Users\\liu200609\\.flow-py\\browser-profile",
            executable_path=CHROME_PATH,
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://flow.google.com/project/72cec3a1-1506-4a70-a045-8ae6c0d1b925", wait_until="domcontentloaded")
        print("Waiting for video card rendering...")
        
        for i in range(30):
            await asyncio.sleep(5)
            # Check card status and percent
            info = await page.evaluate("""() => {
                const text = document.body.innerText;
                const percentMatch = text.match(/(\d{1,3})%/);
                const videos = Array.from(document.querySelectorAll('video')).map(v => v.src);
                return {
                    percent: percentMatch ? percentMatch[1] : null,
                    videoCount: videos.length,
                    videoSrcs: videos.filter(s => s && s.length > 5)
                };
            }""")
            print(f"[{i*5+5}s] Render info: {info}")
            if not info['percent'] and info['videoCount'] > 0:
                print("Video completed rendering!")
                # Take fresh screenshot
                await page.screenshot(path="D:\\chatgpt聊天记录1\\日常\\flow-py\\output\\romance_completed.png")
                break
        await ctx.close()

asyncio.run(wait_video())
