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
        # Direct fetch via page context
        res = await page.evaluate("""async () => {
            const resp = await fetch("https://myaccount.google.com/?pli=1");
            const text = await resp.text();
            // Search for @gmail.com or other email
            const matches = text.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g);
            return {
                status: resp.status,
                url: resp.url,
                matches: matches ? Array.from(new Set(matches)).slice(0, 10) : []
            };
        }""")
        print("Fetch myaccount result:", res)
        await ctx.close()

asyncio.run(test())
