# flow-py 🎬

> Unofficial Python API & CLI for [Google Flow AI](https://labs.google/fx/tools/flow) — full programmatic control of video and image generation.

[![PyPI](https://img.shields.io/badge/pypi-flow--py-blue)](https://pypi.org/project/flow-py/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

Inspired by [notebooklm-py](https://github.com/teng-lin/notebooklm-py). Uses Playwright browser automation to drive Google Flow AI — no undocumented API hacking needed.

---

> ⚠️ **Unofficial** — uses browser automation. Google can change the UI at any time.  
> Not affiliated with Google. For research and personal projects only.

---

## Features

| Capability | CLI | Python API |
|---|---|---|
| Text → Video (Veo 3) | ✅ | ✅ |
| Text → Image (Imagen / Nano Banana 2) | ✅ | ✅ |
| Image → Video (I2V) | ✅ | ✅ |
| Multi-reference Video (R2V) | ✅ | ✅ |
| Extend Video | ✅ | ✅ |
| Extend Loop (make arbitrarily long videos) | ✅ | ✅ |
| Upscale to 1080p / 4K (**free, 0 credits**) | ✅ | ✅ |
| Camera Motion (Dolly, Orbit, Zoom…) | ✅ | ✅ |
| Camera Position (Stationary variants) | ✅ | ✅ |
| Insert Object into Video | ✅ | ✅ |
| Remove Object from Video | ✅ | ✅ |
| Batch generation (prompts file) | ✅ | ✅ |
| Project & workflow management | ✅ | ✅ |
| Credit balance check | ✅ | ✅ |
| Media download | ✅ | ✅ |

---

## How It Works

Google Flow AI's generation endpoints are protected by **reCAPTCHA Enterprise**. Tokens generated programmatically are rejected with 403. The only way to get valid tokens is through **real UI button clicks**.

flow-py solves this with a two-layer architecture:

- **Read-only ops** (credits, model config, poll status) → direct HTTP via `requests` / `aiohttp`
- **Generation ops** → Playwright browser automation + network interception (`UIInterceptor`)

The `UIInterceptor` listens to all `aisandbox-pa.googleapis.com` traffic, waits for the real button click to fire the reCAPTCHA, then captures the full request/response for result extraction.

---

## Installation

```bash
# From PyPI
pip install flow-py

# Or from source
git clone https://github.com/eddiefu576/flow-py
cd flow-py
pip install -e ".[dev]"
playwright install chromium
```

---

## Quick Start

### CLI

```bash
# Authenticate once (opens browser)
flow login

# Generate a video
flow video "Temple bells ring as golden mist rises over sacred mountains"

# Generate images
flow image "Crystal lotus floating on sacred mountain lake" -n 4

# Extend a video
flow extend <media_id> --prompt "Continue the scene with wind and light"

# Upscale to 1080p (FREE!)
flow upscale <media_id>

# Apply camera motion
flow camera <media_id> --motion dolly-in

# Check credits
flow credits
```

### Python API

```python
import asyncio
from flow import FlowClient

async def main():
    async with await FlowClient.create(
        project_id="your-project-id",
        cdp_url="http://127.0.0.1:9222",  # attach to existing Chrome
    ) as client:

        # Check credits
        credits = await client.get_credits()
        print(f"Credits: {credits}")

        # Text → Video
        job = await client.generate_video(
            "Golden lotus temple at dusk, cinematic camera sweep",
            aspect="portrait",
        )
        result = await client.wait_for_video(job)
        print(f"Video ready: {result.media_name}")

        # Text → Image (synchronous, ~45s)
        images = await client.generate_image(
            "Sacred mountain lake at dawn",
            count=4,
        )
        for img in images:
            print(f"Image: {img.fife_url}")

        # Extend video
        extended = await client.extend_video(
            result.media_name,
            prompt="Continue with wind sweeping through the valley",
        )

        # Upscale (FREE!)
        hd_name = await client.upscale_video(result.media_name)

asyncio.run(main())
```

---

## CLI Reference

```
flow video      <PROMPT>         Text → Video (Veo)
flow image      <PROMPT>         Text → Image (Imagen / Nano Banana 2)
flow frames     <IMG> <PROMPT>   Image → Video (I2V / frame-to-video)
flow extend     <MEDIA_ID>       Extend a video (make it longer)
flow extend-loop <MEDIA_ID>      Extend N times in sequence
flow upscale    <MEDIA_ID>       Upscale to 1080p (FREE)
flow camera     <MEDIA_ID>       Apply camera motion
flow camera-pos <MEDIA_ID>       Apply camera position change
flow insert     <MEDIA_ID>       Insert object with text prompt
flow remove     <MEDIA_ID>       Remove object with mask

flow credits                     Show remaining credits
flow models                      List all available models + costs
flow projects                    List saved projects
flow use        <PROJECT_ID>     Set active project
flow workflows                   List workflows in active project
flow poll       <MEDIA_ID>       Poll video generation status
flow download   <MEDIA_ID>       Download generated media
flow download-all                Download all media from active workflow
flow batch-images <FILE>         Batch image generation from prompts file
flow batch-videos <FILE>         Batch video generation from prompts file
flow login                       Authenticate with Google
flow logout                      Clear saved session
flow config                      Show current configuration
```

---

## Camera Motions

| Value | Description |
|---|---|
| `dolly-in` / `dolly-out` | Camera moves toward / away from subject |
| `orbit-left` / `orbit-right` | Orbital pan around subject |
| `orbit-up` / `orbit-low` | Orbital tilt |
| `dolly-zoom-in` / `dolly-zoom-out` | Hitchcock effect |
| `pan-left` / `pan-right` | Horizontal pan |
| `tilt-up` / `tilt-down` | Vertical tilt |
| `crane-up` / `crane-down` | Vertical lift |

## Camera Positions

| Value | Description |
|---|---|
| `center` | Stationary center |
| `left` / `right` | Offset left / right |
| `higher` / `lower` | Offset up / down |
| `closer` / `further` | Offset closer / further |

---

## Models

| Model | Type | Cost |
|---|---|---|
| `veo_3_1_t2v_fast` | T2V | 20–100 cr |
| `veo_3_1_upsampler_1080p` | Upscale | **FREE** |
| `veo_3_1_extend_fast_landscape` | Extend | 20 cr |
| `veo_3_1_r2v_fast_landscape` | Multi-ref | 20 cr |
| `veo_3_0_reshoot_landscape` | Camera | 20 cr |
| `veo_2_0_object_insertion_landscape` | Insert | 20 cr |
| `veo_2_0_object_removal_landscape` | Remove | 20 cr |
| `nano_banana_2` / `imagen` | T2I | varies |

---

## Batch Prompts File

```
# Plain text (blank-line separated)
A golden Buddha on a lotus throne, divine rays

Subhuti meditating, white hair, golden light

# Tagged blocks
[V1-S1] Establishing wide shot of golden pagoda

[V1-S2] Close-up of lotus petals opening at dawn

# Image→Video pipeline (image_prompt ||| video_prompt)
[V1-S1] Golden Buddha statue ||| Slow zoom-in with particles rising
```

---

## Known Limitations

1. **reCAPTCHA** — all generation ops require real browser clicks; headless automation may fail
2. **Session required** — must be logged in via `flow login` or attach to an existing Chrome CDP session
3. **Image generation** — T2I is synchronous, takes 45–60 seconds
4. **Settings panel** — switching Video ↔ Image mode via the UI pill can be unreliable; workaround: click an image thumbnail first

---

## Architecture

```
flow/
├── _api.py            # Direct API calls (read-only: credits, poll, config)
├── _browser.py        # BrowserManager — Playwright launch + CDP attach
├── _client.py         # FlowClient — main public API
├── _exceptions.py     # Custom exceptions (AuthError, GenerationTimeout…)
├── _flow_ui.py        # UI automation (click Extend, fill prompt, draw mask…)
├── _ui_interceptor.py # Network interceptor — captures reCAPTCHA-signed calls
├── _models.py         # Dataclasses: VideoJob, GeneratedImage, BatchResult…
├── _storage.py        # Config persistence (~/.flow/config.json)
├── _downloader.py     # Media download helpers
├── cli/
│   └── main.py        # Click-based CLI (23 commands)
└── __init__.py        # Public exports
```

---

## Credits

- Inspired by [notebooklm-py](https://github.com/teng-lin/notebooklm-py) by teng-lin
- Google Flow AI: https://labs.google/fx/tools/flow

---

## License

[MIT License](LICENSE) — see LICENSE file.
