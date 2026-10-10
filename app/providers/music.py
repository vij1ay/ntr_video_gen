"""
Stub music provider — generates silent audio as a placeholder.

Used when no real music model is configured, so the pipeline can complete
end-to-end without a music model. Replace with a real provider by implementing
MusicProvider and pointing MUSIC_PROVIDER at it.
"""
from __future__ import annotations

import struct
import wave
from pathlib import Path
from typing import Optional

from app.core.logging import get_logger
from app.providers.base import MusicProvider

logger = get_logger("providers.music_stub")


class StubMusicProvider(MusicProvider):
    """
    Generates a silent WAV file as a music placeholder.

    This allows the full pipeline to run without any music model installed.
    """

    def health_check(self) -> bool:
        logger.debug("StubMusicProvider: always healthy.")
        return True

    def generate(
        self,
        description: str,
        duration_seconds: int,
        style: str,
        mood: str,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Write a silent PCM WAV file of the requested duration.

        Args:
            description: Ignored (no real generation).
            duration_seconds: Length of the silent audio track.
            style: Ignored.
            mood: Ignored.
            output_path: Where to save the WAV file.

        Returns:
            Path to the generated silent WAV file.
        """
        if output_path is None:
            output_path = Path("music_stub.wav")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        sample_rate = 44100
        n_channels = 2
        sample_width = 2  # 16-bit
        n_frames = sample_rate * duration_seconds

        logger.info(
            "StubMusicProvider: writing %ds silent WAV → %s",
            duration_seconds,
            output_path,
        )

        with wave.open(str(output_path), "w") as wav_file:
            wav_file.setnchannels(n_channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            # Write zeros in chunks to avoid huge memory allocation
            chunk_size = sample_rate  # 1 second at a time
            silent_chunk = b"\x00" * chunk_size * n_channels * sample_width
            for _ in range(n_frames // chunk_size):
                wav_file.writeframes(silent_chunk)
            remainder = n_frames % chunk_size
            if remainder:
                wav_file.writeframes(b"\x00" * remainder * n_channels * sample_width)

        return output_path


class MusicGenProvider(MusicProvider):
    """
    Local AI Music generation using Hugging Face Transformers (Meta MusicGen).
    Compatible with Python 3.12+ (bypasses legacy audiocraft torch==2.1.0 pin).
    """

    def __init__(self, model_id: str = "facebook/musicgen-small") -> None:
        self.model_id = model_id
        self._model = None
        self._processor = None

    def health_check(self) -> bool:
        try:
            import torch
            import transformers
            import scipy
            return True
        except ImportError as e:
            logger.warning("MusicGenProvider dependencies missing: %s", e)
            return False

    def _load_model(self):
        if self._model is None:
            import torch
            from transformers import AutoProcessor, MusicgenForConditionalGeneration

            logger.info("Loading MusicGen model '%s' (this may take a moment on first run)...", self.model_id)
            self._processor = AutoProcessor.from_pretrained(self.model_id)
            self._model = MusicgenForConditionalGeneration.from_pretrained(self.model_id)
            
            # Use GPU if CUDA available, otherwise CPU
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model.to(device)
            logger.info("MusicGen loaded on device: %s", device)

    def generate(
        self,
        description: str,
        duration_seconds: int,
        style: str,
        mood: str,
        output_path: Optional[Path] = None,
    ) -> Path:
        import torch
        import scipy.io.wavfile

        if output_path is None:
            output_path = Path("music_generated.wav")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self._load_model()

        # MusicGen tokens: roughly 50 tokens per second of audio
        max_new_tokens = int(duration_seconds * 50)
        # Cap generation per call to 1500 tokens (~30s) for stability
        max_new_tokens = min(max_new_tokens, 1500)

        prompt_text = f"{style} relaxing nature music, {mood}, {description}"
        logger.info("Generating music with prompt: '%s' (tokens=%d)...", prompt_text, max_new_tokens)

        device = self._model.device
        inputs = self._processor(
            text=[prompt_text],
            padding=True,
            return_tensors="pt",
        ).to(device)

        with torch.no_grad():
            audio_values = self._model.generate(**inputs, max_new_tokens=max_new_tokens)

        sampling_rate = self._model.config.audio_encoder.sampling_rate
        # audio_values shape: (batch, channels, samples) -> extract first batch
        audio_data = audio_values[0, 0].cpu().numpy()

        scipy.io.wavfile.write(str(output_path), rate=sampling_rate, data=audio_data)
        logger.info("Saved generated music to %s", output_path)
        return output_path


def get_music_provider(provider_name: str, model_id: str = "facebook/musicgen-small") -> MusicProvider:
    """
    Factory function — return the appropriate MusicProvider.

    Supported values for provider_name:
        "stub"          → StubMusicProvider (silent placeholder)
        "musicgen"      → MusicGenProvider (Hugging Face Transformers)
        "audiocraft"    → MusicGenProvider (aliases to modern Transformers provider)
    """
    name = provider_name.lower().strip()
    if name in ("musicgen", "audiocraft"):
        return MusicGenProvider(model_id=model_id)

    if name != "stub":
        logger.warning(
            "Unknown music provider '%s'. Falling back to stub.", provider_name
        )
    return StubMusicProvider()

