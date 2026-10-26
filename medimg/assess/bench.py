"""Benchmark: time the model load, then one short generation per size."""
from __future__ import annotations

import time
from datetime import datetime

from medimg.assess.estimate import REF_PIXELS, fit

BENCH_PROMPT = "a simple anatomical line drawing of a human hand, white background"


def benchmark(engine, *, sizes=((512, 512, 4), (1024, 1024, 2))) -> dict:
    """Run the engine at each (width, height, steps). Never called by tests with a real engine.

    Overhead (load/encode/decode) cannot be separated from step time with two short runs, so it is
    modelled as the measured load time scaled by sqrt(pixels / 512x512), capped at half the run."""
    t0 = time.perf_counter()
    engine.load()
    load_s = time.perf_counter() - t0
    points = []
    for width, height, steps in sizes:
        t1 = time.perf_counter()
        engine.generate(BENCH_PROMPT, 0, steps, width, height, lambda *_: None, lambda: False)
        total_s = time.perf_counter() - t1
        overhead = min(load_s * ((width * height) / REF_PIXELS) ** 0.5, total_s * 0.5)
        per_step = max((total_s - overhead) / steps, 1e-6)
        points.append({"width": width, "height": height, "steps": steps,
                       "total_s": round(total_s, 3), "per_step_s": round(per_step, 6),
                       "overhead_s": round(overhead, 3)})
    return {"measured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "load_s": round(load_s, 3), "points": points, "fit": fit(points)}
