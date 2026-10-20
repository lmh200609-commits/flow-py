#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Flow Video Generation Client
Reads configuration from environment variables or local config.json.
"""

import sys
import os
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

CONFIG_FILE = Path.home() / ".codex" / "google_flow_config.json"

def get_config():
    # 1. Environment variables
    url = os.environ.get("FLOW_GATEWAY_URL")
    key = os.environ.get("FLOW_API_KEY")

    # 2. Local config file
    if (not url or not key) and CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            url = url or data.get("gateway_url")
            key = key or data.get("api_key")
        except Exception:
            pass

    # 3. Defaults
    url = url or "http://127.0.0.1:8765"
    key = key or "sk-flow-84049243d7bd02b5f3c17e9041e073ec"
    return url.rstrip("/"), key

def request_json(url, method="GET", data=None, headers=None):
    req_headers = {"User-Agent": "Codex-Flow-Plugin/1.0.0"}
    if headers:
        req_headers.update(headers)
    req_data = None
    if data is not None:
        req_data = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=req_data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        try:
            err_json = json.loads(body)
            raise RuntimeError(f"HTTP {e.code}: {err_json.get('detail') or body}")
        except Exception:
            raise RuntimeError(f"HTTP {e.code}: {body}")
    except Exception as e:
        raise RuntimeError(f"网络连接错误: {e}")

def main():
    if len(sys.argv) < 2:
        print("Usage: flow_generate.py <prompt> [aspect_ratio]")
        sys.exit(1)

    prompt = sys.argv[1]
    aspect_ratio = sys.argv[2] if len(sys.argv) > 2 else "16:9"

    gateway_url, api_key = get_config()

    # 1. Submit task
    submit_url = f"{gateway_url}/v1/video/generations"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "prompt": prompt,
        "model": "Veo 3.1 - Fast",
        "aspect_ratio": aspect_ratio
    }

    print(f"[1/3] 正在向视频中转站提交任务: '{prompt}'...")
    try:
        res = request_json(submit_url, method="POST", data=payload, headers=headers)
    except Exception as e:
        print(f"❌ 提交失败: {e}", file=sys.stderr)
        sys.exit(1)

    task_id = res.get("task_id")
    if not task_id:
        print(f"❌ 未能获取 task_id: {res}", file=sys.stderr)
        sys.exit(1)

    print(f"[2/3] 任务已进入调度队列 (ID: {task_id})，正在调度 Google Pro 号池渲染...")

    # 2. Poll for completion
    query_url = f"{gateway_url}/v1/video/generations/{task_id}"
    start_time = time.time()
    download_url = None
    preview_url = None
    local_path = None

    while time.time() - start_time < 200:
        time.sleep(4)
        try:
            status_res = request_json(query_url, method="GET", headers=headers)
            status = status_res.get("status")
            if status == "SUCCESS":
                download_url = status_res.get("download_url") or status_res.get("video_url")
                preview_url = status_res.get("preview_url")
                local_path = status_res.get("local_video_path")
                break
            elif status == "FAILED":
                err = status_res.get("error_message") or "未知错误"
                print(f"❌ 视频生成失败: {err}", file=sys.stderr)
                sys.exit(1)
            else:
                elapsed = int(time.time() - start_time)
                print(f"  - 渲染生成中... 已等待 {elapsed}s")
        except Exception as e:
            print(f"  - 状态轮询重试中: {e}")

    if not download_url and not local_path:
        print("❌ 任务执行超时 (180s)，请稍后检查网关状态。", file=sys.stderr)
        sys.exit(1)

    # Output machine-friendly and human-friendly JSON
    out = {
        "success": True,
        "task_id": task_id,
        "prompt": prompt,
        "video_url": download_url,
        "local_path": local_path,
        "preview_url": preview_url
    }
    print("[3/3] 🎉 视频生成完毕！")
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
