import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
p_dir = Path.home() / ".flow-py" / "profiles" / "acc_02"

async def test():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(p_dir),
            executable_path=CHROME_PATH,
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        cookies = await ctx.cookies()
        print("Total cookies in acc_02:", len(cookies))
        for c in cookies:
            if "mail" in c["value"].lower() or "@" in c["value"]:
                print("Cookie with @:", c["name"], c["value"][:50])
            if c["name"] in ["ACCOUNT_CHOOSER", "COMPASS"]:
                print("Special cookie:", c["name"], c["value"])
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://flow.google.com/", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        html = await page.content()
        print("URL after goto:", page.url)
        # Check if login button or profile avatar exists
        avatar = await page.evaluate("""() => {
            const imgs = Array.from(document.querySelectorAll('img')).map(i => i.src + ' | ' + i.alt);
            const aria = Array.from(document.querySelectorAll('[aria-label]')).map(i => i.getAttribute('aria-label'));
            return { imgs, aria: aria.filter(a => a && (a.includes('@') || a.includes('Google') || a.includes('帐号') || a.includes('Account'))) };
        }""")
        print("Avatar/Aria info:", avatar)
        await ctx.close()

asyncio.run(test())
