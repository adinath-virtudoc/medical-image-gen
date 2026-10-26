"""Pure parsers for tool output. No subprocess calls, no I/O."""
from __future__ import annotations

import csv
import io
import json
import re


def _num(text: str) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(m.group(0)) if m else None


def parse_nvidia_smi(csv_text: str, header_text: str) -> dict | None:
    """Parse `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv[,noheader,nounits]`
    plus the plain `nvidia-smi` banner (for the CUDA version). Returns the GPU with the most VRAM,
    or None when nothing parseable is there."""
    best: dict | None = None
    for row in csv.reader(io.StringIO(csv_text or ""), skipinitialspace=True):
        if len(row) < 3:
            continue
        name, mem, driver = (c.strip() for c in row[:3])
        if not name or name.lower() == "name":
            continue                                    # header row
        mib = _num(mem)
        if mib is None:
            continue
        gpu = {"vendor": "nvidia", "name": name, "vram_gb": round(mib / 1024, 1),
               "driver": driver or None, "cuda": None}
        if best is None or gpu["vram_gb"] > best["vram_gb"]:
            best = gpu
    if best is None:
        return None
    m = re.search(r"CUDA Version:\s*([0-9]+(?:\.[0-9]+)?)", header_text or "")
    if m:
        best["cuda"] = m.group(1)
    if not best["driver"]:
        m = re.search(r"Driver Version:\s*([0-9.]+)", header_text or "")
        best["driver"] = m.group(1) if m else None
    return best


def parse_system_profiler(json_text: str) -> dict:
    """`system_profiler SPHardwareDataType -json` -> {"chip", "memory_gb", "model"} (missing -> None)."""
    out = {"chip": None, "memory_gb": None, "model": None}
    try:
        items = json.loads(json_text).get("SPHardwareDataType") or []
        hw = items[0] if items else {}
    except (ValueError, AttributeError, TypeError):
        return out
    chip = hw.get("chip_type") or hw.get("cpu_type")
    out["chip"] = chip.strip() if isinstance(chip, str) else None
    out["memory_gb"] = _num(str(hw.get("physical_memory", "")))
    out["model"] = hw.get("machine_name") or hw.get("machine_model")
    return out


def parse_sysctl(text: str) -> dict:
    """`sysctl machdep.cpu.brand_string hw.memsize hw.optional.arm64` lines (`k: v` or `k = v`)."""
    kv: dict[str, str] = {}
    for line in (text or "").splitlines():
        m = re.match(r"\s*([\w.]+)\s*[:=]\s*(.*?)\s*$", line)
        if m:
            kv[m.group(1)] = m.group(2)
    out: dict = {"cpu": kv.get("machdep.cpu.brand_string") or None, "ram_bytes": None, "arm64": None}
    if kv.get("hw.memsize", "").isdigit():
        out["ram_bytes"] = int(kv["hw.memsize"])
    if kv.get("hw.optional.arm64", "") in ("0", "1"):
        out["arm64"] = kv["hw.optional.arm64"] == "1"
    return out


def parse_wmic_or_powershell(text: str) -> dict:
    """CPU name from `wmic cpu get name /value` (`Name=...`), `wmic cpu get name` (header table) or
    PowerShell `(Get-CimInstance Win32_Processor).Name` (bare value, or a Name/---- table).
    Also returns every device name seen as "names" (used for video controllers)."""
    names: list[str] = []
    for raw in (text or "").replace("\r", "\n").splitlines():
        line = raw.strip()
        if not line or set(line) <= {"-", " "}:
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            if key.strip().lower() == "name" and val.strip():
                names.append(val.strip())
            continue
        if line.lower() == "name":
            continue
        names.append(line)
    return {"cpu": names[0] if names else None, "names": names}
