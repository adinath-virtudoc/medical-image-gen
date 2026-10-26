"""Job specs and pure validation logic. No I/O."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from medimg import config, rules
from medimg.errors import Blocked, Invalid


@dataclass
class RowJob:
    prompt: str
    seed: int | None
    steps: int
    width: int
    height: int
    subject: str
    unit: str
    lecture: str
    image_name: str
    sheet_row: int | None = None
    overwrite: bool = False


@dataclass
class JobSpec:
    kind: str                      # "batch" | "single" | "regenerate" | "benchmark"
    rows: list[RowJob] = field(default_factory=list)
    sheet_path: Path | None = None
    sheet_name: str | None = None


_SIZE_RE = re.compile(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*$")


def random_seed() -> int:
    return random.randint(0, config.SEED_MAX)


def parse_size(text: str) -> tuple[int, int]:
    m = _SIZE_RE.match(text or "")
    if not m:
        raise Invalid(f"Size {text!r} is not in the form WIDTHxHEIGHT.",
                      "Write the size like 768x1344.")
    return int(m.group(1)), int(m.group(2))


def normalise_size(width: int, height: int) -> tuple[int, int]:
    """Round each side down to a multiple of 16, then check the limits (D18)."""
    try:
        w, h = int(width), int(height)
    except (TypeError, ValueError):
        raise Invalid("Width and height must be whole numbers.", "Use a size like 1024x1024.")
    m = config.SIZE_MULTIPLE
    w, h = (w // m) * m, (h // m) * m
    if not (config.SIDE_MIN <= w <= config.SIDE_MAX and config.SIDE_MIN <= h <= config.SIDE_MAX):
        raise Invalid(
            f"Size {width}x{height} is outside {config.SIDE_MIN}-{config.SIDE_MAX} pixels per side.",
            f"Choose a width and height between {config.SIDE_MIN} and {config.SIDE_MAX}.")
    if w * h > config.MAX_PIXELS:
        raise Invalid(f"Size {w}x{h} has more than {config.MAX_PIXELS:,} pixels.",
                      "Pick a smaller size, for example 1024x1024 or 768x1344.")
    return w, h


def validate_row_job(j: RowJob) -> RowJob:
    """Return a validated copy: rules gate, size rounded, steps and seed checked, seed filled."""
    if not (j.prompt or "").strip():
        raise Invalid("The prompt is empty.", "Write a prompt that describes the image.")
    reason = rules.check_prompt(j.prompt)
    if reason:
        fix = rules.HINT if "does not state an adult" in reason else \
            "Rephrase the prompt so it describes an adult."
        raise Blocked(reason, fix)
    w, h = normalise_size(j.width, j.height)
    steps = j.steps
    if isinstance(steps, bool) or not isinstance(steps, int) or not (
            config.STEPS_MIN <= steps <= config.STEPS_MAX):
        raise Invalid(f"Steps {steps!r} is outside {config.STEPS_MIN}-{config.STEPS_MAX}.",
                      f"Use a number of steps from {config.STEPS_MIN} to {config.STEPS_MAX} (8-9 recommended).")
    seed = j.seed
    if seed is None:
        seed = random_seed()
    elif isinstance(seed, bool) or not isinstance(seed, int) or not (0 <= seed <= config.SEED_MAX):
        raise Invalid(f"Seed {seed!r} is outside 0-{config.SEED_MAX}.",
                      f"Use a whole number from 0 to {config.SEED_MAX}, or leave it blank.")
    return replace(j, width=w, height=h, steps=steps, seed=seed)
