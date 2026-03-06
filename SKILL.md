---
name: flow
description: Google Flow AI CLI and Python SDK for generating videos and images with Veo 3.1, Imagen, and all editing features. Commands: flow video, flow image, flow extend, flow extend-loop, flow camera, flow camera-pos, flow insert, flow remove, flow upscale, flow credits, flow models, flow poll, flow download, flow batch-images, flow batch-videos.
---

# Flow AI Skill

Automate Google Flow AI (labs.google/fx) for video and image generation.

## Installation

```bash
bash ~/.openclaw/workspace/skills/flow-py/install.sh
```

## Quick Start

```bash
flow credits                                    # Check balance
flow video "golden sunset over temple" --wait   # Text to Video (Veo 3.1)
flow image "serene lotus pond" -n 4             # Text to Image (x4)
flow extend <media_id> -w <workflow_id>         # Extend a video
flow extend-loop <media_id> -n 10 -w <wid>     # Make 10x longer video!
flow upscale <media_id> -w <wid>                # Free 1080p upscale
```

## All Commands

### Auth & Config
```bash
flow login                      # Open browser for Google auth
flow logout                     # Clear browser session
flow config                     # Show current configuration
flow use <project_id>           # Set active project
flow projects                   # List saved projects
flow workflows                  # List workflows in active project
```

### Generation
```bash
# Text to Video (Veo 3.1)
flow video "prompt" [options]
  -p, --project <id>           # Override project
  -m, --model "Veo 3.1 - Fast" # Model display name
  -a, --aspect landscape|portrait
  -n, --count 1-4
  --start <image_path>         # Image-to-Video mode
  --wait / --no-wait
  -o, --output <dir>
  --cdp                        # Use existing Chrome (port 9222)

# Text to Image (Imagen / Nano Banana)
flow image "prompt" [options]
  -a, --aspect landscape|portrait|square
  -n, --count 1-4
  -o, --output <dir>

# Image to Video (Frames mode)
flow frames <image_path> [options]
  -p, --prompt "motion description"
  -a, --aspect landscape|portrait
```

### Video Editing (requires media_id + workflow_id)
```bash
# Extend video
flow extend <media_id> -w <workflow_id> [options]
  -p, --prompt "what happens next"
  --wait / --no-wait

# Extend N times (infinite video!)
flow extend-loop <media_id> -w <wid> [options]
  -n, --iterations 5
  -p, --prompt "steady push forward"
  -o, --output <dir>

# Camera motion
flow camera <media_id> -w <wid> --motion <type>
  Types: dolly_in, dolly_out, orbit_left, orbit_right,
         orbit_up, orbit_low, dolly_zoom_in, dolly_zoom_out

# Camera position
flow camera-pos <media_id> -w <wid> --position <pos>
  Positions: center, left, right, high, low, closer, further

# Insert object
flow insert <media_id> -w <wid> -t "golden lotus flower"

# Remove object
flow remove <media_id> -w <wid> --x 0.5 --y 0.5

# Upscale (FREE!)
flow upscale <media_id> -w <wid> [-r 1080p|4k]
```

### Status & Download
```bash
flow poll <media_id>             # Check generation status
flow poll <media_id> --wait      # Wait until complete
flow download <media_id> -o .    # Download video/image
flow download-all [-w wid] -o .  # Download all from workflow
```

### Batch Operations
```bash
flow batch-images prompts.txt -n 4 -o ./gallery
flow batch-videos prompts.txt -o ./videos
```

### Info
```bash
flow credits                    # Show credits remaining
flow models                     # List all models with costs
flow models --json              # Full model config as JSON
```

## Architecture

All generation commands use UI automation + network interception to bypass
reCAPTCHA Enterprise score requirements. Read-only commands (credits, poll,
models) use the direct REST API.

| File | Purpose |
|---|---|
| `flow/_api.py` | Direct REST API client (all endpoints) |
| `flow/_browser.py` | Playwright browser lifecycle (persistent + CDP) |
| `flow/_client.py` | High-level FlowClient combining API + UI + interceptor |
| `flow/_flow_ui.py` | UI automation (selectors, clicks, form filling) |
| `flow/_ui_interceptor.py` | Network request/response capture |
| `flow/_models.py` | Data models, enums, prompt file parser |
| `flow/_exceptions.py` | Exception hierarchy |
| `flow/_storage.py` | Config + project persistence (~/.flow-py/) |
| `flow/cli/main.py` | Click CLI with all commands |

## Python API

```python
import asyncio
from flow import FlowClient

async def main():
    async with await FlowClient.create(
        project_id="4f3c93f5-...",
        cdp_url="http://127.0.0.1:9222",
    ) as client:
        # Credits
        credits = await client.get_credits()
        print(f"Credits: {credits.credits}")

        # Generate video
        jobs = await client.generate_video("golden lotus at dawn")
        status = await client.wait_for_video(jobs[0])
        await client.download(status.fife_url, "output.mp4")

        # Extend loop (infinite video!)
        extensions = await client.extend_loop(
            media_id, workflow_id, iterations=10,
            prompt="camera slowly pushes forward",
            output_dir="./extended",
        )

asyncio.run(main())
```
