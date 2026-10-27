"""Device assessment: detect, decide, benchmark, estimate, profile, report."""
from __future__ import annotations

import json
import sys

from medimg import config
from medimg.assess.bench import benchmark
from medimg.assess.decide import Decision, decide
from medimg.assess.detect import Machine, detect
from medimg.assess.estimate import estimate_seconds, estimates_table, fit
from medimg.assess.parse import (parse_nvidia_smi, parse_sysctl, parse_system_profiler,
                                 parse_wmic_or_powershell)
from medimg.assess.profile import build_profile, load_profile, record_actual, save_profile
from medimg.assess.report import render_report
from medimg.config import PROFILE_PATH

__all__ = ["Machine", "Decision", "detect", "parse_nvidia_smi", "parse_system_profiler",
           "parse_sysctl", "parse_wmic_or_powershell", "decide", "benchmark", "fit",
           "estimate_seconds", "record_actual", "load_profile", "save_profile", "estimates_table",
           "render_report", "build_profile", "run", "PROFILE_PATH", "SDCPP_BENCH_SIZES"]


SDCPP_BENCH_SIZES = ((512, 512, 4), (768, 768, 2))


def _engine_version(engine, backend: str | None = None) -> str | None:
    if backend == "sdcpp":
        return f"sdcpp {config.SDCPP_RELEASE_TAG}"
    import importlib.metadata as md
    try:
        return f"{engine.name} {md.version(engine.name)}"
    except Exception:
        return None


def _device_listed(candidate: str, devices) -> bool:
    c = candidate.lower()
    wanted = {c, "mtl"} if c == "metal" else {c}       # sd-cli lists Metal as MTL0
    for name, *_ in devices:
        n = str(name).lower()
        if any(n.startswith(w) or w.startswith(n) for w in wanted):
            return True
    return False


def _run_sdcpp(machine, decision, settings, no_benchmark, previous, keep_ok):
    """Pick the device, benchmark it (CPU fallback). Returns (bench, notes, sdcpp_dict, device)."""
    from medimg.engines import make_engine
    from medimg.sdcpp import install
    notes: list[str] = []
    tier = decision.tier
    build = install.chosen_build(machine.os_name, machine.arch)
    dev = settings.sdcpp_device or decision.device or "cpu"
    sd = {"release": config.SDCPP_RELEASE_TAG, "build": build, "tier": tier,
          "vulkan_tried": False, "vulkan_error": None}
    if no_benchmark:
        return None, notes, sd, dev

    def mk(device):
        profile_like = {"backend": {"name": "sdcpp", "device": device,
                                    "sdcpp": {"build": build, "tier": tier}},
                        "machine": {"ram_total_gb": machine.ram_total_gb}}
        return make_engine("sdcpp", profile_like)

    def bench_on(device):
        engine = mk(device)
        try:
            result = benchmark(engine, sizes=SDCPP_BENCH_SIZES)
            if getattr(engine, "device", device) != device:
                # The engine silently retried on the CPU; the timings are polluted, so treat as a failure.
                notes_ = getattr(engine, "notes", None) or []
                raise RuntimeError(notes_[-1] if notes_ else f"engine fell back from {device}")
            return result
        finally:
            engine.unload()

    if dev != "cpu":
        try:
            paths = install.resolve_paths(build, tier)
            devices = install.list_devices(paths.sd_cli, paths.cwd)
        except Exception as e:
            notes.append(f"Could not list graphics devices ({e}); using the processor")
            dev = "cpu"
        else:
            if not _device_listed(dev, devices):
                notes.append(f"Graphics device {dev} is not available in sd.cpp; using the processor")
                dev = "cpu"
    bench = None
    if dev != "cpu":
        sd["vulkan_tried"] = True
        try:
            bench = bench_on(dev)
        except Exception as e:
            cause = str(e) or type(e).__name__
            notes.append(f"Graphics chip benchmark failed on {dev}: {cause}; using the processor")
            sd["vulkan_error"] = cause
            dev = "cpu"
    if bench is None:
        bench = bench_on("cpu")
    return bench, notes, sd, dev


def run(args) -> int:
    """CLI entry for `python -m medimg assess`."""
    settings = config.load_settings()
    output_root = getattr(args, "output_root", None) or settings.output_root
    engine_arg = getattr(args, "engine", None)
    if engine_arg is None:
        engine_arg = settings.engine
    engine_arg = None if engine_arg in (None, "auto") else engine_arg
    machine = detect(disk_path=output_root)
    decision = decide(machine, engine=engine_arg)
    previous = load_profile()
    no_bench = getattr(args, "no_benchmark", False)
    prev_b = (previous or {}).get("backend") or {}
    keep = bool(previous and (previous.get("machine") or {}).get("cpu") == machine.cpu
                and prev_b.get("name") == decision.backend)
    if keep and decision.backend == "sdcpp":
        keep = (prev_b.get("device") == (settings.sdcpp_device or decision.device)
                and (prev_b.get("sdcpp") or {}).get("tier") == decision.tier)
    bench, notes, engine_version = (previous or {}).get("benchmark") if keep else None, [], None
    device = decision.device
    sdcpp = None
    if decision.supported and decision.backend == "sdcpp":
        engine_version = _engine_version(None, "sdcpp")
        try:
            b, notes, sdcpp, device = _run_sdcpp(machine, decision, settings, no_bench, previous, keep)
            if b is not None:
                bench = b
        except Exception as e:                      # benchmark must never lose the detection result
            notes.append(f"Benchmark failed: {e}")
            from medimg.sdcpp import install
            sdcpp = {"release": config.SDCPP_RELEASE_TAG,
                     "build": install.chosen_build(machine.os_name, machine.arch),
                     "tier": decision.tier, "vulkan_tried": False, "vulkan_error": None}
            device = settings.sdcpp_device or decision.device
    elif decision.supported and not no_bench:
        try:
            from medimg.engines import make_engine
            engine = make_engine(decision.backend, {"backend": {"offload_mode": decision.offload_mode}})
            engine_version = _engine_version(engine)
            try:
                bench = benchmark(engine)
            finally:
                engine.unload()
        except Exception as e:                      # benchmark must never lose the detection result
            notes.append(f"Benchmark failed: {e}")
    profile = build_profile(machine, decision, bench, actuals=(previous or {}).get("actuals") if keep else [],
                            notes=notes, engine_version=engine_version, device=device, sdcpp=sdcpp)
    save_profile(profile)
    print(json.dumps(profile, indent=2) if getattr(args, "json", False) else render_report(profile))
    return 0 if decision.supported else 1
