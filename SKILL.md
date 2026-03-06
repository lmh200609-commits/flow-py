# flow-py Skill

Automate Google Flow AI (labs.google/fx) image and video generation via the `flow` CLI or Python API.

## Installation

```bash
bash ~/.openclaw/workspace/skills/flow-py/install.sh
```

First-time auth (one-time per machine):
```bash
flow login
```
This opens a browser window. Sign into Google, navigate to Flow, then press ENTER in the terminal.

## When to Use This Skill

Use `flow` (CLI) or `FlowClient` (Python) when:
- Generating AI images in bulk from text prompts (Imagen / Nano Banana Pro)
- Generating AI videos from text prompts (Veo)
- Converting static images to animated videos (Frame-to-Video)
- Running image→video pipelines from a prompts file
- Automating any batch workflow on Google Flow AI

Do **not** use this skill for:
- NotebookLM (use `notebooklm` CLI)
- Non-Flow AI image generation (use other tools)

## CLI Commands

### One-off generation
```bash
# Image
flow generate image "golden Buddha on lotus throne, divine rays, 8K"
flow generate image "cherry blossoms" --aspect 9:16 --output ~/Desktop/imgs

# Video (Veo, 30-90s generation time)
flow generate video "aurora borealis, cinematic time-lapse"
flow generate video "temple bells, slow motion" --duration 5s --aspect 9:16

# Animate a still image
flow generate frame slide.png "slow zoom-in with golden particles"
flow generate frame image.jpg "gentle orbit left, wind in trees" --duration 5s
```

### Batch mode (most common for pipelines)
```bash
# Process a prompts file
flow batch prompts.txt --mode image --output-dir ./gallery

# Video batch
flow batch prompts.txt --mode video --output-dir ./videos

# Pipeline mode (image||| syntax auto-detected)
flow batch pipeline.txt
```

### Project management
```bash
flow projects list         # Show known projects
flow projects create       # Create a new project
flow projects use <id>     # Switch project
flow status                # Check auth + config
```

### Config
```bash
flow config show
flow config set headless false            # Watch browser (debugging)
flow config set generation_timeout_s 600  # Longer timeout for slow runs
flow config set inter_prompt_delay_s 3    # Pause between prompts
```

## Prompts File Format

Create a text file, e.g. `prompts.txt`:

```
# Comments start with #

[V1-S1] Establishing wide shot of golden Buddha on lotus throne, celestial clouds

[V1-S2] Close-up of Subhuti with white hair, contemplative expression

[V1-S3] Grand temple exterior, cherry blossoms, golden hour
```

**Pipeline mode** (image → video in one batch):
```
[V1-S1] Golden Buddha on lotus throne ||| Slow zoom-in with golden particles rising
[V1-S2] Subhuti meditating, white hair ||| Gentle camera orbit, wind stirring robes
```

## Python API (for agents/scripts)

```python
import asyncio
from flow import FlowClient, GenerationMode, AspectRatio

async def main():
    async with await FlowClient.create() as client:

        # Single image
        r = await client.generate_image(
            "golden Buddha, celestial light",
            output_dir="./outputs",
            aspect_ratio=AspectRatio.PORTRAIT,
        )
        print(r.primary_file)  # Path to downloaded PNG

        # Single video
        r = await client.generate_video(
            "aurora borealis, cinematic",
            output_dir="./videos",
        )

        # Frame-to-video
        r = await client.generate_frame_to_video(
            image_path="./slide.png",
            prompt="slow zoom, particles rise",
            output_dir="./animated",
        )

        # Batch
        batch = await client.batch_generate(
            "prompts.txt",
            mode=GenerationMode.IMAGE,
            output_dir="./gallery",
        )
        print(f"{batch.completed}/{batch.total} succeeded")

        # Streaming batch (real-time progress)
        async for result in client.stream_batch("prompts.txt"):
            print("✅" if result.succeeded else "❌", result.prompt[:50])

asyncio.run(main())
```

## Troubleshooting

| Error | Fix |
|---|---|
| `Auth error` | Run `flow login` |
| `No active project` | Run `flow projects create` or `flow login` |
| Timeout | Run with `--no-headless` to see what's happening; or `flow config set generation_timeout_s 600` |
| Policy rejection | Revise the prompt |
| Selector failed (UIError) | Flow UI may have changed; check `flow --debug generate image "test"` |

## Architecture Overview

| File | Purpose |
|---|---|
| `flow/__init__.py` | Package exports, public API surface |
| `flow/_models.py` | Data models (enums, dataclasses), prompt file parser |
| `flow/_exceptions.py` | Exception hierarchy (FlowError, AuthError, PolicyError, etc.) |
| `flow/_storage.py` | `~/.flow-py/` config + project persistence (JSON) |
| `flow/_browser.py` | Playwright browser lifecycle manager, persistent context |
| `flow/_client.py` | Main async `FlowClient` API (generate, batch, project mgmt) |
| `flow/_downloader.py` | Robust media downloader (URL extraction + aiohttp download) |
| `flow/_gallery.py` | `GalleryWatcher`: DOM snapshot, wait-for-new, latest media src |
| `flow/_flow_ui.py` | `FlowUI`: High-level UI selectors/interactions for Flow |
| `flow/cli/main.py` | Click CLI root, login/batch/projects/config/status commands |
| `flow/cli/_generate.py` | `generate image/video/frame` subcommands (refactored) |
| `tests/test_models.py` | Tests for models, prompt parser, safe_filename |
| `tests/test_storage.py` | Tests for config/project persistence |

### Key design patterns
- **Persistent Playwright context**: Session cookies survive across CLI runs (no re-login)
- **Multiple selector strategies**: Each UI method tries aria-label, role, text, CSS class, then JS fallback
- **Response interception**: Captures `storage.googleapis.com` URLs during generation for direct download
- **Gallery polling**: Watches DOM for new items after clicking Generate
- **Pipeline mode**: `|||` syntax in prompt files chains image generation -> frame-to-video animation

## Troubleshooting (Extended)

| Problem | Cause | Fix |
|---|---|---|
| `Auth error: Not logged in` | No session cookies | Run `flow login` |
| `No active project` | Config missing project | Run `flow projects create` or `flow login` |
| Generation times out | Slow network or UI changed | `flow config set generation_timeout_s 600`; try `--no-headless` |
| Policy rejection | Google content filter | Revise the prompt text |
| UI changed / selector failed | Flow UI updated | Update selectors in `_flow_ui.py`; check with `--debug` |
| `input()` blocks event loop | Bug in async code | Fixed: uses `run_in_executor` |
| Import errors on CLI | Package not installed | Run `pip3 install -e ".[dev]"` |
| `asyncio.run()` nesting | Calling from inside event loop | CLI uses sync Click commands that call `asyncio.run()` correctly |
| Download fails but URL intercepted | GCS URL expired | Increase `download_timeout_s` in config |

## Integration with Buddhist Video Pipeline

For 大般若经 video slides, use batch mode with 9:16 portrait images:

```bash
# Generate slide images for one volume
flow batch /tmp/vol_042_prompts.txt \
    --mode image \
    --aspect 9:16 \
    --output-dir ~/Desktop/Vol042-slides

# Then animate key slides to video
flow batch /tmp/vol_042_pipeline.txt \
    --output-dir ~/Desktop/Vol042-videos
```

Example prompt format for Buddhist slides:
```
[S1] 《大般若波罗蜜多经》第四十二卷，金色佛光，莲花宝座，庄严法界

[S2] 须菩提合掌问法，白发长者，金色光芒萦绕，禅定深处
```
