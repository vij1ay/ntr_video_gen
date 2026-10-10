"""
LLM Scene Planner — Phase 2.

Takes a user prompt (or structured input) and uses the LLM to generate
a complete, validated ProjectPlan.
"""
from __future__ import annotations

import json
from typing import Optional

from pydantic import ValidationError

from app.core.config import AppConfig
from app.core.logging import get_logger
from app.providers.lmstudio import LMStudioProvider
from app.schemas.project import ProjectPlan

logger = get_logger("pipeline.planner")

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a creative director and video producer specialising in relaxing nature videos.
Your job is to create a detailed, structured production plan for a nature video.

IMPORTANT RULES:
1. Output ONLY a single valid JSON object — no markdown, no prose, no code fences.
2. All fields are required unless marked optional.
3. Scene durations should sum close to the requested total duration.
4. Visual prompts must be highly detailed, cinematic, photorealistic.
5. Negative prompts must exclude: people, text, logos, watermarks, cartoons, distortion.
6. Music must be calm, ambient, non-distracting.
7. The video must feel peaceful, continuous, and relaxing.
8. Camera motions must be subtle — no fast movement.
9. scene ids must be formatted as: scene_001, scene_002, etc.
10. generation_type for each scene: "image", "video", or "hybrid".
    - Prefer "image" for still landscapes (cheaper, faster).
    - Use "video" for water/movement scenes where motion is essential.
    - Use "hybrid" for scenes benefiting from both.
"""

_USER_PROMPT_TEMPLATE = """\
Create a complete video production plan for the following request:

USER REQUEST: {user_prompt}

REQUIREMENTS:
- Total duration: {duration_seconds} seconds ({duration_minutes:.1f} minutes)
- Resolution: {resolution}
- Aspect ratio: {aspect_ratio}
- Visual style: {visual_style}
- Music style: {music_style}
- Seed (for reproducibility): {seed}

SCENE PLANNING GUIDE:
- Plan approximately {min_scenes}–{max_scenes} scenes for this duration.
- Each scene should be {min_scene_dur}–{max_scene_dur} seconds long.
- Use visual continuity: scenes should flow naturally from one to the next.
- For a 15-minute video, prefer IMAGE generation for most scenes (faster).
- Include at least one VIDEO scene for dynamic water/movement.

OUTPUT FORMAT — Return exactly this JSON structure (all fields required):

{{
  "title": "...",
  "concept": "...",
  "duration_seconds": {duration_seconds},
  "resolution": "{resolution}",
  "aspect_ratio": "{aspect_ratio}",
  "fps": 30,
  "visual_style": "{visual_style}",
  "mood": "...",
  "theme": "nature",
  "scenes": [
    {{
      "id": "scene_001",
      "title": "...",
      "duration_seconds": 60,
      "description": "...",
      "visual_prompt": "highly detailed cinematic nature photography, ...",
      "negative_prompt": "text, watermark, logo, people, humans, ...",
      "camera_motion": "slow_zoom_in",
      "transition": "crossfade",
      "generation_type": "image",
      "ambience": ["rain", "wind"],
      "intensity": "very_low",
      "seed": null
    }}
  ],
  "music_plan": {{
    "style": "ambient",
    "mood": "peaceful",
    "tempo": "very_slow",
    "instruments": ["piano", "strings", "ambient_pads"],
    "energy": "very_low",
    "description": "..."
  }},
  "ambient_audio_plan": {{
    "sounds": ["rain", "wind"],
    "primary_sound": "rain",
    "music_volume": 0.65,
    "ambience_volume": 0.35
  }},
  "youtube_metadata": {{
    "title": "...",
    "description": "...",
    "tags": ["nature", "relaxing", "..."],
    "category": "Entertainment",
    "language": "en",
    "privacy": "private",
    "chapters": []
  }},
  "thumbnail_plan": {{
    "concept": "...",
    "visual_prompt": "...",
    "negative_prompt": "text, watermark, logo, blur, ...",
    "scene_reference": null
  }}
}}
"""


class ScenePlanner:
    """
    Orchestrates the LLM call to produce a validated ProjectPlan.

    Handles:
    - Prompt construction
    - JSON response extraction
    - Pydantic validation
    - Repair/retry on validation failure
    """

    def __init__(
        self,
        llm: LMStudioProvider,
        config: AppConfig,
    ) -> None:
        self.llm = llm
        self.config = config

    def plan(
        self,
        user_prompt: str,
        duration_seconds: int,
        resolution: str,
        visual_style: str,
        music_style: str,
        seed: Optional[int] = None,
    ) -> ProjectPlan:
        """
        Generate a validated ProjectPlan from a user prompt.

        Args:
            user_prompt: Natural-language video description.
            duration_seconds: Target video length.
            resolution: Resolution preset string.
            visual_style: Visual style preset.
            music_style: Music style preset.
            seed: Optional seed for reproducibility.

        Returns:
            A validated ProjectPlan instance.

        Raises:
            RuntimeError: If a valid plan cannot be produced after all retries.
        """
        width, height = self.config.get_resolution(resolution)
        aspect_ratio = self.config.get_aspect_ratio(resolution)

        # Calculate reasonable scene count range
        min_scenes = max(3, duration_seconds // 90)
        max_scenes = max(min_scenes + 2, duration_seconds // 45)
        min_scene_dur = 30
        max_scene_dur = max(60, duration_seconds // min_scenes)

        user_prompt_text = _USER_PROMPT_TEMPLATE.format(
            user_prompt=user_prompt,
            duration_seconds=duration_seconds,
            duration_minutes=duration_seconds / 60,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            visual_style=visual_style,
            music_style=music_style,
            seed=seed if seed is not None else "random",
            min_scenes=min_scenes,
            max_scenes=max_scenes,
            min_scene_dur=min_scene_dur,
            max_scene_dur=max_scene_dur,
        )

        logger.info(
            "Generating project plan via LLM (duration=%ds, resolution=%s) …",
            duration_seconds,
            resolution,
        )

        max_attempts = self.config.llm.max_retries
        last_error: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                logger.debug("Scene planning attempt %d/%d", attempt, max_attempts)
                raw_dict = self.llm.generate_json(
                    prompt=user_prompt_text,
                    system_prompt=_SYSTEM_PROMPT,
                )
                plan = self._validate_and_fix(raw_dict, duration_seconds, resolution)
                logger.info(
                    "Project plan validated: %d scenes, total=%ds",
                    len(plan.scenes),
                    plan.total_scene_duration,
                )
                return plan

            except (ValidationError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "Plan validation failed (attempt %d): %s",
                    attempt,
                    exc,
                )
                if attempt < max_attempts:
                    # Add the error to the next attempt's prompt
                    user_prompt_text += (
                        f"\n\nPREVIOUS ATTEMPT FAILED VALIDATION:\n{exc}\n"
                        f"Please fix all issues and return valid JSON."
                    )

        raise RuntimeError(
            f"Failed to generate a valid project plan after {max_attempts} attempts.\n"
            f"Last error: {last_error}"
        )

    def _validate_and_fix(
        self,
        raw: dict,
        duration_seconds: int,
        resolution: str,
    ) -> ProjectPlan:
        """
        Validate raw LLM dict against ProjectPlan schema.

        Applies auto-fixes for common LLM mistakes before validation.
        """
        # Auto-fix common issues
        raw.setdefault("duration_seconds", duration_seconds)
        raw.setdefault("resolution", resolution)
        raw.setdefault("fps", 30)
        raw.setdefault("theme", "nature")

        # Ensure music_plan exists
        if "music_plan" not in raw or not isinstance(raw["music_plan"], dict):
            raw["music_plan"] = {
                "style": "ambient",
                "mood": "peaceful",
                "tempo": "very_slow",
            }

        # Ensure ambient_audio_plan exists
        if "ambient_audio_plan" not in raw or not isinstance(raw["ambient_audio_plan"], dict):
            raw["ambient_audio_plan"] = {
                "sounds": ["rain", "wind"],
                "primary_sound": "rain",
            }

        # Ensure thumbnail_plan exists
        if "thumbnail_plan" not in raw or not isinstance(raw["thumbnail_plan"], dict):
            raw["thumbnail_plan"] = {
                "concept": raw.get("title", "Nature thumbnail"),
                "visual_prompt": f"cinematic photorealistic {raw.get('title', 'nature')}",
            }

        # Ensure youtube_metadata exists
        if "youtube_metadata" not in raw or not isinstance(raw["youtube_metadata"], dict):
            raw["youtube_metadata"] = {
                "title": raw.get("title", "Relaxing Nature Video"),
                "description": raw.get("concept", "A peaceful nature video."),
                "tags": ["nature", "relaxing", "peaceful"],
            }

        # Ensure scenes list exists and is well-formed
        scenes = raw.get("scenes", [])
        if not isinstance(scenes, list) or not scenes:
            scenes = [
                {
                    "id": "scene_001",
                    "title": raw.get("title", "Serene Landscape"),
                    "duration_seconds": duration_seconds,
                    "description": raw.get("concept", "Peaceful nature view"),
                    "visual_prompt": f"cinematic photography of {raw.get('title', 'nature landscape')}",
                    "generation_type": "image",
                }
            ]
            raw["scenes"] = scenes

        for i, scene in enumerate(scenes, start=1):
            if not isinstance(scene, dict):
                continue
            if not scene.get("id"):
                scene["id"] = f"scene_{i:03d}"
            if not scene.get("title"):
                scene["title"] = f"Scene {i}"
            if not scene.get("description"):
                scene["description"] = f"Peaceful nature scene {i}"
            if not scene.get("visual_prompt"):
                scene["visual_prompt"] = scene.get("description", "cinematic nature photography")
            if not scene.get("duration_seconds") or scene.get("duration_seconds") < 5:
                scene["duration_seconds"] = max(30, duration_seconds // len(scenes))

        return ProjectPlan.model_validate(raw)
