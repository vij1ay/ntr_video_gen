"""Tests for the stub music provider."""
from pathlib import Path
import wave

from app.providers.music import StubMusicProvider, get_music_provider


class TestStubMusicProvider:
    def test_health_check(self):
        provider = StubMusicProvider()
        assert provider.health_check() is True

    def test_generate_creates_wav(self, tmp_path):
        provider = StubMusicProvider()
        out = tmp_path / "music.wav"
        result = provider.generate(
            description="peaceful ambient",
            duration_seconds=5,
            style="ambient",
            mood="peaceful",
            output_path=out,
        )
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0

    def test_generated_wav_is_valid(self, tmp_path):
        provider = StubMusicProvider()
        out = tmp_path / "music.wav"
        provider.generate("test", 3, "ambient", "peaceful", output_path=out)
        with wave.open(str(out), "r") as wav:
            assert wav.getnchannels() == 2
            assert wav.getframerate() == 44100
            assert wav.getnframes() > 0

    def test_generate_correct_duration(self, tmp_path):
        provider = StubMusicProvider()
        out = tmp_path / "music.wav"
        provider.generate("test", 10, "ambient", "peaceful", output_path=out)
        with wave.open(str(out), "r") as wav:
            actual_secs = wav.getnframes() / wav.getframerate()
        assert abs(actual_secs - 10) < 1


class TestGetMusicProvider:
    def test_stub_provider(self):
        provider = get_music_provider("stub")
        assert isinstance(provider, StubMusicProvider)

    def test_unknown_falls_back_to_stub(self):
        provider = get_music_provider("unknown_provider_xyz")
        assert isinstance(provider, StubMusicProvider)
