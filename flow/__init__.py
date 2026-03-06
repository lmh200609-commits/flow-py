"""flow-py — Unofficial Python API & CLI for Google Flow AI (labs.google/fx).

Quick start::

    from flow import FlowClient, GenerationMode

    import asyncio

    async def main():
        async with await FlowClient.create() as client:
            result = await client.generate_image(
                "Golden Buddha on a lotus throne, celestial clouds, 8K",
                output_dir="./outputs",
            )
            print("Saved to:", result.primary_file)

    asyncio.run(main())
"""

from ._client import FlowClient, CAMERA_MOTIONS, CAMERA_POSITIONS
from ._ui_interceptor import UIInterceptor, CapturedCall
from ._exceptions import (
    AuthError,
    DownloadError,
    FeatureUnavailableError,
    FlowError,
    GenerationError,
    GenerationTimeout,
    InvalidArgumentError,
    NoProjectError,
    NotFoundError,
    NotLoggedInError,
    PolicyError,
    UIError,
)
from ._api import (
    FlowAPI,
    GeneratedImage,
    create_removal_mask,
    VideoJob,
    VideoStatus,
    Credits,
    Workflow,
    # Image constants
    IMAGE_MODEL_NARWHAL, IMAGE_MODEL_IMAGEN3,
    IMAGE_AR_PORTRAIT, IMAGE_AR_LANDSCAPE, IMAGE_AR_SQUARE,
    IMAGE_ROLE_START, IMAGE_ROLE_END, IMAGE_ROLE_REFERENCE,
    # Video model constants — T2V
    VIDEO_MODEL_VEO31_FAST, VIDEO_MODEL_VEO31_FAST_P,
    VIDEO_MODEL_VEO31_STD,  VIDEO_MODEL_VEO31_STD_P,
    VIDEO_MODEL_VEO21_T2V,
    VIDEO_MODEL_VEO20_STD,
    # Video model constants — I2V
    VIDEO_MODEL_VEO31_I2V, VIDEO_MODEL_VEO31_I2V_P,
    VIDEO_MODEL_VEO31_I2V_STD, VIDEO_MODEL_VEO31_I2V_STD_P,
    VIDEO_MODEL_VEO21_I2V,  VIDEO_MODEL_VEO20_I2V_STD,
    # Video model constants — Start+End
    VIDEO_MODEL_VEO31_SE, VIDEO_MODEL_VEO31_SE_P,
    VIDEO_MODEL_VEO31_SE_STD, VIDEO_MODEL_VEO31_SE_STD_P,
    VIDEO_MODEL_VEO21_SE,
    # Video model constants — Multi-reference
    VIDEO_MODEL_VEO31_R2V, VIDEO_MODEL_VEO31_R2V_P,
    # Video model constants — Extend
    VIDEO_MODEL_EXTEND_L, VIDEO_MODEL_EXTEND_P,
    VIDEO_MODEL_EXTEND_L_STD, VIDEO_MODEL_EXTEND_P_STD,
    VIDEO_MODEL_VEO21_EXTEND,
    # Video model constants — Reshoot/Camera
    VIDEO_MODEL_RESHOOT_L, VIDEO_MODEL_RESHOOT_P,
    # Video model constants — Object editing
    VIDEO_MODEL_INSERT, VIDEO_MODEL_INSERT_L, VIDEO_MODEL_INSERT_P,
    VIDEO_MODEL_REMOVE, VIDEO_MODEL_REMOVE_L, VIDEO_MODEL_REMOVE_P,
    # Video model constants — Upscaling (FREE!)
    VIDEO_MODEL_UPSCALER_1080P,
    # Aspect ratio / resolution
    VIDEO_AR_LANDSCAPE, VIDEO_AR_PORTRAIT,
    VIDEO_RES_1080P, VIDEO_RES_720P,
    # Camera motion presets (reshootMotionType values)
    RESHOOT_FORWARD, RESHOOT_BACKWARD, RESHOOT_LEFT, RESHOOT_RIGHT,
    RESHOOT_UP, RESHOOT_DOWN, RESHOOT_DOLLY_ZOOM_IN, RESHOOT_DOLLY_ZOOM_OUT,
    # Camera position presets (also reshootMotionType, confirmed from JS bundle)
    RESHOOT_POS_CENTER, RESHOOT_POS_LEFT, RESHOOT_POS_RIGHT,
    RESHOOT_POS_HIGH, RESHOOT_POS_LOW,
    RESHOOT_POS_CLOSER, RESHOOT_POS_FURTHER,
    # Human-readable alias dict
    CAMERA_PRESETS,
    # Mask utilities
    MASK_USAGE_TYPE,
    create_removal_mask,
    encode_mask_b64,
    # Model registry
    MODEL_REGISTRY,
)
from ._models import (
    AspectRatio,
    BatchResult,
    FlowConfig,
    GenerationMode,
    GenerationResult,
    GenerationStatus,
    ParsedPrompt,
    parse_prompt_file,
)

__version__ = "0.1.0"
__all__ = [
    # High-level client
    "FlowClient",
    # Low-level API
    "FlowAPI",
    # Response types
    "GeneratedImage",
    "VideoJob",
    "VideoStatus",
    "Credits",
    "Workflow",
    # Exceptions
    "FlowError",
    "AuthError",
    "NotLoggedInError",
    "GenerationError",
    "GenerationTimeout",
    "PolicyError",
    "DownloadError",
    "NoProjectError",
    "UIError",
    "InvalidArgumentError",
    "NotFoundError",
    "FeatureUnavailableError",
    # High-level models
    "FlowConfig",
    "GenerationMode",
    "GenerationResult",
    "GenerationStatus",
    "BatchResult",
    "AspectRatio",
    "ParsedPrompt",
    "parse_prompt_file",
    # Image constants
    "IMAGE_MODEL_NARWHAL", "IMAGE_MODEL_IMAGEN3",
    "IMAGE_AR_PORTRAIT", "IMAGE_AR_LANDSCAPE", "IMAGE_AR_SQUARE",
    # Video constants
    "VIDEO_MODEL_VEO31_FAST", "VIDEO_MODEL_VEO31_I2V",
    "VIDEO_MODEL_EXTEND_L", "VIDEO_MODEL_RESHOOT_L",
    "VIDEO_MODEL_INSERT", "VIDEO_MODEL_REMOVE",
    "VIDEO_AR_LANDSCAPE", "VIDEO_AR_PORTRAIT",
    # Image roles
    "IMAGE_ROLE_START", "IMAGE_ROLE_END", "IMAGE_ROLE_REFERENCE",
    # Video models — T2V
    "VIDEO_MODEL_VEO31_FAST", "VIDEO_MODEL_VEO31_FAST_P",
    "VIDEO_MODEL_VEO31_STD",  "VIDEO_MODEL_VEO31_STD_P",
    "VIDEO_MODEL_VEO21_T2V",  "VIDEO_MODEL_VEO20_STD",
    # Video models — I2V
    "VIDEO_MODEL_VEO31_I2V",  "VIDEO_MODEL_VEO31_I2V_P",
    "VIDEO_MODEL_VEO31_I2V_STD", "VIDEO_MODEL_VEO31_I2V_STD_P",
    "VIDEO_MODEL_VEO21_I2V",  "VIDEO_MODEL_VEO20_I2V_STD",
    # Video models — Start+End
    "VIDEO_MODEL_VEO31_SE",   "VIDEO_MODEL_VEO31_SE_P",
    "VIDEO_MODEL_VEO31_SE_STD","VIDEO_MODEL_VEO31_SE_STD_P",
    "VIDEO_MODEL_VEO21_SE",
    # Video models — Multi-reference (NEW)
    "VIDEO_MODEL_VEO31_R2V",  "VIDEO_MODEL_VEO31_R2V_P",
    # Video models — Extend
    "VIDEO_MODEL_EXTEND_L",   "VIDEO_MODEL_EXTEND_P",
    "VIDEO_MODEL_EXTEND_L_STD","VIDEO_MODEL_EXTEND_P_STD",
    "VIDEO_MODEL_VEO21_EXTEND",
    # Video models — Reshoot
    "VIDEO_MODEL_RESHOOT_L",  "VIDEO_MODEL_RESHOOT_P",
    # Video models — Object editing
    "VIDEO_MODEL_INSERT",  "VIDEO_MODEL_INSERT_L",  "VIDEO_MODEL_INSERT_P",
    "VIDEO_MODEL_REMOVE",  "VIDEO_MODEL_REMOVE_L",  "VIDEO_MODEL_REMOVE_P",
    # Video models — Upscaling (FREE)
    "VIDEO_MODEL_UPSCALER_1080P",
    # Resolution
    "VIDEO_AR_LANDSCAPE", "VIDEO_AR_PORTRAIT",
    "VIDEO_RES_1080P",    "VIDEO_RES_720P",
    # Camera motion presets
    "RESHOOT_FORWARD", "RESHOOT_BACKWARD", "RESHOOT_LEFT", "RESHOOT_RIGHT",
    "RESHOOT_UP", "RESHOOT_DOWN", "RESHOOT_DOLLY_ZOOM_IN", "RESHOOT_DOLLY_ZOOM_OUT",
    # Camera position presets
    "RESHOOT_POS_CENTER", "RESHOOT_POS_LEFT",   "RESHOOT_POS_RIGHT",
    "RESHOOT_POS_HIGH",   "RESHOOT_POS_LOW",
    "RESHOOT_POS_CLOSER", "RESHOOT_POS_FURTHER",
    "CAMERA_PRESETS",
    # Mask utilities
    "MASK_USAGE_TYPE",
    "create_removal_mask",
    "encode_mask_b64",
    # Model registry
    "MODEL_REGISTRY",
    # Mask helper
    "create_removal_mask",
    "__version__",
]
