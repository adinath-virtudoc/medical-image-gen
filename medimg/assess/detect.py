"""Machine detection. Every external tool is optional; nothing here raises on a missing tool."""
from __future__ import annotations

import platform
import re
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

import psutil

from medimg import config
from medimg.assess import parse


@dataclass
class Machine:
    hostname: str
    os_name: str
    os_version: str
    cpu: str
    apple_chip: str | None
    ram_total_gb: float
    ram_free_gb: float
    gpu: dict | None            # {"vendor", "name", "vram_gb", "driver", "cuda"}
    disk_free_gb: float
    disk_path: str
    python: str
    uv: str | None
    arch: str


def _out(run, cmd: list[str], timeout: float = 20) -> str | None:
    """stdout of a command, or None when it is missing, fails or times out."""
    try:
        r = run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None
    if getattr(r, "returncode", 1) != 0:
        return None
    out = getattr(r, "stdout", None)
    return out if isinstance(out, str) and out.strip() else None


def _existing_parent(path: Path) -> Path:
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    return p


def _vendor_of(name: str) -> str:
    n = name.lower()
    if "nvidia" in n or "geforce" in n or "quadro" in n or "rtx" in n:
        return "nvidia"
    if "amd" in n or "radeon" in n:
        return "amd"
    if "intel" in n:
        return "intel"
    return "other"


def _pick_gpu_name(names: list[str]) -> dict | None:
    """Best guess from device strings: prefer NVIDIA, then AMD, then anything else."""
    ranked = sorted(names, key=lambda n: {"nvidia": 0, "amd": 1}.get(_vendor_of(n), 2))
    for n in ranked:
        v = _vendor_of(n)
        if v in ("nvidia", "amd"):
            return {"vendor": v, "name": n, "vram_gb": None, "driver": None, "cuda": None}
    return {"vendor": _vendor_of(ranked[0]), "name": ranked[0], "vram_gb": None,
            "driver": None, "cuda": None} if ranked else None


def detect(run=subprocess.run, platform_mod=platform, psutil_mod=psutil,
           disk_path: str | Path | None = None) -> Machine:
    system = platform_mod.system() or "Unknown"
    arch = (platform_mod.machine() or "").lower()
    if arch in ("amd64", "x64"):
        arch = "x86_64"
    if arch == "aarch64" and system == "Darwin":
        arch = "arm64"
    try:
        hostname = platform_mod.node() or socket.gethostname()
    except Exception:
        hostname = ""

    cpu, apple_chip, gpu = "", None, None
    ram_override = None

    if system == "Darwin":
        sc = parse.parse_sysctl(_out(run, ["sysctl", "machdep.cpu.brand_string", "hw.memsize",
                                           "hw.optional.arm64"]) or "")
        sp = parse.parse_system_profiler(
            _out(run, ["system_profiler", "SPHardwareDataType", "-json"], timeout=60) or "")
        cpu = sc["cpu"] or sp["chip"] or ""
        if sc["arm64"]:
            arch = "arm64"                      # Python under Rosetta reports x86_64
        chip = sp["chip"] or (sc["cpu"] if sc["cpu"] and sc["cpu"].startswith("Apple") else None)
        if arch == "arm64":
            apple_chip = chip or "Apple silicon"
            cpu = cpu or apple_chip
            gpu = {"vendor": "apple", "name": apple_chip, "vram_gb": None, "driver": None, "cuda": None}
        if sc["ram_bytes"]:
            ram_override = sc["ram_bytes"] / 1024 ** 3
    elif system == "Windows":
        text = _out(run, ["wmic", "cpu", "get", "name", "/value"]) or _out(
            run, ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"])
        cpu = parse.parse_wmic_or_powershell(text or "")["cpu"] or ""
    else:
        text = _out(run, ["lscpu"])
        if text:
            m = re.search(r"^Model name:\s*(.+)$", text, re.M)
            cpu = m.group(1).strip() if m else ""
    cpu = cpu or (platform_mod.processor() or "") or "unknown"

    if gpu is None:
        smi_csv = _out(run, ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                             "--format=csv,noheader,nounits"])
        if smi_csv:
            gpu = parse.parse_nvidia_smi(smi_csv, _out(run, ["nvidia-smi"]) or "")
    if gpu is None and system == "Windows":
        names = parse.parse_wmic_or_powershell(
            _out(run, ["wmic", "path", "win32_videocontroller", "get", "name", "/value"]) or "")["names"]
        gpu = _pick_gpu_name(names)
    elif gpu is None and system == "Linux":
        lines = [ln.split(": ", 1)[-1] for ln in (_out(run, ["lspci"]) or "").splitlines()
                 if re.search(r"VGA|3D controller|Display controller", ln)]
        gpu = _pick_gpu_name(lines)

    try:
        vm = psutil_mod.virtual_memory()
        total_gb = vm.total / 1024 ** 3
        free_gb = vm.available / 1024 ** 3
    except Exception:
        total_gb, free_gb = ram_override or 0.0, 0.0
    if ram_override and not total_gb:
        total_gb = ram_override

    target = Path(disk_path) if disk_path else config.DEFAULT_OUTPUT_ROOT
    probe = _existing_parent(target)
    try:
        disk_free = psutil_mod.disk_usage(str(probe)).free / 1e9
    except Exception:
        disk_free = 0.0

    uv_text = _out(run, ["uv", "--version"])
    m = re.search(r"(\d+\.\d+\.\d+\S*)", uv_text or "")
    return Machine(hostname=hostname, os_name=system, os_version=platform_mod.release() or "",
                   cpu=cpu, apple_chip=apple_chip, ram_total_gb=round(total_gb, 1),
                   ram_free_gb=round(free_gb, 1), gpu=gpu, disk_free_gb=round(disk_free, 1),
                   disk_path=str(target), python=platform_mod.python_version(),
                   uv=m.group(1) if m else None, arch=arch)
