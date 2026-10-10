"""
Main orchestrator — ties all pipeline stages together.

This is the top-level engine that the CLI calls. It coordinates:
  1. Pre-flight health checks
  2. LLM scene planning
  3. Output directory creation
  4. Scene generation (ComfyUI)
  5. Audio generation + mixing
  6. Video composition (FFmpeg)
  7. Thumbnail generation
  8. YouTube metadata writing
  9. Final validation
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.core.config import AppConfig
from app.core.logging import get_logger, setup_logging
from app.core.output import make_output_dir
from app.pipeline.audio import AudioPipeline
from app.pipeline.composer import VideoComposer
from app.pipeline.generator import SceneGenerator
from app.pipeline.planner import ScenePlanner
from app.pipeline.validator import OutputValidator
from app.providers.comfyui import ComfyUIProvider
from app.providers.ffmpeg import FFmpegRenderer
from app.providers.lmstudio import LMStudioProvider
from app.schemas.project import ProjectPlan, ProjectState, ProjectStatus

logger = get_logger("orchestrator")
console = Console()


class GenerationOrchestrator:
    """
    Top-level pipeline orchestrator.

    Designed for single-threaded local execution. All state is
    persisted to disk so the job can be resumed after failure.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config

        # Instantiate all providers
        self.llm = LMStudioProvider(settings=config.llm)
        self.comfyui = ComfyUIProvider(settings=config.comfyui)
        self.renderer = FFmpegRenderer(settings=config.ffmpeg)

        # Instantiate pipeline stages
        self.planner = ScenePlanner(llm=self.llm, config=config)

    # ── Public entry points ───────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        duration_seconds: int,
        resolution: str,
        visual_style: str,
        music_style: str,
        output_dir: str,
        dry_run: bool = False,
        seed: Optional[int] = None,
        model: Optional[str] = None,
        no_ambience: bool = False,
    ) -> Optional[Path]:
        """
        Run the full generation pipeline.

        Args:
            prompt: Natural-language video description.
            duration_seconds: Target duration.
            resolution: Resolution preset.
            visual_style: Visual style preset.
            music_style: Music style preset.
            output_dir: Base output directory.
            dry_run: If True, only plan — no expensive generation.
            seed: Optional reproducibility seed.
            model: Override LLM model.
            no_ambience: If True, skip ambient audio.

        Returns:
            Path to the project output directory, or None on failure.
        """
        if model:
            self.llm.model = model

        # ── Phase 0: Pre-flight checks ────────────────────────────────────────
        if not dry_run:
            self._preflight_checks(skip_comfyui=False)
        else:
            self._preflight_checks(skip_comfyui=True)

        # ── Phase 1: LLM Scene Planning ───────────────────────────────────────
        console.rule("[bold blue]Phase 1: Planning")
        plan = self.planner.plan(
            user_prompt=prompt,
            duration_seconds=duration_seconds,
            resolution=resolution,
            visual_style=visual_style,
            music_style=music_style,
            seed=seed,
        )

        # ── Create output directory ───────────────────────────────────────────
        project_dir = make_output_dir(title=plan.title, base_dir=output_dir)
        plan.output_dir = str(project_dir)
        plan.created_at = datetime.now().isoformat()

        # Setup file logging
        setup_logging(
            log_file=project_dir / "logs" / "generation.log",
            verbose=True,
        )
        logger.info("Project: %s → %s", plan.title, project_dir)

        # Build initial state
        state = ProjectState(
            project_id=plan.project_id,
            plan=plan,
            status=ProjectStatus.PLANNING,
            output_dir=str(project_dir),
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        self._save_state(state, project_dir)
        self._save_scene_plan(plan, project_dir)
        self._print_plan_summary(plan, project_dir)

        if dry_run:
            console.print(
                Panel(
                    "[bold green]Dry run complete.[/]\n"
                    f"Plan saved to: [cyan]{project_dir}[/]",
                    title="Dry Run",
                )
            )
            return project_dir

        # ── Phase 2: Scene Generation ─────────────────────────────────────────
        console.rule("[bold blue]Phase 2: Scene Generation")
        state.status = ProjectStatus.GENERATING
        generator = SceneGenerator(
            comfyui=self.comfyui,
            renderer=self.renderer,
            config=self.config,
            project_dir=project_dir,
        )
        scene_clips = generator.generate_all(state)

        failed = [s for s in plan.scenes if s.status.value == "failed"]
        if not scene_clips:
            raise RuntimeError(
                "No scene clips were generated. Check ComfyUI connectivity and workflow files."
            )
        if failed:
            logger.warning("%d scene(s) failed — continuing with available clips.", len(failed))

        # ── Phase 3: Video Composition ────────────────────────────────────────
        console.rule("[bold blue]Phase 3: Video Composition")
        state.status = ProjectStatus.COMPOSING
        self._save_state(state, project_dir)

        composer = VideoComposer(
            renderer=self.renderer,
            config=self.config,
            project_dir=project_dir,
        )
        silent_video = composer.compose(plan, scene_clips)

        # ── Phase 4: Audio ────────────────────────────────────────────────────
        console.rule("[bold blue]Phase 4: Audio")
        audio_pipeline = AudioPipeline(
            renderer=self.renderer,
            config=self.config,
            project_dir=project_dir,
            assets_dir=Path(self.config.paths.assets_dir),
        )
        if no_ambience:
            plan.ambient_audio_plan.sounds = []
            plan.ambient_audio_plan.primary_sound = None

        final_video, ambience_path = audio_pipeline.build_final_audio(
            video_path=silent_video,
            music_plan=plan.music_plan,
            audio_plan=plan.ambient_audio_plan,
            duration_seconds=duration_seconds,
        )

        # ── Phase 5: Finalize + Thumbnail ─────────────────────────────────────
        console.rule("[bold blue]Phase 5: Finalize")
        final = composer.finalize(final_video, plan)
        composer.generate_thumbnail(
            plan=plan,
            comfyui=self.comfyui,
            video_path=final,
        )

        # ── Phase 6: Validation ───────────────────────────────────────────────
        console.rule("[bold blue]Phase 6: Validation")
        validator = OutputValidator(renderer=self.renderer, project_dir=project_dir)
        report = validator.validate(plan)

        # ── Done ──────────────────────────────────────────────────────────────
        state.status = ProjectStatus.COMPLETED
        state.completed_at = datetime.now().isoformat()
        self._save_state(state, project_dir)

        self._print_completion_summary(plan, project_dir, report)
        return project_dir

    def resume(self, project_dir: Path) -> Optional[Path]:
        """
        Resume a failed or interrupted project.

        Args:
            project_dir: Path to the existing project output directory.

        Returns:
            Path to the completed project directory.
        """
        state_path = project_dir / "project" / "project.json"
        if not state_path.exists():
            raise FileNotFoundError(
                f"No project.json found in {project_dir}. "
                "Cannot resume — project state is missing."
            )

        with open(state_path, encoding="utf-8") as fh:
            raw = json.load(fh)

        state = ProjectState.model_validate(raw)
        plan = state.plan
        logger.info("Resuming project: %s", plan.title)

        # Re-run from scene generation (skips completed scenes)
        setup_logging(
            log_file=project_dir / "logs" / "generation.log",
            verbose=True,
        )

        console.rule("[bold yellow]Resuming Generation")
        generator = SceneGenerator(
            comfyui=self.comfyui,
            renderer=self.renderer,
            config=self.config,
            project_dir=project_dir,
        )
        scene_clips = generator.generate_all(state)

        composer = VideoComposer(
            renderer=self.renderer,
            config=self.config,
            project_dir=project_dir,
        )
        silent_video = composer.compose(plan, scene_clips)

        audio_pipeline = AudioPipeline(
            renderer=self.renderer,
            config=self.config,
            project_dir=project_dir,
            assets_dir=Path(self.config.paths.assets_dir),
        )
        final_video, _ = audio_pipeline.build_final_audio(
            video_path=silent_video,
            music_plan=plan.music_plan,
            audio_plan=plan.ambient_audio_plan,
            duration_seconds=plan.duration_seconds,
        )

        final = composer.finalize(final_video, plan)
        composer.generate_thumbnail(plan=plan, comfyui=self.comfyui, video_path=final)

        validator = OutputValidator(renderer=self.renderer, project_dir=project_dir)
        report = validator.validate(plan)

        state.status = ProjectStatus.COMPLETED
        state.completed_at = datetime.now().isoformat()
        self._save_state(state, project_dir)

        self._print_completion_summary(plan, project_dir, report)
        return project_dir

    # ── Private helpers ───────────────────────────────────────────────────────

    def _preflight_checks(self, skip_comfyui: bool = False) -> None:
        """Check all required dependencies before starting."""
        console.rule("[bold blue]Pre-flight Checks")
        all_ok = True

        checks = [
            ("FFmpeg", self.renderer.health_check),
            ("LM Studio", self.llm.health_check),
        ]
        if not skip_comfyui:
            checks.append(("ComfyUI", self.comfyui.health_check))

        for name, check_fn in checks:
            try:
                ok = check_fn()
            except Exception:
                ok = False

            status = "[green]OK[/]" if ok else "[red]UNAVAILABLE[/]"
            console.print(f"  {name:15s} {status}")
            if not ok:
                all_ok = False

        if not all_ok:
            raise RuntimeError(
                "One or more dependencies are unavailable. "
                "Please check the services above and retry."
            )
        console.print()

    def _save_state(self, state: ProjectState, project_dir: Path) -> None:
        state.updated_at = datetime.now().isoformat()
        state_path = project_dir / "project" / "project.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(state.model_dump(), fh, indent=2, default=str)

    def _save_scene_plan(self, plan: ProjectPlan, project_dir: Path) -> None:
        plan_path = project_dir / "project" / "scene_plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump(plan.model_dump(), fh, indent=2, default=str)

    def _print_plan_summary(self, plan: ProjectPlan, project_dir: Path) -> None:
        """Print a rich summary table of the scene plan."""
        table = Table(title=f"Scene Plan: {plan.title}", show_lines=True)
        table.add_column("#", style="dim", width=4)
        table.add_column("Scene", style="bold")
        table.add_column("Duration", justify="right")
        table.add_column("Type", style="cyan")
        table.add_column("Motion")

        for i, scene in enumerate(plan.scenes, 1):
            table.add_row(
                str(i),
                scene.title,
                f"{scene.duration_seconds}s",
                scene.generation_type.value,
                scene.camera_motion,
            )

        console.print(table)
        console.print(f"  Total planned:   [bold]{plan.total_scene_duration}s[/]")
        console.print(f"  Target duration: [bold]{plan.duration_seconds}s[/]")
        console.print(f"  Music style:     [bold]{plan.music_plan.style}[/]")
        console.print(f"  Output dir:      [cyan]{project_dir}[/]")
        console.print()

    def _print_completion_summary(self, plan: ProjectPlan, project_dir: Path, report) -> None:
        status_color = (
            "green" if report.status == "success"
            else "yellow" if report.status == "partial"
            else "red"
        )
        console.print(
            Panel(
                f"[bold {status_color}]Validation: {report.status.upper()}[/]\n\n"
                f"Output folder:  [cyan]{project_dir}[/]\n"
                f"Video:          [cyan]{project_dir / 'video.mp4'}[/]\n"
                f"Thumbnail:      [cyan]{project_dir / 'thumbnail.jpg'}[/]\n"
                f"Duration:       {report.duration_seconds}s "
                f"(requested: {report.requested_duration_seconds}s)\n"
                f"Resolution:     {report.resolution}\n",
                title="[DONE] Generation Complete" if report.status == "success" else "[WARN] Generation Done",
            )
        )
