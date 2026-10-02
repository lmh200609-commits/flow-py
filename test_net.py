import asyncio
import time
from playwright.async_api import async_playwright

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

async def test():
    async with async_playwright() as p:
        # Launch browser without proxy first
        browser = await p.chromium.launch(
            executable_path=CHROME_PATH,
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        page = await browser.new_page()
        print("Testing direct navigation to https://www.google.com...")
        t0 = time.time()
        try:
            resp = await page.goto("https://www.google.com", timeout=15000)
            print(f"Google status: {resp.status} in {time.time()-t0:.2f}s")
        except Exception as e:
            print("Direct google failed:", e)

        print("Testing direct navigation to https://flow.google.com/...")
        t0 = time.time()
        try:
            resp = await page.goto("https://flow.google.com/", timeout=15000)
            print(f"Flow status: {resp.status} in {time.time()-t0:.2f}s")
        except Exception as e:
            print("Direct flow failed:", e)

        await browser.close()

asyncio.run(test())
