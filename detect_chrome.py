import json
from pathlib import Path

chrome_user_data = Path.home() / "AppData/Local/Google/Chrome/User Data"
local_state_file = chrome_user_data / "Local State"

if local_state_file.exists():
    try:
        with open(local_state_file, "r", encoding="utf-8") as f:
            ls = json.load(f)
        profiles = ls.get("profile", {}).get("info_cache", {})
        print("Detected Profiles in Chrome:")
        for p_name, p_info in profiles.items():
            name = p_info.get("name")
            email = p_info.get("user_name")
            print(f"  Folder: {p_name} | Name: {name} | Email: {email}")
    except Exception as e:
        print("Error:", e)
