"""Stub torch/diffusers modules. Installed into sys.modules by the fake_diffusers fixture."""
from __future__ import annotations

import sys
import types

from PIL import Image

MODULE_NAMES = ["torch", "torch.cuda", "diffusers"]


class _Generator:
    def __init__(self, device="cpu"):
        self.device = device
        self.seed = None

    def manual_seed(self, n):
        self.seed = n
        return self


class _Output:
    def __init__(self, images):
        self.images = images


class ZImagePipeline:
    calls: list = []

    def __init__(self, kw):
        self.init_kwargs = kw
        self._interrupt = False

    @classmethod
    def from_pretrained(cls, *args, **kw):
        cls.calls.append(("from_pretrained", {"args": args, **kw}))
        return cls(kw)

    @property
    def interrupt(self):
        return self._interrupt

    def to(self, *a, **kw):
        type(self).calls.append(("to", {"args": a, **kw}))
        return self

    def enable_model_cpu_offload(self, **kw):
        type(self).calls.append(("enable_model_cpu_offload", dict(kw)))

    def enable_sequential_cpu_offload(self, **kw):
        type(self).calls.append(("enable_sequential_cpu_offload", dict(kw)))

    def set_progress_bar_config(self, **kw):
        type(self).calls.append(("set_progress_bar_config", dict(kw)))

    def __call__(self, **kw):
        type(self).calls.append(("__call__", dict(kw)))
        assert kw.get("guidance_scale") == 0.0, "Turbo requires guidance_scale=0.0"
        assert "num_inference_steps" in kw, "num_inference_steps must be passed (default is 50)"
        cb = kw.get("callback_on_step_end")
        self._interrupt = False
        n = kw["num_inference_steps"]
        for i in range(n):
            if self._interrupt:
                continue
            if cb is not None:
                out = cb(self, i, i, {"latents": None})
                assert isinstance(out, dict), "callback_on_step_end must return a dict"
        w, h = kw.get("width", 64), kw.get("height", 64)
        return _Output([Image.new("RGB", (max(1, w // 16), max(1, h // 16)), (30, 20, 10))])


class ZImageTransformer2DModel:
    calls: list = []

    @classmethod
    def from_single_file(cls, *args, **kw):
        cls.calls.append(("from_single_file", {"args": args, **kw}))
        return object()


class GGUFQuantizationConfig:
    calls: list = []

    def __init__(self, **kw):
        self.kw = kw
        type(self).calls.append(("GGUFQuantizationConfig", dict(kw)))


def install(monkeypatch):
    """Install stub modules; returns the shared calls list."""
    calls: list[tuple[str, dict]] = []
    ZImagePipeline.calls = calls
    ZImageTransformer2DModel.calls = calls
    GGUFQuantizationConfig.calls = calls

    mods = {n: types.ModuleType(n) for n in MODULE_NAMES}
    torch, cuda, diffusers = mods["torch"], mods["torch.cuda"], mods["diffusers"]
    torch.bfloat16 = "bfloat16"
    torch.Generator = _Generator
    cuda.reset_peak_memory_stats = lambda *a, **k: calls.append(("reset_peak_memory_stats", {}))
    cuda.max_memory_allocated = lambda *a, **k: 1.2e10
    cuda.empty_cache = lambda: calls.append(("empty_cache", {}))
    cuda.is_available = lambda: True
    torch.cuda = cuda
    diffusers.ZImagePipeline = ZImagePipeline
    diffusers.ZImageTransformer2DModel = ZImageTransformer2DModel
    diffusers.GGUFQuantizationConfig = GGUFQuantizationConfig

    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)

    import importlib.metadata as md
    real_version = md.version
    monkeypatch.setattr(md, "version", lambda n, *a, **k: "0.41.0" if n == "diffusers" else real_version(n, *a, **k))
    return calls
