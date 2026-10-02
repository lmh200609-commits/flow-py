import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

log = logging.getLogger("pool_manager")

BASE_FLOW_DIR = Path.home() / ".flow-py"
ACCOUNTS_FILE = BASE_FLOW_DIR / "accounts.json"
PROFILES_DIR = BASE_FLOW_DIR / "profiles"

class AccountPoolManager:
    _instance: Optional["AccountPoolManager"] = None

    def __init__(self):
        BASE_FLOW_DIR.mkdir(parents=True, exist_ok=True)
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        self.accounts_file = ACCOUNTS_FILE
        self._current_index = 0
        self._init_default_pool()

    @classmethod
    def get_instance(cls) -> "AccountPoolManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _init_default_pool(self):
        """Initialize accounts.json if not exists, integrating existing profile."""
        if not self.accounts_file.exists():
            default_profile = BASE_FLOW_DIR / "browser-profile"
            default_account = {
                "id": "acc_01",
                "name": "Gemini Pro (lmh200609@gmail.com)",
                "email": "lmh200609@gmail.com",
                "profile_dir": str(default_profile),
                "project_url": "https://flow.google.com/project/72cec3a1-1506-4a70-a045-8ae6c0d1b925",
                "status": "active",
                "credits": 1050,
                "total_generated": 1,
                "last_used_at": int(time.time()),
                "exhausted_at": None,
                "auto_reset_hours": 24
            }
            data = {
                "active_strategy": "round_robin",
                "accounts": [default_account]
            }
            self.save_data(data)
            log.info("Initialized account pool with default account acc_01")

    def load_data(self) -> Dict[str, Any]:
        if not self.accounts_file.exists():
            self._init_default_pool()
        try:
            with open(self.accounts_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error("Failed to read accounts.json: %s", e)
            return {"active_strategy": "round_robin", "accounts": []}

    def save_data(self, data: Dict[str, Any]):
        with open(self.accounts_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def list_accounts(self) -> List[Dict[str, Any]]:
        data = self.load_data()
        now = time.time()
        updated = False
        for acc in data.get("accounts", []):
            if acc.get("status") == "exhausted" and acc.get("exhausted_at"):
                reset_secs = acc.get("auto_reset_hours", 24) * 3600
                if (now - acc["exhausted_at"]) > reset_secs:
                    acc["status"] = "active"
                    acc["exhausted_at"] = None
                    acc["credits"] = 1050
                    log.info("Account %s automatically revived after reset period.", acc["id"])
                    updated = True
        if updated:
            self.save_data(data)
        return data.get("accounts", [])

    def get_next_available_account(self) -> Optional[Dict[str, Any]]:
        accounts = self.list_accounts()
        active_accounts = [a for a in accounts if a.get("status") == "active" and a.get("credits", 1) > 0]
        if not active_accounts:
            log.warning("No active accounts available in pool! All exhausted or disabled.")
            return None
        idx = self._current_index % len(active_accounts)
        selected = active_accounts[idx]
        self._current_index = (self._current_index + 1) % len(active_accounts)
        return selected

    def mark_exhausted(self, account_id: str, reason: str = "quota_exceeded"):
        data = self.load_data()
        for acc in data.get("accounts", []):
            if acc["id"] == account_id:
                acc["status"] = "exhausted"
                acc["exhausted_at"] = int(time.time())
                acc["exhaust_reason"] = reason
                acc["credits"] = 0
                log.warning("Marked account %s as EXHAUSTED: %s", account_id, reason)
                break
        self.save_data(data)

    def mark_success(self, account_id: str, credits_deducted: int = 10):
        data = self.load_data()
        for acc in data.get("accounts", []):
            if acc["id"] == account_id:
                acc["last_used_at"] = int(time.time())
                acc["total_generated"] = acc.get("total_generated", 0) + 1
                if "credits" in acc and acc["credits"] is not None:
                    acc["credits"] = max(0, acc["credits"] - credits_deducted)
                break
        self.save_data(data)

    def find_account_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        if not email:
            return None
        data = self.load_data()
        for acc in data.get("accounts", []):
            if acc.get("email", "").lower() == email.strip().lower():
                return acc
        return None

    def update_account(self, account_id: str, updates: Dict[str, Any]):
        data = self.load_data()
        for acc in data.get("accounts", []):
            if acc["id"] == account_id:
                acc.update(updates)
                break
        self.save_data(data)

    def add_account(
        self,
        account_id: str,
        name: str,
        profile_dir: str,
        project_url: str,
        credits: int = 1050,
        email: Optional[str] = None
    ):
        data = self.load_data()
        # Find if existing by id or email
        existing_idx = None
        for i, a in enumerate(data.get("accounts", [])):
            if a["id"] == account_id or (email and a.get("email", "").lower() == email.strip().lower()):
                existing_idx = i
                break

        now = int(time.time())
        if existing_idx is not None:
            acc = data["accounts"][existing_idx]
            acc["name"] = name
            acc["profile_dir"] = str(profile_dir)
            if project_url and "project" in project_url:
                acc["project_url"] = project_url
            if email:
                acc["email"] = email
            acc["status"] = "active"
            acc["last_used_at"] = now
            log.info("Updated existing account %s (%s)", acc["id"], email)
        else:
            new_acc = {
                "id": account_id,
                "name": name,
                "email": email or "",
                "profile_dir": str(profile_dir),
                "project_url": project_url,
                "status": "active",
                "credits": credits,
                "total_generated": 0,
                "last_used_at": now,
                "exhausted_at": None,
                "auto_reset_hours": 24
            }
            data["accounts"].append(new_acc)
            log.info("Added new account %s to pool: %s (Email: %s)", account_id, name, email)

        self.save_data(data)

    def delete_account(self, account_id: str):
        data = self.load_data()
        data["accounts"] = [a for a in data.get("accounts", []) if a["id"] != account_id]
        self.save_data(data)
        log.info("Deleted account %s from pool", account_id)
