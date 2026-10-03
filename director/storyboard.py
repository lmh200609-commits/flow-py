"""
AI Director Storyboard Planner
Decomposes high-level film narratives into coherent multi-shot storyboards with unified style anchors.
"""

import uuid
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from .prompt_compiler import PromptCompiler, PromptSpec, ShotType, CameraMovement, LightingStyle, LensGear, ColorGrade, GENRE_PRESETS


@dataclass
class StoryboardShot:
    shot_index: int
    shot_name: str
    description: str
    prompt: str
    camera_movement: str
    duration_s: int = 10
    task_id: Optional[str] = None
    status: str = "pending"  # pending | rendering | completed | failed
    video_path: Optional[str] = None
    preview_url: Optional[str] = None
    error: Optional[str] = None


@dataclass
class StoryboardPlan:
    storyboard_id: str
    title: str
    genre: str
    style_anchor: str
    shots: List[StoryboardShot] = field(default_factory=list)
    status: str = "draft"  # draft | rendering | assembling | completed | failed
    current_shot_index: int = 0
    final_video_path: Optional[str] = None
    final_video_url: Optional[str] = None
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class StoryboardPlanner:
    """Plans multi-shot cinematics with narrative progression and visual consistency."""

    @staticmethod
    def create_storyboard(
        title: str,
        narrative: str,
        genre: str = "sci-fi",
        num_shots: int = 3,
        style_anchor: Optional[str] = None,
        custom_shots: Optional[List[Dict[str, Any]]] = None
    ) -> StoryboardPlan:
        sb_id = str(uuid.uuid4())
        genre_key = genre.lower() if genre.lower() in GENRE_PRESETS else "sci-fi"
        preset = GENRE_PRESETS[genre_key]

        anchor = style_anchor or f"Unified {genre} cinematic world, consistent lighting and character design across cuts"

        shots: List[StoryboardShot] = []

        if custom_shots:
            for idx, c in enumerate(custom_shots, start=1):
                raw_p = c.get("prompt") or c.get("description") or narrative
                compiled_p = PromptCompiler.auto_enhance(
                    raw_prompt=raw_p,
                    genre=genre,
                    style_anchor=anchor,
                    shot_type=c.get("shot_type")
                )
                shots.append(StoryboardShot(
                    shot_index=idx,
                    shot_name=c.get("shot_name", f"Shot {idx}"),
                    description=c.get("description", raw_p),
                    prompt=compiled_p,
                    camera_movement=c.get("camera_movement", "Slow Dolly-In"),
                    duration_s=c.get("duration_s", 10)
                ))
        else:
            # Automatic 3-Act Progression:
            # Shot 1: Establishing / Environment & Context
            # Shot 2: Medium / Character Action & Intrigue
            # Shot 3: Close-up / Climax & Resolution
            shot_templates = [
                {
                    "name": "镜头 1：环境全景建立 (Establishing)",
                    "action_prefix": f"Panoramic wide establishing view of the scene: {narrative}",
                    "shot_type": ShotType.ESTABLISHING,
                    "move": CameraMovement.FPV_DRONE
                },
                {
                    "name": "镜头 2：主体与核心动作 (Main Action)",
                    "action_prefix": f"Focused tracking medium shot following the central characters: {narrative}",
                    "shot_type": ShotType.MEDIUM,
                    "move": CameraMovement.TRACKING
                },
                {
                    "name": "镜头 3：特写高潮与情感反应 (Climax / Close-up)",
                    "action_prefix": f"Intense dramatic close-up capturing dynamic details and tension: {narrative}",
                    "shot_type": ShotType.CLOSE_UP,
                    "move": CameraMovement.SLOW_DOLLY_IN
                }
            ]

            # Adjust to requested num_shots
            templates_to_use = shot_templates[:max(1, min(num_shots, len(shot_templates)))]
            while len(templates_to_use) < num_shots:
                extra_idx = len(templates_to_use) + 1
                templates_to_use.append({
                    "name": f"镜头 {extra_idx}：场景延伸推进 (Continuation)",
                    "action_prefix": f"Dynamic cinematic continuation: {narrative}",
                    "shot_type": ShotType.WIDE,
                    "move": CameraMovement.SLOW_DOLLY_OUT
                })

            for idx, tmpl in enumerate(templates_to_use, start=1):
                spec = PromptSpec(
                    subject_action=tmpl["action_prefix"],
                    shot_type=tmpl["shot_type"],
                    movement=tmpl["move"],
                    lighting=preset["lighting"],
                    lens=preset["lens"],
                    color=preset["color"],
                    style_anchor=anchor,
                    extra_keywords=preset["keywords"]
                )
                compiled_prompt = PromptCompiler.compile(spec)

                shots.append(StoryboardShot(
                    shot_index=idx,
                    shot_name=tmpl["name"],
                    description=f"第 {idx} 幕：{narrative}",
                    prompt=compiled_prompt,
                    camera_movement=tmpl["move"].name.replace("_", " ").title(),
                    duration_s=10
                ))

        return StoryboardPlan(
            storyboard_id=sb_id,
            title=title,
            genre=genre,
            style_anchor=anchor,
            shots=shots,
            status="draft"
        )

