"""Engine factory. Real engines are imported lazily so nothing heavy loads here."""
from __future__ import annotations

from pathlib import Path

from medimg import config
from medimg.engines.base import Engine


def _find_gguf(name: str) -> Path | None:
    """Locate a GGUF file in the local Hugging Face cache (never downloads)."""
    try:
        from huggingface_hub import hf_hub_download
        return Path(hf_hub_download(config.GGUF_REPO_ID, name, local_files_only=True))
    except Exception:
        return None


def make_engine(backend: str, profile: dict | None, *, fake: bool = False,
                tier: str | None = None) -> Engine:
    if fake or backend == "fake":
        from medimg.engines.fake_engine import FakeEngine
        return FakeEngine()
    if backend == "mflux":
        from medimg.engines.mflux_engine import MfluxEngine
        return MfluxEngine()
    if backend == "diffusers":
        from medimg.engines.diffusers_engine import DiffusersEngine
        mode = ((profile or {}).get("backend") or {}).get("offload_mode") or "model_cpu_offload"
        gguf_path = None
        if mode == "gguf_q8_offload":
            gguf_path = _find_gguf(config.GGUF_FILES["q8_0"][0])
        elif mode == "gguf_q4_sequential":
            gguf_path = _find_gguf(config.GGUF_FILES["q4_k_m"][0])
        return DiffusersEngine(offload_mode=mode, gguf_path=gguf_path)
    if backend == "sdcpp":
        return _make_sdcpp(profile, tier)
    raise ValueError(f"unknown backend: {backend!r}")


def _make_sdcpp(profile: dict | None, tier: str | None = None) -> Engine:
    import platform

    import psutil

    from medimg.engines.sdcpp_engine import SdcppEngine
    from medimg.errors import ModelUnavailable
    from medimg.sdcpp import install
    from medimg.sdcpp.pins import tier_for_ram

    settings = config.load_settings()
    prof = profile or {}
    be = prof.get("backend") or {}
    sd = be.get("sdcpp") or {}
    device = settings.sdcpp_device or be.get("device") or "cpu"
    tier = tier or settings.sdcpp_tier or sd.get("tier")
    if not tier:
        ram = (prof.get("machine") or {}).get("ram_total_gb")
        if not ram:
            ram = psutil.virtual_memory().total / 1024**3
        tier = tier_for_ram(ram)
    build = sd.get("build") or install.chosen_build(platform.system(), platform.machine())
    if build is None:
        raise ModelUnavailable("This computer type has no stable-diffusion.cpp build.",
                               "Use a Windows or Linux PC (64-bit) or an Apple Silicon Mac.")
    paths = install.resolve_paths(build, tier)
    return SdcppEngine(paths, device, threads=settings.sdcpp_threads)


__all__ = ["make_engine"]
