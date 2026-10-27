"""device_profile.json: schema v1 build/load/save and rolling actuals."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from medimg import config
from medimg.config import PROFILE_PATH, VERSION
from medimg.osutil import replace_retry

SCHEMA_VERSION = 1
MAX_ACTUALS = 50
_ORIGINAL_PATH = PROFILE_PATH
TOP_KEYS = ("schema_version", "created_at", "app_version", "machine", "backend",
            "benchmark", "actuals", "notes")


def _default_path() -> Path:
    """Late-bound PROFILE_PATH so tests can monkeypatch it here, on medimg.assess or on config."""
    for mod in (sys.modules.get(__name__), sys.modules.get("medimg.assess"), config):
        p = getattr(mod, "PROFILE_PATH", None)
        if p is not None and Path(p) != _ORIGINAL_PATH:
            return Path(p)
    return _ORIGINAL_PATH


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def build_profile(machine, decision, benchmark: dict | None = None, *, actuals: list | None = None,
                  notes: list | None = None, engine_version: str | None = None,
                  device: str | None = None, sdcpp: dict | None = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": now_iso(),
        "app_version": VERSION,
        "machine": asdict(machine),
        "backend": {"name": decision.backend, "supported": decision.supported,
                    "reason": decision.reason, "fix": decision.fix,
                    "model_id": decision.model_id, "offload_mode": decision.offload_mode,
                    "unload_after_job": decision.unload_after_job,
                    "engine_version": engine_version, "device": device, "sdcpp": sdcpp,
                    "reason_code": getattr(decision, "reason_code", None)},
        "benchmark": benchmark,
        "actuals": list(actuals or []),
        "notes": list(notes or []),
    }


def profile_matches(profile: dict | None, engine_name: str) -> bool:
    """True when the profile belongs to this engine (fake engine and nameless profiles always match)."""
    if profile is None:
        return False
    if engine_name == "fake":
        return True
    name = (profile.get("backend") or {}).get("name")
    return name is None or name == engine_name


def record_actual(profile: dict, width: int, height: int, steps: int, time_s: float) -> dict:
    """Append a real timing (keeps the last 50). Mutates and returns the profile."""
    actuals = list(profile.get("actuals") or [])
    actuals.append({"at": now_iso(), "width": int(width), "height": int(height),
                    "steps": int(steps), "time_s": round(float(time_s), 3)})
    profile["actuals"] = actuals[-MAX_ACTUALS:]
    return profile


def load_profile(path=None) -> dict | None:
    p = Path(path) if path is not None else _default_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema_version") == SCHEMA_VERSION else None


def save_profile(profile: dict, path=None) -> None:
    """Atomic write: temp file in the same folder, then os.replace."""
    p = Path(path) if path is not None else _default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)
            f.write("\n")
        replace_retry(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
