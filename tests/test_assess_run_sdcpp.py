"""assess.run() for the sdcpp backend: device choice, Vulkan try with CPU fallback, profile keys."""
from __future__ import annotations

import json
import types

import pytest

import medimg.assess as assess
import medimg.engines as engines
from medimg import config
from medimg.assess import Decision, Machine, build_profile, render_report
from medimg.sdcpp import install

MACHINE = Machine(hostname="h", os_name="Windows", os_version="11", cpu="i5-1135G7", apple_chip=None,
                  ram_total_gb=16.0, ram_free_gb=8.0,
                  gpu={"vendor": "intel", "name": "Iris Xe", "vram_gb": None, "driver": None, "cuda": None},
                  disk_free_gb=100.0, disk_path="C:/out", python="3.12", uv="0.11", arch="x86_64")


def decision(device="vulkan0", tier="mid"):
    return Decision("sdcpp", True, "r", "", None, False, config.SDCPP_MODEL_ID, 5.56, 10.56, device, tier)


class StubEngine:
    name = "sdcpp"

    def __init__(self, device, fail=False):
        self.device, self.fail, self.unloaded = device, fail, False

    def unload(self):
        self.unloaded = True


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / "device_profile.json"
    monkeypatch.setattr(assess, "PROFILE_PATH", path)
    monkeypatch.setattr(assess, "detect", lambda **kw: MACHINE)
    monkeypatch.setattr(config, "load_settings", lambda: config.Settings())
    monkeypatch.setattr(install, "chosen_build", lambda os_name, arch: "win-vulkan-x64")
    monkeypatch.setattr(install, "resolve_paths",
                        lambda build, tier: types.SimpleNamespace(sd_cli=("sd-cli",), cwd=tmp_path))
    ns = types.SimpleNamespace(path=path, made=[], bench_calls=[], devices=[("Vulkan0", "x"), ("CPU", "y")],
                               fail_devices=set(), sizes=[])

    def make(backend, profile, fake=False):
        dev = profile["backend"]["device"]
        ns.made.append((backend, dev, profile["backend"]["sdcpp"]))
        return StubEngine(dev)

    def bench(engine, *, sizes):
        ns.bench_calls.append(engine.device)
        ns.sizes.append(sizes)
        if engine.device in ns.fail_devices:
            raise RuntimeError("ErrorOutOfDeviceMemory")
        pt = {"width": 512, "height": 512, "steps": 4, "total_s": 100.0 if engine.device == "cpu" else 5.0,
              "per_step_s": 20.0, "overhead_s": 10.0}
        return {"measured_at": "t", "load_s": 1.0, "points": [pt], "fit": None, "device": engine.device}

    monkeypatch.setattr(engines, "make_engine", make)
    monkeypatch.setattr(assess, "benchmark", bench)
    monkeypatch.setattr(install, "list_devices", lambda sd_cli, cwd: ns.devices)
    ns.set_decision = lambda d: monkeypatch.setattr(assess, "decide", lambda m, **kw: d)
    ns.decide_kw = []
    monkeypatch.setattr(assess, "decide", lambda m, **kw: (ns.decide_kw.append(kw), decision())[1])
    return ns


def args(**kw):
    return types.SimpleNamespace(**{"no_benchmark": False, "json": True, "output_root": None, **kw})


def test_vulkan_failure_falls_back_to_cpu(env, capsys):
    env.fail_devices = {"vulkan0"}
    assert assess.run(args()) == 0
    saved = json.loads(env.path.read_text())
    assert env.bench_calls == ["vulkan0", "cpu"]
    b = saved["backend"]
    assert b["device"] == "cpu" and b["name"] == "sdcpp"
    assert b["sdcpp"]["vulkan_tried"] is True and b["sdcpp"]["vulkan_error"] == "ErrorOutOfDeviceMemory"
    assert b["sdcpp"]["tier"] == "mid" and b["sdcpp"]["build"] == "win-vulkan-x64"
    assert b["sdcpp"]["release"] == config.SDCPP_RELEASE_TAG
    assert b["engine_version"] == f"sdcpp {config.SDCPP_RELEASE_TAG}"
    assert any("Graphics chip benchmark failed on vulkan0: ErrorOutOfDeviceMemory; using the processor" in n
               for n in saved["notes"])
    assert saved["benchmark"]["points"][0]["total_s"] == 100.0       # points from the cpu run
    assert env.sizes == [assess.SDCPP_BENCH_SIZES] * 2
    assert assess.SDCPP_BENCH_SIZES == ((512, 512, 4), (768, 768, 2))
    assert [m[1] for m in env.made] == ["vulkan0", "cpu"]


def test_vulkan_success_keeps_device(env, capsys):
    assert assess.run(args()) == 0
    saved = json.loads(env.path.read_text())
    assert env.bench_calls == ["vulkan0"]
    assert saved["backend"]["device"] == "vulkan0" and saved["backend"]["sdcpp"]["vulkan_tried"] is True
    assert saved["backend"]["sdcpp"]["vulkan_error"] is None


def test_candidate_not_listed_goes_cpu_without_vulkan_attempt(env, capsys):
    env.devices = [("CPU", "y")]
    assert assess.run(args()) == 0
    saved = json.loads(env.path.read_text())
    assert env.bench_calls == ["cpu"]
    assert saved["backend"]["device"] == "cpu" and saved["backend"]["sdcpp"]["vulkan_tried"] is False
    assert saved["notes"]


def test_metal_matches_mtl_prefix(env, capsys):
    env.set_decision(decision("metal"))
    env.devices = [("MTL0", "Apple M2 Pro"), ("CPU", "x")]
    assess.run(args())
    assert env.bench_calls == ["metal"]
    assert json.loads(env.path.read_text())["backend"]["device"] == "metal"


def test_cpu_decision_never_lists_devices(env, monkeypatch, capsys):
    env.set_decision(decision("cpu", "low"))
    monkeypatch.setattr(install, "list_devices", lambda *a: pytest.fail("listed"))
    assess.run(args())
    assert env.bench_calls == ["cpu"]


def test_no_benchmark_skips_everything(env, capsys):
    assess.run(args(no_benchmark=True))
    saved = json.loads(env.path.read_text())
    assert env.bench_calls == [] and env.made == []
    assert saved["benchmark"] is None and saved["backend"]["device"] == "vulkan0"
    assert saved["backend"]["sdcpp"]["tier"] == "mid"


def test_settings_device_override(env, monkeypatch, capsys):
    monkeypatch.setattr(config, "load_settings", lambda: config.Settings(sdcpp_device="cpu"))
    assess.run(args())
    assert env.bench_calls == ["cpu"]


def test_engine_arg_none_falls_back_to_settings(env, monkeypatch, capsys):
    monkeypatch.setattr(config, "load_settings", lambda: config.Settings(engine="sdcpp"))
    assess.run(args(no_benchmark=True))
    assert env.decide_kw[-1] == {"engine": "sdcpp"}
    monkeypatch.setattr(config, "load_settings", lambda: config.Settings())
    assess.run(args(no_benchmark=True))
    assert env.decide_kw[-1] == {"engine": None}
    assess.run(args(no_benchmark=True, engine="auto"))
    assert env.decide_kw[-1] == {"engine": None}
    assess.run(args(no_benchmark=True, engine="sdcpp"))
    assert env.decide_kw[-1] == {"engine": "sdcpp"}


def test_keeps_previous_benchmark_only_when_device_and_tier_match(env, capsys):
    first = build_profile(MACHINE, decision("cpu", "mid"), {"measured_at": "old", "load_s": 1, "points": [],
                                                           "fit": None},
                          device="cpu", sdcpp={"release": "r", "build": "b", "tier": "mid",
                                               "vulkan_tried": False, "vulkan_error": None})
    assess.save_profile(first, env.path)
    env.set_decision(decision("cpu", "mid"))
    assess.run(args(no_benchmark=True))
    assert json.loads(env.path.read_text())["benchmark"]["measured_at"] == "old"
    env.set_decision(decision("cpu", "low"))
    assess.run(args(no_benchmark=True))
    assert json.loads(env.path.read_text())["benchmark"] is None


def test_build_profile_writes_new_keys_and_report():
    sd = {"release": "master-1015-e41fbcf", "build": "win-cpu-x64", "tier": "mid",
          "vulkan_tried": True, "vulkan_error": "oom"}
    p = build_profile(MACHINE, decision("cpu"), None, device="cpu", sdcpp=sd,
                      notes=["Graphics chip benchmark failed on vulkan0: oom; using the processor"],
                      engine_version="sdcpp master-1015-e41fbcf")
    assert p["backend"]["device"] == "cpu" and p["backend"]["sdcpp"] == sd and p["schema_version"] == 1
    text = render_report(p)
    assert "Backend sdcpp on cpu (tier mid: Q3_K image model)" in text
    assert "Graphics chip benchmark failed" in text
    p2 = build_profile(MACHINE, decision("cpu", "low"), None, device="cpu",
                       sdcpp={**sd, "tier": "low"})
    assert "tier low: Q2_K image model" in render_report(p2)
    other = build_profile(MACHINE, Decision("mflux", True, "r", "", None, True, "m", 1.0, 2.0), None)
    assert other["backend"]["device"] is None and other["backend"]["sdcpp"] is None


def test_real_engine_silent_fallback_is_detected(env, monkeypatch, tmp_path):
    """SdcppEngine retries gpu_oom on the CPU itself; assess must still record the Vulkan failure."""
    import sys
    from pathlib import Path
    from medimg.assess.bench import benchmark as real_bench
    from medimg.engines.sdcpp_engine import SdcppEngine
    from medimg.sdcpp.install import SdcppPaths
    stub = Path(__file__).parent / "stubs" / "fake_sd_cli.py"
    files = []
    for n in ("d.gguf", "l.gguf", "v.safetensors"):
        (tmp_path / n).write_bytes(b"x")
        files.append(tmp_path / n)
    paths = SdcppPaths(sd_cli=(sys.executable, "-I", str(stub)), cwd=tmp_path,
                       diffusion=files[0], llm=files[1], vae=files[2],
                       build="win-vulkan-x64", tier="mid")
    monkeypatch.setenv("FAKE_SD_CLI_FAIL", "gpu_oom")
    monkeypatch.setattr(assess, "benchmark", real_bench)
    monkeypatch.setattr(engines, "make_engine",
                        lambda backend, profile, fake=False: SdcppEngine(paths, profile["backend"]["device"]))
    assess.run(args())
    saved = json.loads(env.path.read_text())
    assert saved["backend"]["device"] == "cpu"
    assert saved["backend"]["sdcpp"]["vulkan_error"]
