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
           "render_report", "build_profile", "run", "PROFILE_PATH"]


def _engine_version(engine) -> str | None:
    import importlib.metadata as md
    try:
        return f"{engine.name} {md.version(engine.name)}"
    except Exception:
        return None


def run(args) -> int:
    """CLI entry for `python -m medimg assess`."""
    output_root = getattr(args, "output_root", None) or config.load_settings().output_root
    machine = detect(disk_path=output_root)
    decision = decide(machine)
    previous = load_profile()
    keep = bool(previous and (previous.get("machine") or {}).get("cpu") == machine.cpu
                and (previous.get("backend") or {}).get("name") == decision.backend)
    bench, notes, engine_version = (previous or {}).get("benchmark") if keep else None, [], None
    if decision.supported and not getattr(args, "no_benchmark", False):
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
                            notes=notes, engine_version=engine_version)
    save_profile(profile)
    print(json.dumps(profile, indent=2) if getattr(args, "json", False) else render_report(profile))
    return 0 if decision.supported else 1
