"""Tests for FFmpeg renderer (mocked subprocess calls)."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import FFmpegSettings
from app.providers.ffmpeg import FFmpegRenderer


def make_renderer(binary="ffmpeg", ffprobe="ffprobe") -> FFmpegRenderer:
    settings = FFmpegSettings(binary=binary, ffprobe_binary=ffprobe)
    return FFmpegRenderer(settings=settings)


class TestFFmpegRenderer:
    def test_health_check_found(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            renderer = make_renderer()
            assert renderer.health_check() is True

    def test_health_check_not_found(self):
        with patch("shutil.which", return_value=None):
            renderer = make_renderer()
            assert renderer.health_check() is False

    def test_camera_motion_filter_zoom_in(self):
        renderer = make_renderer()
        vf = renderer._camera_motion_filter("slow_zoom_in", 1920, 1080, 60, 30)
        assert "zoompan" in vf
        assert "1920x1080" in vf

    def test_camera_motion_filter_static(self):
        renderer = make_renderer()
        vf = renderer._camera_motion_filter("static", 1920, 1080, 60, 30)
        assert "zoompan" in vf

    def test_camera_motion_filter_pan_right(self):
        renderer = make_renderer()
        vf = renderer._camera_motion_filter("slow_pan_right", 1920, 1080, 60, 30)
        assert "zoompan" in vf

    @patch("subprocess.run")
    def test_run_succeeds(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        renderer = make_renderer()
        renderer._run(["ffmpeg", "-version"])  # Should not raise

    @patch("subprocess.run")
    def test_run_raises_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="error msg", stdout="")
        renderer = make_renderer()
        with pytest.raises(RuntimeError, match="FFmpeg command failed"):
            renderer._run(["ffmpeg", "-bad-flag"])

    @patch("subprocess.run")
    def test_get_duration(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="123.45\n", stderr="")
        renderer = make_renderer()
        duration = renderer._get_duration(Path("test.mp4"))
        assert duration == pytest.approx(123.45)
