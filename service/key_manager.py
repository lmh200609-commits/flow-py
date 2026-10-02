import json
import logging
import secrets
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

log = logging.getLogger("key_manager")

BASE_FLOW_DIR = Path.home() / ".flow-py"
KEYS_FILE = BASE_FLOW_DIR / "api_keys.json"

class KeyManager:
    _instance: Optional["KeyManager"] = None

    def __init__(self):
        BASE_FLOW_DIR.mkdir(parents=True, exist_ok=True)
        self.keys_file = KEYS_FILE
        self._init_default_keys()

    @classmethod
    def get_instance(cls) -> "KeyManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _init_default_keys(self):
        """Create a default master key if no keys exist."""
        if not self.keys_file.exists():
            default_key_val = "sk-flow-" + secrets.token_hex(16)
            default_key = {
                "id": "key_01",
                "name": "默认主密钥 (Default Master)",
                "key": default_key_val,
                "quota": -1,
                "used_credits": 0,
                "total_calls": 0,
                "status": "active",
                "created_at": int(time.time()),
                "last_used_at": None
            }
            self.save_data({"keys": [default_key]})
            log.info("Initialized default API key: %s", default_key_val)

    def load_data(self) -> Dict[str, Any]:
        if not self.keys_file.exists():
            self._init_default_keys()
        try:
            with open(self.keys_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error("Failed to read api_keys.json: %s", e)
            return {"keys": []}

    def save_data(self, data: Dict[str, Any]):
        with open(self.keys_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def list_keys(self) -> List[Dict[str, Any]]:
        return self.load_data().get("keys", [])

    def create_key(self, name: str, quota: int = -1) -> Dict[str, Any]:
        data = self.load_data()
        keys = data.get("keys", [])
        next_idx = len(keys) + 1
        key_id = f"key_{next_idx:02d}"
        key_val = "sk-flow-" + secrets.token_hex(16)
        
        new_entry = {
            "id": key_id,
            "name": name.strip() or f"API Key #{next_idx}",
            "key": key_val,
            "quota": quota,
            "used_credits": 0,
            "total_calls": 0,
            "status": "active",
            "created_at": int(time.time()),
            "last_used_at": None
        }
        keys.append(new_entry)
        data["keys"] = keys
        self.save_data(data)
        log.info("Created new API key %s (%s)", key_id, name)
        return new_entry

    def validate_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Validate if key exists, is active, and has sufficient quota."""
        if not api_key:
            return None
        # Support raw key or with Bearer prefix
        token = api_key.replace("Bearer ", "").strip()
        data = self.load_data()
        for k in data.get("keys", []):
            if k["key"] == token:
                if k.get("status") != "active":
                    return None
                # Check quota
                if k.get("quota", -1) != -1:
                    if k.get("used_credits", 0) >= k["quota"]:
                        return None
                return k
        return None

    def record_usage(self, api_key: str, credits_used: int = 10):
        token = api_key.replace("Bearer ", "").strip()
        data = self.load_data()
        for k in data.get("keys", []):
            if k["key"] == token:
                k["used_credits"] = k.get("used_credits", 0) + credits_used
                k["total_calls"] = k.get("total_calls", 0) + 1
                k["last_used_at"] = int(time.time())
                break
        self.save_data(data)

    def delete_key(self, key_id: str):
        data = self.load_data()
        data["keys"] = [k for k in data.get("keys", []) if k["id"] != key_id]
        self.save_data(data)

    def toggle_key(self, key_id: str):
        data = self.load_data()
        for k in data.get("keys", []):
            if k["id"] == key_id:
                k["status"] = "disabled" if k.get("status") == "active" else "active"
                break
        self.save_data(data)
