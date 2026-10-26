import subprocess
import sys
from pathlib import Path

import pytest

from medimg.engines.diffusers_engine import OFFLOAD_MODES, DiffusersEngine
from medimg.errors import Cancelled

GGUF = Path("/models/z.gguf")


def mk(mode, **kw):
    if mode.startswith("gguf"):
        kw.setdefault("gguf_path", GGUF)
    return DiffusersEngine(mode, **kw)


def names(calls):
    return [c[0] for c in calls]


def gen(eng, steps=4, cancel=lambda: False, log=None):
    log = log if log is not None else []
    return eng.generate("p", 7, steps, 64, 48, lambda *a: log.append(a), cancel)


def test_import_without_torch():
    code = ("import sys; sys.modules['torch']=None; sys.modules['diffusers']=None; "
            "import medimg.engines.diffusers_engine as m; print(m.OFFLOAD_MODES)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_bad_mode():
    with pytest.raises(ValueError):
        DiffusersEngine("nope")


def test_generate_before_load():
    with pytest.raises(RuntimeError, match="engine not loaded"):
        DiffusersEngine("resident").generate("p", 1, 2, 64, 64, lambda *a: None, lambda: False)


@pytest.mark.parametrize("mode,expected", [
    ("resident", "to"),
    ("model_cpu_offload", "enable_model_cpu_offload"),
    ("gguf_q8_offload", "enable_model_cpu_offload"),
    ("gguf_q4_sequential", "enable_sequential_cpu_offload"),
])
def test_load_per_mode(fake_diffusers, mode, expected):
    eng = mk(mode)
    eng.load()
    assert eng.loaded
    placement = {"to", "enable_model_cpu_offload", "enable_sequential_cpu_offload"}
    assert [n for n in names(fake_diffusers) if n in placement] == [expected]
    if expected == "to":
        assert dict(fake_diffusers)["to"]["args"] == ("cuda",)
    assert ("set_progress_bar_config", {"disable": True}) in fake_diffusers
    fp = [c for c in fake_diffusers if c[0] == "from_pretrained"][0][1]
    assert fp["args"] == ("Tongyi-MAI/Z-Image-Turbo",)
    assert fp["torch_dtype"] == "bfloat16"
    from medimg import config as _cfg
    assert fp["revision"] == _cfg.DIFFUSERS_MODEL_REVISION
    assert "low_cpu_mem_usage" not in fp
    if mode.startswith("gguf"):
        sf = [c for c in fake_diffusers if c[0] == "from_single_file"][0][1]
        assert sf["args"] == (str(GGUF),)
        assert sf["config"] == "Tongyi-MAI/Z-Image-Turbo"
        assert sf["subfolder"] == "transformer"
        assert sf["revision"] == _cfg.DIFFUSERS_MODEL_REVISION
        assert sf["torch_dtype"] == "bfloat16"
        assert sf["quantization_config"].kw == {"compute_dtype": "bfloat16"}
        assert "transformer" in fp
        assert names(fake_diffusers).index("from_single_file") < names(fake_diffusers).index("from_pretrained")
    else:
        assert "transformer" not in fp
        assert "from_single_file" not in names(fake_diffusers)


def test_load_idempotent(fake_diffusers):
    eng = mk("resident")
    eng.load()
    eng.load()
    assert names(fake_diffusers).count("from_pretrained") == 1


def test_unload_twice(fake_diffusers):
    eng = mk("resident")
    eng.load()
    eng.unload()
    assert not eng.loaded
    eng.unload()
    with pytest.raises(RuntimeError, match="engine not loaded"):
        gen(eng)


@pytest.mark.parametrize("mode", OFFLOAD_MODES)
def test_generate_contract(fake_diffusers, mode):
    eng = mk(mode)
    eng.load()
    log = []
    res = gen(eng, steps=4, log=log)
    call = [c for c in fake_diffusers if c[0] == "__call__"][0][1]
    assert call["guidance_scale"] == 0.0
    assert call["num_inference_steps"] == 4
    assert (call["height"], call["width"]) == (48, 64)
    assert call["prompt"] == "p"
    assert call["generator"].seed == 7 and call["generator"].device == "cuda"
    assert call["callback_on_step_end_tensor_inputs"] == ["latents"]
    assert callable(call["callback_on_step_end"])
    assert "negative_prompt" not in call and "low_cpu_mem_usage" not in call
    assert log[0] == ("encoding", 0, 0)
    assert [l for l in log if l[0] == "denoising"] == [("denoising", k, 4) for k in range(1, 5)]
    assert log.count(("decoding", 4, 4)) == 1 and log[-1] == ("decoding", 4, 4)
    assert res.engine == "diffusers 0.41.0"
    assert res.peak_mem_gb == pytest.approx(12.0)
    assert res.steps == 4 and res.seed == 7 and res.model_id == "Tongyi-MAI/Z-Image-Turbo"
    assert res.image.size[0] > 0
    n = names(fake_diffusers)
    assert n.index("reset_peak_memory_stats") < n.index("__call__")
    assert "empty_cache" in n[n.index("__call__"):]


def test_cancel(fake_diffusers):
    eng = mk("resident")
    eng.load()
    polls = []

    def cancel():
        polls.append(1)
        return len(polls) >= 2

    log = []
    with pytest.raises(Cancelled):
        gen(eng, steps=6, cancel=cancel, log=log)
    assert eng._pipe._interrupt is True
    assert len(polls) == 2
    assert [l for l in log if l[0] == "denoising"][-1] == ("denoising", 2, 6)
    n = names(fake_diffusers)
    assert "empty_cache" in n[n.index("__call__"):]


def test_empty_cache_on_error(fake_diffusers):
    eng = mk("resident")
    eng.load()

    def boom(*a, **k):
        raise ValueError("boom")

    eng._pipe.__class__.__call__, orig = boom, eng._pipe.__class__.__call__
    try:
        with pytest.raises(ValueError):
            gen(eng)
    finally:
        eng._pipe.__class__.__call__ = orig
    assert names(fake_diffusers)[-1] == "empty_cache"


def test_callback_returns_dict_even_on_cancel(fake_diffusers):
    eng = mk("resident")
    eng.load()
    with pytest.raises(Cancelled):
        gen(eng, steps=2, cancel=lambda: True)
