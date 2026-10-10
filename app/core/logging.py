"""
Structured logging system.

All log output goes to both console (rich-formatted) and the project's
log file simultaneously.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler

_console = Console(stderr=True)

# Root logger for the application
APP_LOGGER_NAME = "ntr_video_gen"


def setup_logging(
    log_file: Optional[Path] = None,
    verbose: bool = False,
) -> logging.Logger:
    """
    Configure application-wide logging.

    Args:
        log_file: If provided, writes logs to this file in addition to console.
        verbose: If True, sets level to DEBUG; otherwise INFO.

    Returns:
        The root application logger.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(level)

    # Avoid duplicate handlers on re-configuration
    if logger.handlers:
        logger.handlers.clear()

    # ── Console handler via Rich ──────────────────────────────────────────────
    rich_handler = RichHandler(
        console=_console,
        rich_tracebacks=True,
        show_time=True,
        show_level=True,
        show_path=False,
        markup=True,
    )
    rich_handler.setLevel(level)
    logger.addHandler(rich_handler)

    # ── File handler ─────────────────────────────────────────────────────────
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # Always full detail in file
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Prevent propagation to root logger
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the application namespace."""
    return logging.getLogger(f"{APP_LOGGER_NAME}.{name}")
