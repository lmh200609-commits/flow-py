import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
ACCOUNTS_FILE = Path.home() / ".flow-py" / "accounts.json"

async def extract_email_from_profile(p, profile_dir):
    try:
        ctx = await p.chromium.launch_persistent_context(
            str(profile_dir),
            executable_path=CHROME_PATH,
            headless=True,
            viewport={"width": 1280, "height": 800},
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        
        # Method 1: Check myaccount
        try:
            await page.goto("https://myaccount.google.com/?pli=1", wait_until="domcontentloaded", timeout=12000)
            await asyncio.sleep(1.5)
            email = await page.evaluate("""() => {
                const el = document.querySelector('[aria-label*="@"]');
                if (el) {
                    const m = el.getAttribute('aria-label').match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/);
                    if (m) return m[0];
                }
                const text = document.body.innerText;
                const m2 = text.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/);
                return m2 ? m2[0] : null;
            }""")
            if email:
                await ctx.close()
                return email
        except Exception:
            pass

        # Method 2: Check flow.google.com
        try:
            await page.goto("https://flow.google.com/", wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            email = await page.evaluate("""() => {
                const el = document.querySelector('[aria-label*="@"]');
                if (el) {
                    const m = el.getAttribute('aria-label').match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/);
                    if (m) return m[0];
                }
                const text = document.body.innerText;
                const m2 = text.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/);
                return m2 ? m2[0] : null;
            }""")
            await ctx.close()
            return email
        except Exception:
            pass

        await ctx.close()
    except Exception as e:
        print("launch error:", e)
    return None

async def main():
    if not ACCOUNTS_FILE.exists():
        return
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    async with async_playwright() as p:
        for acc in data.get("accounts", []):
            acc_id = acc["id"]
            p_dir = Path(acc["profile_dir"])
            if not p_dir.exists():
                continue
            print(f"Detecting {acc_id}...")
            email = await extract_email_from_profile(p, p_dir)
            print(f"{acc_id} email: {email}")
            if email:
                acc["email"] = email
                acc["name"] = f"Gemini Pro ({email})"
            elif "email" not in acc:
                acc["email"] = "未检测"

    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("Finished detecting emails.")

if __name__ == "__main__":
    asyncio.run(main())
