"""
Generation pipeline — scene rendering orchestrator.

Handles:
  - Scene-by-scene image/video generation via ComfyUI
  - FFmpeg motion effects for image scenes
  - State persistence for resume support
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import AppConfig
from app.core.logging import get_logger
from app.core.output import get_scenes_dir
from app.providers.comfyui import ComfyUIProvider
from app.providers.ffmpeg import FFmpegRenderer
from app.schemas.project import (
    GenerationType,
    ProjectPlan,
    ProjectState,
    ProjectStatus,
    Scene,
    SceneStatus,
)

logger = get_logger("pipeline.generator")


class SceneGenerator:
    """
    Generates visual media for each scene in a ProjectPlan.

    Supports:
      - IMAGE: ComfyUI → still image → FFmpeg motion effects
      - VIDEO: ComfyUI → short video clip
      - HYBRID: ComfyUI image + FFmpeg composite
    """

    def __init__(
        self,
        comfyui: ComfyUIProvider,
        renderer: FFmpegRenderer,
        config: AppConfig,
        project_dir: Path,
    ) -> None:
        self.comfyui = comfyui
        self.renderer = renderer
        self.config = config
        self.project_dir = project_dir

    def generate_all(self, state: ProjectState, dry_run: bool = False) -> list[Path]:
        """
        Generate all pending/failed scenes in the plan.

        Skips already-completed scenes (resume support).

        Args:
            state: Current project state (modified in place).
            dry_run: If True, skip actual generation.

        Returns:
            List of paths to rendered scene video clips.
        """
        plan = state.plan
        width, height = self.config.get_resolution(plan.resolution)
        rendered_clips: list[Path] = []

        for scene in plan.scenes:
            if scene.status == SceneStatus.COMPLETED and scene.output_file:
                clip_path = Path(scene.output_file)
                if clip_path.exists():
                    logger.info("Scene %s: already completed, skipping.", scene.id)
                    rendered_clips.append(clip_path)
                    continue
                # File missing — re-generate
                scene.status = SceneStatus.PENDING

            if scene.status == SceneStatus.SKIPPED:
                logger.info("Scene %s: skipped.", scene.id)
                continue

            if dry_run:
                logger.info(
                    "[DRY RUN] Scene %s: %s (%ds) — %s",
                    scene.id,
                    scene.title,
                    scene.duration_seconds,
                    scene.generation_type.value,
                )
                continue

            try:
                scene.status = SceneStatus.IN_PROGRESS
                self._save_state(state)

                clip = self._generate_scene(scene, width, height, plan.fps)
                scene.output_file = str(clip)
                scene.status = SceneStatus.COMPLETED
                rendered_clips.append(clip)
                logger.info("Scene %s completed: %s", scene.id, clip)

            except Exception as exc:
                scene.status = SceneStatus.FAILED
                logger.error("Scene %s FAILED: %s", scene.id, exc, exc_info=True)
                # Continue with remaining scenes — don't abort the whole run

            finally:
                self._save_state(state)

        return rendered_clips

    # ── Private: scene dispatch ───────────────────────────────────────────────

    def _generate_scene(
        self,
        scene: Scene,
        width: int,
        height: int,
        fps: int,
    ) -> Path:
        """Dispatch to the appropriate generation strategy."""
        scene_dir = get_scenes_dir(self.project_dir, scene.id)

        logger.info(
            "Generating scene %s: '%s' (%s, %ds)",
            scene.id,
            scene.title,
            scene.generation_type.value,
            scene.duration_seconds,
        )

        if scene.generation_type == GenerationType.IMAGE:
            return self._generate_image_scene(scene, scene_dir, width, height, fps)
        elif scene.generation_type == GenerationType.VIDEO:
            return self._generate_video_scene(scene, scene_dir, width, height, fps)
        elif scene.generation_type == GenerationType.HYBRID:
            return self._generate_hybrid_scene(scene, scene_dir, width, height, fps)
        else:
            raise ValueError(f"Unknown generation type: {scene.generation_type}")

    def _generate_image_scene(
        self,
        scene: Scene,
        scene_dir: Path,
        width: int,
        height: int,
        fps: int,
    ) -> Path:
        """Generate a still image and apply FFmpeg motion effects."""
        image_path = scene_dir / "image.png"
        video_path = scene_dir / "clip.mp4"

        # Step 1: Generate still image via ComfyUI
        logger.info("  → Generating image via ComfyUI …")
        self.comfyui.generate_image(
            prompt=scene.visual_prompt,
            negative_prompt=scene.negative_prompt,
            width=width,
            height=height,
            seed=scene.seed,
            output_path=image_path,
        )

        # Step 2: Apply camera motion via FFmpeg
        logger.info("  → Applying camera motion: %s …", scene.camera_motion)
        self.renderer.image_to_video(
            image_path=image_path,
            output_path=video_path,
            duration_seconds=scene.duration_seconds,
            width=width,
            height=height,
            camera_motion=scene.camera_motion,
            fps=fps,
        )
        return video_path

    def _generate_video_scene(
        self,
        scene: Scene,
        scene_dir: Path,
        width: int,
        height: int,
        fps: int,
    ) -> Path:
        """
        Generate a short AI video clip via ComfyUI.
        Falls back to image + FFmpeg motion effects if no video model is available.
        """
        video_path = scene_dir / "clip.mp4"
        raw_clip = scene_dir / "raw_clip.mp4"

        try:
            logger.info("  → Attempting video clip via ComfyUI …")
            self.comfyui.generate_video(
                prompt=scene.visual_prompt,
                negative_prompt=scene.negative_prompt,
                width=width,
                height=height,
                duration_seconds=min(10, scene.duration_seconds),
                seed=scene.seed,
                output_path=raw_clip,
            )

            # Extend to full scene duration by looping
            if raw_clip.exists():
                self._loop_video_to_duration(raw_clip, video_path, scene.duration_seconds)
                return video_path
        except Exception as err:
            logger.warning(
                "Video model generation unavailable (%s). "
                "Falling back to high-res image + cinematic FFmpeg motion.",
                err,
            )

        # Fallback: render still image + Ken Burns camera motion
        return self._generate_image_scene(scene, scene_dir, width, height, fps)

    def _generate_hybrid_scene(
        self,
        scene: Scene,
        scene_dir: Path,
        width: int,
        height: int,
        fps: int,
    ) -> Path:
        """Generate image + apply motion (same as IMAGE for now, extensible)."""
        return self._generate_image_scene(scene, scene_dir, width, height, fps)

    def _loop_video_to_duration(
        self,
        source: Path,
        output: Path,
        target_seconds: int,
    ) -> None:
        """Loop a video clip to fill the target duration using FFmpeg."""
        cmd_parts = [
            self.renderer._ffmpeg, "-y",
            "-stream_loop", "-1",
            "-i", str(source),
            "-t", str(target_seconds),
            "-c", "copy",
            str(output),
        ]
        self.renderer._run(cmd_parts)

    def _save_state(self, state: ProjectState) -> None:
        """Persist project state to project/project.json."""
        state.updated_at = datetime.now().isoformat()
        state_path = self.project_dir / "project" / "project.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(state.model_dump(), fh, indent=2, default=str)
