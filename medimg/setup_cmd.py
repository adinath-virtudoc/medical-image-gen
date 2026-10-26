"""`python -m medimg setup`: one-time, re-runnable setup (brief 5.1).

Every step is idempotent and prints "✔ already done" when it has nothing to do.
Setup is the only command that may use the network, so it never sets HF_HUB_OFFLINE.
"""
from __future__ import annotations

import importlib
import importlib.util
import shutil
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

from medimg import config, download
from medimg.errors import MedimgError

DONE = "✔ already done"


def _step(n: int, text: str) -> None:
    print(f"\n[{n}/6] {text}")


def _confirm(question: str) -> bool:
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return True
        return input(f"{question} [Y/n] ").strip().lower() in ("", "y", "yes")
    except EOFError:
        return True


def _extra_for(backend: str) -> tuple[str, str]:
    """(uv extra, python module that proves it is installed)."""
    return ("mac", "mflux") if backend == "mflux" else ("nvidia", "diffusers")


def _module_present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _uv_sync(extra: str) -> int:
    uv = shutil.which("uv")
    if not uv:
        return 127
    return subprocess.run([uv, "sync", "--extra", extra], cwd=str(config.REPO_ROOT)).returncode


def _next_command() -> str:
    if sys.platform == "win32":
        return "start.bat   (double-click it, or type start.bat in this folder)"
    if sys.platform == "darwin":
        return "./start.sh   (or double-click start.command)"
    return "./start.sh"


def _smoke_done(root: Path) -> bool:
    d = root / "_smoke"
    return d.is_dir() and any(d.glob("*.png"))


def _assess_done(backend: str | None, cpu: str) -> bool:
    from medimg.assess import load_profile
    p = load_profile()
    return bool(p and p.get("benchmark") and (p.get("backend") or {}).get("name") == backend
                and (p.get("machine") or {}).get("cpu") == cpu)


def run(args) -> int:
    from medimg.assess import decide, detect

    settings = config.load_settings()
    root = Path(getattr(args, "output_root", None) or settings.output_root)
    yes = bool(getattr(args, "yes", False))

    # 1. Machine, disk
    _step(1, "Checking this computer")
    machine = detect(disk_path=root)
    decision = decide(machine)
    print(f"  {machine.os_name} {machine.os_version}, {machine.cpu}, "
          f"{machine.ram_total_gb:g} GB RAM, {machine.disk_free_gb:.1f} GB free disk, "
          f"Python {machine.python}")
    if not decision.supported:
        print(f"This computer cannot run the generator: {decision.reason}")
        if decision.fix:
            print(f"Fix: {decision.fix}")
        return 1
    print(f"  Backend: {decision.backend}. {decision.reason}")
    backend = decision.backend
    mode = decision.offload_mode

    cached = (download.mflux_cached() is not None if backend == "mflux"
              else download.diffusers_cached(mode or "model_cpu_offload"))
    if cached:
        print(f"  Disk check: {DONE} (model weights are already downloaded)")
    else:
        need = round((decision.download_gb or 0) + config.DISK_MARGIN_GB, 1)
        if machine.disk_free_gb < need:
            print(f"Not enough disk space: {machine.disk_free_gb:.1f} GB free, need {need:.1f} GB "
                  f"({decision.download_gb:g} GB model + {config.DISK_MARGIN_GB} GB spare). "
                  "Free up space and run setup again.")
            return 1
        print(f"  Disk check passed: {machine.disk_free_gb:.1f} GB free, need {need:.1f} GB.")

    # 2. Python packages
    _step(2, "Installing Python packages")
    extra, module = _extra_for(backend)
    if _module_present(module):
        print(f"  {DONE}")
    else:
        print(f"  Installing the {extra} packages (uv sync --extra {extra})...")
        rc = _uv_sync(extra)
        if rc != 0:
            print(f"Package install failed (exit {rc}). Check your internet connection, "
                  f"then run setup again. To retry by hand: uv sync --extra {extra}")
            return 1
        importlib.invalidate_caches()

    # 3. Model weights
    _step(3, "Downloading the model")
    if cached:
        print(f"  {DONE}")
    else:
        if not yes and not _confirm(f"  Download about {decision.download_gb:g} GB now?"):
            print("Stopped. Run setup again when you are ready to download.")
            return 1
        try:
            if backend == "mflux":
                download.download_mflux(print)
            else:
                download.download_diffusers(mode or "model_cpu_offload", print)
        except MedimgError as e:
            print(f"Problem: {e.cause}")
            if e.fix:
                print(f"Fix: {e.fix}")
            return 1

    # 4. Smoke test
    _step(4, "Making one test image (512x512, 4 steps)")
    if getattr(args, "skip_smoke", False):
        print("  Skipped (--skip-smoke).")
    elif _smoke_done(root):
        print(f"  {DONE}")
    else:
        from medimg import smoke
        rc = smoke.run(Namespace(size="512x512", steps=4, fake_engine=False, output_root=str(root)))
        if rc != 0:
            print("The test image failed. Run: python -m medimg smoke   to see the error.")
            return 1

    # 5. Assess
    _step(5, "Measuring this computer's speed")
    if getattr(args, "skip_assess", False):
        print("  Skipped (--skip-assess).")
    elif _assess_done(backend, machine.cpu):
        print(f"  {DONE}")
    else:
        from medimg import assess
        rc = assess.run(Namespace(no_benchmark=False, json=False, output_root=str(root)))
        if rc != 0:
            print("The assessment failed. Run: python -m medimg assess   to see the error.")
            return 1

    # 6. Next
    _step(6, "Done")
    print(f"  Setup finished. Start the app with:\n\n      {_next_command()}\n")
    return 0
