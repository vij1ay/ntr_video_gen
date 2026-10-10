"""
CLI entry point — `python -m app generate ...`

Uses Click for argument parsing. Rich is used for all user-facing output.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from app.core.config import AppConfig, RESOLUTION_PRESETS, get_config
from app.core.duration import format_duration, parse_duration
from app.core.logging import setup_logging

console = Console()

# ── Shared option groups ──────────────────────────────────────────────────────

VALID_STYLES = [
    "realistic", "cinematic", "realistic_cinematic", "nature_documentary",
    "peaceful", "dreamy", "atmospheric", "minimalist", "photorealistic",
]
VALID_MUSIC_STYLES = [
    "ambient", "soft_piano", "meditation", "sleep", "nature_ambient",
    "cinematic_ambient", "acoustic", "minimal", "deep_ambient",
]


@click.group()
@click.version_option(version="0.1.0", prog_name="ntr-video-gen")
def cli() -> None:
    """
    Nature Video Generator — local AI video automation.

    Generate relaxing nature videos using local LLM + ComfyUI + FFmpeg.
    """
    pass


# ── generate command ──────────────────────────────────────────────────────────

@cli.command()
@click.option(
    "--prompt", "-p",
    default=None,
    help="Natural-language description of the video.",
)
@click.option(
    "--input", "-i", "input_file",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Input file (.txt, .yaml, .json) containing the prompt or full project.",
)
@click.option(
    "--duration", "-d",
    default="15m",
    show_default=True,
    help="Video duration: 15m, 30m, 90s, 1h, etc. Default: 15m.",
)
@click.option(
    "--resolution", "-r",
    default="1920x1080",
    show_default=True,
    type=click.Choice(list(RESOLUTION_PRESETS.keys()), case_sensitive=False),
    help="Output resolution preset.",
)
@click.option(
    "--model", "-m",
    default=None,
    help="Override LLM model (e.g. qwen/qwen3.8-27b).",
)
@click.option(
    "--output", "-o",
    default=None,
    help="Output directory base path. Default from config.",
)
@click.option(
    "--style", "-s",
    default="realistic_cinematic",
    show_default=True,
    type=click.Choice(VALID_STYLES, case_sensitive=False),
    help="Visual style preset.",
)
@click.option(
    "--music",
    default="ambient",
    show_default=True,
    type=click.Choice(VALID_MUSIC_STYLES, case_sensitive=False),
    help="Music style preset.",
)
@click.option(
    "--no-ambience",
    is_flag=True,
    default=False,
    help="Disable ambient nature sounds.",
)
@click.option(
    "--seed",
    default=None,
    type=int,
    help="Random seed for reproducibility.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Plan only — do not run ComfyUI or FFmpeg.",
)
@click.option(
    "--config", "config_file",
    default=None,
    type=click.Path(dir_okay=False),
    help="Path to config YAML file. Default: config/app.yaml.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Enable debug logging.",
)
def generate(
    prompt: Optional[str],
    input_file: Optional[str],
    duration: str,
    resolution: str,
    model: Optional[str],
    output: Optional[str],
    style: str,
    music: str,
    no_ambience: bool,
    seed: Optional[int],
    dry_run: bool,
    config_file: Optional[str],
    verbose: bool,
) -> None:
    """
    Generate a relaxing nature video.

    \b
    Examples:
      python -m app generate --prompt "Peaceful rainy mountains with forest and deer"
      python -m app generate --input projects/rainy_alps.txt --duration 30m
      python -m app generate --prompt "Ocean sunset" --duration 10m --dry-run
    """
    # Setup console logging (file logging is set up once project dir exists)
    setup_logging(verbose=verbose)

    # Load config
    cfg_path = Path(config_file) if config_file else None
    config = get_config(cfg_path)

    # Resolve prompt
    user_prompt = _resolve_prompt(prompt, input_file)
    if not user_prompt:
        console.print(
            "[red]Error:[/] Provide --prompt or --input.\n"
            "Example: python -m app generate --prompt 'Peaceful alpine valley'"
        )
        sys.exit(1)

    # Parse duration
    try:
        duration_seconds = parse_duration(duration)
    except ValueError as exc:
        console.print(f"[red]Error:[/] {exc}")
        sys.exit(1)

    output_dir = output or config.paths.output_dir
    console.print(
        f"\n[bold green]Nature Video Generator[/]\n"
        f"  Prompt:    {user_prompt[:80]}{'…' if len(user_prompt) > 80 else ''}\n"
        f"  Duration:  {format_duration(duration_seconds)}\n"
        f"  Resolution:{resolution}\n"
        f"  Style:     {style}\n"
        f"  Music:     {music}\n"
        f"  Dry run:   {dry_run}\n"
    )

    # Run orchestrator
    from app.pipeline.orchestrator import GenerationOrchestrator

    try:
        orchestrator = GenerationOrchestrator(config=config)
        project_dir = orchestrator.generate(
            prompt=user_prompt,
            duration_seconds=duration_seconds,
            resolution=resolution,
            visual_style=style,
            music_style=music,
            output_dir=output_dir,
            dry_run=dry_run,
            seed=seed,
            model=model,
            no_ambience=no_ambience,
        )
        if project_dir:
            console.print(f"\n[bold cyan]Output:[/] {project_dir}\n")
    except RuntimeError as exc:
        console.print(f"\n[bold red]Error:[/] {exc}\n")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/]")
        sys.exit(130)


# ── resume command ────────────────────────────────────────────────────────────

@cli.command()
@click.argument(
    "project_dir",
    type=click.Path(exists=True, file_okay=False),
)
@click.option("--verbose", "-v", is_flag=True, default=False)
@click.option(
    "--config", "config_file",
    default=None,
    type=click.Path(dir_okay=False),
)
def resume(project_dir: str, verbose: bool, config_file: Optional[str]) -> None:
    """
    Resume a failed or interrupted video generation.

    \b
    Example:
      python -m app resume output/peaceful_rainy_mountains_20261006_143012
    """
    setup_logging(verbose=verbose)
    cfg_path = Path(config_file) if config_file else None
    config = get_config(cfg_path)

    from app.pipeline.orchestrator import GenerationOrchestrator

    try:
        orchestrator = GenerationOrchestrator(config=config)
        result = orchestrator.resume(Path(project_dir))
        if result:
            console.print(f"\n[bold cyan]Resumed project:[/] {result}\n")
    except (FileNotFoundError, RuntimeError) as exc:
        console.print(f"\n[bold red]Error:[/] {exc}\n")
        sys.exit(1)


# ── check command ─────────────────────────────────────────────────────────────

@cli.command()
@click.option(
    "--config", "config_file",
    default=None,
    type=click.Path(dir_okay=False),
)
def check(config_file: Optional[str]) -> None:
    """
    Check all dependencies (LM Studio, ComfyUI, FFmpeg).

    \b
    Example:
      python -m app check
    """
    setup_logging(verbose=False)
    cfg_path = Path(config_file) if config_file else None
    config = get_config(cfg_path)

    from app.providers.comfyui import ComfyUIProvider
    from app.providers.ffmpeg import FFmpegRenderer
    from app.providers.lmstudio import LMStudioProvider

    checks = [
        ("FFmpeg", FFmpegRenderer(settings=config.ffmpeg).health_check),
        ("LM Studio", LMStudioProvider(settings=config.llm).health_check),
        ("ComfyUI", ComfyUIProvider(settings=config.comfyui).health_check),
    ]

    console.print("\n[bold]Dependency Check[/]\n")
    all_ok = True
    for name, fn in checks:
        try:
            ok = fn()
        except Exception:
            ok = False
        status = "[green]OK[/]" if ok else "[red]UNAVAILABLE[/]"
        console.print(f"  {name:20s} {status}")
        if not ok:
            all_ok = False

    console.print()
    if all_ok:
        console.print("[bold green]All dependencies ready.[/]")
    else:
        console.print("[bold red]Some dependencies are unavailable.[/]")
        sys.exit(1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_prompt(prompt: Optional[str], input_file: Optional[str]) -> Optional[str]:
    """Return the final prompt string from CLI flag or file."""
    if prompt:
        return prompt.strip()

    if input_file:
        path = Path(input_file)
        suffix = path.suffix.lower()

        if suffix == ".txt":
            return path.read_text(encoding="utf-8").strip()

        if suffix in (".yaml", ".yml"):
            import yaml
            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict):
                return data.get("prompt") or data.get("description") or str(data)
            return str(data)

        if suffix == ".json":
            import json
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data.get("prompt") or data.get("description") or str(data)
            return str(data)

        # Fallback: read as plain text
        return path.read_text(encoding="utf-8").strip()

    return None
