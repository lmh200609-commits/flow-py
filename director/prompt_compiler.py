"""
AI Director Prompt Compiler
Inspired by Open-Sora Prompt Refinement & Show-1 Cinematic Grammar.
Transforms natural language requests into high-fidelity, diffusion-optimized prompts for Google Veo 3.1.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any


class ShotType(str, Enum):
    ESTABLISHING = "establishing wide shot"
    WIDE = "wide cinematic shot"
    MEDIUM = "medium shot"
    MEDIUM_CLOSE_UP = "medium close-up shot"
    CLOSE_UP = "intimate close-up shot"
    EXTREME_CLOSE_UP = "extreme detailed close-up shot"
    POV = "first-person point-of-view shot"
    DRONE_AERIAL = "sweeping aerial high-angle shot"


class CameraMovement(str, Enum):
    STATIC = "static camera with natural internal movement"
    SLOW_DOLLY_IN = "slow, smooth dolly-in towards the subject"
    SLOW_DOLLY_OUT = "gentle dolly-out revealing surrounding environment"
    TRACKING = "steady lateral tracking shot following the motion"
    CRANE_PEDESTAL = "smooth vertical crane pedestal shot"
    ORBIT = "graceful 360-degree orbiting camera movement"
    HANDHELD = "subtle realistic handheld camera motion with gentle organic breathing"
    FPV_DRONE = "dynamic cinematic FPV drone glide"


class LightingStyle(str, Enum):
    GOLDEN_HOUR = "warm golden hour glow with soft backlighting and warm lens flare"
    VOLUMETRIC_TYNDALL = "dramatic volumetric god rays and Tyndall beams cutting through dust"
    CHIAROSCURO = "moody chiaroscuro lighting with deep expressive shadows and bright highlights"
    NEON_CYBERPUNK = "vibrant neon cyberpunk lighting with cyan and magenta ambient reflections"
    DAPPLED_SUNLIGHT = "dappled sunlight filtering through lush tree canopy with delicate bokeh"
    DEEP_SPACE_RIM = "harsh single-point solar starlight with intense volumetric rim lighting"
    SOFT_STUDIO = "soft diffused high-key studio lighting with wrap-around fill"


class LensGear(str, Enum):
    IMAX_70MM = "shot on IMAX 70mm, crystal clear depth, hyper-detailed textures"
    ARRI_ALEXA_65 = "shot on ARRI Alexa 65, Master Anamorphic prime lens, subtle oval bokeh"
    VINTAGE_35MM = "35mm film grain, analog warmth, natural halation around highlights"
    MACRO_PROBE = "macro probe lens, microscopic edge-to-edge sharpness and shallow depth of field"


class ColorGrade(str, Enum):
    TEAL_ORANGE = "blockbuster teal and orange cinematic color grade"
    MAKOTO_SHINKAI = "Makoto Shinkai anime aesthetic, hyper-vibrant sky, clean pastel tones"
    KODAK_PORTRA = "Kodak Portra 400 skin tones, soft contrast, nostalgic filmic mood"
    NOIR_MONOCHROME = "high-contrast cinematic noir with rich silver tones"
    SCI_FI_COOL = "cool desaturated blue-slate palette with vivid accent emissions"


GENRE_PRESETS: Dict[str, Dict[str, Any]] = {
    "sci-fi": {
        "lighting": LightingStyle.DEEP_SPACE_RIM,
        "lens": LensGear.IMAX_70MM,
        "color": ColorGrade.SCI_FI_COOL,
        "keywords": ["hyper-realistic", "4k UHD", "volumetric atmosphere", "intricate mechanical details", "weightless drift"]
    },
    "romance": {
        "lighting": LightingStyle.DAPPLED_SUNLIGHT,
        "lens": LensGear.ARRI_ALEXA_65,
        "color": ColorGrade.MAKOTO_SHINKAI,
        "keywords": ["delicate emotional nuances", "gentle breeze flutter", "nostalgic atmosphere", "warm cinematic bokeh"]
    },
    "cyberpunk": {
        "lighting": LightingStyle.NEON_CYBERPUNK,
        "lens": LensGear.ARRI_ALEXA_65,
        "color": ColorGrade.TEAL_ORANGE,
        "keywords": ["wet asphalt rain reflections", "holographic neon flicker", "fog and steam", "gritty futuristic realism"]
    },
    "nature": {
        "lighting": LightingStyle.GOLDEN_HOUR,
        "lens": LensGear.IMAX_70MM,
        "color": ColorGrade.KODAK_PORTRA,
        "keywords": ["National Geographic cinematography", "ultra sharp natural textures", "organic environmental motion"]
    },
    "suspense": {
        "lighting": LightingStyle.CHIAROSCURO,
        "lens": LensGear.VINTAGE_35MM,
        "color": ColorGrade.NOIR_MONOCHROME,
        "keywords": ["tense atmospheric fog", "heavy silhouettes", "suspenseful pacing", "tactile realism"]
    }
}


@dataclass
class PromptSpec:
    subject_action: str
    shot_type: ShotType = ShotType.WIDE
    movement: CameraMovement = CameraMovement.TRACKING
    lighting: LightingStyle = LightingStyle.VOLUMETRIC_TYNDALL
    lens: LensGear = LensGear.ARRI_ALEXA_65
    color: ColorGrade = ColorGrade.TEAL_ORANGE
    style_anchor: Optional[str] = None
    extra_keywords: Optional[List[str]] = None


class PromptCompiler:
    """Compiles high-level storyboard specifications into diffusion-ready prompts."""

    @staticmethod
    def compile(spec: PromptSpec) -> str:
        parts: List[str] = []

        # 1. Shot & Framing
        parts.append(spec.shot_type.value)

        # 2. Subject & Primary Action
        parts.append(spec.subject_action.strip().rstrip("."))

        # 3. Camera Movement
        parts.append(spec.movement.value)

        # 4. Lighting & Atmosphere
        parts.append(spec.lighting.value)

        # 5. Lens, Gear & Color Grade
        parts.append(spec.lens.value)
        parts.append(spec.color.value)

        # 6. Style Anchor (Preserves consistent character/world identity across shots)
        if spec.style_anchor:
            parts.append(f"Visual style anchor: {spec.style_anchor}")

        # 7. Quality & Custom Tokens
        if spec.extra_keywords:
            parts.extend(spec.extra_keywords)
        else:
            parts.extend(["masterpiece", "8k resolution", "photorealistic", "smooth fluid motion"])

        return ", ".join(parts)

    @classmethod
    def auto_enhance(
        cls,
        raw_prompt: str,
        genre: str = "general",
        style_anchor: Optional[str] = None,
        shot_type: Optional[str] = None
    ) -> str:
        """Quickly enhances a casual prompt with cinematic parameters."""
        genre_key = genre.lower() if genre.lower() in GENRE_PRESETS else "sci-fi"
        preset = GENRE_PRESETS[genre_key]

        selected_shot = ShotType.WIDE
        if shot_type:
            for st in ShotType:
                if shot_type.lower() in st.name.lower() or shot_type.lower() in st.value.lower():
                    selected_shot = st
                    break

        spec = PromptSpec(
            subject_action=raw_prompt,
            shot_type=selected_shot,
            movement=CameraMovement.SLOW_DOLLY_IN,
            lighting=preset["lighting"],
            lens=preset["lens"],
            color=preset["color"],
            style_anchor=style_anchor,
            extra_keywords=preset["keywords"]
        )
        return cls.compile(spec)
