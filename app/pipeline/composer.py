"""
Composer — final video composition using FFmpeg.

Takes all rendered scene clips and produces the final video.mp4.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.core.config import AppConfig
from app.core.logging import get_logger
from app.providers.ffmpeg import FFmpegRenderer
from app.schemas.project import ProjectPlan, SceneStatus

logger = get_logger("pipeline.composer")


class VideoComposer:
    """
    Assembles scene clips into the final video using FFmpeg.

    Applies:
    - Crossfade transitions between scenes
    - Thumbnail extraction (fallback if ComfyUI generation fails)
    - YouTube metadata file writing
    - Final quality validation
    """

    def __init__(
        self,
        renderer: FFmpegRenderer,
        config: AppConfig,
        project_dir: Path,
    ) -> None:
        self.renderer = renderer
        self.config = config
        self.project_dir = project_dir

    def compose(
        self,
        plan: ProjectPlan,
        scene_clips: list[Path],
        crossfade_duration: Optional[float] = None,
    ) -> Path:
        """
        Concatenate scene clips into a single silent video.

        Args:
            plan: The project plan.
            scene_clips: Ordered list of rendered scene clip paths.
            crossfade_duration: Override crossfade duration (seconds).

        Returns:
            Path to the composed silent video (no audio yet).
        """
        if not scene_clips:
            raise RuntimeError("No rendered scene clips available for composition.")

        xfade = crossfade_duration or self.config.video.crossfade_duration
        output_path = self.project_dir / "video_silent.mp4"

        logger.info(
            "Composing %d scene clips → %s (crossfade=%.1fs)",
            len(scene_clips),
            output_path.name,
            xfade,
        )

        self.renderer.concatenate_videos(
            video_paths=scene_clips,
            output_path=output_path,
            crossfade_duration=xfade,
        )
        return output_path

    def finalize(
        self,
        video_with_audio: Path,
        plan: ProjectPlan,
    ) -> Path:
        """
        Copy the final video to video.mp4 and write all YouTube metadata.

        Args:
            video_with_audio: Path to the video with mixed audio.
            plan: The project plan containing YouTube metadata.

        Returns:
            Path to the final video.mp4.
        """
        final_path = self.project_dir / "video.mp4"

        # If video already has audio mixed in, just rename/move
        if video_with_audio != final_path:
            import shutil
            shutil.copy2(str(video_with_audio), str(final_path))

        logger.info("Final video: %s", final_path)

        # Write YouTube metadata
        self._write_youtube_metadata(plan, final_path)

        return final_path

    def generate_thumbnail(
        self,
        plan: ProjectPlan,
        comfyui=None,
        video_path: Optional[Path] = None,
    ) -> Optional[Path]:
        """
        Generate thumbnail via ComfyUI, or extract a frame as fallback.

        Args:
            plan: Project plan with thumbnail_plan.
            comfyui: ComfyUIProvider instance (optional).
            video_path: Final video path (used for fallback extraction).

        Returns:
            Path to thumbnail.jpg, or None if generation failed.
        """
        thumbnail_path = self.project_dir / "thumbnail.jpg"

        # Try ComfyUI thumbnail generation first
        if comfyui is not None:
            try:
                width, height = self.config.get_resolution(plan.resolution)
                thumbnail_raw = self.project_dir / "thumbnails" / "thumbnail_raw.png"
                thumbnail_raw.parent.mkdir(exist_ok=True)

                comfyui.generate_image(
                    prompt=plan.thumbnail_plan.visual_prompt,
                    negative_prompt=plan.thumbnail_plan.negative_prompt,
                    width=width,
                    height=height,
                    output_path=thumbnail_raw,
                    workflow_path=Path("workflows") / "thumbnail_generation.json",
                )

                # Convert PNG → JPG
                self._convert_to_jpg(thumbnail_raw, thumbnail_path)
                logger.info("Thumbnail generated via ComfyUI: %s", thumbnail_path)
                return thumbnail_path

            except Exception as exc:
                logger.warning(
                    "ComfyUI thumbnail generation failed: %s. "
                    "Using video frame fallback.",
                    exc,
                )

        # Fallback: extract frame from video
        if video_path and video_path.exists():
            try:
                # Extract frame at 10% into the video
                info = self.renderer.get_video_info(video_path)
                duration = info.get("duration", 60)
                offset = max(5.0, duration * 0.10)
                self.renderer.extract_thumbnail(video_path, thumbnail_path, offset)
                logger.info("Thumbnail extracted from video at %.1fs", offset)
                return thumbnail_path
            except Exception as exc:
                logger.error("Thumbnail extraction failed: %s", exc)

        return None

    # ── YouTube metadata ──────────────────────────────────────────────────────

    def _write_youtube_metadata(self, plan: ProjectPlan, video_path: Path) -> None:
        """Write all YouTube metadata files to youtube/ directory."""
        yt_dir = self.project_dir / "youtube"
        yt_dir.mkdir(exist_ok=True)
        meta = plan.youtube_metadata

        # Plain text files
        (yt_dir / "title.txt").write_text(meta.title, encoding="utf-8")
        (yt_dir / "description.txt").write_text(meta.description, encoding="utf-8")
        (yt_dir / "tags.txt").write_text(
            "\n".join(meta.tags), encoding="utf-8"
        )
        (yt_dir / "category.txt").write_text(meta.category, encoding="utf-8")
        (yt_dir / "language.txt").write_text(meta.language, encoding="utf-8")

        # Structured metadata JSON
        metadata = {
            "title": meta.title,
            "description": meta.description,
            "tags": meta.tags,
            "category": meta.category,
            "language": meta.language,
            "privacy": meta.privacy,
            "thumbnail": "thumbnail.jpg",
            "video": video_path.name,
            "chapters": meta.chapters,
        }
        with open(yt_dir / "metadata.json", "w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=2, ensure_ascii=False)

        logger.info("YouTube metadata written to %s", yt_dir)

    def _convert_to_jpg(self, source: Path, dest: Path) -> None:
        """Convert any image to JPG using FFmpeg."""
        cmd = [
            self.renderer._ffmpeg, "-y",
            "-i", str(source),
            "-q:v", "2",
            str(dest),
        ]
        self.renderer._run(cmd)
