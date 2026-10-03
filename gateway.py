import asyncio
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, BackgroundTasks, HTTPException, Header, Query, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# Ensure project root in sys.path
BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from service.flow_engine import OUTPUT_DIR
from service.pool_manager import AccountPoolManager, PROFILES_DIR
from service.pool_engine import PoolEngine
from service.key_manager import KeyManager
from account_manager import CHROME_PATH

LOG_FILE = BASE_DIR / "gateway.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("gateway")

app = FastAPI(
    title="Google Flow (Veo 3.1) Video Gateway - Account Pool Edition",
    description="Multi-Account Pool Reverse Proxy Gateway for Google Flow AI Video Generation with Auto Failover",
    version="2.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount output folder for static access
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(OUTPUT_DIR)), name="files")

# In-memory tracking
TASKS: Dict[str, Dict[str, Any]] = {}
TASK_QUEUE: Optional[asyncio.Queue] = None

def get_task_queue() -> asyncio.Queue:
    global TASK_QUEUE
    if TASK_QUEUE is None:
        TASK_QUEUE = asyncio.Queue()
    return TASK_QUEUE
AUTH_SESSIONS: Dict[str, Dict[str, Any]] = {}


security = HTTPBearer(auto_error=False)

def verify_api_key(
    req: Request,
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security),
    api_key_query: Optional[str] = Query(None, alias="api_key"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
) -> Optional[Dict[str, Any]]:
    """Verify API Key for public/external access."""
    km = KeyManager.get_instance()
    keys = km.list_keys()
    
    # If no keys exist at all, allow access
    if not keys:
        return {"id": "open", "name": "Open", "quota": -1}

    # Extract token
    token = None
    if auth and auth.credentials:
        token = auth.credentials
    elif x_api_key:
        token = x_api_key
    elif api_key_query:
        token = api_key_query
    else:
        auth_hdr = req.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            token = auth_hdr[7:].strip()
        elif auth_hdr:
            token = auth_hdr.strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail={"error": {"message": "Missing API key in Authorization header. Format: Bearer sk-flow-...", "type": "auth_error"}}
        )

    matched = km.validate_key(token)
    if not matched:
        raise HTTPException(
            status_code=403,
            detail={"error": {"message": "Invalid or expired API Key, or credit quota exceeded.", "type": "auth_error"}}
        )

    return matched

class VideoGenerationRequest(BaseModel):
    prompt: str = Field(..., description="Prompt describing the video to generate")
    model: str = Field("Veo 3.1 - Fast", description="Model name (e.g. Veo 3.1 - Fast, Veo 3.1 - Quality, Veo 3.1 - Lite, Omni 1.1 Flash)")
    aspect_ratio: str = Field("16:9", description="Video aspect ratio: 16:9 or 9:16")
    wait: bool = Field(False, description="Whether to wait synchronously until completion")
    timeout_s: int = Field(150, description="Max waiting time in seconds")

class VideoTaskResponse(BaseModel):
    task_id: str
    status: str
    prompt: str
    model: str
    aspect_ratio: str
    created_at: int
    video_url: Optional[str] = None
    local_video_path: Optional[str] = None
    preview_url: Optional[str] = None
    download_url: Optional[str] = None
    used_account: Optional[str] = None
    check_url: str

class AccountActionRequest(BaseModel):
    id: str

class ImportCookiesRequest(BaseModel):
    project_url: str
    cookies: List[Dict[str, Any]]
    name: Optional[str] = ""
    email: Optional[str] = None

class UpdateAccountRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None

async def worker_loop():
    """Background worker that continuously processes tasks using PoolEngine with failover."""
    pool_engine = PoolEngine.get_instance()
    log.info("PoolEngine background worker loop initialized.")

    while True:
        try:
            q = get_task_queue()
            task = await q.get()
            task_id = task["task_id"]
            prompt = task["prompt"]
            model = task["model"]
            aspect_ratio = task["aspect_ratio"]
            timeout_s = task.get("timeout_s", 150)

            TASKS[task_id]["status"] = "processing"
            TASKS[task_id]["started_at"] = int(time.time())
            log.info("Worker starting task: %s (prompt: '%s')", task_id, prompt)

            try:
                res = await pool_engine.generate_with_failover(
                    prompt=prompt,
                    model=model,
                    aspect_ratio=aspect_ratio,
                    timeout_s=timeout_s
                )
                TASKS[task_id].update(res)
                TASKS[task_id]["status"] = res.get("status", "completed")
                
                # generate web download urls
                if res.get("local_video_path") and Path(res["local_video_path"]).exists():
                    fn = Path(res["local_video_path"]).name
                    TASKS[task_id]["download_url"] = f"http://127.0.0.1:8765/files/{fn}"
                if res.get("preview_image_path") and Path(res["preview_image_path"]).exists():
                    fn = Path(res["preview_image_path"]).name
                    TASKS[task_id]["preview_url"] = f"http://127.0.0.1:8765/files/{fn}"

                log.info("Worker finished task: %s using account [%s] with status %s",
                         task_id, res.get("used_account"), TASKS[task_id]["status"])
            except Exception as e:
                log.exception("Error processing task %s: %s", task_id, e)
                TASKS[task_id]["status"] = "failed"
                TASKS[task_id]["error"] = str(e)
            finally:
                TASK_QUEUE.task_done()
        except Exception as e:
            log.error("Worker loop exception: %s", e)
            await asyncio.sleep(2)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(worker_loop())

@app.on_event("shutdown")
async def shutdown_event():
    pool_engine = PoolEngine.get_instance()
    await pool_engine.stop_all()

# ── Web Console ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
@app.get("/capture", response_class=HTMLResponse)
async def serve_capture_page():
    html_file = BASE_DIR / "templates" / "capture.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Capture page template not found</h1>")

# ── OAuth Style Flow Capture ─────────────────────────────────────────────────

async def _run_oauth_task(auth_id: str, acc_id: str, name: str):
    from playwright.async_api import async_playwright
    mgr = AccountPoolManager.get_instance()
    target_profile = PROFILES_DIR / acc_id
    target_profile.mkdir(parents=True, exist_ok=True)
    captured_project_url = None

    try:
        log.info("[%s] Launching interactive Chrome for OAuth flow...", auth_id)
        async with async_playwright() as p:
            ctx = await p.chromium.launch_persistent_context(
                str(target_profile),
                executable_path=CHROME_PATH,
                headless=False,
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
            await page.goto("https://flow.google.com/")

            # Wait up to 180 seconds for user to sign in
            for _ in range(36):
                await asyncio.sleep(5)
                cur_url = page.url
                if "flow.google.com/project/" in cur_url:
                    captured_project_url = cur_url
                    log.info("[%s] Detected project URL: %s", auth_id, cur_url)
                    break

            await asyncio.sleep(3)
            await ctx.close()

        if captured_project_url:
            mgr.add_account(
                account_id=acc_id,
                name=name,
                profile_dir=str(target_profile),
                project_url=captured_project_url,
                credits=1050
            )
            AUTH_SESSIONS[auth_id] = {
                "status": "success",
                "account": {"id": acc_id, "name": name, "project_url": captured_project_url}
            }
            log.info("[%s] OAuth completed successfully for %s", auth_id, acc_id)
        else:
            AUTH_SESSIONS[auth_id] = {"status": "failed", "message": "登录超时，未检测到进入项目工作区"}
    except Exception as e:
        log.exception("[%s] OAuth error: %s", auth_id, e)
        AUTH_SESSIONS[auth_id] = {"status": "failed", "message": str(e)}

@app.post("/api/pool/start-oauth")
async def start_oauth_endpoint():
    mgr = AccountPoolManager.get_instance()
    accounts = mgr.list_accounts()
    next_idx = len(accounts) + 1
    acc_id = f"acc_{next_idx:02d}"
    name = f"Gemini Pro {next_idx}号"
    auth_id = str(uuid.uuid4())

    AUTH_SESSIONS[auth_id] = {"status": "waiting", "acc_id": acc_id, "name": name}
    asyncio.create_task(_run_oauth_task(auth_id, acc_id, name))
    return {"status": "started", "auth_id": auth_id, "acc_index": next_idx}

@app.get("/api/pool/oauth-status/{auth_id}")
async def get_oauth_status_endpoint(auth_id: str):
    if auth_id not in AUTH_SESSIONS:
        raise HTTPException(status_code=404, detail="Auth session not found")
    return AUTH_SESSIONS[auth_id]

# ── Extension One-Click Cookies Import ────────────────────────────────────────

@app.post("/api/pool/import-cookies")
async def import_cookies_endpoint(req: ImportCookiesRequest):
    """Directly import cookies from the user's active Chrome browser extension."""
    mgr = AccountPoolManager.get_instance()
    
    # Check if matching account exists by email
    existing_acc = mgr.find_account_by_email(req.email) if req.email else None
    if existing_acc:
        acc_id = existing_acc["id"]
        target_profile = Path(existing_acc["profile_dir"])
        name = req.name or existing_acc.get("name") or f"Gemini Pro ({req.email})"
    else:
        accounts = mgr.list_accounts()
        next_idx = len(accounts) + 1
        acc_id = f"acc_{next_idx:02d}"
        name = req.name or (f"Gemini Pro ({req.email})" if req.email else f"Gemini Pro {next_idx}号")
        target_profile = PROFILES_DIR / acc_id

    target_profile.mkdir(parents=True, exist_ok=True)

    # Save cookies to profile
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(target_profile),
            executable_path=CHROME_PATH,
            headless=True,
            viewport={"width": 1440, "height": 900},
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        # Format cookies for playwright
        pw_cookies = []
        for c in req.cookies:
            dom = c.get("domain", "")
            # Ensure domain starts with . or is valid
            item = {
                "name": c["name"],
                "value": c["value"],
                "domain": dom,
                "path": c.get("path", "/")
            }
            if c.get("secure") is not None:
                item["secure"] = bool(c["secure"])
            if c.get("httpOnly") is not None:
                item["httpOnly"] = bool(c["httpOnly"])
            if c.get("expires") and c["expires"] > 0:
                item["expires"] = float(c["expires"])
            pw_cookies.append(item)

        try:
            await ctx.add_cookies(pw_cookies)
        except Exception as e:
            log.warning("Could not add some cookies: %s", e)

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        target_url = req.project_url if "project" in req.project_url else "https://flow.google.com/"
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            final_url = page.url
        except Exception:
            final_url = req.project_url or "https://flow.google.com/"
        await ctx.close()

    mgr.add_account(
        account_id=acc_id,
        name=name,
        profile_dir=str(target_profile),
        project_url=final_url if "project" in final_url else "https://flow.google.com/",
        credits=1050,
        email=req.email
    )
    log.info("Successfully imported account %s via extension cookies! Email: %s, Target: %s", acc_id, req.email, final_url)
    return {"status": "ok", "account": {"id": acc_id, "name": name, "email": req.email, "project_url": final_url}}

@app.post("/api/pool/accounts/{account_id}/update")
async def update_account_endpoint(account_id: str, req: UpdateAccountRequest):
    mgr = AccountPoolManager.get_instance()
    updates = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.email is not None:
        updates["email"] = req.email
        if not req.name:
            updates["name"] = f"Gemini Pro ({req.email})"
    mgr.update_account(account_id, updates)
    return {"status": "ok", "account_id": account_id}

@app.delete("/api/pool/accounts/{account_id}")
async def delete_account_endpoint(account_id: str):
    mgr = AccountPoolManager.get_instance()
    mgr.delete_account(account_id)
    return {"status": "ok", "deleted": account_id}
# ── Health & Pool APIs ───────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    mgr = AccountPoolManager.get_instance()
    accounts = mgr.list_accounts()
    active_count = len([a for a in accounts if a.get("status") == "active"])
    return {
        "status": "ok",
        "service": "Google Flow (Veo 3.1) Pool Gateway",
        "queue_size": get_task_queue().qsize(),
        "total_accounts": len(accounts),
        "active_accounts": active_count,
        "timestamp": int(time.time())
    }

@app.get("/v1/pool/accounts")
async def get_pool_accounts():
    mgr = AccountPoolManager.get_instance()
    accounts = mgr.list_accounts()
    return {
        "object": "list",
        "total": len(accounts),
        "accounts": accounts
    }

@app.post("/api/pool/reset")
async def reset_account_endpoint(req: AccountActionRequest):
    mgr = AccountPoolManager.get_instance()
    data = mgr.load_data()
    found = False
    for a in data.get("accounts", []):
        if a["id"] == req.id:
            a["status"] = "active"
            a["exhausted_at"] = None
            a["credits"] = 1050
            found = True
            break
    if found:
        mgr.save_data(data)
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Account not found")

@app.post("/api/pool/delete")
async def delete_account_endpoint(req: AccountActionRequest):
    mgr = AccountPoolManager.get_instance()
    data = mgr.load_data()
    data["accounts"] = [a for a in data.get("accounts", []) if a["id"] != req.id]
    mgr.save_data(data)
    return {"status": "ok"}

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": "Veo 3.1 - Fast", "type": "video", "owned_by": "google", "description": "Fast cinematic generation"},
            {"id": "Veo 3.1 - Quality", "type": "video", "owned_by": "google", "description": "Highest quality cinematic details"},
            {"id": "Veo 3.1 - Lite", "type": "video", "owned_by": "google", "description": "Lightweight video model"},
            {"id": "Omni 1.1 Flash", "type": "video", "owned_by": "google", "description": "Omni multimodal video model"},
            {"id": "Nano Banana 2", "type": "image", "owned_by": "google", "description": "High fidelity image generation"}
        ]
    }

@app.get("/v1/credits")
async def get_total_credits():
    mgr = AccountPoolManager.get_instance()
    accounts = mgr.list_accounts()
    total_credits = sum(a.get("credits", 0) for a in accounts if a.get("status") == "active")
    return {
        "tier": "PRO_POOL",
        "total_active_credits": total_credits,
        "active_account_count": len([a for a in accounts if a.get("status") == "active"]),
        "updated_at": int(time.time())
    }

# ── Video Generation APIs ────────────────────────────────────────────────────

@app.post("/v1/video/generations", response_model=VideoTaskResponse)
async def create_video_task(
    req: VideoGenerationRequest,
    key_info: Optional[Dict[str, Any]] = Depends(verify_api_key)
):
    task_id = str(uuid.uuid4())
    task_data = {
        "task_id": task_id,
        "status": "queued",
        "prompt": req.prompt,
        "model": req.model,
        "aspect_ratio": req.aspect_ratio,
        "timeout_s": req.timeout_s,
        "created_at": int(time.time()),
        "api_key": key_info.get("key") if key_info else None,
        "key_id": key_info.get("id") if key_info else None,
        "video_url": None,
        "local_video_path": None,
        "preview_url": None,
        "download_url": None,
        "used_account": None,
        "check_url": f"http://127.0.0.1:8765/v1/video/status/{task_id}"
    }
    TASKS[task_id] = task_data
    q = get_task_queue()
    await q.put(task_data)

    if req.wait:
        start = time.time()
        while (time.time() - start) < req.timeout_s:
            await asyncio.sleep(2)
            cur = TASKS[task_id]
            if cur["status"] in ["completed", "failed"]:
                return cur
        return TASKS[task_id]

    return task_data

@app.get("/v1/video/status/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="Task ID not found")
    return TASKS[task_id]

@app.post("/v1/video/generate_sync")
async def generate_sync(req: VideoGenerationRequest):
    req.wait = True
    return await create_video_task(req)




# ── API Key Management Endpoints ──────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    name: str = ""
    quota: int = -1  # -1 means unlimited

@app.get("/api/keys")
async def list_keys_endpoint():
    km = KeyManager.get_instance()
    return {"object": "list", "keys": km.list_keys()}

@app.post("/api/keys")
async def create_key_endpoint(req: CreateKeyRequest):
    km = KeyManager.get_instance()
    new_key = km.create_key(name=req.name, quota=req.quota)
    return {"status": "ok", "key": new_key}

@app.delete("/api/keys/{key_id}")
async def delete_key_endpoint(key_id: str):
    km = KeyManager.get_instance()
    km.delete_key(key_id)
    return {"status": "ok", "deleted": key_id}

@app.post("/api/keys/{key_id}/toggle")
async def toggle_key_endpoint(key_id: str):
    km = KeyManager.get_instance()
    km.toggle_key(key_id)
    return {"status": "ok", "key_id": key_id}

# ── OpenAI Compatible Endpoints ──────────────────────────────────────────

@app.get("/v1/models")
async def list_openai_models():
    """OpenAI standard /v1/models endpoint for universal Agent discovery."""
    return {
        "object": "list",
        "data": [
            {"id": "veo-3.1", "object": "model", "created": int(time.time()), "owned_by": "google-flow"},
            {"id": "veo-3.1-fast", "object": "model", "created": int(time.time()), "owned_by": "google-flow"},
            {"id": "veo-3.1-quality", "object": "model", "created": int(time.time()), "owned_by": "google-flow"},
            {"id": "google-flow-video", "object": "model", "created": int(time.time()), "owned_by": "google-flow"}
        ]
    }

@app.get("/v1/video/generations/{task_id}")
async def get_video_generation_by_id(task_id: str):
    """Standard video query endpoint matching /v1/video/generations/{task_id}."""
    return await get_task_status(task_id)

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str = "veo-3.1"
    messages: List[ChatMessage]
    stream: bool = False

@app.post("/v1/chat/completions")
async def chat_completions_fallback(
    req: ChatCompletionRequest,
    key_info: Optional[Dict[str, Any]] = Depends(verify_api_key)
):
    """
    OpenAI Chat Completions adapter for traditional LLM Agents (e.g. Dify, FastGPT, NextChat).
    Extracts the user's prompt, submits video generation, waits for completion, and returns the result.
    """
    # Extract last user message
    user_prompt = ""
    for m in reversed(req.messages):
        if m.role == "user" and m.content:
            user_prompt = m.content.strip()
            break
    if not user_prompt:
        raise HTTPException(status_code=400, detail="No user message found in request")

    # Create video task and wait synchronously
    task_id = str(uuid.uuid4())
    task_data = {
        "task_id": task_id,
        "status": "queued",
        "prompt": user_prompt,
        "model": "Veo 3.1 - Fast",
        "aspect_ratio": "16:9",
        "timeout_s": 150,
        "created_at": int(time.time()),
        "api_key": key_info.get("key") if key_info else None,
        "key_id": key_info.get("id") if key_info else None,
        "video_url": None,
        "local_video_path": None,
        "preview_url": None,
        "download_url": None,
        "used_account": None,
        "check_url": f"http://127.0.0.1:8765/v1/video/status/{task_id}"
    }
    TASKS[task_id] = task_data
    await TASK_QUEUE.put(task_data)

    # Wait for completion (up to 150s)
    start_t = time.time()
    while time.time() - start_t < 150:
        await asyncio.sleep(2)
        cur = TASKS.get(task_id, {})
        status = cur.get("status")
        if status in ["SUCCESS", "FAILED"]:
            break

    final_task = TASKS.get(task_id, {})
    if final_task.get("status") == "SUCCESS":
        vid_url = final_task.get("download_url") or final_task.get("preview_url") or final_task.get("video_url")
        content_text = f"🎬 **Google Flow (Veo 3.1) 视频已生成成功！**\n\n- **提示词**: {user_prompt}\n- **调度账号**: {final_task.get('used_account')}\n- **视频链接**: [点击下载/播放]({vid_url})"
    else:
        err = final_task.get("error_message") or "生成超时或账号调度失败"
        content_text = f"❌ 视频生成失败: {err}"

    return {
        "id": f"chatcmpl-{task_id[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content_text
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": len(user_prompt),
            "completion_tokens": len(content_text),
            "total_tokens": len(user_prompt) + len(content_text)
        }
    }


@app.get("/api/debug/current_render")
async def debug_current_render():
    pe = PoolEngine.get_instance()
    eng = pe._engines.get("acc_01")
    if not eng or not eng._page:
        return {"status": "no_active_engine", "active_engines": list(pe._engines.keys())}
    page = eng._page
    
    # Evaluate current page state
    state = await page.evaluate("""() => {
        const text = document.body ? document.body.innerText : "";
        const m = text.match(/(\\d{1,3})%/);
        const videos = Array.from(document.querySelectorAll('video')).map(v => v.src);
        return {
            percent: m ? m[1] : null,
            videoSrcs: videos.filter(Boolean),
            url: window.location.href
        };
    }""")
    
    # Save a fresh screenshot
    shot_path = OUTPUT_DIR / "live_render_status.png"
    await page.screenshot(path=str(shot_path))
    state["screenshot"] = str(shot_path)
    state["preview_url"] = "http://127.0.0.1:8765/files/live_render_status.png"
    return state

# ── Storyboard & AI Director Pipelines ───────────────────────────────────────
from director.prompt_compiler import PromptCompiler, PromptSpec, ShotType, CameraMovement, LightingStyle, LensGear, ColorGrade
from director.storyboard import StoryboardPlanner, StoryboardPlan, StoryboardShot
from pipeline.ffmpeg_assembler import FFmpegAssembler

STORYBOARDS: Dict[str, Dict[str, Any]] = {}

class CompilePromptRequest(BaseModel):
    subject: str
    genre: str = "sci-fi"
    shot_type: Optional[str] = None
    camera_movement: Optional[str] = None
    lighting: Optional[str] = None
    lens: Optional[str] = None
    color_grade: Optional[str] = None
    style_anchor: Optional[str] = None

class PlanStoryboardRequest(BaseModel):
    title: str = "微电影分镜"
    narrative: str
    genre: str = "sci-fi"
    num_shots: int = 3
    style_anchor: Optional[str] = None
    custom_shots: Optional[List[Dict[str, Any]]] = None

class CreateStoryboardRequest(BaseModel):
    title: str = "微电影分镜"
    narrative: str
    genre: str = "sci-fi"
    num_shots: int = 3
    style_anchor: Optional[str] = None
    custom_shots: Optional[List[Dict[str, Any]]] = None
    transition: str = "fast"  # fast | crossfade
    wait: bool = False

async def _execute_storyboard(sb_id: str, transition: str = "fast"):
    """Background task to sequentially render each shot in storyboard and merge with FFmpeg."""
    sb = STORYBOARDS.get(sb_id)
    if not sb:
        return

    sb["status"] = "rendering"
    log.info("[Storyboard %s] Starting multi-shot production pipeline...", sb_id)
    pool_engine = PoolEngine.get_instance()
    rendered_video_paths: List[Path] = []

    try:
        shots = sb.get("shots", [])
        for idx, shot in enumerate(shots, start=1):
            sb["current_shot_index"] = idx
            shot["status"] = "rendering"
            log.info("[Storyboard %s] Rendering Shot %d/%d: %s", sb_id, idx, len(shots), shot.get("shot_name"))

            # Render single shot
            shot_res = await pool_engine.generate_with_failover(
                prompt=shot["prompt"],
                model="Veo 3.1 - Fast",
                aspect_ratio="16:9",
                timeout_s=150
            )

            shot["status"] = shot_res.get("status", "completed")
            vpath = shot_res.get("local_video_path")
            if vpath and Path(vpath).exists():
                shot["video_path"] = vpath
                shot["video_url"] = f"http://127.0.0.1:8765/files/{Path(vpath).name}"
                rendered_video_paths.append(Path(vpath))
            else:
                log.warning("[Storyboard %s] Shot %d did not produce local video path!", sb_id, idx)

            if shot_res.get("preview_image_path") and Path(shot_res["preview_image_path"]).exists():
                shot["preview_url"] = f"http://127.0.0.1:8765/files/{Path(shot_res['preview_image_path']).name}"

        # All shots rendered, start assembly
        if rendered_video_paths:
            sb["status"] = "assembling"
            log.info("[Storyboard %s] Assembling %d video clips using FFmpeg...", sb_id, len(rendered_video_paths))
            assembler = FFmpegAssembler()
            final_mp4 = OUTPUT_DIR / f"storyboard_{sb_id}_final.mp4"

            if transition == "crossfade" and len(rendered_video_paths) > 1:
                assembler.concat_with_crossfade(rendered_video_paths, final_mp4, transition_duration=0.5, shot_duration=10.0)
            else:
                assembler.concat_fast(rendered_video_paths, final_mp4)

            if final_mp4.exists():
                sb["status"] = "completed"
                sb["final_video_path"] = str(final_mp4)
                sb["final_video_url"] = f"http://127.0.0.1:8765/files/{final_mp4.name}"
                log.info("[Storyboard %s] Successfully assembled master video: %s (Size: %d bytes)",
                         sb_id, final_mp4, final_mp4.stat().st_size)
            else:
                sb["status"] = "failed"
                sb["error"] = "FFmpeg assembly completed but output file not found"
        else:
            sb["status"] = "failed"
            sb["error"] = "No shots produced valid video files"

    except Exception as e:
        log.exception("[Storyboard %s] Failed during production: %s", sb_id, e)
        sb["status"] = "failed"
        sb["error"] = str(e)
    finally:
        sb["updated_at"] = int(time.time())

@app.post("/v1/director/compile_prompt")
async def compile_prompt_endpoint(
    req: CompilePromptRequest,
    key_info: Optional[Dict[str, Any]] = Depends(verify_api_key)
):
    """Compiles a short description into a detailed cinematic prompt for Veo 3.1."""
    enhanced = PromptCompiler.auto_enhance(
        raw_prompt=req.subject,
        genre=req.genre,
        style_anchor=req.style_anchor,
        shot_type=req.shot_type
    )
    return {
        "status": "ok",
        "genre": req.genre,
        "raw_subject": req.subject,
        "compiled_prompt": enhanced
    }

@app.post("/v1/director/plan_storyboard")
async def plan_storyboard_endpoint(
    req: PlanStoryboardRequest,
    key_info: Optional[Dict[str, Any]] = Depends(verify_api_key)
):
    """Generates a structured multi-shot storyboard plan for preview and confirmation."""
    plan = StoryboardPlanner.create_storyboard(
        title=req.title,
        narrative=req.narrative,
        genre=req.genre,
        num_shots=req.num_shots,
        style_anchor=req.style_anchor,
        custom_shots=req.custom_shots
    )
    return plan.to_dict()

@app.post("/v1/storyboard/create")
async def create_storyboard_endpoint(
    req: CreateStoryboardRequest,
    background_tasks: BackgroundTasks,
    key_info: Optional[Dict[str, Any]] = Depends(verify_api_key)
):
    """Initiates an end-to-end multi-shot storyboard production and assembly pipeline."""
    plan = StoryboardPlanner.create_storyboard(
        title=req.title,
        narrative=req.narrative,
        genre=req.genre,
        num_shots=req.num_shots,
        style_anchor=req.style_anchor,
        custom_shots=req.custom_shots
    )
    sb_dict = plan.to_dict()
    sb_dict["transition"] = req.transition
    STORYBOARDS[plan.storyboard_id] = sb_dict

    background_tasks.add_task(_execute_storyboard, plan.storyboard_id, req.transition)

    if req.wait:
        # Wait up to timeout
        start = time.time()
        while time.time() - start < (req.num_shots * 160):
            await asyncio.sleep(3)
            cur = STORYBOARDS.get(plan.storyboard_id, {})
            if cur.get("status") in ["completed", "failed"]:
                return cur
        return STORYBOARDS.get(plan.storyboard_id, {})

    return {
        "storyboard_id": plan.storyboard_id,
        "title": plan.title,
        "num_shots": len(plan.shots),
        "status": "queued",
        "check_url": f"http://127.0.0.1:8765/v1/storyboard/status/{plan.storyboard_id}"
    }

@app.get("/v1/storyboard/status/{storyboard_id}")
async def get_storyboard_status(storyboard_id: str):
    if storyboard_id not in STORYBOARDS:
        raise HTTPException(status_code=404, detail="Storyboard ID not found")
    return STORYBOARDS[storyboard_id]

@app.get("/v1/storyboards")
async def list_storyboards():
    return {
        "object": "list",
        "total": len(STORYBOARDS),
        "storyboards": list(STORYBOARDS.values())
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("gateway:app", host="127.0.0.1", port=8765, reload=False)

