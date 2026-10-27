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
from medimg.assess.profile import (build_profile, load_profile, profile_matches, record_actual,
                                   save_profile)
from medimg.assess.report import render_report
from medimg.config import PROFILE_PATH

__all__ = ["Machine", "Decision", "detect", "parse_nvidia_smi", "parse_system_profiler",
           "parse_sysctl", "parse_wmic_or_powershell", "decide", "benchmark", "fit",
           "estimate_seconds", "record_actual", "load_profile", "save_profile", "estimates_table",
           "render_report", "build_profile", "profile_matches", "run", "PROFILE_PATH", "SDCPP_BENCH_SIZES"]


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


def _sdcpp_prior(previous: dict | None, machine, decision, build: str | None) -> dict | None:
    """The previous profile when it describes this same sd.cpp setup (cpu, tier, build, release)."""
    if not previous:
        return None
    b = previous.get("backend") or {}
    sd = b.get("sdcpp") or {}
    if (b.get("name") == "sdcpp"
            and (previous.get("machine") or {}).get("cpu") == machine.cpu
            and sd.get("tier") == decision.tier and sd.get("build") == build
            and sd.get("release") == config.SDCPP_RELEASE_TAG):
        return previous
    return None


def _prior_sdcpp(prior: dict | None) -> dict:
    return ((prior or {}).get("backend") or {}).get("sdcpp") or {}


def _prior_device(prior: dict | None):
    return ((prior or {}).get("backend") or {}).get("device")


def _run_sdcpp(machine, decision, settings, *, no_benchmark: bool, prior: dict | None,
               retry_gpu: bool = False):
    """Pick the device, benchmark it (CPU fallback). Returns (bench, notes, sdcpp_dict, device).
    A benchmark failure never raises."""
    from medimg.engines import make_engine
    from medimg.sdcpp import install
    notes: list[str] = []
    tier = decision.tier
    build = install.chosen_build(machine.os_name, machine.arch)
    wanted = settings.sdcpp_device or decision.device or "cpu"
    psd = _prior_sdcpp(prior)
    failed = [d for d in (psd.get("failed_devices") or [])]
    sd = {"release": config.SDCPP_RELEASE_TAG, "build": build, "tier": tier,
          "vulkan_tried": bool(psd.get("vulkan_tried", False)), "vulkan_error": psd.get("vulkan_error"),
          "device_proven": False, "failed_devices": failed}
    if wanted != "cpu" and wanted in failed:
        if retry_gpu or settings.sdcpp_device:
            failed.remove(wanted)
        else:
            notes.append(f"The graphics chip ({wanted}) failed on this computer before; using the processor. "
                         "Run assess --retry-gpu to try it again.")
            wanted = "cpu"
    if no_benchmark:
        if prior and _prior_device(prior) == wanted:
            sd["device_proven"] = bool(psd.get("device_proven", False))
        return None, notes, sd, wanted

    def mk(device):
        profile_like = {"backend": {"name": "sdcpp", "device": device,
                                    "sdcpp": {"build": build, "tier": tier}},
                        "machine": {"ram_total_gb": machine.ram_total_gb}}
        return make_engine("sdcpp", profile_like, tier=tier)

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

    dev = wanted
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
            sd["device_proven"] = True
            if dev in failed:
                failed.remove(dev)
        except Exception as e:
            cause = str(e) or type(e).__name__
            tail = "" if cause.rstrip().endswith(("using the processor", "using the processor.")) \
                else "; using the processor"
            notes.append(f"Graphics chip benchmark failed on {dev}: {cause}{tail}")
            sd["vulkan_error"] = cause
            if dev not in failed:
                failed.append(dev)
            dev = "cpu"
    if bench is None:
        try:
            bench = bench_on("cpu")
            sd["device_proven"] = True
        except Exception as e:
            notes.append(f"Benchmark failed on the processor: {str(e) or type(e).__name__}")
            bench = None
            sd["device_proven"] = False
    return bench, notes, sd, dev


def run(args) -> int:
    """CLI entry for `python -m medimg assess`."""
    settings = config.load_settings()
    output_root = getattr(args, "output_root", None) or settings.output_root
    engine_arg = getattr(args, "engine", None)
    if engine_arg is None:
        engine_arg = settings.engine
    engine_arg = None if engine_arg in (None, "auto") else engine_arg
    tier = getattr(args, "tier", None)
    tier = None if tier in (None, "auto") else tier
    retry_gpu = bool(getattr(args, "retry_gpu", False))
    machine = detect(disk_path=output_root)
    decision = decide(machine, engine=engine_arg, tier=tier)
    previous = load_profile()
    no_bench = getattr(args, "no_benchmark", False)
    notes: list[str] = []
    engine_version = None
    device = decision.device
    sdcpp = None
    if decision.supported and decision.backend == "sdcpp":
        from medimg.sdcpp import install
        engine_version = _engine_version(None, "sdcpp")
        prior = None
        bench = None
        actuals: list = []
        try:
            build = install.chosen_build(machine.os_name, machine.arch)
            prior = _sdcpp_prior(previous, machine, decision, build)
            b, notes, sdcpp, device = _run_sdcpp(machine, decision, settings, no_benchmark=no_bench,
                                                 prior=prior, retry_gpu=retry_gpu)
            same = prior is not None and _prior_device(prior) == device
            bench = b if b is not None else (prior.get("benchmark") if same else None)
            actuals = (prior.get("actuals") or []) if same else []
        except Exception as e:                      # unexpected only; benchmark failures are handled inside
            notes.append(f"Benchmark failed: {e}")
            psd = _prior_sdcpp(prior)
            try:
                build = install.chosen_build(machine.os_name, machine.arch)
            except Exception:
                build = None
            sdcpp = {"release": config.SDCPP_RELEASE_TAG, "build": build, "tier": decision.tier,
                     "vulkan_tried": bool(psd.get("vulkan_tried", False)),
                     "vulkan_error": psd.get("vulkan_error"), "device_proven": False,
                     "failed_devices": list(psd.get("failed_devices") or [])}
            device = "cpu"
            bench, actuals = None, []
    else:
        prev_b = (previous or {}).get("backend") or {}
        keep = bool(previous and (previous.get("machine") or {}).get("cpu") == machine.cpu
                    and prev_b.get("name") == decision.backend)
        bench = (previous or {}).get("benchmark") if keep else None
        actuals = (previous or {}).get("actuals") if keep else []
        if decision.supported and not no_bench:
            try:
                from medimg.engines import make_engine
                engine = make_engine(decision.backend, {"backend": {"offload_mode": decision.offload_mode}})
                engine_version = _engine_version(engine)
                try:
                    bench = benchmark(engine)
                finally:
                    engine.unload()
            except Exception as e:                  # benchmark must never lose the detection result
                notes.append(f"Benchmark failed: {e}")
    profile = build_profile(machine, decision, bench, actuals=actuals,
                            notes=notes, engine_version=engine_version, device=device, sdcpp=sdcpp)
    save_profile(profile)
    print(json.dumps(profile, indent=2) if getattr(args, "json", False) else render_report(profile))
    return 0 if decision.supported else 1
