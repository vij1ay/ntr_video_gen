"""
Output directory management.

Every generated video gets one self-contained output directory.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional


def _sanitize_title(title: str, max_len: int = 60) -> str:
    """
    Convert an arbitrary title string into a filesystem-safe slug.

    - Normalise unicode to ASCII where possible
    - Convert spaces and separators to underscores
    - Remove Windows-invalid characters
    - Collapse consecutive underscores
    - Lowercase
    - Truncate to max_len
    """
    # Normalise unicode (decompose accents)
    title = unicodedata.normalize("NFKD", title)
    title = title.encode("ascii", errors="ignore").decode("ascii")
    # lowercase
    title = title.lower()
    # replace non-word chars with underscore
    title = re.sub(r"[^\w\s-]", "", title)
    title = re.sub(r"[\s\-]+", "_", title)
    title = re.sub(r"_+", "_", title)
    title = title.strip("_")
    return title[:max_len]


def make_output_dir(
    title: str,
    base_dir: str | Path = "output",
    timestamp: Optional[datetime] = None,
) -> Path:
    """
    Create and return the project output directory.

    Structure:
        <base_dir>/<slug>_<YYYYMMDD_HHMMSS>/

    Args:
        title: Video title used to form the directory name slug.
        base_dir: Root output directory.
        timestamp: Override timestamp (defaults to now).

    Returns:
        Path to the newly created project output directory.
    """
    if timestamp is None:
        timestamp = datetime.now()

    slug = _sanitize_title(title)
    ts = timestamp.strftime("%Y%m%d_%H%M%S")
    folder_name = f"{slug}_{ts}"

    project_dir = Path(base_dir) / folder_name
    _create_structure(project_dir)
    return project_dir


def _create_structure(project_dir: Path) -> None:
    """Create the full output directory tree."""
    subdirs = [
        "youtube",
        "project",
        "scenes",
        "audio",
        "logs",
        "thumbnails",
    ]
    project_dir.mkdir(parents=True, exist_ok=True)
    for sub in subdirs:
        (project_dir / sub).mkdir(exist_ok=True)


def get_scenes_dir(project_dir: Path, scene_id: str) -> Path:
    """Return path to a specific scene's directory, creating it if necessary."""
    scene_dir = project_dir / "scenes" / scene_id
    scene_dir.mkdir(parents=True, exist_ok=True)
    return scene_dir
