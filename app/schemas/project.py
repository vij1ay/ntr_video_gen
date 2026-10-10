"""
Pydantic schemas for the full project plan and all related structures.

These are the canonical data contracts used throughout the pipeline.
The LLM must produce JSON that validates against ProjectPlan.
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Enumerations ──────────────────────────────────────────────────────────────


class GenerationType(str, Enum):
    """How a scene's visual content is produced."""
    IMAGE = "image"      # Still image + FFmpeg motion effects
    VIDEO = "video"      # Short AI video clip via ComfyUI
    HYBRID = "hybrid"    # Image + motion clip + FFmpeg effects


class TransitionType(str, Enum):
    CROSSFADE = "crossfade"
    FADE = "fade"
    DISSOLVE = "dissolve"
    CUT = "cut"
    SLOW_BLEND = "slow_blend"


class IntensityLevel(str, Enum):
    SILENT = "silent"
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class CameraMotion(str, Enum):
    STATIC = "static"
    SLOW_PAN_LEFT = "slow_pan_left"
    SLOW_PAN_RIGHT = "slow_pan_right"
    SLOW_TILT_UP = "slow_tilt_up"
    SLOW_TILT_DOWN = "slow_tilt_down"
    SLOW_ZOOM_IN = "slow_zoom_in"
    SLOW_ZOOM_OUT = "slow_zoom_out"
    SLOW_FORWARD = "slow_forward"
    SLOW_BACKWARD = "slow_backward"
    GENTLE_DRIFT = "gentle_drift"


class SceneStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ProjectStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPOSING = "composing"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Sub-models ────────────────────────────────────────────────────────────────


class Scene(BaseModel):
    """A single visual segment within the video."""

    id: str = Field(
        description="Unique scene identifier, e.g. 'scene_001'."
    )
    title: str = Field(
        description="Short human-readable scene title."
    )
    duration_seconds: Annotated[int, Field(ge=5, le=600)] = Field(
        description="Target display duration in seconds."
    )
    description: str = Field(
        description="Prose description of what is visible in this scene."
    )
    visual_prompt: str = Field(
        description="Detailed positive prompt for image/video generation."
    )
    negative_prompt: str = Field(
        default=(
            "text, watermark, logo, signature, distorted anatomy, "
            "duplicate animals, deformed animals, artificial vegetation, "
            "oversaturated colors, excessive sharpness, cartoon, anime, "
            "low quality, artifacts, blurry, noise, people, humans, "
            "urban, city, buildings, cars"
        ),
        description="Negative prompt for generation model."
    )
    camera_motion: str = Field(
        default=CameraMotion.SLOW_ZOOM_IN.value,
        description="Desired camera movement description."
    )
    transition: TransitionType = Field(
        default=TransitionType.CROSSFADE,
        description="Transition into the NEXT scene."
    )
    generation_type: GenerationType = Field(
        default=GenerationType.IMAGE,
        description="How to generate the scene's visual content."
    )
    ambience: list[str] = Field(
        default_factory=list,
        description="List of ambience sound types for this scene."
    )
    intensity: IntensityLevel = Field(
        default=IntensityLevel.VERY_LOW,
        description="Overall energy / motion intensity of the scene."
    )
    seed: Optional[int] = Field(
        default=None,
        description="Optional fixed seed for reproducibility."
    )
    # Runtime state (not from LLM)
    status: SceneStatus = Field(default=SceneStatus.PENDING, exclude=False)
    output_file: Optional[str] = Field(
        default=None,
        description="Path to rendered scene file (set during generation)."
    )

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Scene id must not be empty.")
        return v.strip()

    @field_validator("transition", mode="before")
    @classmethod
    def normalize_transition(cls, v: Any) -> TransitionType:
        if isinstance(v, TransitionType):
            return v
        val = str(v).lower().strip().replace(" ", "_").replace("-", "_")
        mapping = {
            "crossfade": TransitionType.CROSSFADE,
            "fade": TransitionType.FADE,
            "dissolve": TransitionType.DISSOLVE,
            "cut": TransitionType.CUT,
            "slow_blend": TransitionType.SLOW_BLEND,
            "blend": TransitionType.SLOW_BLEND,
            "none": TransitionType.CUT,
            "smooth": TransitionType.CROSSFADE,
        }
        return mapping.get(val, TransitionType.CROSSFADE)

    @field_validator("intensity", mode="before")
    @classmethod
    def normalize_intensity(cls, v: Any) -> IntensityLevel:
        if isinstance(v, IntensityLevel):
            return v
        val = str(v).lower().strip().replace(" ", "_").replace("-", "_")
        mapping = {
            "silent": IntensityLevel.SILENT,
            "very_low": IntensityLevel.VERY_LOW,
            "low": IntensityLevel.LOW,
            "medium": IntensityLevel.MEDIUM,
            "high": IntensityLevel.HIGH,
            "very_high": IntensityLevel.VERY_HIGH,
            "calm": IntensityLevel.VERY_LOW,
            "peaceful": IntensityLevel.VERY_LOW,
            "moderate": IntensityLevel.MEDIUM,
            "gentle": IntensityLevel.LOW,
        }
        return mapping.get(val, IntensityLevel.VERY_LOW)

    @field_validator("generation_type", mode="before")
    @classmethod
    def normalize_generation_type(cls, v: Any) -> GenerationType:
        if isinstance(v, GenerationType):
            return v
        val = str(v).lower().strip()
        if "video" in val:
            return GenerationType.VIDEO
        if "hybrid" in val:
            return GenerationType.HYBRID
        return GenerationType.IMAGE


class MusicPlan(BaseModel):
    """Describes the desired music for the video."""

    style: str = Field(
        default="ambient",
        description="Music style: ambient, soft_piano, meditation, etc."
    )
    mood: str = Field(
        description="Emotional mood: peaceful, melancholic, uplifting, etc."
    )
    tempo: str = Field(
        default="very_slow",
        description="Tempo descriptor: very_slow, slow, moderate."
    )
    instruments: list[str] = Field(
        default_factory=list,
        description="Suggested instruments or sonic elements."
    )
    energy: IntensityLevel = Field(
        default=IntensityLevel.VERY_LOW,
        description="Overall energy level of the music."
    )
    description: str = Field(
        default="",
        description="Free-form music direction for the generation model."
    )

    @field_validator("energy", mode="before")
    @classmethod
    def normalize_energy(cls, v: Any) -> IntensityLevel:
        if isinstance(v, IntensityLevel):
            return v
        val = str(v).lower().strip().replace(" ", "_").replace("-", "_")
        mapping = {
            "silent": IntensityLevel.SILENT,
            "very_low": IntensityLevel.VERY_LOW,
            "low": IntensityLevel.LOW,
            "medium": IntensityLevel.MEDIUM,
            "high": IntensityLevel.HIGH,
            "very_high": IntensityLevel.VERY_HIGH,
            "calm": IntensityLevel.VERY_LOW,
            "peaceful": IntensityLevel.VERY_LOW,
            "moderate": IntensityLevel.MEDIUM,
            "gentle": IntensityLevel.LOW,
        }
        return mapping.get(val, IntensityLevel.VERY_LOW)


class AmbientAudioPlan(BaseModel):
    """Describes the environmental/ambient audio layer."""

    sounds: list[str] = Field(
        default_factory=list,
        description="Ordered list of ambient sound types to blend."
    )
    primary_sound: Optional[str] = Field(
        default=None,
        description="The dominant ambient sound."
    )
    music_volume: Annotated[float, Field(ge=0.0, le=1.0)] = Field(
        default=0.65,
        description="Music layer volume (0.0–1.0)."
    )
    ambience_volume: Annotated[float, Field(ge=0.0, le=1.0)] = Field(
        default=0.35,
        description="Ambience layer volume (0.0–1.0)."
    )


class YouTubeMetadata(BaseModel):
    """YouTube publishing metadata generated by the LLM."""

    title: str = Field(description="YouTube video title.")
    description: str = Field(description="YouTube video description.")
    tags: list[str] = Field(
        default_factory=list,
        description="Relevant tags (no spam, max 500 chars combined)."
    )
    category: str = Field(default="Entertainment")
    language: str = Field(default="en")
    privacy: str = Field(default="private")
    chapters: list[dict] = Field(
        default_factory=list,
        description="Optional chapter markers: [{time_seconds, title}]"
    )

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("YouTube title must not be empty.")
        return v.strip()

    @field_validator("tags")
    @classmethod
    def limit_tags(cls, v: list[str]) -> list[str]:
        # YouTube allows up to 500 characters of tags
        total = sum(len(t) for t in v)
        if total > 500:
            # Trim tags to fit within limit
            result: list[str] = []
            running = 0
            for tag in v:
                if running + len(tag) + 1 > 500:
                    break
                result.append(tag)
                running += len(tag) + 1
            return result
        return v


class ThumbnailPlan(BaseModel):
    """Concept for the video thumbnail."""

    concept: str = Field(description="Description of the ideal thumbnail image.")
    visual_prompt: str = Field(description="Generation prompt for ComfyUI.")
    negative_prompt: str = Field(
        default=(
            "text, watermark, logo, blur, low quality, distorted, "
            "cartoon, anime, oversaturated"
        )
    )
    scene_reference: Optional[str] = Field(
        default=None,
        description="If set, use this scene_id as thumbnail source instead of generating."
    )


# ── Root project plan ─────────────────────────────────────────────────────────


class ProjectPlan(BaseModel):
    """
    The complete, LLM-generated plan for one video.

    This is the canonical contract. Every field must be present and valid
    before the generation pipeline starts.
    """

    project_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique project identifier."
    )
    title: str = Field(description="Video title (used for output dir naming).")
    concept: str = Field(description="High-level concept / elevator pitch.")
    duration_seconds: Annotated[int, Field(ge=30, le=7200)] = Field(
        description="Total target video duration in seconds."
    )
    resolution: str = Field(
        default="1920x1080",
        description="Output resolution preset string, e.g. '1920x1080'."
    )
    aspect_ratio: str = Field(default="16:9")
    fps: int = Field(default=30)
    visual_style: str = Field(
        default="realistic_cinematic",
        description="Visual style preset."
    )
    mood: str = Field(description="Overall emotional mood of the video.")
    theme: str = Field(
        default="nature",
        description="Content theme (nature, travel, meditation, etc.)."
    )
    scenes: list[Scene] = Field(
        min_length=1,
        description="Ordered list of scenes."
    )
    music_plan: MusicPlan
    ambient_audio_plan: AmbientAudioPlan
    youtube_metadata: YouTubeMetadata
    thumbnail_plan: ThumbnailPlan

    # Runtime fields
    status: ProjectStatus = Field(default=ProjectStatus.PENDING)
    created_at: Optional[str] = Field(default=None)
    completed_at: Optional[str] = Field(default=None)
    output_dir: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def validate_scene_durations(self) -> "ProjectPlan":
        """Warn if scenes don't approximately fill the target duration."""
        total = sum(s.duration_seconds for s in self.scenes)
        # Allow ±20% tolerance
        tolerance = self.duration_seconds * 0.20
        if abs(total - self.duration_seconds) > tolerance:
            # Not a hard error — LLM may intentionally plan shorter scenes
            # that will be looped/extended by the pipeline
            pass
        return self

    @property
    def total_scene_duration(self) -> int:
        return sum(s.duration_seconds for s in self.scenes)

    def scene_by_id(self, scene_id: str) -> Optional[Scene]:
        for scene in self.scenes:
            if scene.id == scene_id:
                return scene
        return None


# ── Project state (persisted during generation) ───────────────────────────────


class ProjectState(BaseModel):
    """
    Persisted project state for resume support.

    Written to project/project.json after each milestone.
    """

    project_id: str
    plan: ProjectPlan
    status: ProjectStatus = ProjectStatus.PENDING
    output_dir: str
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None


# ── Validation report ─────────────────────────────────────────────────────────


class ValidationReport(BaseModel):
    """Final quality-check report written to project/validation.json."""

    status: str = "pending"   # success | failed | partial
    video_exists: bool = False
    audio_exists: bool = False
    thumbnail_exists: bool = False
    metadata_valid: bool = False
    project_json_valid: bool = False
    duration_seconds: Optional[int] = None
    requested_duration_seconds: Optional[int] = None
    resolution: Optional[str] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
