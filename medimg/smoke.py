"""`python -m medimg smoke`: load the engine and make one test image."""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

from medimg import config
from medimg.errors import Invalid, Unsupported

SMOKE_PROMPT = ("Clinical medical illustration of an adult human hand, X-ray style, "
                "neutral grey background, sharp detail")
SMOKE_SEED = 12345


def parse_size(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", str(text))
    if not m:
        raise Invalid(f"Size '{text}' is not in WxH form.", "Use for example --size 512x512.")
    w, h = (int(v) // config.SIZE_MULTIPLE * config.SIZE_MULTIPLE for v in m.groups())
    if not (config.SIDE_MIN <= w <= config.SIDE_MAX and config.SIDE_MIN <= h <= config.SIDE_MAX):
        raise Invalid(f"Size {text} is outside {config.SIDE_MIN}-{config.SIDE_MAX} pixels per side.",
                      "Pick a smaller size, for example 512x512.")
    return w, h


def _make_engine(fake: bool):
    from medimg.engines import make_engine
    if fake:
        return make_engine("fake", None, fake=True)
    from medimg.assess import decide, detect, load_profile
    profile = load_profile()
    backend_info = (profile or {}).get("backend") or {}
    if profile and backend_info.get("supported") and backend_info.get("name"):
        return make_engine(backend_info["name"], profile)
    decision = decide(detect())
    if not decision.supported:
        raise Unsupported(decision.reason, decision.fix)
    return make_engine(decision.backend, {"backend": {"offload_mode": decision.offload_mode}})


def run(args) -> int:
    width, height = parse_size(getattr(args, "size", None) or "512x512")
    steps = int(getattr(args, "steps", None) or 4)
    fake = bool(getattr(args, "fake_engine", False))
    root = Path(getattr(args, "output_root", None) or config.load_settings().output_root)

    engine = _make_engine(fake)
    print(f"Loading the model ({engine.name})...")
    t0 = time.monotonic()
    engine.load()
    load_s = time.monotonic() - t0
    try:
        def progress(phase: str, done: int, total: int) -> None:
            if phase == "denoising" and total:
                print(f"  step {done}/{total}", flush=True)
        result = engine.generate(SMOKE_PROMPT, SMOKE_SEED, steps, width, height,
                                 progress, lambda: False)
    finally:
        engine.unload()

    out_dir = root / "_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    result.image.save(path, format="PNG")
    print(f"Test image done: load {load_s:.1f} s, generate {result.time_s:.1f} s "
          f"({width}x{height}, {steps} steps).")
    print(f"Saved to: {path}")
    return 0
