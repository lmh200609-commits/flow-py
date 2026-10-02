import asyncio
import logging
from pathlib import Path
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("check_status")

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
        await asyncio.sleep(8)

        # Inspect chat messages
        messages = await page.evaluate("""
            () => {
                const els = document.querySelectorAll('*');
                const texts = [];
                for (const el of els) {
                    if (el.innerText && el.innerText.length > 5 && el.innerText.length < 500 && el.children.length === 0) {
                        texts.push(el.innerText);
                    }
                }
                return Array.from(new Set(texts));
            }
        """)
        log.info("Found text snippets: %s", messages[:30])

        screenshot_path = "D:/chatgpt聊天记录1/日常/flow-py/status_screenshot.png"
        await page.screenshot(path=screenshot_path)
        log.info("Saved screenshot to %s", screenshot_path)

        await ctx.close()

if __name__ == "__main__":
    asyncio.run(run())
