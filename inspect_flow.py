import asyncio
import logging
from pathlib import Path
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("inspect_flow")

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
        await asyncio.sleep(6)

        # Click on "所有媒体"
        media_btn = await page.query_selector("text='所有媒体'")
        if media_btn:
            log.info("Clicking '所有媒体'...")
            await media_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="D:/chatgpt聊天记录1/日常/flow-py/view_media.png")

        # Click on "工具"
        tools_btn = await page.query_selector("text='工具'")
        if tools_btn:
            log.info("Clicking '工具'...")
            await tools_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="D:/chatgpt聊天记录1/日常/flow-py/view_tools.png")

        # Click on the chat menu (left icon of Golden Retriever Butterfly...)
        chat_menu = await page.query_selector("button:has-text('menu'), [aria-label*='会话'], [aria-label*='历史']")
        if not chat_menu:
            # find icon buttons near the top of the right pane
            header_icons = await page.query_selector_all("aside button, div[role='region'] button")
            log.info("Found %d header buttons in aside", len(header_icons))

        await page.screenshot(path="D:/chatgpt聊天记录1/日常/flow-py/view_final.png")
        await ctx.close()

if __name__ == "__main__":
    asyncio.run(run())
