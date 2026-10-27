"""`python -m medimg smoke`: load the engine and make one test image."""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

from medimg import config, rules
from medimg.errors import Blocked, Invalid, Unsupported

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


def _confirmed_device(device: str, tier) -> str:
    """No saved profile confirms the graphics device, so ask sd-cli; use the processor if unsure."""
    try:
        import platform
        from medimg.assess import _device_listed
        from medimg.sdcpp import install
        build = install.chosen_build(platform.system(), platform.machine())
        paths = install.resolve_paths(build, tier)
        if _device_listed(device, install.list_devices(paths.sd_cli, paths.cwd)):
            return device
    except Exception:
        pass
    return "cpu"


def _make_engine(fake: bool, engine: str | None = None, tier: str | None = None):
    from medimg.engines import make_engine
    if fake:
        return make_engine("fake", None, fake=True)
    from medimg.assess import decide, detect, load_profile
    if engine is None:
        engine = config.load_settings().engine
    engine = None if engine in (None, "auto") else engine
    profile = load_profile()
    backend_info = (profile or {}).get("backend") or {}
    if (profile and backend_info.get("supported") and backend_info.get("name")
            and (engine is None or backend_info["name"] == engine)
            and (tier is None or (backend_info.get("sdcpp") or {}).get("tier") == tier)):
        return make_engine(backend_info["name"], profile)
    decision = decide(detect(), engine=engine, tier=tier)
    if not decision.supported:
        raise Unsupported(decision.reason, decision.fix)
    device = decision.device
    if decision.backend == "sdcpp" and device and device != "cpu":
        device = _confirmed_device(device, decision.tier)
    return make_engine(decision.backend, {"backend": {
        "offload_mode": decision.offload_mode, "device": device,
        "sdcpp": {"tier": decision.tier} if decision.tier else {}}}, tier=decision.tier)


def run(args) -> int:
    width, height = parse_size(getattr(args, "size", None) or "512x512")
    steps = int(getattr(args, "steps", None) or 4)
    fake = bool(getattr(args, "fake_engine", False))
    root = Path(getattr(args, "output_root", None) or config.load_settings().output_root)

    tier = getattr(args, "tier", None)
    tier = None if tier in (None, "auto") else tier
    problem = rules.check_prompt(SMOKE_PROMPT)
    if problem is not None:
        raise Blocked(problem, rules.HINT)

    engine = _make_engine(fake, getattr(args, "engine", None), tier)
    if engine.name == "sdcpp":
        print(f"Loading the model (sdcpp on {getattr(engine, 'device', 'cpu')})...")
    else:
        print(f"Loading the model ({engine.name})...")
    t0 = time.perf_counter()
    engine.load()
    load_s = time.perf_counter() - t0
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
