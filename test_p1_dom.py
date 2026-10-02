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
        await page.goto("https://flow.google.com/project/72cec3a1-1506-4a70-a045-8ae6c0d1b925", wait_until="domcontentloaded")
        await asyncio.sleep(4)
        info = await page.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('*')).filter(el => {
                const label = el.getAttribute('aria-label') || '';
                return label.includes('@') || label.includes('Google 帐号') || label.includes('Google Account');
            });
            return els.map(el => ({
                tag: el.tagName,
                aria: el.getAttribute('aria-label'),
                text: el.innerText
            }));
        }""")
        print("Profile 1 user elements:", info)
        await ctx.close()

asyncio.run(test())
