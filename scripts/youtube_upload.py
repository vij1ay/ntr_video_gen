"""
YouTube Upload Script — Phase 8 stub.

Accepts a completed project output directory and uploads to YouTube
using the YouTube Data API v3.

IMPORTANT: This script is intentionally separate from the video generator.
It reads the output folder produced by `python -m app generate`.

Usage:
    python scripts/youtube_upload.py output/peaceful_rainy_mountains_20261006_143012/

Setup (future):
    pip install google-api-python-client google-auth-oauthlib
    Create OAuth2 credentials in Google Cloud Console.
    Place client_secrets.json in the project root or pass --credentials.

Current status: STUB — prints metadata, does not upload.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load_metadata(project_dir: Path) -> dict:
    """Load YouTube metadata from the project output folder."""
    meta_path = project_dir / "youtube" / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(
            f"metadata.json not found in {project_dir / 'youtube'}\n"
            "Run the generator first to create the project package."
        )
    with open(meta_path, encoding="utf-8") as fh:
        return json.load(fh)


def validate_project(project_dir: Path, meta: dict) -> list[str]:
    """Return a list of validation errors for the project directory."""
    errors: list[str] = []

    video_file = project_dir / meta.get("video", "video.mp4")
    if not video_file.exists():
        errors.append(f"Video file not found: {video_file}")

    thumbnail = project_dir / meta.get("thumbnail", "thumbnail.jpg")
    if not thumbnail.exists():
        errors.append(f"Thumbnail not found: {thumbnail}")

    if not meta.get("title"):
        errors.append("metadata.json has no title.")

    if not meta.get("description"):
        errors.append("metadata.json has no description.")

    return errors


def upload_to_youtube(project_dir: Path, meta: dict, credentials_path: Path) -> None:
    """
    Upload the video to YouTube.

    TODO: Implement using google-api-python-client.
    See: https://developers.google.com/youtube/v3/guides/uploading_a_video
    """
    raise NotImplementedError(
        "YouTube upload is not yet implemented.\n"
        "Install google-api-python-client and implement OAuth2 flow."
    )


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/youtube_upload.py <project_dir>")
        print("Example: python scripts/youtube_upload.py output/peaceful_rainy_mountains_20261006_143012")
        sys.exit(1)

    project_dir = Path(sys.argv[1])
    if not project_dir.exists():
        print(f"Error: Project directory not found: {project_dir}")
        sys.exit(1)

    print(f"\nYouTube Upload — Project: {project_dir.name}")
    print("=" * 60)

    # Load metadata
    try:
        meta = load_metadata(project_dir)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    # Validate
    errors = validate_project(project_dir, meta)
    if errors:
        print("\nValidation errors:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)

    # Print what would be uploaded
    video_path = project_dir / meta.get("video", "video.mp4")
    thumb_path = project_dir / meta.get("thumbnail", "thumbnail.jpg")

    print(f"\n  Title:       {meta['title']}")
    print(f"  Category:    {meta.get('category', 'Entertainment')}")
    print(f"  Language:    {meta.get('language', 'en')}")
    print(f"  Privacy:     {meta.get('privacy', 'private')}")
    print(f"  Tags:        {', '.join(meta.get('tags', [])[:5])} ...")
    print(f"  Video file:  {video_path} ({video_path.stat().st_size // 1024 // 1024} MB)")
    print(f"  Thumbnail:   {thumb_path}")
    print(f"\n  Description preview:")
    desc = meta.get("description", "")
    for line in desc.split("\n")[:5]:
        print(f"    {line}")

    print("\n[STUB] YouTube upload not yet implemented.")
    print("This script is ready to receive the upload implementation.")
    print("See the docstring in scripts/youtube_upload.py for next steps.")


if __name__ == "__main__":
    main()
