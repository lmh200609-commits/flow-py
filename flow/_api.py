"""
flow._api — Direct REST API client for Google Flow AI.

All confirmed endpoints via browser reverse engineering (2026-03-06):

  Text → Image  : POST /v1/projects/{id}/flowMedia:batchGenerateImages       (sync)
  Text → Video  : POST /v1/video:batchAsyncGenerateVideoText                 (async)
  Extend Video  : POST /v1/video:batchAsyncGenerateVideoExtendVideo          (async)
  Camera Motion : POST /v1/video:batchAsyncGenerateVideoReshootVideo         (async)
  Insert Object : POST /v1/video:batchAsyncGenerateVideoObjectInsertion      (async)
  Remove Object : POST /v1/video:batchAsyncGenerateVideoObjectRemoval        (async)
  Upscale Video : POST /v1/video:batchAsyncGenerateVideoUpsampleVideo        (async, FREE!)
  Poll Status   : POST /v1/video:batchCheckAsyncVideoGenerationStatus
  Credits       : GET  /v1/credits
  Model Config  : tRPC videoFx.getVideoModelConfig
  App Config    : tRPC videoFx.getFlowAppConfig

All async video calls return immediately with PENDING status.
Poll batchCheckAsyncVideoGenerationStatus until mediaStatus = COMPLETE.

Upscale notes:
  - Model: veo_3_1_upsampler_1080p (cost=0, FREE)
  - Requires extra field: resolution="VIDEO_RESOLUTION_1080P"
  - Response media.name = "{original_id}_upsampled"
  - workflowStepId = "CAk" in response

Camera Position notes (all use ReshootVideo endpoint):
  - Center  = RESHOOT_MOTION_TYPE_STATIONARY          (confirmed via capture)
  - Left    = RESHOOT_MOTION_TYPE_STATIONARY_LEFT
  - Right   = RESHOOT_MOTION_TYPE_STATIONARY_RIGHT
  - High    = RESHOOT_MOTION_TYPE_STATIONARY_HIGHER
  - Low     = RESHOOT_MOTION_TYPE_STATIONARY_LOWER
  - Closer  = RESHOOT_MOTION_TYPE_STATIONARY_CLOSER
  - Further = RESHOOT_MOTION_TYPE_STATIONARY_FURTHER

Remove Object mask format (confirmed via capture):
  - imageMask.imageBytes   = base64-encoded JPEG mask image
  - imageMask.imageUsageType = "IMAGE_USAGE_TYPE_MASK"

Multi-reference video (NEW):
  - Model: veo_3_1_r2v_fast_landscape / veo_3_1_r2v_fast_portrait
  - Use imageInputs with role="REFERENCE_IMAGE"
  - Same endpoint as T2V: batchAsyncGenerateVideoText
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from ._exceptions import (
    AuthError, GenerationError, GenerationTimeout,
    InvalidArgumentError, NotFoundError, FeatureUnavailableError,
)

log = logging.getLogger(__name__)

# ── Base URLs ────────────────────────────────────────────────────────────────
FLOW_BASE = "https://labs.google/fx"
API_BASE  = "https://aisandbox-pa.googleapis.com/v1"

# reCAPTCHA Enterprise site key (from page source)
RECAPTCHA_SITE_KEY = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"

# ── Image models ─────────────────────────────────────────────────────────────
IMAGE_MODEL_NARWHAL  = "NARWHAL"      # Nano Banana 2 / Imagen 3.5 (default)
IMAGE_MODEL_IMAGEN3  = "IMAGEN_3"     # Imagen 3

# ── Image aspect ratios ──────────────────────────────────────────────────────
IMAGE_AR_PORTRAIT  = "IMAGE_ASPECT_RATIO_PORTRAIT"    # 9:16
IMAGE_AR_LANDSCAPE = "IMAGE_ASPECT_RATIO_LANDSCAPE"   # 16:9
IMAGE_AR_SQUARE    = "IMAGE_ASPECT_RATIO_SQUARE"      # 1:1

# ── Video models (videoModelKey field) ───────────────────────────────────────
# Source: videoFx.getVideoModelConfig API (32 active models, 2026-03-06)

# ── Veo 3.1 Text-to-Video (with audio, 20cr fast / 100cr quality) ────────────
VIDEO_MODEL_VEO31_FAST     = "veo_3_1_t2v_fast"           # Veo 3.1 Fast, landscape, 20cr
VIDEO_MODEL_VEO31_FAST_P   = "veo_3_1_t2v_fast_portrait"  # Veo 3.1 Fast, portrait, 20cr
VIDEO_MODEL_VEO31_STD      = "veo_3_1_t2v"                # Veo 3.1 Quality, landscape, 100cr
VIDEO_MODEL_VEO31_STD_P    = "veo_3_1_t2v_portrait"       # Veo 3.1 Quality, portrait, 100cr

# ── Veo 2.1 Text-to-Video (no audio, 10cr) ───────────────────────────────────
VIDEO_MODEL_VEO21_T2V      = "veo_2_1_fast_d_15_t2v"      # Veo 2.1 Fast T2V, landscape, 10cr
VIDEO_MODEL_VEO20_STD      = "veo_2_0_t2v"                # Veo 2.0 Quality, landscape, 100cr

# ── Veo 3.1 Image-to-Video (with audio) ──────────────────────────────────────
VIDEO_MODEL_VEO31_I2V      = "veo_3_1_i2v_s_fast"         # Veo 3.1 Fast I2V, landscape, 20cr
VIDEO_MODEL_VEO31_I2V_P    = "veo_3_1_i2v_s_fast_portrait"# Veo 3.1 Fast I2V, portrait, 20cr
VIDEO_MODEL_VEO31_I2V_STD  = "veo_3_1_i2v_s"              # Veo 3.1 Quality I2V, landscape, 100cr
VIDEO_MODEL_VEO31_I2V_STD_P= "veo_3_1_i2v_s_portrait"     # Veo 3.1 Quality I2V, portrait, 100cr

# ── Veo 2.1 Image-to-Video ───────────────────────────────────────────────────
VIDEO_MODEL_VEO21_I2V      = "veo_2_1_fast_d_15_i2v"      # Veo 2.1 Fast I2V, landscape, 10cr
VIDEO_MODEL_VEO20_I2V_STD  = "veo_2_0_i2v"                # Veo 2.0 Quality I2V, landscape, 100cr

# ── Start+End Frame (Interpolation) ──────────────────────────────────────────
VIDEO_MODEL_VEO31_SE       = "veo_3_1_i2v_s_fast_fl"          # Veo 3.1 Fast, landscape, 20cr
VIDEO_MODEL_VEO31_SE_P     = "veo_3_1_i2v_s_fast_portrait_fl" # Veo 3.1 Fast, portrait, 20cr
VIDEO_MODEL_VEO31_SE_STD   = "veo_3_1_i2v_s_fl"               # Veo 3.1 Quality, landscape, 100cr
VIDEO_MODEL_VEO31_SE_STD_P = "veo_3_1_i2v_s_portrait_fl"      # Veo 3.1 Quality, portrait, 100cr
VIDEO_MODEL_VEO21_SE       = "veo_2_1_fast_d_15_with_start_image_and_end_image_interpolation"  # 10cr

# ── Multi-Reference Video (NEW! MULTI_REFERENCE_NO_STYLE capability) ─────────
VIDEO_MODEL_VEO31_R2V      = "veo_3_1_r2v_fast_landscape"  # Veo 3.1 Fast R2V, landscape, 20cr
VIDEO_MODEL_VEO31_R2V_P    = "veo_3_1_r2v_fast_portrait"   # Veo 3.1 Fast R2V, portrait, 20cr

# ── Extend (confirmed via capture) ───────────────────────────────────────────
VIDEO_MODEL_EXTEND_L       = "veo_3_1_extend_fast_landscape"   # Veo 3.1 Fast, landscape, 20cr
VIDEO_MODEL_EXTEND_P       = "veo_3_1_extend_fast_portrait"    # Veo 3.1 Fast, portrait, 20cr
VIDEO_MODEL_EXTEND_L_STD   = "veo_3_1_extend_landscape"        # Veo 3.1 Quality, landscape, 100cr
VIDEO_MODEL_EXTEND_P_STD   = "veo_3_1_extend_portrait"         # Veo 3.1 Quality, portrait, 100cr
VIDEO_MODEL_VEO21_EXTEND   = "veo_2_1_fast_d_15_with_video_extension"  # Veo 2.1, 10cr

# ── Camera Motion / Reshoot (confirmed via capture) ──────────────────────────
VIDEO_MODEL_RESHOOT_L      = "veo_3_0_reshoot_landscape"   # Reshoot landscape, 20cr
VIDEO_MODEL_RESHOOT_P      = "veo_3_0_reshoot_portrait"    # Reshoot portrait, 20cr

# ── Object Editing (confirmed via capture) ───────────────────────────────────
VIDEO_MODEL_INSERT_L       = "veo_2_0_object_insertion_landscape"  # Insert, landscape, 20cr
VIDEO_MODEL_INSERT_P       = "veo_2_0_object_insertion_portrait"   # Insert, portrait, 20cr
VIDEO_MODEL_REMOVE_L       = "veo_2_0_object_removal_landscape"    # Remove, landscape, 20cr
VIDEO_MODEL_REMOVE_P       = "veo_2_0_object_removal_portrait"     # Remove, portrait, 20cr

# Aliases for backwards compat
VIDEO_MODEL_INSERT         = VIDEO_MODEL_INSERT_L
VIDEO_MODEL_REMOVE         = VIDEO_MODEL_REMOVE_L

# ── Upscaling (NEW! Confirmed via capture 2026-03-06, cost=0 FREE!) ───────────
VIDEO_MODEL_UPSCALER_1080P = "veo_3_1_upsampler_1080p"     # Upscale to 1080p, FREE (0cr)!

# ── Video resolutions (for upscale) ──────────────────────────────────────────
VIDEO_RES_1080P = "VIDEO_RESOLUTION_1080P"
VIDEO_RES_720P  = "VIDEO_RESOLUTION_720P"   # guessed, not yet confirmed

# ── Video aspect ratios ──────────────────────────────────────────────────────
VIDEO_AR_LANDSCAPE = "VIDEO_ASPECT_RATIO_LANDSCAPE"
VIDEO_AR_PORTRAIT  = "VIDEO_ASPECT_RATIO_PORTRAIT"

# ── Image input roles ────────────────────────────────────────────────────────
IMAGE_ROLE_START     = "START_IMAGE"
IMAGE_ROLE_END       = "END_IMAGE"
IMAGE_ROLE_REFERENCE = "REFERENCE_IMAGE"    # for multi-reference (r2v) models
IMAGE_ROLE_END    = "END_IMAGE"

# ── Camera Motion tab — reshootMotionType values (all confirmed via JS bundle) ─
# Source: reshootOptions arrays in _app-e00b42726f621669.js + API captures
RESHOOT_FORWARD          = "RESHOOT_MOTION_TYPE_FORWARD"          # Dolly in
RESHOOT_BACKWARD         = "RESHOOT_MOTION_TYPE_BACKWARD"         # Dolly out (DEPRECATED: was DOLLY_OUT)
RESHOOT_LEFT             = "RESHOOT_MOTION_TYPE_LEFT"             # Orbit left
RESHOOT_RIGHT            = "RESHOOT_MOTION_TYPE_RIGHT"            # Orbit right
RESHOOT_UP               = "RESHOOT_MOTION_TYPE_UP"               # Orbit up
RESHOOT_DOWN             = "RESHOOT_MOTION_TYPE_DOWN"             # Orbit low
RESHOOT_DOLLY_ZOOM_IN    = "RESHOOT_MOTION_TYPE_DOLLY_IN_ZOOM_OUT"   # Dolly in + zoom out ← CORRECTED from bundle
RESHOOT_DOLLY_ZOOM_OUT   = "RESHOOT_MOTION_TYPE_DOLLY_OUT_ZOOM_IN"   # Dolly out + zoom in ← CORRECTED from bundle

# ── Camera Position tab — all 7 position presets (confirmed via JS bundle + Center via API) ──
# All position presets use RESHOOT_MOTION_TYPE_STATIONARY_* (same endpoint!)
RESHOOT_POS_CENTER  = "RESHOOT_MOTION_TYPE_STATIONARY"           # Center  (API-confirmed)
RESHOOT_POS_LEFT    = "RESHOOT_MOTION_TYPE_STATIONARY_LEFT"      # Left
RESHOOT_POS_RIGHT   = "RESHOOT_MOTION_TYPE_STATIONARY_RIGHT"     # Right
RESHOOT_POS_HIGH    = "RESHOOT_MOTION_TYPE_STATIONARY_HIGHER"    # High
RESHOOT_POS_LOW     = "RESHOOT_MOTION_TYPE_STATIONARY_LOWER"     # Low
RESHOOT_POS_CLOSER  = "RESHOOT_MOTION_TYPE_STATIONARY_CLOSER"    # Closer
RESHOOT_POS_FURTHER = "RESHOOT_MOTION_TYPE_STATIONARY_FURTHER"   # Further

# ── Additional reshoot types from bundle (not yet in UI but usable via API) ──
RESHOOT_ORBIT_LEFT      = "RESHOOT_MOTION_TYPE_ORBIT_LEFT"
RESHOOT_ORBIT_RIGHT     = "RESHOOT_MOTION_TYPE_ORBIT_RIGHT"
RESHOOT_ORBIT_UP        = "RESHOOT_MOTION_TYPE_ORBIT_UP"
RESHOOT_ORBIT_DOWN      = "RESHOOT_MOTION_TYPE_ORBIT_DOWN"
RESHOOT_LEFT_TO_RIGHT   = "RESHOOT_MOTION_TYPE_LEFT_TO_RIGHT"
RESHOOT_RIGHT_TO_LEFT   = "RESHOOT_MOTION_TYPE_RIGHT_TO_LEFT"
RESHOOT_SPIN            = "RESHOOT_MOTION_TYPE_SPIN"
RESHOOT_WIDER_SHOT      = "RESHOOT_MOTION_TYPE_WIDER_SHOT"
RESHOOT_CLOSER_SHOT     = "RESHOOT_MOTION_TYPE_CLOSER_SHOT"
RESHOOT_HIGHER_ANGLE    = "RESHOOT_MOTION_TYPE_HIGHER_ANGLE"
RESHOOT_FORWARD_L       = "RESHOOT_MOTION_TYPE_STATIONARY_FORWARD"
RESHOOT_BACKWARD_L      = "RESHOOT_MOTION_TYPE_STATIONARY_BACKWARD"

# ── Mask usage types (for Remove Object) ─────────────────────────────────────
MASK_USAGE_TYPE = "IMAGE_USAGE_TYPE_MASK"  # confirmed from ObjectRemoval capture

# ── Complete human-readable CAMERA_PRESETS dict ──────────────────────────────
CAMERA_PRESETS = {
    # Camera Motion tab
    "dolly_in":          RESHOOT_FORWARD,
    "dolly_out":         RESHOOT_BACKWARD,
    "orbit_left":        RESHOOT_LEFT,
    "orbit_right":       RESHOOT_RIGHT,
    "orbit_up":          RESHOOT_UP,
    "orbit_down":        RESHOOT_DOWN,
    "dolly_zoom_in":     RESHOOT_DOLLY_ZOOM_IN,
    "dolly_zoom_out":    RESHOOT_DOLLY_ZOOM_OUT,
    # Camera Position tab
    "pos_center":   RESHOOT_POS_CENTER,
    "pos_left":     RESHOOT_POS_LEFT,
    "pos_right":    RESHOOT_POS_RIGHT,
    "pos_high":     RESHOOT_POS_HIGH,
    "pos_low":      RESHOOT_POS_LOW,
    "pos_closer":   RESHOOT_POS_CLOSER,
    "pos_further":  RESHOOT_POS_FURTHER,
    # Extra presets from bundle
    "spin":          RESHOOT_SPIN,
    "wider":         RESHOOT_WIDER_SHOT,
    "closer_shot":   RESHOOT_CLOSER_SHOT,
    "higher_angle":  RESHOOT_HIGHER_ANGLE,
}


# ── Response objects ─────────────────────────────────────────────────────────

class GeneratedImage:
    def __init__(self, raw: dict):
        self._raw          = raw
        self.media_name: str  = raw.get("name", "")
        self.project_id: str  = raw.get("projectId", "")
        self.workflow_id: str = raw.get("workflowId", "")
        img = raw.get("image", {}).get("generatedImage", {})
        self.fife_url: str    = img.get("fifeUrl", "")
        self.seed: int        = img.get("seed", 0)
        self.model: str       = img.get("modelNameType", "")
        self.file_path: Optional[Path] = None

    def __repr__(self):
        return f"<GeneratedImage name={self.media_name[:8]}... model={self.model}>"


class VideoJob:
    """
    Returned immediately after submitting a video generation request.
    Status is PENDING; call api.wait_for_video(job) to block until done.
    """
    def __init__(self, raw: dict):
        self._raw = raw
        media_list = raw.get("media", [])
        if media_list:
            m = media_list[0]
            self.media_name: str  = m.get("name", "")
            self.project_id: str  = m.get("projectId", "")
            self.workflow_id: str = m.get("workflowId", "")
        else:
            wf   = raw.get("workflows", [{}])[0]
            meta = wf.get("metadata", {})
            self.media_name  = meta.get("primaryMediaId", "")
            self.project_id  = wf.get("projectId", "")
            self.workflow_id = wf.get("name", "")

        ops = raw.get("operations", [{}])
        self.operation_name: str     = ops[0].get("operation", {}).get("name", "") if ops else ""
        self.remaining_credits: int  = raw.get("remainingCredits", 0)
        self.status: str             = "PENDING"
        self.fife_url: str           = ""
        self.file_path: Optional[Path] = None
        self.elapsed_s: float        = 0.0

    def __repr__(self):
        return f"<VideoJob media={self.media_name[:8]}... status={self.status}>"


class VideoStatus:
    def __init__(self, raw: dict):
        self._raw        = raw
        media_list       = raw.get("media", [{}])
        m                = media_list[0] if media_list else {}
        self.media_name: str = m.get("name", "")
        meta             = m.get("mediaMetadata", {})
        ms               = meta.get("mediaStatus", {})
        self.status: str = ms.get("mediaGenerationStatus", "UNKNOWN")
        self.complete: bool = self.status in (
            "MEDIA_GENERATION_STATUS_COMPLETE",
            "MEDIA_GENERATION_STATUS_SUCCESS",
            "MEDIA_GENERATION_STATUS_SUCCESSFUL",  # observed in live traffic
        )
        self.failed: bool = self.status in (
            "MEDIA_GENERATION_STATUS_FAILED",
            "MEDIA_GENERATION_STATUS_REJECTED",
        )
        vid = m.get("video", {}).get("generatedVideo", {})
        self.fife_url: str = vid.get("fifeUrl", "")
        self.seed: int     = vid.get("seed", 0)
        self.model: str    = vid.get("model", "")

    def __repr__(self):
        return f"<VideoStatus {self.status} fife={'✓' if self.fife_url else '✗'}>"


class Credits:
    def __init__(self, raw: dict):
        self.credits: int      = raw.get("credits", 0)
        self.tier: str         = raw.get("userPaygateTier", "")
        self.sku: str          = raw.get("sku", "")
        self.service_tier: str = raw.get("serviceTier", "")

    def __repr__(self):
        return f"<Credits {self.credits} ({self.tier})>"


class Workflow:
    def __init__(self, raw: dict):
        self.name: str             = raw.get("name", "")
        meta                       = raw.get("metadata", {})
        self.display_name: str     = meta.get("displayName", "")
        self.create_time: str      = meta.get("createTime", "")
        self.primary_media_id: str = meta.get("primaryMediaId", "")
        self.batch_id: str         = meta.get("batchId", "")
        self.project_id: str       = raw.get("projectId", "")
        self.medias: list          = raw.get("medias", [])

    def __repr__(self):
        return f"<Workflow {self.name[:8]}... '{self.display_name[:30]}'>"


# ── Core API client ──────────────────────────────────────────────────────────

class FlowAPI:
    """
    Direct REST API client for Google Flow AI.

    Uses Playwright browser context for authentication (Google session cookies).
    reCAPTCHA tokens are generated via page.evaluate() on the project page.

    All video generation calls are async:
      1. Submit → VideoJob (PENDING)
      2. Poll   → VideoStatus (loop until .complete)

    Example::

        async with BrowserManager() as bm:
            api = FlowAPI(bm, project_id="4f3c93f5-...")

            # Text → Image
            images = await api.generate_image("Golden lotus in temple")
            await api.download(images[0].fife_url, "out.jpg")

            # Text → Video
            job, status = await api.generate_video_and_wait("Sunrise over mountains")
            await api.download(status.fife_url, "out.mp4")

            # Extend video
            ext_job, ext_status = await api.extend_and_wait(
                job.media_name, job.workflow_id, prompt="Slow pan reveals valley"
            )

            # Camera motion (Dolly in)
            cam_job = await api.reshoot_video(
                job.media_name, job.workflow_id,
                motion_type=RESHOOT_FORWARD
            )

            # Insert object
            ins_job = await api.insert_object(
                job.media_name, job.workflow_id,
                text="golden floating lotus"
            )
    """

    def __init__(
        self,
        browser_manager,
        project_id: str       = "",
        user_tier: str        = "PAYGATE_TIER_ONE",
        poll_interval_s: float = 5.0,
        default_timeout_s: int = 300,
    ):
        self._bm              = browser_manager
        self.project_id       = project_id
        self._user_tier       = user_tier
        self._poll_interval   = poll_interval_s
        self._timeout_s       = default_timeout_s
        self._project_page_url = (
            f"{FLOW_BASE}/tools/flow/project/{project_id}" if project_id else ""
        )
        # Bearer token cache (CDP mode only)
        self._bearer_token:    str   = ""
        self._bearer_token_ts: float = 0.0

    # ── Auth ─────────────────────────────────────────────────────────────────

    async def _ensure_project_page(self):
        page = await self._bm.page()
        if self.project_id and self._project_page_url not in page.url:
            await page.goto(
                self._project_page_url,
                wait_until="domcontentloaded",
                timeout=20000,
            )
            await asyncio.sleep(1.5)

    async def get_recaptcha_token(self) -> str:
        """Generate a fresh reCAPTCHA Enterprise token from the project page.

        In CDP mode we stay on the existing labs.google page (which already has
        the reCAPTCHA script loaded) instead of navigating — navigation would
        lose the page state and force a new load cycle.
        """
        page = await self._bm.page()

        # In CDP mode, only navigate if we're not already on a labs.google page
        is_on_flow = "labs.google" in page.url
        if not is_on_flow:
            await self._ensure_project_page()
            page = await self._bm.page()
        elif self.project_id and self._project_page_url not in page.url:
            # On labs.google but wrong project — navigate only in non-CDP mode
            if not self._bm.cdp_url:
                await self._ensure_project_page()
                page = await self._bm.page()

        token = await page.evaluate(f"""
            async () => {{
                try {{
                    if (window.grecaptcha?.enterprise?.execute) {{
                        return await window.grecaptcha.enterprise.execute(
                            '{RECAPTCHA_SITE_KEY}', {{action: 'GENERATE'}}
                        );
                    }}
                    return '';
                }} catch(e) {{ return ''; }}
            }}
        """)
        return token or ""

    async def _client_context(self) -> dict:
        return {
            "projectId":       self.project_id,
            "tool":            "PINHOLE",
            "userPaygateTier": self._user_tier,
            "sessionId":       f";{int(time.time() * 1000)}",
            "recaptchaContext": {
                "token": await self.get_recaptcha_token(),
                "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
            },
        }

    # ── Auth header management (CDP mode) ─────────────────────────────────────

    # Static API key embedded in the Flow frontend (public, safe to embed)
    FLOW_API_KEY = "AIzaSyBtrm0o5ab1c-Ec8ZuLcGt3oJAA5VWt3pY"

    async def _get_auth_headers(self) -> dict:
        """Return auth headers for aisandbox-pa.googleapis.com requests.

        Required headers (confirmed from live traffic capture 2026-03-06):
          - ``Authorization: Bearer <token>``: OAuth2 token from next-auth session
          - ``Referer: https://labs.google/`` (checked by server)

        The ``X-goog-api-key`` header is only needed for non-auth endpoints
        (checkAppAvailability). Video generation, credits, etc. need Bearer only.

        Bearer token is extracted from ``window.__NEXT_DATA__`` after page navigation.
        Cached for 55 min (tokens expire in ~1h).
        """
        hdrs = {
            "content-type": "text/plain;charset=UTF-8",
            "referer":      "https://labs.google/",
            "origin":       "https://labs.google",
        }

        token = await self._get_bearer_token()
        if token:
            hdrs["authorization"] = f"Bearer {token}"
        return hdrs

    async def _get_bearer_token(self) -> str:
        """Extract OAuth2 Bearer token from the Flow page.

        The token is available in two places (both confirmed from live traffic):

        1. **``window.__NEXT_DATA__.props.pageProps.session.access_token``** (fastest):
           The next-auth session object is embedded in the page HTML and always
           contains the current access token. This is the preferred method.

        2. **CDP Network.requestWillBeSent** (fallback): If the page is navigated
           or the session is fresh, we can catch the token from outgoing requests
           on page load.

        Tokens are cached for 55 min (they expire in ~1h).
        """
        import time as _time

        now = _time.time()
        if self._bearer_token and (now - self._bearer_token_ts) < 3300:
            return self._bearer_token

        page = await self._bm.page()

        # ── Ensure we're on a labs.google page (needed for NEXT_DATA + auth session) ──
        proj_url = f"{FLOW_BASE}/tools/flow/project/{self.project_id}"
        if "labs.google" not in page.url:
            log.info("Navigating to Flow project page for Bearer token extraction")
            await page.goto(proj_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            page = await self._bm.page()

        # ── Method 1: read from __NEXT_DATA__ (instant, embedded in page HTML) ──
        try:
            token = await page.evaluate("""
                () => {
                    try {
                        return window.__NEXT_DATA__?.props?.pageProps?.session?.access_token
                            || null;
                    } catch(e) { return null; }
                }
            """)
            if token and token.startswith("ya29."):
                self._bearer_token = token
                self._bearer_token_ts = now
                log.info("Bearer token from __NEXT_DATA__ (%d chars)", len(token))
                return token
        except Exception as e:
            log.debug("__NEXT_DATA__ method failed: %s", e)

        # ── Method 2: fetch next-auth /api/auth/session ──
        try:
            session_token = await page.evaluate("""
                async () => {
                    try {
                        const resp = await fetch('/fx/api/auth/session', {credentials: 'include'});
                        const data = await resp.json();
                        return data.access_token || null;
                    } catch(e) { return null; }
                }
            """)
            if session_token and session_token.startswith("ya29."):
                self._bearer_token = session_token
                self._bearer_token_ts = now
                log.info("Bearer token from /api/auth/session (%d chars)", len(session_token))
                return session_token
        except Exception as e:
            log.debug("session API method failed: %s", e)

        # ── Method 3: navigate to project page, intercept outgoing requests via CDP ──
        try:
            client = await page.context.new_cdp_session(page)
            await client.send("Network.enable")
            captured: list[str] = []

            def on_req(params):
                url = params.get("request", {}).get("url", "")
                if "aisandbox-pa.googleapis.com" not in url: return
                hdrs = params.get("request", {}).get("headers", {})
                for k, v in hdrs.items():
                    if k.lower() == "authorization" and v.startswith("Bearer ya29."):
                        captured.append(v.replace("Bearer ", ""))

            client.on("Network.requestWillBeSent", on_req)
            await page.goto(proj_url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(3)
            await client.detach()

            if captured:
                self._bearer_token = captured[0]
                self._bearer_token_ts = now
                log.info("Bearer token via CDP Network (%d chars)", len(captured[0]))
                return self._bearer_token
        except Exception as e:
            log.debug("CDP Network method failed: %s", e)

        log.warning("Could not obtain Bearer token — requests may fail with 401")
        return self._bearer_token or ""

    # ── HTTP ──────────────────────────────────────────────────────────────────

    async def _fetch(self, method: str, url: str, body: Optional[dict] = None) -> dict:
        """Authenticated request via Playwright browser context.

        Google's aisandbox-pa.googleapis.com requires an ``Authorization: Bearer``
        OAuth2 token in the request headers. This token is NOT available via
        cookies alone — it's managed by the Flow frontend's JavaScript OAuth flow.

        We extract it from ``window.__NEXT_DATA__`` (embedded in the page HTML)
        or from the next-auth session API, then cache it for ~55 min.

        This applies to both CDP mode and normal persistent-profile mode.
        """
        if not url.startswith("http"):
            url = f"{API_BASE}/{url}"

        # Always inject Bearer token + API key headers
        hdrs = await self._get_auth_headers()

        data = json.dumps(body) if body is not None else None
        ctx  = self._bm.context.request

        if method.upper() == "GET":
            resp = await ctx.get(url, headers=hdrs)
        elif method.upper() == "PATCH":
            resp = await ctx.patch(url, headers=hdrs, data=data)
        else:
            resp = await ctx.post(url, headers=hdrs, data=data)

        if resp.status >= 400:
            text = await resp.text()
            log.error("API %d %s: %s", resp.status, url, text[:300])
            endpoint = url.split("/")[-1].split(":")[-1]
            if resp.status == 404:
                raise NotFoundError(
                    f"Endpoint not found (HTTP 404): {endpoint}\n"
                    f"This feature may be deprecated or unavailable via direct API.\n"
                    f"Response: {text[:200]}"
                )
            if resp.status == 400:
                # Try to extract the Google error message
                try:
                    err_body = json.loads(text)
                    msg = err_body.get("error", {}).get("message", text[:200])
                except Exception:
                    msg = text[:200]
                raise InvalidArgumentError(
                    f"HTTP 400 INVALID_ARGUMENT on {endpoint}: {msg}"
                )
            if resp.status in (401, 403):
                raise AuthError(
                    f"HTTP {resp.status} on {endpoint}: authentication failed. "
                    "Session cookies may be expired — re-open the browser."
                )
            raise GenerationError(f"HTTP {resp.status} on {endpoint}: {text[:200]}")

        try:
            return await resp.json()
        except Exception:
            return {}

    async def _trpc_get(self, proc: str, inp: dict) -> dict:
        from urllib.parse import quote
        url  = f"{FLOW_BASE}/api/trpc/{proc}?input={quote(json.dumps({'json': inp}))}"
        resp = await self._bm.context.request.get(url)
        raw  = await resp.json()
        return raw.get("result", {}).get("data", {}).get("json", raw)

    # ── Credits ───────────────────────────────────────────────────────────────

    async def get_credits(self) -> "Credits":
        data = await self._fetch("GET", f"{API_BASE}/credits")
        return Credits(data)

    async def get_video_model_config(self) -> dict:
        """
        Fetch full video model configuration from Flow.

        Returns all 32+ active models with cost, capabilities, aspect ratios, etc.
        Endpoint: tRPC videoFx.getVideoModelConfig

        Response structure:
            result.videoModels[].key         → videoModelKey string
            result.videoModels[].creditCost  → credits per generation
            result.videoModels[].capabilities → ["TEXT","AUDIO","START_IMAGE",...]
            result.videoModels[].supportedAspectRatios
            result.videoModels[].displayName
            result.videoModels[].modelStatus → "MODEL_STATUS_DEPRECATED" for old models
        """
        # _trpc_get already unwraps result.data.json, giving {"result": {"videoModels": [...]}}
        return await self._trpc_get("videoFx.getVideoModelConfig", {})

    async def get_flow_app_config(self) -> dict:
        """
        Fetch Flow app configuration (feature flags, banners, etc.).

        Endpoint: tRPC videoFx.getFlowAppConfig

        Useful flags:
            isFlowUpsamplingEnabled  → True when upscale feature is available
            isObjectRemovalEnabled   → True when remove object feature is available
            isFlowImageEnabled       → True when image generation is available
            isGemPixProEnabled       → True when Nano Banana Pro is available

        Returns dict with top-level keys like isFlowUpsamplingEnabled, siteContent, etc.
        """
        data = await self._trpc_get("videoFx.getFlowAppConfig", {})
        # _trpc_get gives {"result": {...flags...}} — unwrap one level for convenience
        return data.get("result", data)

    async def get_user_settings(self) -> dict:
        """Fetch user settings (lastAcknowledgedChangeLogId, isEditHistoryVisible, etc.)."""
        data = await self._trpc_get("videoFx.getUserSettings", None)
        return data.get("result", data)

    # ── Project data ──────────────────────────────────────────────────────────

    async def get_project_data(self) -> dict:
        return await self._trpc_get(
            "flow.projectInitialData", {"projectId": self.project_id}
        )

    async def list_workflows(self) -> list[Workflow]:
        data = await self.get_project_data()
        wfs  = data.get("projectContents", {}).get("workflows", [])
        return [Workflow(w) for w in wfs]

    async def rename_workflow(self, workflow_id: str, display_name: str) -> Workflow:
        data = await self._fetch("PATCH", f"{API_BASE}/flowWorkflows/{workflow_id}", {
            "metadata":  {"displayName": display_name},
            "projectId": self.project_id,
        })
        return Workflow(data)

    # ── Image generation (synchronous) ───────────────────────────────────────

    async def generate_image(
        self,
        prompt: str,
        *,
        model:             str          = IMAGE_MODEL_NARWHAL,
        aspect_ratio:      str          = IMAGE_AR_PORTRAIT,
        count:             int          = 4,
        seed:              Optional[int] = None,
        reference_images:  list[str]    = None,   # list of media_name UUIDs for img2img
    ) -> list[GeneratedImage]:
        """
        Generate images from a text prompt (synchronous, blocks until done).

        Endpoint: POST /v1/projects/{id}/flowMedia:batchGenerateImages

        Confirmed request structure (from captured traffic):
          - Top-level ``clientContext`` + per-request ``clientContext`` (both required)
          - ``imageInputs: []`` required even for text-only generation
          - ``structuredPrompt`` directly in the request (not nested under textInput)
          - ``useNewMedia: true`` at the top level

        Args:
            prompt:           Text description.
            model:            IMAGE_MODEL_NARWHAL (default) or IMAGE_MODEL_IMAGEN3.
            aspect_ratio:     IMAGE_AR_PORTRAIT / LANDSCAPE / SQUARE.
            count:            Number of images (1–4, each gets a unique seed).
            seed:             Base seed (each image gets seed+i). None = random.
            reference_images: Optional list of media_name UUIDs to use as reference
                              (image-to-image). Sent as imageInputs with role=REFERENCE_IMAGE.

        Returns:
            List of GeneratedImage objects with fife_url populated.
        """
        cc   = await self._client_context()
        seed = seed if seed is not None else random.randint(0, 2**31)

        # Build imageInputs (empty for text-only; populated for img2img)
        img_inputs = []
        if reference_images:
            img_inputs = [
                {"mediaName": m, "role": "REFERENCE_IMAGE"}
                for m in reference_images
            ]

        # Each request item needs its own clientContext (confirmed by traffic capture)
        # and imageInputs field even when empty (required by API)
        requests = []
        for i in range(count):
            requests.append({
                "clientContext":    cc,           # duplicated inside each item
                "imageModelName":   model,
                "imageAspectRatio": aspect_ratio,
                "structuredPrompt": {"parts": [{"text": prompt}]},
                "seed":             seed + i,     # unique seed per image
                "imageInputs":      img_inputs,   # [] for text-only (required!)
            })

        body = {
            "clientContext":          cc,          # also at top level
            "mediaGenerationContext": {"batchId": str(uuid.uuid4())},
            "useNewMedia":            True,
            "requests":               requests,
        }
        data   = await self._fetch("POST", f"projects/{self.project_id}/flowMedia:batchGenerateImages", body)
        images = [GeneratedImage(m) for m in data.get("media", [])]
        log.info("Generated %d image(s) seed=%d", len(images), seed)
        return images

    # ── Async video helpers ───────────────────────────────────────────────────

    def _video_body(self, endpoint_reqs: list) -> dict:
        """Wrap request list in the standard async video envelope."""
        return {
            "mediaGenerationContext": {"batchId": str(uuid.uuid4())},
            "clientContext":          None,     # filled by callers via _video_call
            "requests":               endpoint_reqs,
            "useV2ModelConfig":       True,
        }

    async def _video_call(self, endpoint: str, requests: list) -> VideoJob:
        """Submit one async video request list to *endpoint* and return a VideoJob."""
        cc   = await self._client_context()
        body = {
            "mediaGenerationContext": {"batchId": str(uuid.uuid4())},
            "clientContext":          cc,
            "requests":               requests,
            "useV2ModelConfig":       True,
        }
        data = await self._fetch("POST", endpoint, body)
        job  = VideoJob(data)
        log.info("Submitted %s → media=%s op=%s credits=%d",
                 endpoint.split(":")[-1], job.media_name[:8],
                 job.operation_name[:8], job.remaining_credits)
        return job

    # ── Text → Video ──────────────────────────────────────────────────────────

    async def generate_video(
        self,
        prompt: str,
        *,
        model:        str          = VIDEO_MODEL_VEO31_FAST,
        aspect_ratio: str          = VIDEO_AR_LANDSCAPE,
        seed:         Optional[int] = None,
    ) -> VideoJob:
        """
        Submit a text-to-video job. Returns immediately (PENDING).

        Endpoint: POST /v1/video:batchAsyncGenerateVideoText
        Model:    veo_3_1_t2v_fast (default)
        """
        seed = seed if seed is not None else random.randint(0, 2**31)
        return await self._video_call("video:batchAsyncGenerateVideoText", [{
            "aspectRatio":   aspect_ratio,
            "seed":          seed,
            "textInput":     {"structuredPrompt": {"parts": [{"text": prompt}]}},
            "videoModelKey": model,
            "metadata":      {},
        }])

    # ── Image → Video (Frames mode) ───────────────────────────────────────────

    async def generate_video_from_image(
        self,
        prompt: str,
        start_media_name: str,
        *,
        end_media_name: Optional[str] = None,
        model:          str           = VIDEO_MODEL_VEO31_I2V,
        aspect_ratio:   str           = VIDEO_AR_PORTRAIT,
        seed:           Optional[int]  = None,
    ) -> VideoJob:
        """
        Submit an image-to-video job (Frames mode).

        Endpoint: POST /v1/video:batchAsyncGenerateVideoText
        Model:    veo_3_1_i2v_fast (default)

        Args:
            start_media_name: Media UUID of the start-frame image.
            end_media_name:   Optional end-frame (uses veo_2_1_start_end model).
        """
        seed   = seed if seed is not None else random.randint(0, 2**31)
        inputs = [{"mediaName": start_media_name, "role": IMAGE_ROLE_START}]
        if end_media_name:
            inputs.append({"mediaName": end_media_name, "role": IMAGE_ROLE_END})
            model = VIDEO_MODEL_VEO21_SE

        return await self._video_call("video:batchAsyncGenerateVideoText", [{
            "aspectRatio":   aspect_ratio,
            "seed":          seed,
            "textInput":     {"structuredPrompt": {"parts": [{"text": prompt}]}},
            "videoModelKey": model,
            "imageInputs":   inputs,
            "metadata":      {},
        }])

    # ── Multi-Reference Video (NEW!) ─────────────────────────────────────────

    async def generate_video_multi_ref(
        self,
        prompt: str,
        reference_media_names: list[str],
        *,
        model:        str          = VIDEO_MODEL_VEO31_R2V,
        aspect_ratio: str          = VIDEO_AR_LANDSCAPE,
        seed:         Optional[int] = None,
        workflow_id:  str          = "",
    ) -> "VideoJob":
        """
        Generate a video using multiple reference images (style/subject reference).

        Model capability: MULTI_REFERENCE_NO_STYLE
        Models: veo_3_1_r2v_fast_landscape (20cr), veo_3_1_r2v_fast_portrait (20cr)

        Uses the same endpoint as T2V but with imageInputs populated:
          imageInputs = [{"mediaName": uuid, "role": "REFERENCE_IMAGE"}, ...]

        Args:
            prompt:                 Text description of the video.
            reference_media_names:  List of media UUIDs to use as reference images.
            model:                  R2V model key (default = landscape Fast).
            aspect_ratio:           Aspect ratio.
            seed:                   Random seed.
            workflow_id:            Optional workflow ID.
        """
        seed = seed if seed is not None else random.randint(0, 2**31)
        image_inputs = [
            {"mediaName": m, "role": IMAGE_ROLE_REFERENCE}
            for m in reference_media_names
        ]
        return await self._video_call("video:batchAsyncGenerateVideoText", [{
            "aspectRatio":   aspect_ratio,
            "seed":          seed,
            "textInput":     {"structuredPrompt": {"parts": [{"text": prompt}]}},
            "videoModelKey": model,
            "imageInputs":   image_inputs,
            "metadata":      {"workflowId": workflow_id} if workflow_id else {},
        }])

    # ── Extend Video ─────────────────────────────────────────────────────────

    async def extend_video(
        self,
        media_name: str,
        workflow_id: str,
        prompt: str      = "",
        *,
        model:        str          = VIDEO_MODEL_EXTEND_L,
        aspect_ratio: str          = VIDEO_AR_LANDSCAPE,
        seed:         Optional[int] = None,
    ) -> VideoJob:
        """
        Extend an existing video (append new content after the last frame).

        Endpoint: POST /v1/video:batchAsyncGenerateVideoExtendVideo
        Model:    veo_3_1_extend_fast_landscape

        Args:
            media_name:  Media UUID of the video to extend.
            workflow_id: Workflow UUID the media belongs to.
            prompt:      Continuation prompt (empty = auto).
        """
        seed = seed if seed is not None else random.randint(0, 2**31)
        return await self._video_call("video:batchAsyncGenerateVideoExtendVideo", [{
            "aspectRatio":   aspect_ratio,
            "seed":          seed,
            "textInput":     {"structuredPrompt": {"parts": [{"text": prompt}]}},
            "videoModelKey": model,
            "videoInput":    {"mediaId": media_name},
            "metadata":      {"workflowId": workflow_id},
        }])

    # ── Camera / Reshoot ──────────────────────────────────────────────────────

    async def reshoot_video(
        self,
        media_name: str,
        workflow_id: str,
        *,
        motion_type:  str          = RESHOOT_FORWARD,
        model:        str          = VIDEO_MODEL_RESHOOT_L,
        aspect_ratio: str          = VIDEO_AR_LANDSCAPE,
        seed:         Optional[int] = None,
    ) -> VideoJob:
        """
        Apply a camera motion preset to an existing video.

        Endpoint: POST /v1/video:batchAsyncGenerateVideoReshootVideo
        Model:    veo_3_0_reshoot_landscape

        Motion presets (reshootMotionType):
            RESHOOT_FORWARD        → Dolly in
            RESHOOT_BACKWARD       → Dolly out
            RESHOOT_LEFT           → Orbit left
            RESHOOT_RIGHT          → Orbit right
            RESHOOT_UP             → Orbit up
            RESHOOT_DOWN           → Orbit low
            RESHOOT_DOLLY_ZOOM_IN  → Dolly in + zoom out
            RESHOOT_DOLLY_ZOOM_OUT → Dolly out + zoom in

        Tip: use CAMERA_PRESETS dict for human-readable aliases:
            motion_type = CAMERA_PRESETS["dolly_in"]

        Args:
            media_name:   Media UUID of the source video.
            workflow_id:  Workflow UUID.
            motion_type:  One of the RESHOOT_* constants above.
        """
        seed = seed if seed is not None else random.randint(0, 2**31)
        return await self._video_call("video:batchAsyncGenerateVideoReshootVideo", [{
            "aspectRatio":       aspect_ratio,
            "seed":              seed,
            "textInput":         {"structuredPrompt": {"parts": []}},
            "videoModelKey":     model,
            "videoInput":        {"mediaId": media_name},
            "metadata":          {"workflowId": workflow_id},
            "reshootMotionType": motion_type,
        }])

    # ── Insert Object ─────────────────────────────────────────────────────────

    async def insert_object(
        self,
        media_name: str,
        workflow_id: str,
        text: str,
        *,
        model:        str          = VIDEO_MODEL_INSERT,
        aspect_ratio: str          = VIDEO_AR_LANDSCAPE,
        seed:         Optional[int] = None,
    ) -> VideoJob:
        """
        Insert a new object into an existing video using natural language.

        Endpoint: POST /v1/video:batchAsyncGenerateVideoObjectInsertion
        Model:    veo_2_0_object_insertion_landscape

        Args:
            media_name:  Media UUID of the source video.
            workflow_id: Workflow UUID.
            text:        Description of the object to insert
                         (e.g. "golden lotus flower floating in center").
        """
        seed = seed if seed is not None else random.randint(0, 2**31)
        return await self._video_call("video:batchAsyncGenerateVideoObjectInsertion", [{
            "aspectRatio":   aspect_ratio,
            "seed":          seed,
            "textInput":     {"structuredPrompt": {"parts": [{"text": text}]}},
            "videoModelKey": model,
            "videoInput":    {"mediaId": media_name},
            "metadata":      {"workflowId": workflow_id},
        }])

    # ── Remove Object ─────────────────────────────────────────────────────────

    async def remove_object(
        self,
        media_name: str,
        workflow_id: str,
        *,
        model:          str          = VIDEO_MODEL_REMOVE,
        aspect_ratio:   str          = VIDEO_AR_LANDSCAPE,
        seed:           Optional[int]    = None,
        mask_jpeg_b64:  Optional[str]    = None,   # base64-encoded JPEG mask (confirmed format!)
        mask_jpeg_bytes: Optional[bytes] = None,   # raw JPEG bytes (auto-encoded)
    ) -> VideoJob:
        """
        Remove an object from a video using a drawn mask.

        Endpoint: POST /v1/video:batchAsyncGenerateVideoObjectRemoval
        Model:    veo_2_0_object_removal_landscape

        ✅ Mask format CONFIRMED via live traffic capture 2026-03-06:
          imageMask.imageBytes     = base64-encoded JPEG
          imageMask.imageUsageType = "IMAGE_USAGE_TYPE_MASK"

          Mask is a JPEG at video resolution where:
            white = REMOVE, black = KEEP

        Use ``create_removal_mask()`` to generate a simple rectangular mask.

        Args:
            media_name:       Media UUID of source video.
            workflow_id:      Workflow UUID.
            mask_jpeg_b64:    Base64-encoded JPEG mask image.
            mask_jpeg_bytes:  Raw JPEG bytes (auto-encoded to base64).
        """
        import base64 as _b64
        seed = seed if seed is not None else random.randint(0, 2**31)
        req: dict = {
            "aspectRatio":   aspect_ratio,
            "seed":          seed,
            "textInput":     {"structuredPrompt": {"parts": []}},
            "videoModelKey": model,
            "videoInput":    {"mediaId": media_name},
            "metadata":      {"workflowId": workflow_id},
        }
        if mask_jpeg_bytes is not None:
            mask_jpeg_b64 = _b64.b64encode(mask_jpeg_bytes).decode()
        if mask_jpeg_b64:
            req["imageMask"] = {
                "imageBytes":     mask_jpeg_b64,
                "imageUsageType": MASK_USAGE_TYPE,
            }
            log.debug("remove_object: mask provided (%d b64 chars)", len(mask_jpeg_b64))
        else:
            log.warning("remove_object: no mask provided — API may return 400 INVALID_ARGUMENT")
        return await self._video_call("video:batchAsyncGenerateVideoObjectRemoval", [req])

    # ── Upscale Video ────────────────────────────────────────────────────────

    async def upscale_video(
        self,
        media_name: str,
        workflow_id: str,
        *,
        resolution:  str          = VIDEO_RES_1080P,
        aspect_ratio: str         = VIDEO_AR_LANDSCAPE,
        seed:         Optional[int] = None,
    ) -> VideoJob:
        """
        Upscale an existing video to 1080p.  **FREE — costs 0 credits!**

        Endpoint: POST /v1/video:batchAsyncGenerateVideoUpsampleVideo
        Model:    veo_3_1_upsampler_1080p  (cost=0, UPSCALING capability)

        Confirmed via live traffic capture 2026-03-06:
          - The UI Download dialog has an "1080p Upscaled" button that triggers this.
          - Response media.name = "{original_id}_upsampled"
          - workflowStepId = "CAk"
          - remainingCredits unchanged after upscale (cost=0 confirmed!)

        Args:
            media_name:   Media UUID of the source video.
            workflow_id:  Workflow UUID.
            resolution:   Target resolution (default VIDEO_RES_1080P = "VIDEO_RESOLUTION_1080P").
            aspect_ratio: Aspect ratio matching the source video.
            seed:         Random seed.

        Returns:
            VideoJob whose media_name ends with "_upsampled".
        """
        seed = seed if seed is not None else random.randint(0, 2**31)
        return await self._video_call(
            "video:batchAsyncGenerateVideoUpsampleVideo",
            [{
                "resolution":    resolution,         # ← NEW required field for upscale!
                "aspectRatio":   aspect_ratio,
                "seed":          seed,
                "videoModelKey": VIDEO_MODEL_UPSCALER_1080P,
                "videoInput":    {"mediaId": media_name},
                "metadata":      {"workflowId": workflow_id},
            }]
        )

    async def upscale_and_wait(
        self,
        media_name: str,
        workflow_id: str,
        *,
        timeout_s:    int          = 180,
        on_poll:      Optional[Callable] = None,
        resolution:   str          = VIDEO_RES_1080P,
        aspect_ratio: str          = VIDEO_AR_LANDSCAPE,
    ) -> tuple["VideoJob", "VideoStatus"]:
        """Upscale video and wait for completion (convenience wrapper)."""
        job    = await self.upscale_video(media_name, workflow_id,
                                          resolution=resolution, aspect_ratio=aspect_ratio)
        status = await self.wait_for_video(job, timeout_s=timeout_s, on_poll=on_poll)
        return job, status

    # ── Poll status ───────────────────────────────────────────────────────────

    async def poll_video(
        self,
        media_name: str,
        project_id: Optional[str] = None,
    ) -> VideoStatus:
        """
        Check the status of a pending video generation job.

        Endpoint: POST /v1/video:batchCheckAsyncVideoGenerationStatus
        """
        pid  = project_id or self.project_id
        data = await self._fetch(
            "POST",
            "video:batchCheckAsyncVideoGenerationStatus",
            {"media": [{"name": media_name, "projectId": pid}]},
        )
        return VideoStatus(data)

    async def wait_for_video(
        self,
        job: VideoJob,
        *,
        timeout_s: int   = 0,
        poll_s:    float = 5.0,
        on_poll: Optional[Callable] = None,
    ) -> VideoStatus:
        """
        Wait for a VideoJob to complete, polling every ``poll_s`` seconds.

        Args:
            job:       VideoJob returned by any generate_* method.
            timeout_s: Max seconds to wait (0 = use default 300s).
            poll_s:    Poll interval in seconds.
            on_poll:   Optional callback(status: VideoStatus, elapsed: float).

        Returns:
            Completed VideoStatus with fife_url populated.

        Raises:
            GenerationTimeout if job doesn't complete in time.
            GenerationError   if job fails.
        """
        if not job.media_name:
            raise GenerationError("VideoJob has no media_name — cannot poll")

        limit = timeout_s or self._timeout_s
        t0    = time.monotonic()

        while True:
            elapsed = time.monotonic() - t0
            if elapsed > limit:
                raise GenerationTimeout(limit)

            status = await self.poll_video(job.media_name)
            log.debug("poll %s → %s (%.0fs)", job.media_name[:8], status.status, elapsed)

            if on_poll:
                on_poll(status, elapsed)

            if status.complete:
                job.status    = "COMPLETE"
                job.fife_url  = status.fife_url
                job.elapsed_s = elapsed
                return status

            if status.failed:
                raise GenerationError(f"Generation failed: {status.status}")

            await asyncio.sleep(poll_s)

    # ── Convenience: submit + wait ────────────────────────────────────────────

    async def generate_video_and_wait(
        self,
        prompt: str,
        *,
        model:            str          = VIDEO_MODEL_VEO31_FAST,
        aspect_ratio:     str          = VIDEO_AR_LANDSCAPE,
        seed:             Optional[int] = None,
        timeout_s:        int          = 0,
        on_poll:          Optional[Callable] = None,
        # Image-to-video passthrough params
        start_media_name: Optional[str] = None,
        end_media_name:   Optional[str] = None,
    ) -> tuple[VideoJob, VideoStatus]:
        """Submit text-to-video (or image-to-video) and wait for completion.

        Pass ``start_media_name`` to animate from an image (Frames mode).
        Pass both ``start_media_name`` and ``end_media_name`` for start+end pinning.
        """
        if start_media_name:
            job = await self.generate_video_from_image(
                prompt, start_media_name,
                end_media_name=end_media_name,
                model=model if start_media_name else VIDEO_MODEL_VEO31_I2V,
                aspect_ratio=aspect_ratio, seed=seed,
            )
        else:
            job = await self.generate_video(
                prompt, model=model, aspect_ratio=aspect_ratio, seed=seed
            )
        status = await self.wait_for_video(job, timeout_s=timeout_s, on_poll=on_poll)
        return job, status

    async def extend_and_wait(
        self,
        media_name: str,
        workflow_id: str,
        prompt: str = "",
        *,
        model:     str          = VIDEO_MODEL_EXTEND_L,
        aspect_ratio: str       = VIDEO_AR_LANDSCAPE,
        timeout_s: int          = 0,
        on_poll: Optional[Callable] = None,
    ) -> tuple[VideoJob, VideoStatus]:
        """Extend a video and wait for the result."""
        job    = await self.extend_video(media_name, workflow_id, prompt, model=model, aspect_ratio=aspect_ratio)
        status = await self.wait_for_video(job, timeout_s=timeout_s, on_poll=on_poll)
        return job, status

    async def reshoot_and_wait(
        self,
        media_name: str,
        workflow_id: str,
        motion_type: str = RESHOOT_FORWARD,
        *,
        model:     str          = VIDEO_MODEL_RESHOOT_L,
        aspect_ratio: str       = VIDEO_AR_LANDSCAPE,
        timeout_s: int          = 0,
        on_poll: Optional[Callable] = None,
    ) -> tuple[VideoJob, VideoStatus]:
        """Apply camera motion and wait for the result."""
        job    = await self.reshoot_video(media_name, workflow_id, motion_type=motion_type, model=model, aspect_ratio=aspect_ratio)
        status = await self.wait_for_video(job, timeout_s=timeout_s, on_poll=on_poll)
        return job, status

    async def insert_and_wait(
        self,
        media_name: str,
        workflow_id: str,
        text: str,
        *,
        timeout_s: int          = 0,
        on_poll: Optional[Callable] = None,
    ) -> tuple[VideoJob, VideoStatus]:
        """Insert an object into a video and wait for the result."""
        job    = await self.insert_object(media_name, workflow_id, text)
        status = await self.wait_for_video(job, timeout_s=timeout_s, on_poll=on_poll)
        return job, status

    async def remove_and_wait(
        self,
        media_name: str,
        workflow_id: str,
        *,
        timeout_s: int          = 0,
        on_poll: Optional[Callable] = None,
    ) -> tuple[VideoJob, VideoStatus]:
        """Remove an object from a video and wait for the result."""
        job    = await self.remove_object(media_name, workflow_id)
        status = await self.wait_for_video(job, timeout_s=timeout_s, on_poll=on_poll)
        return job, status

    # ── Chain extend (infinite video) ────────────────────────────────────────

    async def extend_loop(
        self,
        media_name: str,
        workflow_id: str,
        n: int,
        prompt: str          = "",
        output_dir: str | Path = ".",
        *,
        model:     str          = VIDEO_MODEL_EXTEND_L,
        aspect_ratio: str       = VIDEO_AR_LANDSCAPE,
        timeout_s: int          = 0,
        download:  bool         = True,
        on_progress: Optional[Callable] = None,
    ) -> list[tuple[VideoJob, VideoStatus]]:
        """
        Chain-extend a video N times.

        Each extension takes the previous segment's media_name as input,
        enabling theoretically infinite video generation.

        Args:
            media_name:   Starting video media UUID.
            workflow_id:  Starting workflow UUID.
            n:            Number of extensions.
            prompt:       Continuation prompt (empty = auto).
            output_dir:   Download directory for each segment.
            on_progress:  Optional callback(i, n, job, status).

        Returns:
            List of (VideoJob, VideoStatus) for each extension.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        results = []

        cur_media = media_name
        cur_wf    = workflow_id

        for i in range(n):
            log.info("Extend %d/%d from media=%s", i + 1, n, cur_media[:8])
            job, status = await self.extend_and_wait(
                cur_media, cur_wf, prompt,
                model=model, aspect_ratio=aspect_ratio, timeout_s=timeout_s,
            )

            if download and status.fife_url:
                path = output_dir / f"segment_{i:03d}.mp4"
                await self.download(status.fife_url, path)
                job.file_path = path

            results.append((job, status))
            cur_media = job.media_name
            cur_wf    = job.workflow_id or cur_wf

            if on_progress:
                on_progress(i + 1, n, job, status)

        return results

    # ── Media download ────────────────────────────────────────────────────────

    async def download(self, fife_url: str, output_path: str | Path) -> Path:
        """
        Download a generated image or video from its fife_url.

        Uses Playwright browser context (carries Google auth cookies).
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        resp = await self._bm.context.request.get(fife_url)
        if resp.status != 200:
            raise GenerationError(f"Download failed HTTP {resp.status}")

        body = await resp.body()
        output_path.write_bytes(body)
        log.info("Downloaded %dKB → %s", len(body) // 1024, output_path)
        return output_path

    async def download_image(self, img: GeneratedImage, output_dir: str | Path = ".") -> Path:
        """Download a GeneratedImage to a directory."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{img.media_name[:8]}.jpg"
        await self.download(img.fife_url, path)
        img.file_path = path
        return path

    async def download_video(self, job: VideoJob, output_dir: str | Path = ".") -> Path:
        """Download a completed VideoJob to a directory."""
        if not job.fife_url:
            raise GenerationError("VideoJob has no fife_url")
        out  = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{job.media_name[:8]}.mp4"
        await self.download(job.fife_url, path)
        job.file_path = path
        return path

    # ── Upload local image ────────────────────────────────────────────────────

    async def upload_image(self, image_path: str | Path) -> str:
        """
        Upload a local image to Flow and return its media_name (UUID).

        The media_name can then be passed to generate_video_from_image().
        Uses the FlowUI helper (file input interaction).
        """
        from ._flow_ui import FlowUI
        page = await self._bm.page()
        await self._ensure_project_page()

        ui  = FlowUI()
        ok  = await ui.upload_image(page, str(image_path))
        if not ok:
            raise GenerationError(f"Failed to upload: {image_path}")

        await asyncio.sleep(2)
        data = await self.get_project_data()
        wfs  = data.get("projectContents", {}).get("workflows", [])
        if not wfs:
            raise GenerationError("No workflows after upload")

        latest   = wfs[-1]
        media_id = latest.get("metadata", {}).get("primaryMediaId", "")
        if not media_id:
            medias   = latest.get("medias", [])
            media_id = medias[-1].get("name", "") if medias else ""

        if not media_id:
            raise GenerationError("Could not find uploaded image media_name")

        log.info("Uploaded image → %s", media_id)
        return media_id

    # ── Batch helpers ─────────────────────────────────────────────────────────

    async def batch_generate_images(
        self,
        prompts: list[str],
        output_dir: str | Path = ".",
        *,
        aspect_ratio: str    = IMAGE_AR_PORTRAIT,
        count:        int    = 1,
        delay_s:      float  = 1.0,
        download:     bool   = True,
    ) -> list[list[GeneratedImage]]:
        """Generate images for multiple prompts sequentially."""
        output_dir = Path(output_dir)
        results    = []

        for idx, prompt in enumerate(prompts):
            log.info("[%d/%d] image: %s", idx + 1, len(prompts), prompt[:60])
            images = await self.generate_image(
                prompt, aspect_ratio=aspect_ratio, count=count
            )
            if download:
                for img in images:
                    if img.fife_url:
                        await self.download_image(img, output_dir / f"{idx:04d}")
            results.append(images)
            if idx < len(prompts) - 1:
                await asyncio.sleep(delay_s)

        return results

    async def batch_generate_videos(
        self,
        prompts: list[str],
        output_dir: str | Path = ".",
        *,
        model:        str    = VIDEO_MODEL_VEO31_FAST,
        aspect_ratio: str    = VIDEO_AR_LANDSCAPE,
        concurrency:  int    = 3,
        timeout_s:    int    = 0,
        download:     bool   = True,
        on_done: Optional[Callable] = None,
    ) -> list[tuple[VideoJob, VideoStatus]]:
        """
        Generate videos for multiple prompts with concurrency control.
        Submits all jobs, then waits concurrently (max ``concurrency`` at once).
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        sem     = asyncio.Semaphore(concurrency)
        results: list = [None] * len(prompts)

        async def _one(idx: int, prompt: str):
            async with sem:
                job, status = await self.generate_video_and_wait(
                    prompt, model=model, aspect_ratio=aspect_ratio,
                    timeout_s=timeout_s,
                )
                if download and status.fife_url:
                    path = output_dir / f"{idx:04d}_{job.media_name[:8]}.mp4"
                    await self.download(status.fife_url, path)
                    job.file_path = path
                if on_done:
                    on_done(prompt, job, status)
                results[idx] = (job, status)

        await asyncio.gather(*[_one(i, p) for i, p in enumerate(prompts)])
        return results


# ── Module-level utilities ────────────────────────────────────────────────────

def create_removal_mask(
    width: int,
    height: int,
    regions: list[tuple[int, int, int, int]],
    *,
    quality: int = 85,
) -> bytes:
    """
    Generate a JPEG mask image for use with ``FlowAPI.remove_object()``.

    The mask is a JPEG image at the specified resolution where:
      - White (255, 255, 255) = area to REMOVE
      - Black (0, 0, 0)       = area to KEEP

    Confirmed format from live traffic capture (2026-03-06):
      imageMask.imageBytes     = base64-encoded JPEG
      imageMask.imageUsageType = "IMAGE_USAGE_TYPE_MASK"

    Args:
        width:    Width in pixels (should match video width).
        height:   Height in pixels (should match video height).
        regions:  List of (x, y, w, h) rectangles to mark for removal.
        quality:  JPEG quality (1-95, default 85).

    Returns:
        JPEG bytes ready for base64 encoding and use in ``imageMask.imageBytes``.

    Example:
        # Remove top-left 20% of a 1280x720 video
        mask = create_removal_mask(1280, 720, [(0, 0, 256, 144)])
        job = await api.remove_object(media_id, wf_id, mask_jpeg_bytes=mask)
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise ImportError(
            "Pillow is required for create_removal_mask(). "
            "Install with: pip install pillow"
        )
    import io

    img  = Image.new("RGB", (width, height), (0, 0, 0))   # black = keep
    draw = ImageDraw.Draw(img)
    for x, y, w, h in regions:
        draw.rectangle([x, y, x + w, y + h], fill=(255, 255, 255))   # white = remove

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def encode_mask_b64(mask_bytes: bytes) -> str:
    """Base64-encode a mask JPEG for use in imageMask.imageBytes."""
    import base64
    return base64.b64encode(mask_bytes).decode()


# ── MODEL_REGISTRY (complete list from getVideoModelConfig, 2026-03-06) ───────
MODEL_REGISTRY: dict[str, dict] = {
    # key: {display, cost, caps, ratios, status}
    "veo_3_1_t2v_fast":           {"display": "Veo 3.1 Fast",         "cost": 20,  "caps": ["TEXT","AUDIO"],                   "ratios": ["LANDSCAPE"]},
    "veo_3_1_t2v_fast_portrait":  {"display": "Veo 3.1 Fast Portrait","cost": 20,  "caps": ["TEXT","AUDIO"],                   "ratios": ["PORTRAIT"]},
    "veo_3_1_t2v":                {"display": "Veo 3.1 Quality",      "cost": 100, "caps": ["TEXT","AUDIO"],                   "ratios": ["LANDSCAPE"]},
    "veo_3_1_t2v_portrait":       {"display": "Veo 3.1 Quality P",    "cost": 100, "caps": ["TEXT","AUDIO"],                   "ratios": ["PORTRAIT"]},
    "veo_2_1_fast_d_15_t2v":      {"display": "Veo 2.1 Fast",         "cost": 10,  "caps": ["TEXT"],                           "ratios": ["LANDSCAPE"]},
    "veo_2_0_t2v":                {"display": "Veo 2.0 Quality",      "cost": 100, "caps": ["TEXT"],                           "ratios": ["LANDSCAPE"]},
    "veo_3_1_r2v_fast_landscape": {"display": "Veo 3.1 R2V Fast",     "cost": 20,  "caps": ["MULTI_REFERENCE_NO_STYLE","AUDIO"],"ratios": ["LANDSCAPE"]},
    "veo_3_1_r2v_fast_portrait":  {"display": "Veo 3.1 R2V Fast P",   "cost": 20,  "caps": ["MULTI_REFERENCE_NO_STYLE","AUDIO"],"ratios": ["PORTRAIT"]},
    "veo_3_1_i2v_s_fast":         {"display": "Veo 3.1 Fast I2V",     "cost": 20,  "caps": ["START_IMAGE","AUDIO"],            "ratios": ["LANDSCAPE"]},
    "veo_3_1_i2v_s_fast_portrait":{"display": "Veo 3.1 Fast I2V P",   "cost": 20,  "caps": ["START_IMAGE","AUDIO"],            "ratios": ["PORTRAIT"]},
    "veo_3_1_i2v_s":              {"display": "Veo 3.1 Quality I2V",  "cost": 100, "caps": ["START_IMAGE","AUDIO"],            "ratios": ["LANDSCAPE"]},
    "veo_3_1_i2v_s_portrait":     {"display": "Veo 3.1 Quality I2V P","cost": 100, "caps": ["START_IMAGE","AUDIO"],            "ratios": ["PORTRAIT"]},
    "veo_2_1_fast_d_15_i2v":      {"display": "Veo 2.1 Fast I2V",     "cost": 10,  "caps": ["START_IMAGE"],                   "ratios": ["LANDSCAPE"]},
    "veo_2_0_i2v":                {"display": "Veo 2.0 Quality I2V",  "cost": 100, "caps": ["START_IMAGE"],                   "ratios": ["LANDSCAPE"]},
    "veo_3_1_i2v_s_fast_fl":      {"display": "Veo 3.1 Fast SE",      "cost": 20,  "caps": ["START_IMAGE_AND_END_IMAGE","AUDIO"],"ratios":["LANDSCAPE"]},
    "veo_3_1_i2v_s_fast_portrait_fl":{"display":"Veo 3.1 Fast SE P",  "cost": 20,  "caps": ["START_IMAGE_AND_END_IMAGE","AUDIO"],"ratios":["PORTRAIT"]},
    "veo_3_1_i2v_s_fl":           {"display": "Veo 3.1 Quality SE",   "cost": 100, "caps": ["START_IMAGE_AND_END_IMAGE","AUDIO"],"ratios":["LANDSCAPE"]},
    "veo_3_1_i2v_s_portrait_fl":  {"display": "Veo 3.1 Quality SE P", "cost": 100, "caps": ["START_IMAGE_AND_END_IMAGE","AUDIO"],"ratios":["PORTRAIT"]},
    "veo_2_1_fast_d_15_with_start_image_and_end_image_interpolation":
                                  {"display": "Veo 2.1 SE",           "cost": 10,  "caps": ["START_IMAGE_AND_END_IMAGE"],      "ratios": ["LANDSCAPE"]},
    "veo_3_1_extend_fast_landscape":{"display":"Veo 3.1 Fast Extend", "cost": 20,  "caps": ["VIDEO_EXTENSION"],                "ratios": ["LANDSCAPE"]},
    "veo_3_1_extend_fast_portrait": {"display":"Veo 3.1 Fast Ext P",  "cost": 20,  "caps": ["VIDEO_EXTENSION"],                "ratios": ["PORTRAIT"]},
    "veo_3_1_extend_landscape":   {"display": "Veo 3.1 Quality Ext",  "cost": 100, "caps": ["VIDEO_EXTENSION"],                "ratios": ["LANDSCAPE"]},
    "veo_3_1_extend_portrait":    {"display": "Veo 3.1 Quality Ext P","cost": 100, "caps": ["VIDEO_EXTENSION"],                "ratios": ["PORTRAIT"]},
    "veo_2_1_fast_d_15_with_video_extension":
                                  {"display": "Veo 2.1 Extend",       "cost": 10,  "caps": ["VIDEO_EXTENSION"],                "ratios": ["LANDSCAPE"]},
    "veo_3_0_reshoot_landscape":  {"display": "Camera Motion",        "cost": 20,  "caps": ["RESHOOT"],                        "ratios": ["LANDSCAPE"]},
    "veo_3_0_reshoot_portrait":   {"display": "Camera Motion P",      "cost": 20,  "caps": ["RESHOOT"],                        "ratios": ["PORTRAIT"]},
    "veo_2_0_object_insertion_landscape":{"display":"Insert Object",   "cost": 20,  "caps": ["OBJECT_INSERTION"],               "ratios": ["LANDSCAPE"]},
    "veo_2_0_object_insertion_portrait": {"display":"Insert Object P", "cost": 20,  "caps": ["OBJECT_INSERTION"],               "ratios": ["PORTRAIT"]},
    "veo_2_0_object_removal_landscape":  {"display":"Remove Object",   "cost": 20,  "caps": ["OBJECT_REMOVAL"],                 "ratios": ["LANDSCAPE"]},
    "veo_2_0_object_removal_portrait":   {"display":"Remove Object P", "cost": 20,  "caps": ["OBJECT_REMOVAL"],                 "ratios": ["PORTRAIT"]},
    "veo_3_1_upsampler_1080p":    {"display": "Upscale 1080p",        "cost": 0,   "caps": ["UPSCALING"],                      "ratios": ["LANDSCAPE","PORTRAIT"]},
}
