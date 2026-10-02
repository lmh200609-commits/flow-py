import asyncio
import json
import logging
import time
from pathlib import Path
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("e2e")

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

        found_videos = []

        async def on_response(resp):
            url = resp.url
            ct = resp.headers.get("content-type", "")
            if "video" in ct or "googlevideo" in url or ".mp4" in url:
                log.info("FOUND VIDEO URL: %s", url)
                found_videos.append(url)
        page.on("response", on_response)

        log.info("Navigating to project: %s", project_url)
        await page.goto(project_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

        # 1. Click New Chat button if exists to start fresh
        new_chat_btn = page.locator("button[aria-label='发起新的会话']")
        if await new_chat_btn.count() > 0:
            log.info("Clicking new chat button...")
            await new_chat_btn.first.click()
            await asyncio.sleep(1)

        # 2. Focus ProseMirror
        editor = page.locator(".ProseMirror")
        await editor.wait_for(state="visible", timeout=10000)
        await editor.click()
        await asyncio.sleep(0.5)

        prompt = "生成一段5秒视频：一只可爱的小猫在阳光下的草坪上打滚，写实风格，电影感"
        log.info("Typing prompt: %s", prompt)
        await page.keyboard.type(prompt, delay=25)
        await asyncio.sleep(1)

        # 3. Wait for generate button to be enabled
        gen_btn = page.locator("button.generate-icon-button, button[aria-label='开始生成']")
        await gen_btn.wait_for(state="visible", timeout=5000)

        is_disabled = await gen_btn.is_disabled()
        log.info("Generate button disabled: %s", is_disabled)

        if is_disabled:
            # Maybe press Enter
            log.info("Pressing Enter to activate...")
            await page.keyboard.press("Enter")
            await asyncio.sleep(1)

        log.info("Clicking generate button...")
        await gen_btn.click()

        # 4. Loop to monitor video generation progress
        log.info("Monitoring generation...")
        for sec in range(5, 75, 5):
            await asyncio.sleep(5)
            log.info("Checking at %ds...", sec)

            # Check if any confirmation button appeared
            for label in ["确认", "生成", "批准", "Approve", "Confirm"]:
                btn = page.locator(f"button:has-text('{label}')")
                if await btn.count() > 0 and await btn.first.is_visible():
                    log.info("Found confirmation button '%s', clicking it!", label)
                    await btn.first.click()
                    await asyncio.sleep(1)

            # Check DOM for video tags
            video_tags = await page.evaluate("""
                () => {
                    const vids = [...document.querySelectorAll('video')].map(v => v.src || v.currentSrc);
                    return vids.filter(Boolean);
                }
            """)
            if video_tags:
                log.info("Video tags in DOM: %s", video_tags)
                found_videos.extend(video_tags)

            await page.screenshot(path=f"D:/chatgpt聊天记录1/日常/flow-py/e2e_step_{sec}s.png")

            if found_videos:
                log.info("Video successfully generated! %s", found_videos)
                break

        await ctx.close()

if __name__ == "__main__":
    asyncio.run(run())
