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


def make_engine(backend: str, profile: dict | None, *, fake: bool = False) -> Engine:
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
    raise ValueError(f"unknown backend: {backend!r}")


__all__ = ["make_engine"]
