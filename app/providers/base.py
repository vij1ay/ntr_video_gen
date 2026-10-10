"""
Abstract base classes for all AI/media provider interfaces.

Concrete implementations live in app/providers/*.py.
Never import concrete providers directly — always depend on these ABCs.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional


class LLMProvider(ABC):
    """Abstract interface for a language model provider."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the provider is reachable and ready."""

    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Generate a free-form text response.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system-level instructions.

        Returns:
            Generated text.
        """

    @abstractmethod
    def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        schema: Optional[dict] = None,
    ) -> dict:
        """
        Generate a structured JSON response.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system-level instructions.
            schema: Optional JSON schema to guide the model.

        Returns:
            Parsed JSON as a dict.

        Raises:
            ValueError: If the response cannot be parsed as valid JSON.
        """


class ImageProvider(ABC):
    """Abstract interface for image generation."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the provider is reachable."""

    @abstractmethod
    def generate_image(
        self,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        seed: Optional[int] = None,
        output_path: Optional[Path] = None,
        extra_params: Optional[dict] = None,
    ) -> Path:
        """
        Generate a still image.

        Returns:
            Path to the generated image file.
        """


class VideoProvider(ABC):
    """Abstract interface for video clip generation."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the provider is reachable."""

    @abstractmethod
    def generate_video(
        self,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        duration_seconds: int,
        seed: Optional[int] = None,
        output_path: Optional[Path] = None,
        extra_params: Optional[dict] = None,
    ) -> Path:
        """
        Generate a short video clip.

        Returns:
            Path to the generated video file.
        """


class MusicProvider(ABC):
    """Abstract interface for AI music generation."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the provider is reachable."""

    @abstractmethod
    def generate(
        self,
        description: str,
        duration_seconds: int,
        style: str,
        mood: str,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Generate a music track.

        Args:
            description: Text description of the desired music.
            duration_seconds: Target track length in seconds.
            style: Music style preset.
            mood: Emotional mood.
            output_path: Where to save the output audio file.

        Returns:
            Path to the generated audio file.
        """


class Renderer(ABC):
    """Abstract interface for video/audio composition."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the renderer (e.g. FFmpeg) is available."""

    @abstractmethod
    def image_to_video(
        self,
        image_path: Path,
        output_path: Path,
        duration_seconds: int,
        width: int,
        height: int,
        camera_motion: str = "slow_zoom_in",
        fps: int = 30,
    ) -> Path:
        """Apply motion effects to a still image, producing a video clip."""

    @abstractmethod
    def concatenate_videos(
        self,
        video_paths: list[Path],
        output_path: Path,
        crossfade_duration: float = 1.5,
    ) -> Path:
        """Concatenate video clips with crossfade transitions."""

    @abstractmethod
    def mix_audio(
        self,
        video_path: Path,
        music_path: Path,
        output_path: Path,
        ambience_path: Optional[Path] = None,
        music_volume: float = 0.65,
        ambience_volume: float = 0.35,
    ) -> Path:
        """Mix video with music and optional ambience audio."""
