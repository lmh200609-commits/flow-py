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

from ._client import FlowClient
from ._exceptions import (
    AuthError,
    DownloadError,
    FlowError,
    GenerationError,
    GenerationTimeout,
    NoProjectError,
    NotLoggedInError,
    PolicyError,
    UIError,
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
    "FlowClient",
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
    # Models
    "FlowConfig",
    "GenerationMode",
    "GenerationResult",
    "GenerationStatus",
    "BatchResult",
    "AspectRatio",
    "ParsedPrompt",
    "parse_prompt_file",
    "__version__",
]
