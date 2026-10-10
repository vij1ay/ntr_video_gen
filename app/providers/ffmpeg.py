"""
FFmpeg renderer — video/audio composition engine.

All media composition goes through FFmpeg subprocess calls.
Never use this module to do things Python/OpenCV can do better.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from app.core.config import FFmpegSettings
from app.core.logging import get_logger
from app.providers.base import Renderer

logger = get_logger("providers.ffmpeg")


class FFmpegRenderer(Renderer):
    """
    Concrete renderer implementation using FFmpeg subprocesses.

    All FFmpeg commands are logged at DEBUG level so users can
    reproduce or debug individual steps.
    """

    def __init__(self, settings: Optional[FFmpegSettings] = None) -> None:
        self.settings = settings or FFmpegSettings()
        self._ffmpeg = self.settings.binary
        self._ffprobe = self.settings.ffprobe_binary

    # ── Health check ──────────────────────────────────────────────────────────

    def health_check(self) -> bool:
        """Return True if ffmpeg is found in PATH."""
        found = shutil.which(self._ffmpeg)
        if found:
            logger.debug("FFmpeg found at: %s", found)
            return True
        logger.error(
            "FFmpeg not found. Add ffmpeg to PATH or set FFMPEG_BINARY env var."
        )
        return False

    # ── Image → Video ─────────────────────────────────────────────────────────

    def image_to_video(
        self,
        image_path: Path,
        output_path: Path,
        duration_seconds: int,
        width: int,
        height: int,
        camera_motion: str = "slow_zoom_in",
        fps: int = 30,
    ) -> Path:
        """
        Convert a still image to a video clip with motion effects.

        Supports: slow_zoom_in, slow_zoom_out, slow_pan_left, slow_pan_right,
                  slow_tilt_up, slow_tilt_down, gentle_drift, static.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        vf = self._camera_motion_filter(camera_motion, width, height, duration_seconds, fps)

        cmd = [
            self._ffmpeg, "-y",
            "-loop", "1",
            "-i", str(image_path),
            "-vf", vf,
            "-t", str(duration_seconds),
            "-r", str(fps),
            "-c:v", self.settings.video_codec,
            "-crf", str(self.settings.video_crf),
            "-preset", self.settings.preset,
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]
        self._run(cmd)
        return output_path

    # ── Video concatenation ───────────────────────────────────────────────────

    def concatenate_videos(
        self,
        video_paths: list[Path],
        output_path: Path,
        crossfade_duration: float = 1.5,
    ) -> Path:
        """
        Concatenate video clips with crossfade transitions using FFmpeg.

        Uses the xfade filter for smooth transitions between clips.
        """
        if not video_paths:
            raise ValueError("No video clips provided for concatenation.")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if len(video_paths) == 1:
            # Single clip — just copy it
            import shutil as _shutil
            _shutil.copy2(str(video_paths[0]), str(output_path))
            return output_path

        # Build xfade filter chain
        # First get durations
        durations = [self._get_duration(p) for p in video_paths]

        # Build the FFmpeg filter graph for xfade
        inputs = []
        for p in video_paths:
            inputs += ["-i", str(p)]

        filter_parts = []
        current_offset = 0.0

        # Label inputs
        n = len(video_paths)
        if n == 2:
            offset = max(0.01, durations[0] - crossfade_duration)
            filter_parts.append(
                f"[0:v][1:v]xfade=transition=fade:duration={crossfade_duration}"
                f":offset={offset:.3f}[vout]"
            )
            filter_str = ";".join(filter_parts)
            cmd = [
                self._ffmpeg, "-y",
                *inputs,
                "-filter_complex", filter_str,
                "-map", "[vout]",
                "-c:v", self.settings.video_codec,
                "-crf", str(self.settings.video_crf),
                "-preset", self.settings.preset,
                "-pix_fmt", "yuv420p",
                str(output_path),
            ]
        else:
            # For N > 2: chain xfades sequentially
            # [0][1]xfade→[tmp1], [tmp1][2]xfade→[tmp2], …
            offset = max(0.01, durations[0] - crossfade_duration)
            filter_parts.append(
                f"[0:v][1:v]xfade=transition=fade:"
                f"duration={crossfade_duration}:offset={offset:.3f}[tmp1]"
            )
            cumulative = offset + crossfade_duration - crossfade_duration
            running_dur = durations[0] + durations[1] - crossfade_duration

            for i in range(2, n):
                label_in = f"[tmp{i - 1}]"
                label_out = "[vout]" if i == n - 1 else f"[tmp{i}]"
                offset = max(0.01, running_dur - crossfade_duration)
                filter_parts.append(
                    f"{label_in}[{i}:v]xfade=transition=fade:"
                    f"duration={crossfade_duration}:offset={offset:.3f}{label_out}"
                )
                running_dur += durations[i] - crossfade_duration

            filter_str = ";".join(filter_parts)
            cmd = [
                self._ffmpeg, "-y",
                *inputs,
                "-filter_complex", filter_str,
                "-map", "[vout]",
                "-c:v", self.settings.video_codec,
                "-crf", str(self.settings.video_crf),
                "-preset", self.settings.preset,
                "-pix_fmt", "yuv420p",
                str(output_path),
            ]

        self._run(cmd)
        return output_path

    # ── Audio mixing ──────────────────────────────────────────────────────────

    def mix_audio(
        self,
        video_path: Path,
        music_path: Path,
        output_path: Path,
        ambience_path: Optional[Path] = None,
        music_volume: float = 0.65,
        ambience_volume: float = 0.35,
    ) -> Path:
        """
        Mix video with music and optional ambience, writing a final MP4.

        The audio is volume-normalised and loops to match video duration.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        video_duration = self._get_duration(video_path)

        if ambience_path and ambience_path.exists():
            # Three-way mix: video (silent) + music + ambience
            filter_complex = (
                f"[1:a]volume={music_volume},atrim=duration={video_duration}[music];"
                f"[2:a]volume={ambience_volume},atrim=duration={video_duration}[amb];"
                f"[music][amb]amix=inputs=2:normalize=0[aout]"
            )
            cmd = [
                self._ffmpeg, "-y",
                "-i", str(video_path),
                "-stream_loop", "-1", "-i", str(music_path),
                "-stream_loop", "-1", "-i", str(ambience_path),
                "-filter_complex", filter_complex,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", self.settings.audio_codec,
                "-b:a", self.settings.audio_bitrate,
                "-shortest",
                str(output_path),
            ]
        else:
            # Two-way mix: video (silent) + music only
            filter_complex = (
                f"[1:a]volume={music_volume},atrim=duration={video_duration}[aout]"
            )
            cmd = [
                self._ffmpeg, "-y",
                "-i", str(video_path),
                "-stream_loop", "-1", "-i", str(music_path),
                "-filter_complex", filter_complex,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", self.settings.audio_codec,
                "-b:a", self.settings.audio_bitrate,
                "-shortest",
                str(output_path),
            ]

        self._run(cmd)
        return output_path

    def crossfade_audio_tracks(
        self,
        audio_paths: list[Path],
        output_path: Path,
        crossfade_duration: float = 3.0,
        target_duration: Optional[int] = None,
    ) -> Path:
        """
        Crossfade multiple audio tracks into a seamless continuous soundtrack.

        Args:
            audio_paths: List of audio files to chain.
            output_path: Output audio file path.
            crossfade_duration: Overlap duration at each join.
            target_duration: If set, trim/loop to exactly this length.

        Returns:
            Path to the merged audio file.
        """
        if not audio_paths:
            raise ValueError("No audio paths provided.")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if len(audio_paths) == 1:
            if target_duration:
                # Loop single track to target duration
                cmd = [
                    self._ffmpeg, "-y",
                    "-i", str(audio_paths[0]),
                    "-af", (
                        f"aloop=loop=-1:size=2e9,"
                        f"atrim=duration={target_duration},"
                        f"afade=t=in:d=2,afade=t=out:st={target_duration - 3}:d=3"
                    ),
                    str(output_path),
                ]
            else:
                import shutil as _shutil
                _shutil.copy2(str(audio_paths[0]), str(output_path))
                return output_path
            self._run(cmd)
            return output_path

        # For multiple tracks: concatenate with acrossfade
        inputs = []
        for p in audio_paths:
            inputs += ["-i", str(p)]

        durations = [self._get_duration(p) for p in audio_paths]
        n = len(audio_paths)

        if n == 2:
            filter_str = f"[0:a][1:a]acrossfade=d={crossfade_duration}[aout]"
        else:
            parts = [f"[0:a][1:a]acrossfade=d={crossfade_duration}[tmp1]"]
            for i in range(2, n):
                label_in = f"[tmp{i - 1}]"
                label_out = "[aout]" if i == n - 1 else f"[tmp{i}]"
                parts.append(f"{label_in}[{i}:a]acrossfade=d={crossfade_duration}{label_out}")
            filter_str = ";".join(parts)

        if target_duration:
            fade_out_start = max(0, target_duration - 3)
            fade_out_dur = min(3, target_duration)
            filter_complex = (
                f"{filter_str};"
                f"[aout]atrim=duration={target_duration},"
                f"afade=t=in:d=2,afade=t=out:st={fade_out_start}:d={fade_out_dur}[final_audio]"
            )
            map_arg = "[final_audio]"
        else:
            filter_complex = filter_str
            map_arg = "[aout]"

        is_wav = output_path.suffix.lower() == ".wav"
        audio_codec = "pcm_s16le" if is_wav else self.settings.audio_codec

        cmd = [
            self._ffmpeg, "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", map_arg,
            "-c:a", audio_codec,
        ]
        if not is_wav:
            cmd.extend(["-b:a", self.settings.audio_bitrate])

        cmd.append(str(output_path))
        self._run(cmd)
        return output_path

    def extract_thumbnail(
        self,
        video_path: Path,
        output_path: Path,
        time_offset: float = 10.0,
    ) -> Path:
        """Extract a single frame from a video as a thumbnail."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self._ffmpeg, "-y",
            "-ss", str(time_offset),
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(output_path),
        ]
        self._run(cmd)
        return output_path

    def get_video_info(self, video_path: Path) -> dict:
        """
        Return video metadata via ffprobe.

        Returns dict with keys: duration, width, height, video_codec, audio_codec.
        """
        cmd = [
            self._ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            str(video_path),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr}")

        data = json.loads(result.stdout)
        info: dict = {
            "duration": float(data.get("format", {}).get("duration", 0)),
            "width": None,
            "height": None,
            "video_codec": None,
            "audio_codec": None,
        }
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and info["width"] is None:
                info["width"] = stream.get("width")
                info["height"] = stream.get("height")
                info["video_codec"] = stream.get("codec_name")
            elif stream.get("codec_type") == "audio" and info["audio_codec"] is None:
                info["audio_codec"] = stream.get("codec_name")
        return info

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_duration(self, path: Path) -> float:
        """Return the duration of a media file in seconds."""
        cmd = [
            self._ffprobe,
            "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(path),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15
        )
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 0.0

    def _camera_motion_filter(
        self,
        motion: str,
        width: int,
        height: int,
        duration: int,
        fps: int,
    ) -> str:
        """
        Build an FFmpeg zoompan/crop filter string for the given camera motion.

        All motions use very subtle values suitable for relaxing nature videos.
        """
        n_frames = duration * fps
        # Base scale: slightly oversized to allow movement without black borders
        scale_w = int(width * 1.08)
        scale_h = int(height * 1.08)
        motion = motion.lower().replace(" ", "_")

        if motion in ("slow_zoom_in", "slow_forward"):
            zoom_start = 1.0
            zoom_end = 1.06
            # Linear zoom via zoompan
            zoom_rate = (zoom_end - zoom_start) / n_frames
            return (
                f"scale={scale_w}:{scale_h},"
                f"zoompan=z='min(zoom+{zoom_rate:.6f},{zoom_end})':d={n_frames}"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":s={width}x{height}:fps={fps}"
            )

        elif motion in ("slow_zoom_out", "slow_backward"):
            zoom_start = 1.06
            zoom_end = 1.0
            zoom_rate = (zoom_start - zoom_end) / n_frames
            return (
                f"scale={scale_w}:{scale_h},"
                f"zoompan=z='max(zoom-{zoom_rate:.6f},{zoom_end})':d={n_frames}"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":s={width}x{height}:fps={fps}"
            )

        elif motion == "slow_pan_right":
            return (
                f"scale={scale_w}:{scale_h},"
                f"zoompan=z=1.04:d={n_frames}"
                f":x='(iw-iw/zoom)/2 + (iw-iw/zoom)/2 * (on/{n_frames})'"
                f":y='ih/2-(ih/zoom/2)'"
                f":s={width}x{height}:fps={fps}"
            )

        elif motion == "slow_pan_left":
            return (
                f"scale={scale_w}:{scale_h},"
                f"zoompan=z=1.04:d={n_frames}"
                f":x='(iw-iw/zoom)/2 - (iw-iw/zoom)/2 * (on/{n_frames})'"
                f":y='ih/2-(ih/zoom/2)'"
                f":s={width}x{height}:fps={fps}"
            )

        elif motion == "slow_tilt_up":
            return (
                f"scale={scale_w}:{scale_h},"
                f"zoompan=z=1.04:d={n_frames}"
                f":x='iw/2-(iw/zoom/2)'"
                f":y='(ih-ih/zoom)/2 - (ih-ih/zoom)/2 * (on/{n_frames})'"
                f":s={width}x{height}:fps={fps}"
            )

        elif motion == "slow_tilt_down":
            return (
                f"scale={scale_w}:{scale_h},"
                f"zoompan=z=1.04:d={n_frames}"
                f":x='iw/2-(iw/zoom/2)'"
                f":y='(ih-ih/zoom)/2 + (ih-ih/zoom)/2 * (on/{n_frames})'"
                f":s={width}x{height}:fps={fps}"
            )

        elif motion == "gentle_drift":
            # Slow diagonal drift
            return (
                f"scale={scale_w}:{scale_h},"
                f"zoompan=z=1.04:d={n_frames}"
                f":x='(iw-iw/zoom)/2 + (iw-iw/zoom)/4 * sin(on/{n_frames} * 3.14)'"
                f":y='ih/2-(ih/zoom/2)'"
                f":s={width}x{height}:fps={fps}"
            )

        else:  # static / unknown
            return (
                f"scale={scale_w}:{scale_h},"
                f"zoompan=z=1.04:d={n_frames}"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":s={width}x{height}:fps={fps}"
            )

    def _run(self, cmd: list[str]) -> None:
        """Execute an FFmpeg command and raise on failure."""
        logger.debug("FFmpeg: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.settings.timeout_seconds if hasattr(self.settings, "timeout_seconds") else 3600,
        )
        if result.returncode != 0:
            logger.error("FFmpeg stderr:\n%s", result.stderr[-3000:])
            raise RuntimeError(
                f"FFmpeg command failed (exit code {result.returncode}).\n"
                f"Command: {' '.join(cmd)}\n"
                f"Stderr (last 500 chars): {result.stderr[-500:]}"
            )
