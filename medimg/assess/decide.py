"""Backend decision rules (PLAN 4.7, D6, D17). Pure function of a Machine."""
from __future__ import annotations

from dataclasses import dataclass

from medimg import config

# Offload mode names (PLAN 4.2 OFFLOAD_MODES) as plain strings, so diffusers_engine is never imported.
RESIDENT = "resident"
MODEL_OFFLOAD = "model_cpu_offload"
GGUF_Q8 = "gguf_q8_offload"
GGUF_Q4 = "gguf_q4_sequential"

MIN_RAM_MFLUX_GB = 15.5         # a 16 GB Mac reports 16.0 GiB; allow slack
RAM_RECOMMENDED_NVIDIA_GB = 32.0
DRIVER_MIN = {"Windows": (570, 65), "Linux": (570, 26)}
# Non-transformer download for the GGUF modes: text encoder 8.05 + VAE 0.17 + tokenizer etc.
GGUF_REST_GB = 8.3


@dataclass
class Decision:
    backend: str | None
    supported: bool
    reason: str
    fix: str
    offload_mode: str | None
    unload_after_job: bool
    model_id: str | None
    download_gb: float | None
    min_disk_gb: float | None
    device: str | None = None       # sdcpp: "cpu" | "vulkan0" | "metal"
    tier: str | None = None         # sdcpp: "low" | "mid" | "high"


def _mflux_cached() -> bool:
    """True when the mflux snapshot is already in the local HF cache (offline check)."""
    from medimg import download
    return download.mflux_cached() is not None


def _no(reason: str, fix: str = "") -> Decision:
    return Decision(None, False, reason, fix, None, False, None, None, None)


def _ver(text: str | None) -> tuple[int, ...] | None:
    try:
        return tuple(int(x) for x in str(text).split(".")[:2])
    except (ValueError, TypeError):
        return None


def _nvidia_mode(vram: float) -> tuple[str | None, float]:
    """(offload mode, download GB) by VRAM (D6)."""
    if vram >= 22:
        return RESIDENT, config.DIFFUSERS_MODEL_GB
    if vram >= 15:
        return MODEL_OFFLOAD, config.DIFFUSERS_MODEL_GB
    if vram >= 10:
        return GGUF_Q8, round(config.GGUF_FILES["q8_0"][1] + GGUF_REST_GB, 1)
    if vram >= 7.5:
        return GGUF_Q4, round(config.GGUF_FILES["q4_k_m"][1] + GGUF_REST_GB, 1)
    return None, 0.0


def _sdcpp_cached(tier: str) -> bool:
    """True when every model file of the tier is in the local cache. Offline; never raises."""
    try:
        from medimg.sdcpp import install
        return install.models_cached(tier) is not None
    except Exception:
        return False


def _sdcpp_device(m, ram: float) -> str:
    vendor = (m.gpu or {}).get("vendor")
    if m.os_name == "Darwin" and m.arch == "arm64":
        return "metal"
    if vendor in ("amd", "nvidia") or (vendor == "intel" and ram >= 16):
        return "vulkan0"
    return "cpu"


def _sdcpp(m, prefix: str = "") -> Decision:
    """sd.cpp rules (PLAN_SDCPP 3.4). `prefix` is the reason it was chosen over CUDA."""
    from medimg.sdcpp import pins
    ram = m.ram_total_gb
    if m.os_name == "Darwin" and m.arch != "arm64":
        return _no("Intel Mac: Apple-silicon only.",
                   "Use an Apple-silicon Mac (M1 or newer) or a PC with an NVIDIA GPU.")
    if ram < config.SDCPP_MIN_RAM_GB:
        return _no(f"{prefix}This computer has {ram:g} GB of RAM; at least 8 GB is needed.",
                   "Use a computer with 8 GB or more.")
    try:
        override = config.load_settings().sdcpp_tier
    except Exception:
        override = None
    tier = override or pins.tier_for_ram(ram)
    device = _sdcpp_device(m, ram)
    cached = _sdcpp_cached(tier)
    download = 0.0 if cached else pins.TIER_GB[tier]
    need = 0.0 if cached else round(download + config.DISK_MARGIN_GB, 1)
    if m.disk_free_gb < need:
        return _no(f"{prefix}Not enough disk space: {m.disk_free_gb:.1f} GB free at {m.disk_path}, "
                   f"need {need:.1f} GB ({download:g} GB download + {config.DISK_MARGIN_GB} GB margin).",
                   "Free up disk space and run assess again.")
    where = {"cpu": "on the processor", "vulkan0": "on the graphics chip (Vulkan, tried first)",
             "metal": "on the Apple graphics chip (Metal)"}[device]
    span = {"low": "under 12 GB RAM", "mid": "12-24 GB RAM", "high": "24 GB RAM or more"}[tier]
    if prefix:
        reason = f"{prefix}Using stable-diffusion.cpp (sd.cpp) instead: {where}, tier {tier} ({span})"
    else:
        reason = f"{m.os_name}: sd.cpp {where}, tier {tier} ({span})"
    return Decision("sdcpp", True, reason, "", None, False, config.SDCPP_MODEL_ID, download, need,
                    device, tier)


def decide(m, *, engine: str | None = None) -> Decision:
    if engine == "sdcpp":
        return _sdcpp(m)
    d = _decide_native(m)
    if (not d.supported and engine in (None, "auto") and m.os_name in ("Windows", "Linux")
            and "Not enough disk space" not in d.reason):
        why = d.reason.rstrip()
        if not why.endswith((".", "!")):
            why += "."
        return _sdcpp(m, why + " ")
    return d


def _decide_native(m) -> Decision:
    gpu = m.gpu or {}
    vendor = gpu.get("vendor")

    if m.os_name == "Darwin":
        if m.arch != "arm64":
            return _no("Intel Mac: Apple-silicon only.",
                       "Use an Apple-silicon Mac (M1 or newer) or a PC with an NVIDIA GPU.")
        if m.ram_total_gb < MIN_RAM_MFLUX_GB:
            return _no(f"Apple silicon with {m.ram_total_gb:g} GB RAM: at least 16 GB is needed.",
                       "Use a Mac with 16 GB or more memory.")
        cached = _mflux_cached()
        download = 0.0 if cached else config.MFLUX_MODEL_GB
        need = 0.0 if cached else config.MFLUX_MODEL_GB + config.DISK_MARGIN_GB
        if m.disk_free_gb < need:
            return _no(f"Not enough disk space: {m.disk_free_gb:.1f} GB free at {m.disk_path}, "
                       f"need {need:.1f} GB ({config.MFLUX_MODEL_GB} GB model + "
                       f"{config.DISK_MARGIN_GB} GB margin).", "Free up disk space and run assess again.")
        return Decision("mflux", True,
                        f"Apple silicon with {m.ram_total_gb:g} GB"
                        + (" (model already downloaded)" if cached else ""),
                        "", None, m.ram_total_gb <= 16.5, config.MFLUX_MODEL_ID, download, need)

    if vendor == "amd":
        return _no("AMD GPUs are not supported in v1.", "Use an NVIDIA GPU or an Apple-silicon Mac.")
    if vendor != "nvidia":
        return _no("No NVIDIA GPU found.", "Use a PC with an NVIDIA GPU (8 GB VRAM or more) "
                   "or an Apple-silicon Mac.")
    if gpu.get("driver") is None and gpu.get("vram_gb") is None:
        return _no(f"{gpu.get('name', 'An NVIDIA GPU')} was found but nvidia-smi is not available.",
                   "Install the NVIDIA driver, then run assess again.")

    minimum = DRIVER_MIN.get(m.os_name, DRIVER_MIN["Linux"])
    drv = _ver(gpu.get("driver"))
    if drv is not None and drv < minimum:
        return _no(f"NVIDIA driver {gpu['driver']} is older than {minimum[0]}.{minimum[1]:02d}, "
                   "which CUDA 12.8 needs.", "Update the NVIDIA driver and run assess again.")

    vram = float(gpu.get("vram_gb") or 0)
    mode, download = _nvidia_mode(vram)
    if mode is None:
        return _no(f"The GPU has {vram:g} GB of VRAM; at least 8 GB is needed.",
                   "Use a GPU with 8 GB of VRAM or more.")
    need = round(download + config.DISK_MARGIN_GB, 1)
    if m.disk_free_gb < need:
        return _no(f"Not enough disk space: {m.disk_free_gb:.1f} GB free at {m.disk_path}, "
                   f"need {need:.1f} GB ({download:g} GB download + {config.DISK_MARGIN_GB} GB margin).",
                   "Free up disk space and run assess again.")
    reason = f"NVIDIA {gpu.get('name', 'GPU')} with {vram:g} GB VRAM: {mode} mode"
    if mode in (GGUF_Q8, GGUF_Q4):
        reason += " (experimental, quantized model)"
    if m.ram_total_gb < RAM_RECOMMENDED_NVIDIA_GB and mode != RESIDENT:
        reason += (f". Warning: {m.ram_total_gb:g} GB of system RAM is below the recommended "
                   f"{RAM_RECOMMENDED_NVIDIA_GB:g} GB; loading may be slow.")
    return Decision("diffusers", True, reason, "", mode, False, config.DIFFUSERS_MODEL_ID,
                    download, need)
