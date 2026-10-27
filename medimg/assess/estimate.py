"""Time estimates (D24): per-step seconds follow a power law in pixel count; fixed overhead on top."""
from __future__ import annotations

import math
from collections.abc import Sequence
from statistics import mean

from medimg.config import DEFAULT_STEPS, SIZE_PRESETS

REF_PIXELS = 512 * 512
ALPHA_MIN, ALPHA_MAX = 0.5, 2.0
ROLLING = 10


def fit(points: list[dict]) -> dict:
    """Fit {"ref_pixels", "ref_per_step_s", "alpha", "overhead_s"} from benchmark points.
    Each point needs width, height, per_step_s and overhead_s. One point -> alpha 1.0."""
    pts = [p for p in points if p.get("per_step_s", 0) > 0]
    if not pts:
        raise ValueError("fit needs at least one point with per_step_s > 0")
    pts = sorted(pts, key=lambda p: p["width"] * p["height"])
    lo, hi = pts[0], pts[-1]
    px_lo, px_hi = lo["width"] * lo["height"], hi["width"] * hi["height"]
    if px_hi > px_lo:
        alpha = math.log(hi["per_step_s"] / lo["per_step_s"]) / math.log(px_hi / px_lo)
    else:
        alpha = 1.0
    alpha = min(ALPHA_MAX, max(ALPHA_MIN, alpha))
    ref_per_step = lo["per_step_s"] * (REF_PIXELS / px_lo) ** alpha
    return {"ref_pixels": REF_PIXELS, "ref_per_step_s": round(ref_per_step, 6),
            "alpha": round(alpha, 4), "overhead_s": round(float(lo.get("overhead_s", 0.0)), 3)}


def _per_step(f: dict, width: int, height: int) -> float:
    return f["ref_per_step_s"] * ((width * height) / f["ref_pixels"]) ** f["alpha"]


def _curve_seconds(f: dict, width: int, height: int, steps: int) -> float:
    return f["overhead_s"] + steps * _per_step(f, width, height)


def _refit_from_actuals(actuals: list[dict], overhead_s: float) -> dict | None:
    """Refit the curve from actuals when >= 2 distinct sizes exist; else None."""
    groups: dict[tuple[int, int], list[float]] = {}
    for a in actuals:
        ps = (a["time_s"] - overhead_s) / max(1, a["steps"])
        if ps > 0:
            groups.setdefault((a["width"], a["height"]), []).append(ps)
    if len(groups) < 2:
        return None
    pts = [{"width": w, "height": h, "per_step_s": mean(v), "overhead_s": overhead_s}
           for (w, h), v in groups.items()]
    return fit(pts)


def has_basis(profile: dict) -> bool:
    bench_fit = ((profile.get("benchmark") or {}).get("fit"))
    return bool(bench_fit) or bool(profile.get("actuals"))


def estimate_seconds(profile: dict, width: int, height: int, steps: int) -> float:
    """Seconds for one image. Actuals win (D24): the mean of the last 10 at this exact size, adjusted
    for step count; otherwise the curve (refitted from actuals when they cover >= 2 sizes)."""
    actuals = list(profile.get("actuals") or [])
    bench_fit = (profile.get("benchmark") or {}).get("fit")
    overhead = bench_fit["overhead_s"] if bench_fit else 0.0
    curve = _refit_from_actuals(actuals, overhead) or bench_fit
    if curve is None and actuals:                       # actuals but no benchmark, single size
        curve = {"ref_pixels": REF_PIXELS, "alpha": 1.0, "overhead_s": 0.0}
        a0 = actuals[-1]
        curve["ref_per_step_s"] = max(a0["time_s"], 0.001) / max(1, a0["steps"]) * (
            REF_PIXELS / (a0["width"] * a0["height"]))
    if curve is None:
        raise ValueError("no benchmark or actuals in profile; run assess with the benchmark")
    same = [a for a in actuals if a["width"] == width and a["height"] == height][-ROLLING:]
    if same:
        step_s = _per_step(curve, width, height)
        return float(mean(a["time_s"] + (steps - a["steps"]) * step_s for a in same))
    return float(_curve_seconds(curve, width, height, steps))


def estimates_table(profile: dict, steps: int = DEFAULT_STEPS,
                    presets: Sequence[tuple[str, int, int]] = SIZE_PRESETS) -> list[dict]:
    """One row per size preset; empty when the profile has nothing to estimate from."""
    if not has_basis(profile):
        return []
    rows = []
    for label, w, h in presets:
        s = estimate_seconds(profile, w, h, steps)
        rows.append({"label": label, "width": w, "height": h, "seconds": s,
                     "for_10": s * 10, "for_25": s * 25, "for_50": s * 50})
    return rows
