"""Stub mflux/mlx modules. Installed into sys.modules by the fake_mflux fixture."""
from __future__ import annotations

import inspect
import sys
import types
from dataclasses import dataclass

from PIL import Image

MODULE_NAMES = [
    "mlx", "mlx.core", "mflux", "mflux.models", "mflux.models.common",
    "mflux.models.common.config", "mflux.models.common.config.model_config",
    "mflux.models.common.vae", "mflux.models.common.vae.tiling_config",
    "mflux.models.z_image", "mflux.models.z_image.variants",
    "mflux.models.z_image.variants.z_image", "mflux.utils", "mflux.utils.exceptions",
]

# exact keyword names mflux 0.22.0 uses when calling callbacks
_EXPECTED = {
    "call_before_loop": {"seed", "prompt", "latents", "config", "canny_image", "depth_image", "control_images"},
    "call_in_loop": {"t", "seed", "prompt", "latents", "config", "time_steps"},
    "call_after_loop": {"seed", "prompt", "latents", "config"},
}
_REQUIRED = {
    "call_before_loop": {"seed", "prompt", "latents", "config"},
    "call_in_loop": {"t", "seed", "prompt", "latents", "config", "time_steps"},
    "call_after_loop": {"seed", "prompt", "latents", "config"},
}


class StopImageGenerationException(Exception):
    pass


class _Sentinel:
    def __repr__(self) -> str:
        return "<ModelConfig.z_image_turbo>"


@dataclass
class TilingConfig:
    pass


@dataclass
class _Config:
    num_inference_steps: int
    init_time_step: int = 0
    width: int = 0
    height: int = 0


class _GeneratedImage:
    def __init__(self, image, generation_time):
        self.image = image
        self.generation_time = generation_time


def _check_signature(cb, name: str) -> None:
    """Fail like Python would if the callback cannot take the exact keywords."""
    method = getattr(cb, name)
    params = inspect.signature(method).parameters
    names = set(params)
    has_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    if not has_var_kw:
        unexpected = _EXPECTED[name] - names
        # optional args are only passed when declared; required ones must be accepted
        missing = _REQUIRED[name] - names
        if missing:
            raise TypeError(f"{name}() missing keyword parameters: {sorted(missing)}")
        extra_required = {n for n, p in params.items()
                          if p.default is inspect.Parameter.empty and n not in _EXPECTED[name]
                          and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)}
        if extra_required:
            raise TypeError(f"{name}() has unexpected required parameters: {sorted(extra_required)}")
        del unexpected


class _Callbacks:
    def __init__(self):
        self.before_loop, self.in_loop, self.after_loop = [], [], []

    def register(self, obj) -> None:
        for lst, name in ((self.before_loop, "call_before_loop"), (self.in_loop, "call_in_loop"),
                          (self.after_loop, "call_after_loop")):
            if hasattr(obj, name):
                _check_signature(obj, name)
                lst.append(obj)


class ZImage:
    """Records ctor kwargs in calls; generate_image(**kw) drives callbacks keyword-only."""
    calls: list = []  # replaced per install by the fixture's module-level list

    def __init__(self, **kw):
        self.ctor_kwargs = dict(kw)
        type(self).calls.append(("ZImage.__init__", dict(kw)))
        self.callbacks = _Callbacks()
        self.tiling_config = None

    def generate_image(self, **kw):
        type(self).calls.append(("generate_image", dict(kw)))
        assert "num_inference_steps" in kw, "num_inference_steps must always be passed (default is 4)"
        steps = kw["num_inference_steps"]
        config = _Config(num_inference_steps=steps, init_time_step=0,
                         width=kw.get("width", 0), height=kw.get("height", 0))
        latents = object()
        common = dict(seed=kw["seed"], prompt=kw["prompt"], latents=latents, config=config)
        for cb in self.callbacks.before_loop:
            cb.call_before_loop(**common)
        time_steps = range(0, steps)
        for t in time_steps:
            for cb in self.callbacks.in_loop:
                cb.call_in_loop(t=t, time_steps=time_steps, **common)  # StopImageGenerationException propagates
        for cb in self.callbacks.after_loop:
            cb.call_after_loop(**common)
        w, h = kw.get("width", 64), kw.get("height", 64)
        return _GeneratedImage(Image.new("RGB", (max(1, w // 16), max(1, h // 16)), (10, 20, 30)), 0.01)


def install(monkeypatch):
    """Install stub modules; returns the shared calls list."""
    calls: list[tuple[str, dict]] = []
    ZImage.calls = calls

    mods = {n: types.ModuleType(n) for n in MODULE_NAMES}
    core = mods["mlx.core"]
    core.set_cache_limit = lambda n: calls.append(("set_cache_limit", {"limit": n}))
    core.clear_cache = lambda: calls.append(("clear_cache", {}))
    core.reset_peak_memory = lambda: calls.append(("reset_peak_memory", {}))
    core.get_peak_memory = lambda: 1.5e9
    mods["mlx"].core = core

    sentinel = _Sentinel()
    class ModelConfig:
        @staticmethod
        def z_image_turbo():
            return sentinel
    mods["mflux.models.common.config.model_config"].ModelConfig = ModelConfig
    mods["mflux.models.common.vae.tiling_config"].TilingConfig = TilingConfig
    mods["mflux.models.z_image.variants.z_image"].ZImage = ZImage
    mods["mflux.utils.exceptions"].StopImageGenerationException = StopImageGenerationException

    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)

    import importlib.metadata as md
    real_version = md.version
    monkeypatch.setattr(md, "version", lambda n, *a, **k: "0.22.0" if n == "mflux" else real_version(n, *a, **k))
    return calls
