# flow-py 🎬

> Unofficial Python CLI & API for [Google Flow AI](https://labs.google/fx/tools/flow) — bulk image/video generation automation.

Inspired by [notebooklm-py](https://github.com/teng-lin/notebooklm-py). Uses Playwright for browser automation so no private API reverse-engineering is needed.

⚠️ **Unofficial** — uses browser automation. Google can change the UI at any time.

---

## Features

| Capability | CLI | Python API |
|---|---|---|
| Text → Image (Imagen / Nano Banana) | ✅ | ✅ |
| Text → Video (Veo) | ✅ | ✅ |
| Image → Video (Frame-to-Video) | ✅ | ✅ |
| Image → Video Pipeline (`\|\|\|` syntax) | ✅ | ✅ |
| Batch processing (prompts file) | ✅ | ✅ |
| Streaming batch (async generator) | — | ✅ |
| Project management | ✅ | ✅ |
| Session persistence (no re-login) | ✅ | ✅ |
| Media URL interception | auto | auto |
| Progress display (Rich) | ✅ | — |

---

## Installation

```bash
# From the skill directory
bash install.sh

# Or with a self-contained venv
bash install.sh --venv

# Dev/editable mode
bash install.sh --dev
```

---

## Quick Start

```bash
# 1. Authenticate (one-time — opens browser)
flow login

# 2. Generate
flow generate image "golden Buddha on lotus throne, celestial clouds, 8K"
flow generate video "aurora borealis, time-lapse, cinematic" --output ./clips
flow generate frame buddha.png "slow zoom-in with golden particles rising"

# 3. Batch
flow batch prompts.txt --mode image --output-dir ./gallery
```

---

## Prompts File Format

### Plain text
```
A golden Buddha on a lotus throne, celestial clouds
Subhuti meditating, white hair, divine light
```

### Tagged blocks (blank-line separated)
```
[V1-S1] Establishing wide shot of golden Buddha on lotus throne, divine rays

[V1-S2] Close-up of Subhuti, contemplative expression, golden particles
```

### Image → Video Pipeline (image_prompt ||| video_prompt)
```
[V1-S1] Golden Buddha on lotus throne ||| Slow zoom-in with golden particles rising
[V1-S2] Subhuti close-up, white hair  ||| Gentle camera orbit, wind stirring robes
```

---

## CLI Reference

```
flow login                          Authenticate with Google (opens browser)
flow status                         Check auth + active project
flow generate image  <PROMPT>       Text → image
flow generate video  <PROMPT>       Text → video (Veo)
flow generate frame  <IMG> <PROMPT> Image → video (Frame-to-Video)
flow batch <FILE>                   Process a prompts file
flow projects list                  List known projects
flow projects create [NAME]         Create a new project
flow projects use <ID|URL>          Switch active project
flow config show                    View config
flow config set KEY VALUE           Edit config
```

### generate image
```
flow generate image "cherry blossoms in rain, impressionist"
flow generate image "mountain lake" --aspect 9:16 --output ./photos
flow generate image "portrait" -n 4 --no-headless
```

### generate video
```
flow generate video "ocean waves at sunset, slow motion"
flow generate video "temple bells swinging" --duration 5s --aspect 9:16
```

### generate frame
```
flow generate frame slide.jpg "gentle camera pan, wind in trees"
flow generate frame image.png "orbit left, particles rise" --duration 5s
```

### batch
```
flow batch prompts.txt
flow batch prompts.txt --mode video --output-dir ./videos
flow batch pipeline.txt --delay 5
```

---

## Python API

```python
import asyncio
from flow import FlowClient, GenerationMode, AspectRatio

async def main():
    async with await FlowClient.create() as client:

        # Generate image
        result = await client.generate_image(
            "golden Buddha on lotus throne, 8K",
            output_dir="./outputs",
            aspect_ratio=AspectRatio.PORTRAIT,
        )
        print("Saved to:", result.primary_file)

        # Generate video
        result = await client.generate_video(
            "aurora borealis, cinematic time-lapse",
            output_dir="./videos",
        )

        # Frame-to-video
        result = await client.generate_frame_to_video(
            image_path="./slide.png",
            prompt="slow zoom-in, golden particles",
            output_dir="./animated",
        )

        # Batch with progress callback
        def progress(result, idx, total):
            print(f"[{idx+1}/{total}] {'✅' if result.succeeded else '❌'} {result.prompt[:40]}")

        batch = await client.batch_generate(
            "prompts.txt",
            mode=GenerationMode.IMAGE,
            output_dir="./gallery",
            on_result=progress,
        )
        print(f"Done: {batch.completed}/{batch.total}")

        # Streaming batch
        async for result in client.stream_batch("prompts.txt", mode=GenerationMode.VIDEO):
            print(result.primary_file)

asyncio.run(main())
```

---

## Configuration

```bash
flow config show
flow config set headless false           # Show browser window
flow config set default_output_dir ~/Desktop/flow-output
flow config set generation_timeout_s 600
flow config set inter_prompt_delay_s 3.0
```

Config is stored in `~/.flow-py/config.json`.

---

## How It Works

1. **Auth**: Playwright opens a persistent Chromium profile at `~/.flow-py/browser-profile/`. Google session cookies persist across runs — no re-login needed.
2. **Mode switching**: Clicks the appropriate tab in Flow's UI (Create Image / Text-to-Video / Frame-to-Video).
3. **Prompt**: Fills the textarea and clicks Generate.
4. **Wait**: Polls the DOM gallery for new items, also intercepts `storage.googleapis.com` network responses to capture media URLs directly.
5. **Download**: Downloads via intercepted URL (aiohttp) or by clicking the download button.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `Auth error: Not logged in` | Run `flow login` |
| `No active project` | Run `flow projects create` or `flow login` (which auto-captures project) |
| Generation times out | Run with `--no-headless` to watch what's happening |
| Policy rejection | Revise your prompt |
| UI changed / selector failed | Open an issue — selectors may need updating |

---

## License

MIT. Not affiliated with Google.

---

## Test Results (Confirmed Working)

| Feature | Status | Notes |
|---------|--------|-------|
| T2V (Text → Video) | ✅ CONFIRMED | `veo_3_1_t2v_fast`, 20-100cr |
| T2I (Text → Image) | ✅ CONFIRMED | `Nano Banana 2` / `Imagen`, 45-60s sync |
| I2V (Image → Video) | ✅ CONFIRMED | Frame-to-video pipeline |
| Extend Video | ✅ CONFIRMED | `veo_3_1_extend_fast_landscape` |
| Extend Loop | ⏳ Ready | Sequential extend N times |
| Upscale | ✅ CONFIRMED | `veo_3_1_upsampler_1080p`, **FREE (0cr)** |
| Camera Motion | ✅ CONFIRMED | Dolly/Orbit variants |
| Camera Position | ✅ CONFIRMED | Stationary_* presets |
| Insert Object | ✅ CONFIRMED | `veo_2_0_object_insertion_landscape` |
| Remove Object | ✅ CONFIRMED | Requires mask image |
| Multi-Reference (R2V) | ✅ Ready | `veo_3_1_r2v_fast_*` |

---

## Known Limitations

1. **reCAPTCHA Enterprise**: All generation endpoints require valid reCAPTCHA tokens. Direct API calls return 403. Must use UI automation (Playwright) to click real UI buttons.

2. **CDP Connection**: For development, connect to existing Chrome at `http://127.0.0.1:9222` to bypass login. Production use requires full browser launch.

3. **Image Generation Timeout**: T2I is synchronous and takes 45-60 seconds. Default timeout is 120s.

4. **Settings Panel**: The mode switch (Video ↔ Image) via settings pill can be unreliable. Workaround: click an image thumbnail to enter image edit mode first.

---

## Architecture

```
flow/
├── _api.py           # Direct API calls (read-only ops)
├── _browser.py       # BrowserManager (Playwright + CDP)
├── _client.py        # FlowClient (main API)
├── _exceptions.py    # Custom exceptions
├── _flow_ui.py       # UI automation (clicks, fills, etc.)
├── _ui_interceptor.py# Network interceptor for API calls
├── cli/
│   └── main.py       # Click-based CLI (23 commands)
└── __init__.py       # Public exports
```

---

## Credits

- Inspired by [notebooklm-py](https://github.com/teng-lin/notebooklm-py)
- Google Flow AI: https://labs.google/fx/tools/flow

---

## License

MIT License — see LICENSE file.
