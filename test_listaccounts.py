import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
p_dir = Path.home() / ".flow-py" / "browser-profile"

async def test():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(p_dir),
            executable_path=CHROME_PATH,
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        # Test ListAccounts
        resp = await page.goto("https://accounts.google.com/ListAccounts?psdr=true")
        text = await resp.text()
        print("ListAccounts response:", text[:500])
        await ctx.close()

asyncio.run(test())
