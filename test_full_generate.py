import asyncio
import json
import logging
import time
from pathlib import Path
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("full_gen")

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

        captured_media = []
        captured_rpcs = []

        async def on_response(resp):
            url = resp.url
            if any(k in url for k in ["batchexecute", "aisandbox", "videoplayback", "blob:"]):
                try:
                    ct = resp.headers.get("content-type", "")
                    if "video" in ct or "mp4" in url or "googlevideo" in url:
                        log.info("VIDEO MEDIA DETECTED: %s", url)
                        captured_media.append(url)
                    elif "batchexecute" in url:
                        text = await resp.text()
                        if any(k in text for k in ["mp4", "media", "video", "http", "veo"]):
                            captured_rpcs.append({"url": url, "snippet": text[:500]})
                except Exception:
                    pass
        page.on("response", on_response)

        log.info("Navigating to project...")
        await page.goto(project_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(6)

        # First, ensure settings: '永不' confirm if available
        # Click settings icon (slider icon at bottom right of chat box)
        settings_icon = await page.query_selector("button:has-text('tune'), [aria-label*='设置'], [aria-label*='setting'], button:has(i:text-is('tune')), button:has(span:text-is('tune'))")
        if not settings_icon:
            # find icon with tune or slider
            buttons = await page.query_selector_all("button")
            for b in buttons:
                txt = await b.inner_text()
                if "tune" in txt:
                    settings_icon = b
                    break

        if settings_icon:
            log.info("Opening agent settings...")
            await settings_icon.click()
            await asyncio.sleep(1.5)
            # Find '永不' radio
            never_radio = await page.query_selector("text='永不'")
            if never_radio:
                log.info("Selecting '永不' for confirmation...")
                await never_radio.click()
                await asyncio.sleep(0.5)
            # Save button
            save_btn = await page.query_selector("button:has-text('保存')")
            if save_btn:
                log.info("Clicking save button...")
                await save_btn.click()
                await asyncio.sleep(1.5)

        # Now locate the prompt box
        input_elem = await page.query_selector("textarea, [contenteditable='true']")
        if not input_elem:
            log.error("Input element not found!")
            await ctx.close()
            return

        box = await input_elem.bounding_box()
        await page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
        await asyncio.sleep(0.5)

        prompt_text = "生成一段5秒的视频：一朵盛开的金色莲花在水面上缓缓旋转，水波荡漾，写实超清"
        await page.keyboard.type(prompt_text, delay=30)
        await asyncio.sleep(1)

        # Find submit button (arrow)
        send_btn = None
        buttons = await page.query_selector_all("button")
        for b in buttons:
            txt = await b.inner_text()
            if "arrow_forward" in txt or "send" in txt:
                send_btn = b
                break

        if send_btn:
            log.info("Found send button, clicking it...")
            await send_btn.click()
        else:
            log.info("Send button not found by text, pressing Enter...")
            await page.keyboard.press("Enter")

        log.info("Submitted! Now monitoring generation...")
        for i in range(12):  # Poll every 5s for up to 60s
            await asyncio.sleep(5)
            t = (i + 1) * 5
            log.info("Monitoring at t=%ds...", t)
            # Check for video elements or image cards
            videos = await page.query_selector_all("video, [role='progressbar'], canvas")
            img_cards = await page.query_selector_all("img[src*='google'], img[src*='blob']")
            log.info("Current elements: %d videos/canvas, %d images", len(videos), len(img_cards))

            # Check if there is a '确认' or '生成' button that needs to be clicked
            confirm_btn = await page.query_selector("button:has-text('确认'), button:has-text('生成'), button:has-text('继续'), button:has-text('Approve')")
            if confirm_btn and await confirm_btn.is_visible():
                log.info("Detected confirmation button! Clicking it...")
                await confirm_btn.click()

            await page.screenshot(path=f"D:/chatgpt聊天记录1/日常/flow-py/gen_step_{t}s.png")

            # Check if stop button has reverted to send button
            # Or if video element has src
            for v in videos:
                src = await v.get_attribute("src")
                if src:
                    log.info("FOUND VIDEO SRC: %s", src)
                    captured_media.append(src)

            if captured_media:
                log.info("Successfully got media: %s", captured_media)
                break

        log.info("Finished monitoring. Total captured media: %d, RPCs: %d", len(captured_media), len(captured_rpcs))
        with open("D:/chatgpt聊天记录1/日常/flow-py/captured_media.json", "w", encoding="utf-8") as f:
            json.dump({"media": captured_media, "rpcs": captured_rpcs}, f, indent=2, ensure_ascii=False)

        await ctx.close()

if __name__ == "__main__":
    asyncio.run(run())
