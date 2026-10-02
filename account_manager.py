import asyncio
import argparse
import sys
import time
from pathlib import Path
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from service.pool_manager import AccountPoolManager, PROFILES_DIR

CHROME_PATH = "D:/BettaFish/playwright-browsers/chromium-1243/chrome-win64/chrome.exe"

def list_accounts():
    mgr = AccountPoolManager.get_instance()
    accounts = mgr.list_accounts()
    print("\n" + "="*80)
    print(f"{'ID':<10} {'Name':<22} {'Status':<12} {'Credits':<10} {'Total Gen':<10} {'Project URL'}")
    print("="*80)
    for a in accounts:
        status = a.get('status', 'unknown')
        if status == 'active':
            status_str = f"\033[92m{status}\033[0m"
        else:
            status_str = f"\033[91m{status}\033[0m"
        url = a.get('project_url', '')
        if len(url) > 35:
            url = url[:32] + "..."
        print(f"{a['id']:<10} {a.get('name', ''):<22} {status:<12} {a.get('credits', 0):<10} {a.get('total_generated', 0):<10} {url}")
    print("="*80 + "\n")

async def add_account_interactive(acc_id: str, name: str):
    mgr = AccountPoolManager.get_instance()
    target_profile = PROFILES_DIR / acc_id
    target_profile.mkdir(parents=True, exist_ok=True)

    print(f"\n[+] Preparing to add new account: {acc_id} ({name})")
    print(f"[+] Profile directory: {target_profile}")
    print(f"[+] Launching interactive Chrome window for Google login...")
    print(f"[!] Please log in to your Google Gemini Pro account in the opened window.\n")

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(target_profile),
            executable_path=CHROME_PATH,
            headless=False,  # Visible browser for human login!
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars"
            ]
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        flow_home = "https://flow.google.com/"
        await page.goto(flow_home)

        print("[*] Waiting for user to complete login and reach Flow workspace...")
        captured_project_url = None

        # Poll until user is inside a project
        for _ in range(120):  # Wait up to 10 minutes
            await asyncio.sleep(5)
            cur_url = page.url
            if "flow.google.com/project/" in cur_url:
                captured_project_url = cur_url
                print(f"\n[OK] Detected active workspace project: {captured_project_url}")
                break

        if not captured_project_url:
            print("[X] Login timed out or project was not opened. Aborting.")
            await ctx.close()
            return

        # Give it 5s to finish cookie sync
        await asyncio.sleep(5)
        await ctx.close()

    # Save to pool
    mgr.add_account(
        account_id=acc_id,
        name=name,
        profile_dir=str(target_profile),
        project_url=captured_project_url,
        credits=1050
    )
    print(f"\n[SUCCESS] Account {acc_id} ({name}) successfully registered into the pool!\n")
    list_accounts()

def main():
    parser = argparse.ArgumentParser(description="Google Flow Account Pool Manager")
    subparsers = parser.add_subparsers(dest="cmd")

    subparsers.add_parser("list", help="List all accounts in pool")

    add_parser = subparsers.add_parser("add", help="Add a new Google Pro account interactively")
    add_parser.add_argument("--id", required=True, help="Unique ID, e.g. acc_02")
    add_parser.add_argument("--name", default="", help="Descriptive name, e.g. Pro Account 2")

    reset_parser = subparsers.add_parser("reset", help="Manually reset an account from exhausted to active")
    reset_parser.add_argument("--id", required=True, help="Account ID to reset")

    args = parser.parse_args()

    if args.cmd == "list" or not args.cmd:
        list_accounts()
    elif args.cmd == "add":
        name = args.name or f"Pro Account {args.id}"
        asyncio.run(add_account_interactive(args.id, name))
    elif args.cmd == "reset":
        mgr = AccountPoolManager.get_instance()
        data = mgr.load_data()
        for a in data.get("accounts", []):
            if a["id"] == args.id:
                a["status"] = "active"
                a["exhausted_at"] = None
                a["credits"] = 1050
                print(f"[OK] Account {args.id} has been reset to active with 1050 credits.")
                break
        mgr.save_data(data)
        list_accounts()

if __name__ == "__main__":
    main()
