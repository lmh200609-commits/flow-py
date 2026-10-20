#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper script to configure gateway URL and API Key for users.
"""
import sys
import json
from pathlib import Path

CONFIG_FILE = Path.home() / ".codex" / "google_flow_config.json"
CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

def main():
    if len(sys.argv) < 3:
        print("Usage: configure.py <gateway_url> <api_key>")
        if CONFIG_FILE.exists():
            print("Current config:", CONFIG_FILE.read_text(encoding="utf-8"))
        sys.exit(1)

    url = sys.argv[1].rstrip("/")
    key = sys.argv[2]
    cfg = {"gateway_url": url, "api_key": key}
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Google Flow 插件配置已更新！已写入 {CONFIG_FILE}")

if __name__ == "__main__":
    main()
