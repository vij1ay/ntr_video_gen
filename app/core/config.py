"""
Application configuration system.

Loads settings from config/app.yaml and environment variable overrides.
Environment variables always take precedence over file-based configuration.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Resolution presets ────────────────────────────────────────────────────────

RESOLUTION_PRESETS: dict[str, tuple[int, int]] = {
    "1920x1080": (1920, 1080),
    "1280x720":  (1280, 720),
    "3840x2160": (3840, 2160),
    "1080x1920": (1080, 1920),
    "720x1280":  (720, 1280),
    "1080x1080": (1080, 1080),
    "1440x1080": (1440, 1080),
}

ASPECT_RATIO_MAP: dict[str, str] = {
    "1920x1080": "16:9",
    "1280x720":  "16:9",
    "3840x2160": "16:9",
    "1080x1920": "9:16",
    "720x1280":  "9:16",
    "1080x1080": "1:1",
    "1440x1080": "4:3",
}

DEFAULT_RESOLUTION = "1920x1080"


# ── LM Studio settings ────────────────────────────────────────────────────────

class LMStudioSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LM_STUDIO_", extra="ignore")

    base_url: str = Field(default="http://localhost:1234/v1")
    api_key: str = Field(default="lm-studio")
    model: str = Field(default="qwen/qwen3.8-27b")
    max_tokens: int = Field(default=3072)
    temperature: float = Field(default=0.7)
    timeout_seconds: int = Field(default=1200)
    max_retries: int = Field(default=2)


# ── ComfyUI settings ──────────────────────────────────────────────────────────

class ComfyUISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COMFYUI_", extra="ignore")

    base_url: str = Field(default="http://127.0.0.1:8188")
    timeout_seconds: int = Field(default=600)
    poll_interval_seconds: float = Field(default=2.0)
    client_id: str = Field(default="ntr-video-gen")


# ── Music settings ────────────────────────────────────────────────────────────

class MusicSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MUSIC_", extra="ignore")

    provider: str = Field(default="stub")   # stub | audiocraft | musicgen | suno_local
    model: str = Field(default="facebook/musicgen-small")
    base_url: Optional[str] = Field(default=None)
    timeout_seconds: int = Field(default=300)


# ── Video settings ────────────────────────────────────────────────────────────

class VideoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIDEO_", extra="ignore")

    default_duration_seconds: int = Field(default=900)   # 15 minutes
    default_resolution: str = Field(default=DEFAULT_RESOLUTION)
    default_fps: int = Field(default=30)
    default_style: str = Field(default="realistic_cinematic")
    default_music_style: str = Field(default="ambient")
    default_transition: str = Field(default="crossfade")
    crossfade_duration: float = Field(default=1.5)
    music_volume: float = Field(default=0.65)
    ambience_volume: float = Field(default=0.35)

    @field_validator("default_resolution")
    @classmethod
    def validate_resolution(cls, v: str) -> str:
        if v not in RESOLUTION_PRESETS:
            raise ValueError(
                f"Resolution '{v}' is not a valid preset. "
                f"Valid presets: {list(RESOLUTION_PRESETS)}"
            )
        return v


# ── FFmpeg settings ───────────────────────────────────────────────────────────

class FFmpegSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FFMPEG_", extra="ignore")

    binary: str = Field(default="ffmpeg")
    ffprobe_binary: str = Field(default="ffprobe")
    video_codec: str = Field(default="libx264")
    audio_codec: str = Field(default="aac")
    video_crf: int = Field(default=18)
    audio_bitrate: str = Field(default="192k")
    preset: str = Field(default="slow")


# ── Paths settings ────────────────────────────────────────────────────────────

class PathSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PATH_", extra="ignore")

    output_dir: str = Field(default="output")
    assets_dir: str = Field(default="assets")
    workflows_dir: str = Field(default="workflows")
    projects_dir: str = Field(default="projects")


# ── Main AppConfig ────────────────────────────────────────────────────────────

class AppConfig:
    """
    Central application configuration.

    Loads from config/app.yaml first, then allows environment variable overrides
    via the individual Settings classes.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self._yaml_data: dict = {}

        # Load YAML config file if present
        if config_path is None:
            config_path = Path("config") / "app.yaml"

        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as fh:
                self._yaml_data = yaml.safe_load(fh) or {}

        self._apply_yaml_to_env()

        # Instantiate sub-settings (env overrides apply here)
        self.llm = LMStudioSettings()
        self.comfyui = ComfyUISettings()
        self.music = MusicSettings()
        self.video = VideoSettings()
        self.ffmpeg = FFmpegSettings()
        self.paths = PathSettings()

    def _apply_yaml_to_env(self) -> None:
        """
        Push YAML values into environment variables so pydantic-settings picks them up.
        Only sets env vars that are not already explicitly set.
        """
        mappings: dict[str, dict[str, str]] = {
            "lm_studio": "LM_STUDIO_",
            "comfyui": "COMFYUI_",
            "music": "MUSIC_",
            "video": "VIDEO_",
            "ffmpeg": "FFMPEG_",
            "paths": "PATH_",
        }
        for section, prefix in mappings.items():
            section_data = self._yaml_data.get(section, {})
            if not isinstance(section_data, dict):
                continue
            for key, value in section_data.items():
                env_key = f"{prefix}{key.upper()}"
                if env_key not in os.environ:
                    os.environ[env_key] = str(value)

    def get_resolution(self, resolution_str: Optional[str] = None) -> tuple[int, int]:
        """Return (width, height) for a resolution preset string."""
        res = resolution_str or self.video.default_resolution
        if res not in RESOLUTION_PRESETS:
            raise ValueError(
                f"Unknown resolution preset '{res}'. "
                f"Valid: {list(RESOLUTION_PRESETS)}"
            )
        return RESOLUTION_PRESETS[res]

    def get_aspect_ratio(self, resolution_str: Optional[str] = None) -> str:
        """Return aspect ratio string for a resolution preset."""
        res = resolution_str or self.video.default_resolution
        return ASPECT_RATIO_MAP.get(res, "16:9")


# ── Singleton accessor ────────────────────────────────────────────────────────

_config: Optional[AppConfig] = None


def get_config(config_path: Optional[Path] = None) -> AppConfig:
    """Return the global AppConfig singleton, creating it if needed."""
    global _config
    if _config is None:
        _config = AppConfig(config_path)
    return _config


def reset_config() -> None:
    """Reset the singleton (useful for testing)."""
    global _config
    _config = None
