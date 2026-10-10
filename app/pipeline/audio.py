"""
Audio pipeline — music generation, ambience selection, mixing.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Optional

from app.core.config import AppConfig
from app.core.logging import get_logger
from app.providers.ffmpeg import FFmpegRenderer
from app.providers.music import get_music_provider
from app.schemas.project import AmbientAudioPlan, MusicPlan

logger = get_logger("pipeline.audio")


class AudioPipeline:
    """
    Handles all audio processing:
      1. Generate music tracks via MusicProvider
      2. Select and mix ambient nature sounds from assets/
      3. Crossfade music tracks into a seamless soundtrack
      4. Mix music + ambience at configured volumes
    """

    def __init__(
        self,
        renderer: FFmpegRenderer,
        config: AppConfig,
        project_dir: Path,
        assets_dir: Path,
    ) -> None:
        self.renderer = renderer
        self.config = config
        self.project_dir = project_dir
        self.assets_dir = assets_dir
        self.audio_dir = project_dir / "audio"
        self.audio_dir.mkdir(exist_ok=True)

        self.music_provider = get_music_provider(config.music.provider)

    def generate_music(
        self,
        music_plan: MusicPlan,
        duration_seconds: int,
    ) -> Path:
        """
        Generate a continuous music soundtrack.

        If the music model generates shorter clips, multiple clips are
        generated and crossfaded into one seamless track.

        Args:
            music_plan: Music generation parameters from the project plan.
            duration_seconds: Target total music duration.

        Returns:
            Path to the final music WAV file.
        """
        music_path = self.audio_dir / "music.wav"

        # Most local music models max out at ~30s–3min per generation.
        # We generate enough segments to cover the full duration.
        max_segment = 180  # seconds per generation call
        n_segments = max(1, (duration_seconds + max_segment - 1) // max_segment)

        logger.info(
            "Generating music: %d segment(s), total=%ds, style=%s",
            n_segments,
            duration_seconds,
            music_plan.style,
        )

        description = self._build_music_description(music_plan)
        segment_paths: list[Path] = []

        for i in range(n_segments):
            seg_duration = min(max_segment, duration_seconds - i * max_segment)
            seg_path = self.audio_dir / f"music_segment_{i + 1:03d}.wav"
            logger.info("  → Music segment %d/%d (%ds) …", i + 1, n_segments, seg_duration)
            self.music_provider.generate(
                description=description,
                duration_seconds=seg_duration,
                style=music_plan.style,
                mood=music_plan.mood,
                output_path=seg_path,
            )
            segment_paths.append(seg_path)

        if len(segment_paths) == 1:
            segment_paths[0].rename(music_path)
        else:
            logger.info("Crossfading %d music segments …", len(segment_paths))
            self.renderer.crossfade_audio_tracks(
                audio_paths=segment_paths,
                output_path=music_path,
                crossfade_duration=self.config.video.crossfade_duration * 2,
                target_duration=duration_seconds,
            )

        return music_path

    def select_ambience(self, audio_plan: AmbientAudioPlan) -> Optional[Path]:
        """
        Find the best matching ambient audio file from assets/.

        Looks in: assets/ambience/<sound_type>/*.wav|mp3|ogg

        Returns:
            Path to an ambience file, or None if not found.
        """
        sounds = audio_plan.sounds or []
        if audio_plan.primary_sound:
            sounds = [audio_plan.primary_sound] + [
                s for s in sounds if s != audio_plan.primary_sound
            ]

        for sound in sounds:
            sound_dir = self.assets_dir / "ambience" / sound.lower()
            if sound_dir.exists():
                audio_files = (
                    list(sound_dir.glob("*.wav"))
                    + list(sound_dir.glob("*.mp3"))
                    + list(sound_dir.glob("*.ogg"))
                )
                if audio_files:
                    chosen = random.choice(audio_files)
                    logger.info("Ambience selected: %s → %s", sound, chosen.name)
                    return chosen

        logger.warning(
            "No ambience files found for sounds: %s. "
            "Add audio files to assets/ambience/<type>/",
            sounds,
        )
        return None

    def build_final_audio(
        self,
        video_path: Path,
        music_plan: MusicPlan,
        audio_plan: AmbientAudioPlan,
        duration_seconds: int,
    ) -> tuple[Path, Optional[Path]]:
        """
        Generate music, select ambience, mix and attach to video.

        Args:
            video_path: Silent composite video.
            music_plan: Music parameters.
            audio_plan: Ambience parameters.
            duration_seconds: Target audio duration.

        Returns:
            (final_video_with_audio_path, ambience_path_or_none)
        """
        music_path = self.generate_music(music_plan, duration_seconds)
        ambience_path = self.select_ambience(audio_plan)

        final_video = self.project_dir / "video_with_audio.mp4"
        logger.info("Mixing audio into video …")
        self.renderer.mix_audio(
            video_path=video_path,
            music_path=music_path,
            output_path=final_video,
            ambience_path=ambience_path,
            music_volume=audio_plan.music_volume,
            ambience_volume=audio_plan.ambience_volume,
        )
        return final_video, ambience_path

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_music_description(self, plan: MusicPlan) -> str:
        """Build a text description for the music generation model."""
        instruments = ", ".join(plan.instruments) if plan.instruments else "ambient pads"
        return (
            f"{plan.style} music, {plan.mood} mood, {plan.tempo} tempo. "
            f"Instruments: {instruments}. "
            f"Energy: {plan.energy.value}. "
            f"{plan.description}"
        ).strip()
