"""
Final quality validation — checks the completed output package.

Writes project/validation.json with a pass/fail report.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.core.logging import get_logger
from app.providers.ffmpeg import FFmpegRenderer
from app.schemas.project import ProjectPlan, ValidationReport

logger = get_logger("pipeline.validator")


class OutputValidator:
    """
    Validates the final output folder before marking a project complete.

    Checks:
    - video.mp4 exists and has correct codec/duration/resolution
    - thumbnail.jpg exists
    - audio stream present
    - YouTube metadata files exist and are valid JSON
    - project.json valid
    """

    def __init__(self, renderer: FFmpegRenderer, project_dir: Path) -> None:
        self.renderer = renderer
        self.project_dir = project_dir

    def validate(self, plan: ProjectPlan) -> ValidationReport:
        """
        Run all checks and return a ValidationReport.

        Writes the report to project/validation.json.
        """
        report = ValidationReport(
            requested_duration_seconds=plan.duration_seconds
        )
        errors: list[str] = []
        warnings: list[str] = []

        # ── Video file ────────────────────────────────────────────────────────
        video_path = self.project_dir / "video.mp4"
        if video_path.exists():
            report.video_exists = True
            try:
                info = self.renderer.get_video_info(video_path)
                report.duration_seconds = int(info.get("duration", 0))
                report.resolution = (
                    f"{info.get('width')}x{info.get('height')}"
                    if info.get("width") else None
                )
                report.video_codec = info.get("video_codec")
                report.audio_codec = info.get("audio_codec")

                if info.get("audio_codec"):
                    report.audio_exists = True
                else:
                    warnings.append("Video has no audio stream.")

                # Duration tolerance ±15%
                if report.duration_seconds and plan.duration_seconds:
                    tolerance = plan.duration_seconds * 0.15
                    diff = abs(report.duration_seconds - plan.duration_seconds)
                    if diff > tolerance:
                        warnings.append(
                            f"Video duration {report.duration_seconds}s differs from "
                            f"requested {plan.duration_seconds}s by {diff:.0f}s."
                        )

                # Resolution check
                expected = f"{plan.resolution}"
                if report.resolution and report.resolution != expected:
                    warnings.append(
                        f"Resolution mismatch: got {report.resolution}, "
                        f"expected {expected}."
                    )

            except Exception as exc:
                errors.append(f"Failed to probe video: {exc}")
        else:
            errors.append(f"video.mp4 not found at {video_path}")

        # ── Thumbnail ─────────────────────────────────────────────────────────
        thumbnail_path = self.project_dir / "thumbnail.jpg"
        if thumbnail_path.exists() and thumbnail_path.stat().st_size > 0:
            report.thumbnail_exists = True
        else:
            warnings.append("thumbnail.jpg not found or empty.")

        # ── YouTube metadata ──────────────────────────────────────────────────
        yt_metadata_path = self.project_dir / "youtube" / "metadata.json"
        if yt_metadata_path.exists():
            try:
                with open(yt_metadata_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                required = ["title", "description", "tags", "video"]
                missing = [k for k in required if not meta.get(k)]
                if missing:
                    errors.append(f"metadata.json missing fields: {missing}")
                else:
                    report.metadata_valid = True
            except Exception as exc:
                errors.append(f"metadata.json is invalid: {exc}")
        else:
            errors.append("youtube/metadata.json not found.")

        # ── Project JSON ──────────────────────────────────────────────────────
        project_json_path = self.project_dir / "project" / "project.json"
        if project_json_path.exists():
            try:
                with open(project_json_path, encoding="utf-8") as fh:
                    json.load(fh)
                report.project_json_valid = True
            except Exception as exc:
                errors.append(f"project.json is invalid: {exc}")
        else:
            warnings.append("project/project.json not found.")

        # ── Final status ──────────────────────────────────────────────────────
        report.errors = errors
        report.warnings = warnings

        if errors:
            report.status = "failed"
        elif warnings:
            report.status = "partial"
        else:
            report.status = "success"

        # Write report
        report_path = self.project_dir / "project" / "validation.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report.model_dump(), fh, indent=2)

        # Log summary
        icon = "[OK]" if report.status == "success" else ("[WARN]" if report.status == "partial" else "[FAIL]")
        logger.info("%s Validation: %s", icon, report.status.upper())
        for e in errors:
            logger.error("  [X] %s", e)
        for w in warnings:
            logger.warning("  [!] %s", w)
        if report.status == "success":
            logger.info(
                "  [OK] video=%s, duration=%ds, resolution=%s",
                report.video_exists,
                report.duration_seconds,
                report.resolution,
            )

        return report
