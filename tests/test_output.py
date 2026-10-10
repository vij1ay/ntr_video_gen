"""Tests for output directory management."""
from pathlib import Path
import pytest
from app.core.output import _sanitize_title, make_output_dir
from datetime import datetime


class TestSanitizeTitle:
    def test_basic(self):
        assert _sanitize_title("Peaceful Rainy Mountains") == "peaceful_rainy_mountains"

    def test_special_chars_removed(self):
        result = _sanitize_title("Rain & River: A Nature Video!")
        assert ":" not in result
        assert "&" not in result
        assert "!" not in result

    def test_unicode_normalised(self):
        result = _sanitize_title("Björn's Forest")
        assert "bjrn" in result or "bjorn" in result

    def test_truncated(self):
        long = "a" * 100
        assert len(_sanitize_title(long)) <= 60

    def test_windows_invalid_chars(self):
        result = _sanitize_title('Video: "Nature" <Test>')
        for char in r'<>:"/\|?*':
            assert char not in result


class TestMakeOutputDir:
    def test_creates_directory(self, tmp_path):
        ts = datetime(2026, 10, 6, 14, 30, 0)
        project_dir = make_output_dir("Test Video", base_dir=tmp_path, timestamp=ts)
        assert project_dir.exists()

    def test_directory_name_contains_slug(self, tmp_path):
        ts = datetime(2026, 10, 6, 14, 30, 0)
        project_dir = make_output_dir("Peaceful Rain", base_dir=tmp_path, timestamp=ts)
        assert "peaceful_rain" in project_dir.name

    def test_directory_name_contains_timestamp(self, tmp_path):
        ts = datetime(2026, 10, 6, 14, 30, 0)
        project_dir = make_output_dir("Test", base_dir=tmp_path, timestamp=ts)
        assert "20261006_143000" in project_dir.name

    def test_subdirectories_created(self, tmp_path):
        project_dir = make_output_dir("Test", base_dir=tmp_path)
        for subdir in ["youtube", "project", "scenes", "audio", "logs"]:
            assert (project_dir / subdir).is_dir(), f"Missing subdir: {subdir}"
