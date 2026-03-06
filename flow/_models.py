"""Data models for flow-py."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class GenerationMode(str, Enum):
    IMAGE = "image"               # Imagen / Nano Banana Pro
    VIDEO = "video"               # Veo text-to-video
    FRAME_TO_VIDEO = "frame"      # Existing image → animated video


class GenerationStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETE = "complete"
    FAILED = "failed"
    POLICY_REJECTED = "policy_rejected"
    SKIPPED = "skipped"


class AspectRatio(str, Enum):
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"
    SQUARE = "1:1"


class ImageModel(str, Enum):
    NANO_BANANA = "nano_banana"    # Nano Banana Pro
    IMAGEN = "imagen"              # Imagen 3


class VideoModel(str, Enum):
    VEO = "veo"                   # Latest Veo
    VEO_2 = "veo_2"


class VideoDuration(str, Enum):
    S5 = "5s"
    S8 = "8s"


class VideoStyle(str, Enum):
    """Visual style options for video generation (where supported)."""
    CLASSIC = "classic"
    WHITEBOARD = "whiteboard"
    KAWAII = "kawaii"
    ANIME = "anime"
    CINEMATIC = "cinematic"
    DOCUMENTARY = "documentary"


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------

@dataclass
class GenerationResult:
    """Represents a single generation (image or video)."""
    prompt: str
    mode: GenerationMode
    status: GenerationStatus
    # Set after download
    file_paths: list[Path] = field(default_factory=list)
    # Internal DOM id or index used to identify the item in the gallery
    gallery_index: Optional[int] = None
    # Direct media URLs if intercepted
    media_urls: list[str] = field(default_factory=list)
    error: Optional[str] = None
    elapsed_s: Optional[float] = None
    created_at: float = field(default_factory=time.time)

    @property
    def succeeded(self) -> bool:
        return self.status == GenerationStatus.COMPLETE

    @property
    def primary_file(self) -> Optional[Path]:
        return self.file_paths[0] if self.file_paths else None


@dataclass
class BatchResult:
    """Summary of a batch generation run."""
    mode: GenerationMode
    total: int
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[GenerationResult] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    @property
    def elapsed_s(self) -> Optional[float]:
        if self.finished_at:
            return self.finished_at - self.started_at
        return None

    def add(self, result: GenerationResult):
        self.results.append(result)
        if result.status == GenerationStatus.COMPLETE:
            self.completed += 1
        elif result.status == GenerationStatus.SKIPPED:
            self.skipped += 1
        else:
            self.failed += 1


@dataclass
class Project:
    """A Google Flow project."""
    id: str
    name: str
    url: str
    is_active: bool = False


@dataclass
class FlowConfig:
    """Persistent user configuration."""
    active_project_id: Optional[str] = None
    active_project_url: Optional[str] = None
    headless: bool = True
    default_output_dir: str = "."
    default_aspect_ratio: str = AspectRatio.LANDSCAPE.value
    default_image_count: int = 4
    download_timeout_s: int = 30
    generation_timeout_s: int = 300
    inter_prompt_delay_s: float = 2.0


# ---------------------------------------------------------------------------
# Prompt parsing
# ---------------------------------------------------------------------------

@dataclass
class ParsedPrompt:
    """A single prompt entry, optionally with a tag and frame image path."""
    text: str
    tag: Optional[str] = None              # e.g. "[V1-S1]"
    frame_image_path: Optional[str] = None  # For image→video pipeline (left of |||)
    video_prompt: Optional[str] = None      # Right of ||| in pipeline mode


def parse_prompt_file(path: str | Path) -> list[ParsedPrompt]:
    """Parse a prompts file.

    Supported formats:

    1. Plain text (one prompt per non-empty line):
        A golden Buddha on a lotus throne, celestial clouds
        Close-up of Subhuti, contemplative expression

    2. Tagged blocks (blank-line separated):
        [V1-S1] Establishing wide shot of golden Buddha on lotus throne

        [V1-S2] Close-up of Subhuti with white hair

    3. Image→Video pipeline (image prompt ||| video prompt):
        [V1-S1] Golden Buddha on lotus throne ||| Slow zoom-in with golden particles
        [V1-S2] Subhuti close-up ||| Gentle camera orbit with wind stirring robes

    Lines starting with # are treated as comments.
    """
    import re

    text = Path(path).read_text(encoding="utf-8")
    # Remove comments
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    # Re-join and split by blank lines → blocks
    raw_blocks = re.split(r"\n{2,}", "\n".join(lines))

    results: list[ParsedPrompt] = []
    tag_re = re.compile(r"^(\[[^\]]+\])\s*")

    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue

        # Each block may be a single line or multi-line (treated as one prompt)
        content = " ".join(block.splitlines()).strip()
        if not content:
            continue

        # Pipeline mode?
        if "|||" in content:
            left, right = content.split("|||", 1)
            left = left.strip()
            right = right.strip()
            # Extract tag from left
            m = tag_re.match(left)
            tag = m.group(1) if m else None
            image_prompt = tag_re.sub("", left).strip() if m else left
            results.append(ParsedPrompt(
                text=image_prompt,
                tag=tag,
                video_prompt=right,
            ))
        else:
            m = tag_re.match(content)
            tag = m.group(1) if m else None
            prompt_text = tag_re.sub("", content).strip() if m else content
            results.append(ParsedPrompt(text=prompt_text, tag=tag))

    return results
