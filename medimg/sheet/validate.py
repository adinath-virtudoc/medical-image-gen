"""Row validation (PLAN 4.5 rule order) and report building."""
from __future__ import annotations

import dataclasses
from pathlib import Path

from medimg.config import MAX_PIXELS, SEED_MAX, SIDE_MAX, SIDE_MIN, SIZE_MULTIPLE

from . import _compat
from .reader import Problem, Row, SheetReport, SheetError, read_rows  # noqa: F401


def _bad_size(size: tuple[int, int]) -> bool:
    w, h = (v // SIZE_MULTIPLE * SIZE_MULTIPLE for v in size)   # D18: round down first
    return not (SIDE_MIN <= w <= SIDE_MAX and SIDE_MIN <= h <= SIDE_MAX and w * h <= MAX_PIXELS)


def validate(rows: list[Row], *, output_root: Path, default_size: tuple[int, int],
             retry_failed: bool) -> list[Row]:
    out: list[Row] = []
    candidates: list[int] = []          # indexes into out that reached the collision stage
    for row in rows:
        r = dataclasses.replace(row, system=dict(row.system))
        out.append(r)
        if r.status == "done":
            continue
        if r.status == "failed" and not retry_failed:
            continue
        r.status, r.error = "pending", ""

        def fail(status: str, msg: str) -> None:
            r.status, r.error = status, msg

        missing = next((label for label, v in (
            ("Subject", r.subject), ("Unit", r.unit), ("Lecture", r.lecture),
            ("Image Prompt", r.prompt), ("Image Name", r.image_name)) if not v), None)
        if missing:
            fail("invalid", f"Missing {missing}. Fix: fill the cell.")
            r.rel_path = None
            continue
        if row.parse_error:
            fail("invalid", row.parse_error)
            continue
        if r.seed is not None and not 0 <= r.seed <= SEED_MAX:
            fail("invalid", f"Seed must be 0-{SEED_MAX}. Fix: change or clear the Seed cell.")
            continue
        if r.size is not None and _bad_size(r.size):
            fail("invalid", f"Size {r.size[0]}x{r.size[1]} is out of range: each side "
                 f"{SIDE_MIN}-{SIDE_MAX}, at most {MAX_PIXELS} pixels. Size must look like 768x1344")
            continue
        if r.size is None:
            r.size = default_size
        if r.rel_path is None:
            r.rel_path = _compat.rel_path(r.subject, r.unit, r.lecture, r.image_name)
        if _compat.path_too_long(output_root, r.rel_path):
            fail("invalid", "Output path is over 240 characters. Fix: shorten Subject, Unit, "
                 "Lecture or Image Name.")
            continue
        reason = _compat.check_prompt(r.prompt)
        if reason:
            fail("blocked", reason)
            continue
        candidates.append(len(out) - 1)

    # Collisions: case-insensitive; against other candidates and against untouched rows.
    groups: dict[str, list[int]] = {}
    for i, r in enumerate(out):
        if r.rel_path and (i in candidates or r.status in ("done", "failed")):
            groups.setdefault(r.rel_path.casefold(), []).append(i)
    for members in groups.values():
        if len(members) < 2:
            continue
        for i in members:
            if i in candidates:
                other = next(out[j].idx for j in members if j != i)
                out[i].status = "invalid"
                out[i].error = f"Same output path as row {other}. Fix: change Image Name."
                candidates.remove(i)

    for i in candidates:
        r = out[i]
        if (Path(output_root) / r.rel_path).is_file():
            r.status, r.error = "done", ""
            r.system["Output Path"] = r.rel_path
    return out


def build_report(path: Path, original_name: str, **validate_kwargs) -> SheetReport:
    title, rows = read_rows(path)
    rows = validate(rows, **validate_kwargs)
    counts = {k: 0 for k in ("total", "done", "pending", "blocked", "failed", "invalid")}
    counts["total"] = len(rows)
    problems: list[Problem] = []
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
        if r.status in ("blocked", "invalid"):
            fix = ("Rephrase the prompt to describe an adult." if r.status == "blocked"
                   else "Correct the row and upload the sheet again.")
            problems.append(Problem(r.idx, r.status, r.error, fix))
    filters = {k: sorted({getattr(r, a) for r in rows if getattr(r, a)})
               for k, a in (("subjects", "subject"), ("units", "unit"), ("lectures", "lecture"))}
    return SheetReport(sheet_id=Path(path).stem, original_name=original_name,
                       working_path=Path(path), worksheet=title, rows=rows, counts=counts,
                       problems=problems, filters=filters)
