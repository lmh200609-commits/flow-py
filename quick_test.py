import asyncio
import time
from playwright.async_api import async_playwright
from service.flow_engine import get_preferred_proxy

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

async def test():
    proxy = get_preferred_proxy()
    print("Detected proxy:", proxy)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            "C:\\Users\\liu200609\\.flow-py\\browser-profile",
            executable_path=CHROME_PATH,
            headless=True,
            proxy={"server": proxy} if proxy else None,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            t0 = time.time()
            resp = await page.goto("https://flow.google.com/", wait_until="domcontentloaded", timeout=20000)
            print(f"Flow loaded successfully! Status: {resp.status} in {time.time()-t0:.2f}s, URL: {page.url}")
        except Exception as e:
            print("Flow navigation failed:", e)
        await ctx.close()

asyncio.run(test())
