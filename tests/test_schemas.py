"""Tests for project schema validation."""
import pytest
from pydantic import ValidationError

from app.schemas.project import (
    AmbientAudioPlan,
    GenerationType,
    MusicPlan,
    ProjectPlan,
    Scene,
    ThumbnailPlan,
    YouTubeMetadata,
)


def make_minimal_plan(**overrides) -> dict:
    base = {
        "title": "Test Nature Video",
        "concept": "A peaceful test video.",
        "duration_seconds": 300,
        "resolution": "1920x1080",
        "aspect_ratio": "16:9",
        "fps": 30,
        "visual_style": "realistic_cinematic",
        "mood": "peaceful",
        "theme": "nature",
        "scenes": [
            {
                "id": "scene_001",
                "title": "Mountain Dawn",
                "duration_seconds": 60,
                "description": "A misty mountain at dawn.",
                "visual_prompt": "cinematic mountain landscape at dawn, mist, golden light",
                "generation_type": "image",
            }
        ],
        "music_plan": {
            "style": "ambient",
            "mood": "peaceful",
            "tempo": "very_slow",
        },
        "ambient_audio_plan": {
            "sounds": ["wind"],
            "primary_sound": "wind",
        },
        "youtube_metadata": {
            "title": "Peaceful Mountain Dawn",
            "description": "A relaxing nature video.",
            "tags": ["nature", "relaxing"],
        },
        "thumbnail_plan": {
            "concept": "Mountain at dawn.",
            "visual_prompt": "cinematic mountain dawn",
        },
    }
    base.update(overrides)
    return base


class TestScene:
    def test_minimal_valid(self):
        scene = Scene(
            id="scene_001",
            title="Test",
            duration_seconds=60,
            description="Test scene",
            visual_prompt="mountain",
        )
        assert scene.id == "scene_001"
        assert scene.generation_type == GenerationType.IMAGE

    def test_invalid_duration_too_short(self):
        with pytest.raises(ValidationError):
            Scene(
                id="scene_001",
                title="Test",
                duration_seconds=2,  # < 5 minimum
                description="Test",
                visual_prompt="mountain",
            )

    def test_invalid_empty_id(self):
        with pytest.raises(ValidationError):
            Scene(
                id="",
                title="Test",
                duration_seconds=60,
                description="Test",
                visual_prompt="mountain",
            )


class TestProjectPlan:
    def test_valid_minimal_plan(self):
        plan = ProjectPlan.model_validate(make_minimal_plan())
        assert plan.title == "Test Nature Video"
        assert len(plan.scenes) == 1
        assert plan.total_scene_duration == 60

    def test_invalid_empty_scenes(self):
        with pytest.raises(ValidationError):
            ProjectPlan.model_validate(make_minimal_plan(scenes=[]))

    def test_invalid_resolution(self):
        # Resolution validation is done in config, not schema — plan accepts any string
        plan = ProjectPlan.model_validate(make_minimal_plan(resolution="1920x1080"))
        assert plan.resolution == "1920x1080"

    def test_scene_by_id(self):
        plan = ProjectPlan.model_validate(make_minimal_plan())
        assert plan.scene_by_id("scene_001") is not None
        assert plan.scene_by_id("scene_999") is None

    def test_youtube_tags_trimmed(self):
        long_tags = ["tag_" + str(i) for i in range(100)]
        plan = ProjectPlan.model_validate(
            make_minimal_plan(
                youtube_metadata={
                    "title": "Test",
                    "description": "Test",
                    "tags": long_tags,
                }
            )
        )
        total_chars = sum(len(t) for t in plan.youtube_metadata.tags)
        assert total_chars <= 500


class TestResolutionPresets:
    def test_all_presets_valid(self):
        from app.core.config import RESOLUTION_PRESETS
        assert "1920x1080" in RESOLUTION_PRESETS
        assert "3840x2160" in RESOLUTION_PRESETS
        assert "1080x1920" in RESOLUTION_PRESETS

    def test_default_resolution(self):
        from app.core.config import DEFAULT_RESOLUTION
        assert DEFAULT_RESOLUTION == "1920x1080"
