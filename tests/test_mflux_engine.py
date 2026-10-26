"""MfluxEngine contract tests against stub mflux/mlx. The real model is never loaded."""
from __future__ import annotations

import subprocess
import sys

import pytest

from medimg.engines.base import GenResult
from medimg.errors import Cancelled


def _engine():
    from medimg.engines.mflux_engine import MfluxEngine
    return MfluxEngine()


def _kw(calls, name):
    return [kw for n, kw in calls if n == name]


def test_import_without_mflux():
    code = ("import sys; import medimg.engines.mflux_engine as m; "
            "assert 'mflux' not in sys.modules and 'mlx' not in sys.modules; "
            "assert m.MfluxEngine().loaded is False")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_generate_before_load_raises(fake_mflux):
    with pytest.raises(RuntimeError, match="engine not loaded"):
        _engine().generate("p", 1, 2, 64, 64, lambda *a: None, lambda: False)


def test_load_kwargs_tiling_cache(fake_mflux):
    from tests.stubs.mflux_stub import TilingConfig
    eng = _engine()
    eng.load()
    ctor = _kw(fake_mflux, "ZImage.__init__")
    assert len(ctor) == 1
    assert set(ctor[0]) == {"model_path", "model_config", "quantize"}
    assert ctor[0]["model_path"] == "filipstrand/Z-Image-Turbo-mflux-4bit"
    assert ctor[0]["quantize"] is None
    assert repr(ctor[0]["model_config"]) == "<ModelConfig.z_image_turbo>"
    assert isinstance(eng._model.tiling_config, TilingConfig)
    assert _kw(fake_mflux, "set_cache_limit") == [{"limit": 1000**3}]
    assert len(eng._model.callbacks.in_loop) == 1


def test_load_idempotent(fake_mflux):
    eng = _engine()
    eng.load()
    eng.load()
    assert len(_kw(fake_mflux, "ZImage.__init__")) == 1
    assert len(eng._model.callbacks.in_loop) == 1


def test_generate_kwargs_and_result(fake_mflux):
    eng = _engine()
    eng.load()
    res = eng.generate("a prompt", 7, 3, 64, 48, lambda *a: None, lambda: False)
    gen = _kw(fake_mflux, "generate_image")
    assert gen == [{"seed": 7, "prompt": "a prompt", "num_inference_steps": 3,
                    "height": 48, "width": 64}]
    assert isinstance(res, GenResult)
    assert res.seed == 7 and res.steps == 3
    assert res.engine == "mflux 0.22.0"
    assert res.model_id == "filipstrand/Z-Image-Turbo-mflux-4bit"
    assert res.peak_mem_gb == pytest.approx(1.5)
    assert res.time_s >= 0
    assert "reset_peak_memory" in [n for n, _ in fake_mflux]


def test_progress_sequence(fake_mflux):
    eng = _engine()
    eng.load()
    ev = []
    eng.generate("p", 1, 4, 64, 64, lambda *a: ev.append(a), lambda: False)
    assert ev == [("encoding", 0, 0), ("denoising", 1, 4), ("denoising", 2, 4),
                  ("denoising", 3, 4), ("denoising", 4, 4), ("decoding", 4, 4)]


def test_callback_signatures(fake_mflux):
    import inspect
    from medimg.engines.mflux_engine import _Progress
    p = _Progress()
    assert list(inspect.signature(p.call_before_loop).parameters) == [
        "seed", "prompt", "latents", "config", "canny_image", "depth_image", "control_images"]
    assert list(inspect.signature(p.call_in_loop).parameters) == [
        "t", "seed", "prompt", "latents", "config", "time_steps"]
    assert list(inspect.signature(p.call_after_loop).parameters) == [
        "seed", "prompt", "latents", "config"]
    assert not hasattr(p, "call_interrupt")


def test_cancel_after_step_k(fake_mflux):
    eng = _engine()
    eng.load()
    ev = []
    polls = []

    def cancel():
        polls.append(1)
        return len(polls) >= 2

    with pytest.raises(Cancelled):
        eng.generate("p", 1, 5, 64, 64, lambda *a: ev.append(a), cancel)
    assert ev == [("encoding", 0, 0), ("denoising", 1, 5), ("denoising", 2, 5)]
    assert fake_mflux[-1][0] == "clear_cache"
    # engine stays usable after a cancel
    res = eng.generate("p", 2, 2, 64, 64, lambda *a: None, lambda: False)
    assert res.steps == 2


def test_clear_cache_on_success(fake_mflux):
    eng = _engine()
    eng.load()
    eng.generate("p", 1, 2, 64, 64, lambda *a: None, lambda: False)
    assert [n for n, _ in fake_mflux].count("clear_cache") == 1


def test_clear_cache_on_failure(fake_mflux):
    eng = _engine()
    eng.load()

    def boom(*a):
        if a[0] == "denoising":
            raise ValueError("boom")

    with pytest.raises(ValueError):
        eng.generate("p", 1, 2, 64, 64, boom, lambda: False)
    assert [n for n, _ in fake_mflux].count("clear_cache") == 1


def test_unload_twice_noop(fake_mflux):
    eng = _engine()
    eng.unload()  # never loaded
    eng.load()
    eng.unload()
    n = [n for n, _ in fake_mflux].count("clear_cache")
    eng.unload()
    assert [n_ for n_, _ in fake_mflux].count("clear_cache") == n
    assert eng.loaded is False and eng._model is None
    with pytest.raises(RuntimeError, match="engine not loaded"):
        eng.generate("p", 1, 2, 64, 64, lambda *a: None, lambda: False)
    eng.load()
    assert eng.loaded is True
