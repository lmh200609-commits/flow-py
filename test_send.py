import asyncio
import json
import logging
from pathlib import Path
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("test_send")

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

        captured_rpcs = []

        async def on_response(resp):
            url = resp.url
            if "batchexecute" in url:
                try:
                    text = await resp.text()
                    captured_rpcs.append({
                        "url": url,
                        "status": resp.status,
                        "req_post": resp.request.post_data[:200] if resp.request.post_data else "",
                        "resp_preview": text[:300]
                    })
                except Exception:
                    pass
        page.on("response", on_response)

        log.info("Navigating to project...")
        await page.goto(project_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

        # Find the input box
        # Inspect right agent box
        input_elem = await page.query_selector("textarea, [contenteditable='true']")
        if not input_elem:
            log.error("Could not find input element!")
            await page.screenshot(path="D:/chatgpt聊天记录1/日常/flow-py/error_no_input.png")
            await ctx.close()
            return

        box = await input_elem.bounding_box()
        log.info("Input bounding box: %s", box)

        # Move mouse realistically
        await page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
        await asyncio.sleep(0.3)
        await page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
        await asyncio.sleep(0.5)

        # Type prompt with realistic human delay
        prompt_text = "生成一段5秒视频：一只可爱的小金毛犬在草地上追逐蝴蝶，阳光明媚，写实风格"
        await page.keyboard.type(prompt_text, delay=35)
        await asyncio.sleep(1)

        await page.screenshot(path="D:/chatgpt聊天记录1/日常/flow-py/after_typing.png")
        log.info("Saved after_typing.png")

        # Find submit button (the arrow button in the bottom right of the prompt box)
        # Check buttons near the input
        buttons = await page.query_selector_all("button")
        log.info("Found %d buttons", len(buttons))

        # Press Enter or find the submit button
        # Let's try Enter key directly
        log.info("Pressing Enter to submit...")
        await page.keyboard.press("Enter")

        # Wait 10s to see what happens
        await asyncio.sleep(10)

        await page.screenshot(path="D:/chatgpt聊天记录1/日常/flow-py/after_submit.png")
        log.info("Saved after_submit.png")

        with open("D:/chatgpt聊天记录1/日常/flow-py/captured_submit_rpcs.json", "w", encoding="utf-8") as f:
            json.dump(captured_rpcs, f, indent=2, ensure_ascii=False)

        await ctx.close()

if __name__ == "__main__":
    asyncio.run(run())
