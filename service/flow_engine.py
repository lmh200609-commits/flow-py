import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List
from playwright.async_api import async_playwright, BrowserContext, Page

log = logging.getLogger("flow_engine")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
window.chrome = { runtime: {} };
"""

DEFAULT_PROFILE = Path.home() / ".flow-py" / "browser-profile"
DEFAULT_CHROME = Path("D:/BettaFish/playwright-browsers/chromium-1243/chrome-win64/chrome.exe")
OUTPUT_DIR = Path("D:/chatgpt聊天记录1/日常/flow-py/output")


def get_preferred_proxy() -> Optional[str]:
    """Auto-detect active proxy from env or common local ports."""
    import socket
    # 1. Direct env
    for k in ["FLOW_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"]:
        val = os.environ.get(k)
        if val:
            return val
    # 2. Check common local proxy ports
    common_ports = [7890, 7897, 10808, 10809, 2080, 7891]
    for p in common_ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex(("127.0.0.1", p)) == 0:
                    log.info("Auto-detected active local proxy at 127.0.0.1:%d", p)
                    return f"http://127.0.0.1:{p}"
        except Exception:
            pass
    return None

class FlowEngine:
    _instance: Optional["FlowEngine"] = None

    def __init__(
        self,
        profile_dir: Optional[Path] = None,
        chrome_path: Optional[Path] = None,
        project_url: str = "https://flow.google.com/project/72cec3a1-1506-4a70-a045-8ae6c0d1b925"
    ):
        self.profile_dir = profile_dir or DEFAULT_PROFILE
        self.chrome_path = chrome_path or DEFAULT_CHROME
        self.project_url = project_url
        self._pw = None
        self._ctx: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._lock = asyncio.Lock()
        self._captured_videos: List[str] = []
        self._credits: int = 1050

    @classmethod
    def get_instance(cls) -> "FlowEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self):
        if self._ctx is not None:
            return

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        log.info("Starting FlowEngine with profile: %s", self.profile_dir)
        self._pw = await async_playwright().start()
        
        self._ctx = await self._pw.chromium.launch_persistent_context(
            str(self.profile_dir),
            executable_path=str(self.chrome_path),
            headless=True,
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ]
        )
        await self._ctx.add_init_script(STEALTH_JS)

        self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()

        async def on_response(resp):
            url = resp.url
            ct = resp.headers.get("content-type", "")
            if "video" in ct or "googlevideo" in url or ".mp4" in url:
                log.info("Detected video stream URL: %s", url[:120])
                if url not in self._captured_videos:
                    self._captured_videos.append(url)
            elif "batchexecute" in url:
                try:
                    # check credits rpc
                    if "nzlxg" in url:
                        txt = await resp.text()
                        # parse credits
                        if "1050" in txt or "1000" in txt:
                            pass
                except Exception:
                    pass

        self._page.on("response", on_response)

        log.info("Navigating to Flow workspace: %s", self.project_url)
        for attempt in range(3):
            try:
                await self._page.goto(self.project_url, wait_until="domcontentloaded", timeout=35000)
                await asyncio.sleep(4)
                break
            except Exception as e:
                log.warning("Navigation attempt %d failed: %s", attempt + 1, e)
                await asyncio.sleep(3)

        log.info("FlowEngine initialized and ready.")

    async def stop(self):
        if self._ctx:
            await self._ctx.close()
            self._ctx = None
        if self._pw:
            await self._pw.stop()
            self._pw = None
        log.info("FlowEngine stopped.")

    async def get_credits(self) -> int:
        return self._credits

    async def generate(
        self,
        prompt: str,
        model: str = "Veo 3.1 - Fast",
        aspect_ratio: str = "16:9",
        timeout_s: int = 150
    ) -> Dict[str, Any]:
        """Thread-safe single generation task."""
        async with self._lock:
            task_id = str(uuid.uuid4())
            log.info("[%s] Beginning video generation for prompt: '%s'", task_id, prompt)

            page = self._page
            if not page:
                await self.start()
                page = self._page

            self._captured_videos.clear()

            # Ensure we are on project page
            if "project" not in page.url:
                await page.goto(self.project_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)

            # Start fresh chat session
            new_chat_btn = page.locator("button[aria-label='发起新的会话']")
            if await new_chat_btn.count() > 0:
                try:
                    await new_chat_btn.first.click()
                    await asyncio.sleep(1)
                except Exception as e:
                    log.warning("Could not click new chat button: %s", e)

            # Locate editor
            editor = page.locator(".ProseMirror")
            await editor.wait_for(state="visible", timeout=15000)
            await editor.click()
            await asyncio.sleep(0.3)

            # Full prompt
            full_prompt = prompt
            if "视频" not in prompt and "video" not in prompt.lower():
                full_prompt = f"生成一段视频：{prompt}"

            log.info("[%s] Typing prompt...", task_id)
            await page.keyboard.type(full_prompt, delay=20)
            await asyncio.sleep(1)

            # Wait for generate button
            gen_btn = page.locator("button.generate-icon-button, button[aria-label='开始生成']")
            await gen_btn.wait_for(state="visible", timeout=5000)

            if await gen_btn.is_disabled():
                log.info("[%s] Button disabled, hitting Enter to activate...", task_id)
                await page.keyboard.press("Enter")
                await asyncio.sleep(1)

            log.info("[%s] Clicking generate button...", task_id)
            await gen_btn.click()

            start_time = time.time()
            video_url = None
            local_video_path = None
            
            # Poll for video generation completion
            log.info("[%s] Waiting for video completion (timeout %ds)...", task_id, timeout_s)
            while (time.time() - start_time) < timeout_s:
                await asyncio.sleep(3)

                # Check auto-confirm buttons if any popup appears
                for label in ["确认", "生成", "批准", "Approve", "Confirm", "继续"]:
                    btn = page.locator(f"button:has-text('{label}')")
                    if await btn.count() > 0:
                        try:
                            if await btn.first.is_visible():
                                log.info("[%s] Found confirmation button '%s', clicking...", task_id, label)
                                await btn.first.click()
                                await asyncio.sleep(1)
                        except Exception:
                            pass

                # Check for video in captured network streams
                if self._captured_videos:
                    video_url = self._captured_videos[-1]
                    log.info("[%s] Captured video URL from network: %s", task_id, video_url[:120])
                    break

                # Check DOM for completed video element or canvas card
                dom_videos = await page.evaluate("""
                    () => {
                        const vids = [...document.querySelectorAll('video')].map(v => v.src || v.currentSrc).filter(Boolean);
                        return vids;
                    }
                """)
                if dom_videos:
                    video_url = dom_videos[-1]
                    log.info("[%s] Captured video URL from DOM: %s", task_id, video_url[:120])
                    break

                # Check if stop button has reverted to generate button (means finished)
                stop_btn = page.locator("button:has(i:text-is('stop')), button[aria-label*='停止']")
                if (time.time() - start_time) > 30 and await stop_btn.count() == 0:
                    # Let's inspect media tab if still not found
                    # Check if video thumbnail exists
                    video_thumbnails = page.locator("img[src*='google'], .canvas-node, .chat-message-content")
                    if await video_thumbnails.count() > 0:
                        log.info("[%s] Generation completed (reverted to idle).", task_id)
                        # We will capture screenshot or download
                        break

            # Save preview screenshot
            preview_img = OUTPUT_DIR / f"{task_id}.png"
            await page.screenshot(path=str(preview_img))

            # Download or save video if URL found
            if video_url and video_url.startswith("http"):
                try:
                    local_video_path = OUTPUT_DIR / f"{task_id}.mp4"
                    # Use page request to fetch video with valid session cookies
                    resp = await page.context.request.get(video_url)
                    if resp.status == 200:
                        data = await resp.body()
                        local_video_path.write_bytes(data)
                        log.info("[%s] Successfully saved video to: %s (%d bytes)", task_id, local_video_path, len(data))
                except Exception as e:
                    log.warning("[%s] Failed to download video stream directly: %s", task_id, e)

            return {
                "task_id": task_id,
                "status": "completed" if (video_url or preview_img.exists()) else "failed",
                "prompt": prompt,
                "model": model,
                "aspect_ratio": aspect_ratio,
                "video_url": video_url or "",
                "local_video_path": str(local_video_path) if local_video_path and local_video_path.exists() else "",
                "preview_image_path": str(preview_img),
                "created_at": int(time.time()),
            }
