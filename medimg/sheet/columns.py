"""Pinned column names, statuses and header helpers for the sheet contract."""
from __future__ import annotations

REQUIRED = ("subject", "unit", "lecture", "image prompt", "image name", "status")
OPTIONAL = ("size", "seed")
SYSTEM = ("Steps", "Seed Used", "Generated At", "Machine", "Model",
          "Generation Time (s)", "Output Path", "Error")
STATUSES = ("pending", "done", "failed", "blocked", "invalid")

DISPLAY = {
    "subject": "Subject", "unit": "Unit", "lecture": "Lecture",
    "image prompt": "Image Prompt", "image name": "Image Name",
    "status": "Status", "size": "Size", "seed": "Seed",
}


def norm_header(value: object) -> str:
    """Case-insensitive, whitespace-collapsed header key."""
    if value is None:
        return ""
    return " ".join(str(value).split()).casefold()


_SYSTEM_BY_NORM = {norm_header(h): h for h in SYSTEM}


def system_name(norm: str) -> str | None:
    """Canonical SYSTEM header for a normalised header, or None."""
    return _SYSTEM_BY_NORM.get(norm)
