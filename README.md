# Nature Video Automation (ntr-video-gen)

A production-quality local-first automation application for creating relaxing nature videos.
Runs entirely on local hardware with **no cloud AI dependencies**.

```
Natural-language prompt / script
            ↓
     Local LLM (LM Studio)
            ↓
  Video concept + scene plan
            ↓
         ComfyUI
            ↓
 Nature images / short video clips
            ↓
   Local music generation (stub / AI)
            ↓
     FFmpeg composition
            ↓
Final YouTube-ready video package
            ↓
One self-contained output directory
```

---

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation & Setup](#installation--setup)
- [Service Configuration](#service-configuration)
  - [1. LM Studio Setup](#1-lm-studio-setup)
  - [2. ComfyUI Setup](#2-comfyui-setup)
  - [3. FFmpeg Setup](#3-ffmpeg-setup)
  - [4. Local Music Setup](#4-local-music-setup)
- [Configuration](#configuration)
- [CLI Usage](#cli-usage)
  - [Dependency Check](#dependency-check)
  - [Dry-Run Planning](#dry-run-planning)
  - [Generating Videos](#generating-videos)
  - [Resuming Failed / Interrupted Projects](#resuming-failed--interrupted-projects)
- [Self-Contained Output Structure](#self-contained-output-structure)
- [YouTube Uploader Script](#youtube-uploader-script)
- [Running Tests](#running-tests)
- [Troubleshooting](#troubleshooting)

---

## Features

- **Local-First & Private:** Zero cloud telemetry, subscriptions, or external network calls.
- **Provider Abstractions:** Clean pluggable interfaces for LLM (`LMStudioProvider`), image/video generation (`ComfyUIProvider`), music (`MusicProvider`), and composition (`FFmpegRenderer`).
- **Flexible Aspect Ratios:** Strict presets for YouTube landscape (`1920x1080`, `1280x720`, `3840x2160`), Shorts/vertical (`1080x1920`, `720x1280`), square (`1080x1080`), and classic 4:3 (`1440x1080`).
- **ComfyUI Workflow Decoupling:** Workflow JSON templates reside outside source code in [`workflows/`](file:///c:/Users/pon.jeyakumar/.personal/ntr_video_gen/workflows) with dynamic parameter injection.
- **Seamless Audio Mixing:** Multi-track crossfades, volume balancing between music (`0.65`) and ambient nature audio (`0.35`).
- **Resumable State:** State tracking saves progress at every milestone in `project/project.json`, allowing recovery from interruptions or failed scenes without regenerating completed clips.
- **YouTube-Ready Bundle:** Each run generates metadata (`title.txt`, `description.txt`, `tags.txt`, `metadata.json`), video (`video.mp4`), thumbnail (`thumbnail.jpg`), and quality verification (`validation.json`).

---

## Prerequisites

- **OS:** Windows 10/11, macOS, or Linux.
- **Python:** 3.10+ (tested on Python 3.12).
- **FFmpeg:** FFmpeg 6.0+ with `ffprobe` (included in PATH or configured in `config/app.yaml`).
- **LM Studio:** Local LLM server hosting OpenAI-compatible API (e.g., `qwen/qwen3.8-27b` or `prism-ml/bonsai-27b`).
- **ComfyUI:** Running locally on port 8188.

---

## Installation & Setup

1. **Clone or navigate to the repository:**
   ```powershell
   cd c:\Users\pon.jeyakumar\.personal\ntr_video_gen
   ```

2. **Install Python dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```

3. **Configure Environment:**
   Copy `.env.example` to `.env` if you wish to override settings via environment variables:
   ```powershell
   cp .env.example .env
   ```

---

## Service Configuration

### 1. LM Studio Setup
1. Launch LM Studio.
2. Load your model of choice:
   - `qwen/qwen3.8-27b`
   - `prism-ml/bonsai-27b`
3. Start the local inference server (default endpoint: `http://localhost:1234/v1`).
4. Ensure the server has a context window large enough for detailed project plans (8192+ recommended).

### 2. ComfyUI Setup
1. Start ComfyUI (default endpoint: `http://127.0.0.1:8188`).
2. Make sure you have models installed in `models/checkpoints` or relevant folders.
3. Configure workflows in [`workflows/`](file:///c:/Users/pon.jeyakumar/.personal/ntr_video_gen/workflows):
   - `image_generation.json`: Workflow for generating still scenery frames.
   - `text_to_video.json`: Workflow for generating short nature motion clips.
   - `thumbnail_generation.json`: Workflow for YouTube thumbnail rendering.
4. Workflows support dynamic placeholders: `__param__positive_prompt`, `__param__negative_prompt`, `__param__width`, `__param__height`, `__param__seed`.

### 3. FFmpeg Setup
FFmpeg handles zoom/pan effects, clip crossfades (`xfade`), audio mixing (`amix`, `acrossfade`), and video packaging.
- If added to your system PATH: `ffmpeg` and `ffprobe` will be detected automatically.
- Alternatively, specify explicit binary paths in [`config/app.yaml`](file:///c:/Users/pon.jeyakumar/.personal/ntr_video_gen/config/app.yaml):
  ```yaml
  ffmpeg:
    binary: "C:\\Users\\pon.jeyakumar\\Applications\\ffmpeg-9.0.2-full_build\\bin\\ffmpeg.exe"
    ffprobe_binary: "C:\\Users\\pon.jeyakumar\\Applications\\ffmpeg-9.0.2-full_build\\bin\\ffprobe.exe"
  ```

### 4. Local Music Setup
- By default, `MUSIC_PROVIDER=stub` writes silent WAV audio matching scene durations to test end-to-end video composition.
- Pluggable AI audio providers (such as Meta AudioCraft / MusicGen) implement the `MusicProvider` ABC in [`app/providers/base.py`](file:///c:/Users/pon.jeyakumar/.personal/ntr_video_gen/app/providers/base.py).

---

## Configuration

Settings are managed in [`config/app.yaml`](file:///c:/Users/pon.jeyakumar/.personal/ntr_video_gen/config/app.yaml) and can be overridden by environment variables:

| Setting | YAML Key | Env Variable | Default |
|---|---|---|---|
| LM Studio Endpoint | `lm_studio.base_url` | `LM_STUDIO_BASE_URL` | `http://localhost:1234/v1` |
| LLM Model | `lm_studio.model` | `LM_STUDIO_MODEL` | `qwen/qwen3.8-27b` |
| ComfyUI Endpoint | `comfyui.base_url` | `COMFYUI_BASE_URL` | `http://127.0.0.1:8188` |
| Music Provider | `music.provider` | `MUSIC_PROVIDER` | `stub` |
| Video Duration | `video.default_duration_seconds` | `VIDEO_DEFAULT_DURATION_SECONDS` | `900` (15m) |
| Resolution Preset | `video.default_resolution` | `VIDEO_DEFAULT_RESOLUTION` | `1920x1080` |
| Video Codec | `ffmpeg.video_codec` | `FFMPEG_VIDEO_CODEC` | `libx264` |

---

## CLI Usage

### Dependency Check
Verify that FFmpeg, LM Studio, and ComfyUI endpoints are accessible:
```powershell
python -m app check
```

### Dry-Run Planning
To test prompt formulation, scene planning, and YouTube metadata generation without firing heavy rendering or ComfyUI calls:
```powershell
python -m app generate --prompt "A peaceful rainy mountain forest with deer and streams" --duration 5m --dry-run
```

### Generating Videos
Generate a complete video from a natural language prompt:
```powershell
python -m app generate --prompt "Misty alpine sunrise over lake and pine trees" --duration 15m --resolution 1920x1080
```

Generate using an input file:
```powershell
python -m app generate --input projects/rainy_mountains.txt --duration 30m
```

Options:
- `-p, --prompt TEXT`: Natural language description.
- `-i, --input FILE`: Path to `.txt`, `.yaml`, or `.json` file containing prompt or definition.
- `-d, --duration TEXT`: Duration format: `5m`, `15m`, `30m`, `90s`, `1h` (default: `15m`).
- `-r, --resolution PRESET`: One of `1920x1080`, `1280x720`, `3840x2160`, `1080x1920`, `720x1280`, `1080x1080`, `1440x1080`.
- `-m, --model TEXT`: Override LLM model name.
- `-s, --style PRESET`: Visual style preset (e.g., `realistic_cinematic`, `dreamy`, `nature_documentary`).
- `--music PRESET`: Music style (e.g., `ambient`, `soft_piano`, `meditation`).
- `--no-ambience`: Omit environmental ambient audio.
- `--seed INT`: Seed for deterministic generation.
- `--dry-run`: LLM planning only.
- `-v, --verbose`: Enable debug logging.

### Resuming Failed / Interrupted Projects
If generation is interrupted or a specific scene fails, resume where it left off:
```powershell
python -m app resume output/misty_alpine_sunrise_20261006_143000/
```
The generator inspects `project/project.json`, keeps all completed clips, and re-renders only pending or failed segments.

---

## Self-Contained Output Structure

Each run creates an isolated directory in `output/`:

```
output/
    peaceful_rainy_mountains_20261006_143012/
        video.mp4                     # Final compiled video
        thumbnail.jpg                 # Generated or extracted thumbnail
        youtube/
            title.txt                 # Video title
            description.txt           # Video description
            tags.txt                  # Tags (one per line)
            category.txt              # Category
            language.txt              # Video language
            metadata.json             # Structured metadata for uploader
        project/
            project.json              # Full project state & resume tracker
            scene_plan.json           # Raw LLM scene plan
            validation.json           # Quality verification report
        scenes/
            scene_001/                # Generated frames, clip, motion video
            scene_002/
            ...
        audio/
            music.wav                 # Crossfaded continuous music
            ambient.wav               # Environmental nature audio
            final_audio.wav           # Mixed audio
        logs/
            generation.log            # Full trace of LLM responses & FFmpeg runs
```

---

## YouTube Uploader Script

The generator is decoupled from YouTube publishing. A dedicated uploader script consumes the generated bundle:

```powershell
python scripts/youtube_upload.py output/peaceful_rainy_mountains_20261006_143012/
```

The script inspects `youtube/metadata.json`, verifies that `video.mp4` and `thumbnail.jpg` exist, and displays the payload to be uploaded.

---

## Running Tests

Automated unit tests cover all schemas, duration calculations, title sanitization, providers (with mocks), and FFmpeg filter building:

```powershell
python -m pytest tests/ -v
```

All 49 unit tests run offline without requiring external AI services.

---

## Troubleshooting

- **`FFmpeg not found`**: Ensure FFmpeg 6.0+ is in PATH or update `ffmpeg.binary` in `config/app.yaml`.
- **`LM Studio health check failed`**: Ensure LM Studio is open and the local server is started at `http://localhost:1234/v1` with a model loaded.
- **`ComfyUI health check failed`**: Check that ComfyUI is running on `http://127.0.0.1:8188`.
- **Windows Console Glyphs (`charmap` error)**: Standard ASCII fallback output is built in for safe Windows PowerShell/cmd execution.
