import glob
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil
import pytest

from medimg.engines.base import GenResult
from medimg.engines.sdcpp_engine import SdcppEngine, build_argv
from medimg.errors import Cancelled, Invalid, ModelUnavailable
from medimg.sdcpp.install import SdcppPaths
from medimg.sdcpp.progress import NO_BINARY_CAUSE, NO_BINARY_FIX

STUB = Path(__file__).parent / "stubs" / "fake_sd_cli.py"


def fake_paths(tmp_path) -> SdcppPaths:
    d = tmp_path / "models"
    d.mkdir(exist_ok=True)
    files = []
    for n in ("z_image_turbo-Q3_K.gguf", "qwen3-q3.gguf", "ae.safetensors"):
        (d / n).write_bytes(b"x")
        files.append(d / n)
    return SdcppPaths(sd_cli=(sys.executable, "-I", str(STUB)), cwd=tmp_path,
                      diffusion=files[0], llm=files[1], vae=files[2],
                      build="mac-arm64", tier="mid")


@pytest.fixture(autouse=True)
def _private_tempdir(tmp_path, monkeypatch):
    d = tmp_path / "systmp"
    d.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(d))


def temp_dirs():
    return set(glob.glob(str(Path(tempfile.gettempdir()) / "medimg-sdcpp-*")))


def run(eng, steps=4, w=64, h=48, should_cancel=lambda: False, events=None):
    ev = events if events is not None else []
    res = eng.generate("a calm clinic", 7, steps, w, h, lambda *a: ev.append(a), should_cancel)
    return res, ev


def test_build_argv_exact(tmp_path):
    p = fake_paths(tmp_path)
    out = tmp_path / "o.png"
    assert build_argv(p, "vulkan0", "hi", 5, 8, 512, 768, out) == [
        *p.sd_cli, "--diffusion-model", str(p.diffusion), "--llm", str(p.llm), "--vae", str(p.vae),
        "-p", "hi", "--cfg-scale", "1.0", "--steps", "8", "-W", "512", "-H", "768",
        "-s", "5", "-o", str(out), "--backend", "vulkan0",
        "--offload-to-cpu", "--mmap", "--vae-tiling", "--log-level", "info"]
    assert build_argv(p, "cpu", "hi", 5, 8, 512, 512, out, threads=4)[-2:] == ["--threads", "4"]
    assert "--threads" not in build_argv(p, "cpu", "hi", 5, 8, 512, 512, out, threads=None)
    a = build_argv(p, "cpu", "-dash", 5, 8, 512, 512, out)
    assert a[a.index("-p") + 1] == " -dash"


def test_import_is_light():
    code = ("import sys, medimg.engines.sdcpp_engine; "
            "bad=[m for m in ('torch','mflux','diffusers','mlx') if m in sys.modules]; "
            "sys.exit(1 if bad else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_generate_before_load(tmp_path):
    with pytest.raises(RuntimeError, match="engine not loaded"):
        SdcppEngine(fake_paths(tmp_path)).generate("p", 1, 1, 8, 8, lambda *a: None, lambda: False)


def test_load_missing_file(tmp_path):
    p = fake_paths(tmp_path)
    p.llm.unlink()
    with pytest.raises(ModelUnavailable) as e:
        SdcppEngine(p).load()
    assert "setup" in e.value.fix.lower()


def test_happy_path(tmp_path):
    before = temp_dirs()
    eng = SdcppEngine(fake_paths(tmp_path), "cpu")
    ld = []
    eng.load(lambda *a: ld.append(a))
    assert ld == [("loading", 0, 0), ("loading", 1, 1)]
    res, ev = run(eng, steps=4)
    assert isinstance(res, GenResult)
    assert ev[0] == ("encoding", 0, 0)
    assert ev[1:5] == [("denoising", k, 4) for k in (1, 2, 3, 4)]
    assert ev[-1] == ("decoding", 4, 4)
    assert res.image.size == (64, 48) and res.seed == 7 and res.steps == 4
    assert res.engine == "sdcpp master-1015-e41fbcf"
    assert res.model_id.endswith("z_image_turbo-Q3_K.gguf")
    assert res.peak_mem_gb > 0
    assert temp_dirs() == before


def test_cancel_kills_child(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SD_CLI_HANG", "1")
    before = temp_dirs()
    pids = []
    from medimg.sdcpp.procs import popen_group

    def spy(argv, cwd, env=None):
        p = popen_group(argv, cwd, env=env)
        pids.append(p.pid)
        return p

    eng = SdcppEngine(fake_paths(tmp_path), "cpu", popen=spy, poll_s=0.05)
    eng.load()
    seen = []
    t0 = time.time()
    with pytest.raises(Cancelled):
        run(eng, should_cancel=lambda: any(e[0] == "denoising" for e in seen), events=seen)
    assert time.time() - t0 < 5
    assert pids and not psutil.pid_exists(pids[0])
    assert temp_dirs() == before


def test_gpu_oom_falls_back_to_cpu(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SD_CLI_FAIL", "gpu_oom")
    eng = SdcppEngine(fake_paths(tmp_path), "vulkan0")
    eng.load()
    res, ev = run(eng)
    assert res.engine.endswith("(cpu, fallback)")
    assert eng.device == "cpu"
    assert "graphics chip ran out of memory" in eng.notes[-1]
    assert [e for e in ev if e[0] == "encoding"] == [("encoding", 0, 0)] * 2


def test_unknown_gpu_failure_falls_back_to_cpu(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SD_CLI_FAIL", "no_device")
    eng = SdcppEngine(fake_paths(tmp_path), "vulkan0")
    eng.load()
    res, _ = run(eng)
    assert eng.device == "cpu"
    assert res.engine.endswith("(cpu, fallback)")
    assert "could not be used" in eng.notes[-1]


def test_gpu_oom_env_on_cpu_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SD_CLI_FAIL", "gpu_oom")
    eng = SdcppEngine(fake_paths(tmp_path), "cpu")
    eng.load()
    res, _ = run(eng)
    assert res.engine == "sdcpp master-1015-e41fbcf" and eng.notes == []


def test_ram_oom_text(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SD_CLI_FAIL", "ram_oom")
    eng = SdcppEngine(fake_paths(tmp_path), "cpu")
    eng.load()
    with pytest.raises(Invalid) as e:
        run(eng)
    assert e.value.cause == "The computer ran out of memory while making the image."
    assert e.value.fix == ("Close other programs (browser, Teams), pick the 512x512 draft size, "
                           "then try again.")


def test_no_model_text(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SD_CLI_FAIL", "no_model")
    eng = SdcppEngine(fake_paths(tmp_path), "cpu")
    eng.load()
    with pytest.raises(ModelUnavailable) as e:
        run(eng)
    assert e.value.cause == "A model file is missing or damaged."
    assert e.value.fix == "Run setup again; it re-downloads only what is missing."


def test_missing_binary(tmp_path):
    p = fake_paths(tmp_path)
    p.sd_cli = (str(tmp_path / "nope" / "sd-cli"),)
    eng = SdcppEngine(p, "cpu")
    eng.load()
    before = temp_dirs()
    with pytest.raises(ModelUnavailable) as e:
        run(eng)
    assert e.value.cause == NO_BINARY_CAUSE and e.value.fix == NO_BINARY_FIX
    assert temp_dirs() == before


def test_bad_flags_guard_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SD_CLI_BAD_FLAGS", "1")
    eng = SdcppEngine(fake_paths(tmp_path), "cpu", threads=2)
    eng.load()
    res, _ = run(eng)
    assert res.image.size == (64, 48)


def test_count_file(tmp_path, monkeypatch):
    cf = tmp_path / "count.txt"
    monkeypatch.setenv("FAKE_SD_CLI_COUNT_FILE", str(cf))
    eng = SdcppEngine(fake_paths(tmp_path), "cpu")
    eng.load()
    run(eng)
    assert len(cf.read_text().splitlines()) == 1


def test_make_engine_sdcpp(tmp_path, monkeypatch):
    from medimg import config
    from medimg.engines import make_engine
    from medimg.sdcpp import install
    paths = fake_paths(tmp_path)
    calls = []
    monkeypatch.setattr(install, "resolve_paths", lambda b, t: calls.append((b, t)) or paths)
    monkeypatch.setattr(config, "load_settings", lambda *a, **k: config.Settings())
    prof = {"backend": {"device": "vulkan0", "sdcpp": {"tier": "low", "build": "win-vulkan-x64"}},
            "machine": {"ram_total_gb": 32}}
    eng = make_engine("sdcpp", prof)
    assert calls == [("win-vulkan-x64", "low")]
    assert eng.device == "vulkan0" and eng.threads is None

    calls.clear()
    monkeypatch.setattr(install, "chosen_build", lambda o, a: "linux-cpu-x64")
    monkeypatch.setattr(config, "load_settings", lambda *a, **k: config.Settings(
        sdcpp_device="cpu", sdcpp_threads=3))
    eng = make_engine("sdcpp", {"backend": {"device": "vulkan0"}, "machine": {"ram_total_gb": 16}})
    assert calls == [("linux-cpu-x64", "mid")]
    assert eng.device == "cpu" and eng.threads == 3

    monkeypatch.setattr(config, "load_settings", lambda *a, **k: config.Settings(sdcpp_tier="high"))
    make_engine("sdcpp", None)
    assert calls[-1][1] == "high"

    # settings override beats the tier recorded in the profile
    make_engine("sdcpp", {"backend": {"sdcpp": {"tier": "mid"}}})
    assert calls[-1][1] == "high"


def test_make_engine_sdcpp_no_build(monkeypatch):
    from medimg import config
    from medimg.engines import make_engine
    from medimg.sdcpp import install
    monkeypatch.setattr(config, "load_settings", lambda *a, **k: config.Settings())
    monkeypatch.setattr(install, "chosen_build", lambda o, a: None)
    with pytest.raises(ModelUnavailable):
        make_engine("sdcpp", {"backend": {}})


class _Stub:
    def start(self):
        pass

    def stop(self):
        return 0.0


class _FakeProc:
    def __init__(self, chunks):
        self.pid = 1
        self.returncode = 1
        outer = self
        self._chunks = list(chunks)

        class _Out:
            def read(self, n):
                return outer._chunks.pop(0) if outer._chunks else b""

            def close(self):
                pass
        self.stdout = _Out()

    def poll(self):
        return 1

    def wait(self, timeout=None):
        return 1


def test_utf8_split_across_chunks(tmp_path):
    chunks = [b"[E] cannot open 'C:\\Users\\Jos\xc3", b"\xa9\\m.gguf' --- x.cpp:1\n"]
    eng = SdcppEngine(fake_paths(tmp_path), "cpu",
                      popen=lambda argv, cwd, env=None: _FakeProc(chunks),
                      mem_sampler=lambda pid: _Stub())
    eng.load()
    with pytest.raises(Invalid) as e:
        run(eng)
    assert "José" in str(e.value) and "\ufffd" not in str(e.value)


def test_failure_details_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SD_CLI_FAIL", "ram_oom")
    eng = SdcppEngine(fake_paths(tmp_path), "cpu")
    eng.load()
    with pytest.raises(Invalid) as e:
        run(eng)
    assert eng.last_failure["class"] == "ram_oom"
    assert e.value.failure_class == "ram_oom"
    assert any("bad_alloc" in ln for ln in eng.last_log_tail)


def test_gpu_fallback_keeps_last_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SD_CLI_FAIL", "gpu_oom")
    eng = SdcppEngine(fake_paths(tmp_path), "vulkan0")
    eng.load()
    res, _ = run(eng)
    assert res.image is not None
    assert eng.last_failure["class"] == "gpu_oom"
    assert eng.device == "cpu"


def test_last_phases_on_success(tmp_path):
    eng = SdcppEngine(fake_paths(tmp_path), "cpu")
    eng.load()
    run(eng)
    assert isinstance(eng.last_phases, dict)
    assert eng.last_log_tail
    assert eng.last_failure is None


def test_make_engine_tier_kwarg_beats_settings(tmp_path, monkeypatch):
    from medimg import config
    from medimg.engines import make_engine
    from medimg.sdcpp import install
    calls = []
    monkeypatch.setattr(install, "resolve_paths",
                        lambda b, t: calls.append((b, t)) or fake_paths(tmp_path))
    monkeypatch.setattr(config, "load_settings", lambda *a, **k: config.Settings(sdcpp_tier="high"))
    make_engine("sdcpp", {"backend": {"sdcpp": {"build": "linux-cpu-x64"}}}, tier="low")
    assert calls[-1][1] == "low"
