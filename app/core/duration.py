"""
Duration parsing utilities.

Supports formats like: 15m, 5m, 90s, 27m, 3600s, 1h30m
"""
from __future__ import annotations

import re


def parse_duration(value: str) -> int:
    """
    Parse a human-readable duration string into seconds.

    Supported formats:
        - "15m"    → 900
        - "90s"    → 90
        - "1h"     → 3600
        - "1h30m"  → 5400
        - "900"    → 900  (plain integer, assumed seconds)

    Args:
        value: Duration string to parse.

    Returns:
        Duration in seconds as an integer.

    Raises:
        ValueError: If the format is not recognised.
    """
    value = value.strip().lower()

    # Plain integer → seconds
    if value.isdigit():
        return int(value)

    # Compound: 1h30m, 1h, 30m, 90s
    pattern = re.compile(
        r"^(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$"
    )
    match = pattern.match(value)
    if not match or not any(match.group(g) for g in ("hours", "minutes", "seconds")):
        raise ValueError(
            f"Cannot parse duration '{value}'. "
            "Use formats like: 15m, 90s, 1h, 1h30m"
        )

    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return hours * 3600 + minutes * 60 + seconds


def format_duration(seconds: int) -> str:
    """Format seconds into a human-readable string like '15m 0s'."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"
