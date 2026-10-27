import json
import re
import sys
import time
from argparse import Namespace
from pathlib import Path

import pytest

from medimg import config, download, osutil, selftest
from medimg.assess.decide import Decision
from medimg.assess.detect import Machine
from medimg.engines.base import GenResult
from medimg.engines.sdcpp_engine import SdcppEngine
from medimg.sdcpp import install, procs
from medimg.sdcpp.install import SdcppPaths

STUB = Path(__file__).parent / "stubs" / "fake_sd_cli.py"

TOP_KEYS = {"schema", "app_version", "git_commit", "started_at", "finished_at", "host", "command",
            "options", "machine", "decision", "profile_summary", "notes", "runs", "summary",
            "report_txt", "report_json"}
RUN_KEYS = {"index", "label", "engine", "tier", "build", "model_id", "device_requested",
            "device_used", "fell_back", "width", "height", "steps", "seed", "status",
            "failure_class", "cause", "fix", "load_s", "total_s", "per_step_s", "per_step_source",
            "phases", "peak_mem_gb", "ram_free_gb_before", "ram_free_gb_after", "image_path",
            "log_tail", "notes"}


def machine(os_name="Linux", arch="x86_64") -> Machine:
    return Machine(hostname="TEST BOX", os_name=os_name, os_version="6", cpu="Test CPU",
                   apple_chip=None, ram_total_gb=16.0, ram_free_gb=8.0, gpu=None,
                   disk_free_gb=100.0, disk_path="/", python="3.12", uv=None, arch=arch)


def decision(backend="sdcpp", device="cpu", tier="low", supported=True):
    return Decision(backend, supported, "r", "f", None, False, None, None, None, device, tier,
                    "ok" if supported else "no_build")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(selftest, "detect", lambda: machine())
    monkeypatch.setattr(selftest, "load_profile", lambda *a, **k: None)
    monkeypatch.setattr(selftest, "decide", lambda *a, **k: decision())
    monkeypatch.setattr(selftest, "GRACE_S", 1)
    calls = []
    monkeypatch.setattr(osutil, "open_folder", lambda p: calls.append(p) or True)
    return calls


def fake_paths(tmp_path) -> SdcppPaths:
    d = tmp_path / "models"
    d.mkdir(exist_ok=True)
    files = []
    for n in ("d.gguf", "l.gguf", "ae.safetensors"):
        (d / n).write_bytes(b"x")
        files.append(d / n)
    return SdcppPaths(sd_cli=(sys.executable, "-I", str(STUB)), cwd=tmp_path, diffusion=files[0],
                      llm=files[1], vae=files[2], build="mac-arm64", tier="mid")


def sd_cand(device="cpu", ready=True):
    return selftest.Candidate("sdcpp", "mid", device, "mac-arm64", None, ready,
                              None if ready else "not here. Run setup first.",
                              f"sd.cpp, tier mid, {device}")


def use(monkeypatch, tmp_path, cands, factory=None):
    monkeypatch.setattr(selftest, "plan_candidates", lambda *a, **k: cands)
    if factory is None:
        factory = lambda c: SdcppEngine(fake_paths(tmp_path), c.device or "cpu", poll_s=0.05)  # noqa: E731
    monkeypatch.setattr(selftest, "_engine_factory", factory)


def args(tmp_path, **kw):
    base = dict(no_open=True, output_root=str(tmp_path / "out"), size="256x256", steps=3,
                timeout=60)
    base.update(kw)
    return Namespace(**base)


def load_json(tmp_path):
    files = list((tmp_path / "out" / "_selftest").glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_fake_engine_end_to_end(tmp_path, capsys):
    rc = selftest.run(args(tmp_path, fake_engine=True))
    assert rc == 0
    d = tmp_path / "out" / "_selftest"
    txt = list(d.glob("selftest_TEST BOX_*.txt"))
    assert len(txt) == 1 and re.fullmatch(r"selftest_TEST BOX_\d{8}-\d{6}\.txt", txt[0].name)
    rep = load_json(tmp_path)
    assert set(rep) == TOP_KEYS
    assert rep["schema"] == "medimg-selftest/1"
    assert len(rep["runs"]) == 1 and set(rep["runs"][0]) == RUN_KEYS
    r = rep["runs"][0]
    assert r["status"] == "ok" and Path(r["image_path"]).is_file()
    assert re.fullmatch(r"selftest_TEST BOX_\d{8}-\d{6}_1_fake\.png", Path(r["image_path"]).name)
    out = capsys.readouterr().out
    assert "Test 1 of 1:" in out and "  step 3/3" in out and str(txt[0]) in out


def test_sdcpp_with_fake_sd_cli(tmp_path, monkeypatch):
    use(monkeypatch, tmp_path, [sd_cand()])
    assert selftest.run(args(tmp_path)) == 0
    r = load_json(tmp_path)["runs"][0]
    assert r["status"] == "ok" and r["device_used"] == "cpu" and r["per_step_s"] > 0
    assert r["per_step_source"] == "engine" and r["phases"]["sample_s"] > 0


def test_gpu_fallback_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SD_CLI_FAIL", "gpu_oom")
    use(monkeypatch, tmp_path, [sd_cand("vulkan0")])
    assert selftest.run(args(tmp_path)) == 0
    r = load_json(tmp_path)["runs"][0]
    assert r["status"] == "ok" and r["fell_back"] is True and r["device_used"] == "cpu"
    assert r["notes"] and r["device_requested"] == "vulkan0"


def test_timeout_kills_sd_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SD_CLI_HANG", "1")
    use(monkeypatch, tmp_path, [sd_cand()])
    t0 = time.monotonic()
    rc = selftest.run(args(tmp_path, timeout=2))
    assert time.monotonic() - t0 < 20 and rc == 1
    r = load_json(tmp_path)["runs"][0]
    assert r["status"] == "timeout" and r["failure_class"] == "timeout"
    assert all(p.poll() is not None for p in list(procs._LIVE))


def test_failure_classified(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SD_CLI_FAIL", "ram_oom")
    use(monkeypatch, tmp_path, [sd_cand()])
    assert selftest.run(args(tmp_path)) == 1
    r = load_json(tmp_path)["runs"][0]
    assert r["status"] == "failed" and r["failure_class"] == "ram_oom"
    assert any("bad_alloc" in ln for ln in r["log_tail"]) and r["fix"]


def test_blocked_prompt_never_builds_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(selftest, "SELFTEST_PROMPT", "photo of a 12-year-old child")

    def boom(c):
        pytest.fail("engine must not be built")
    use(monkeypatch, tmp_path, [sd_cand(), sd_cand("vulkan0")], boom)
    assert selftest.run(args(tmp_path)) == 1
    runs = load_json(tmp_path)["runs"]
    assert [r["status"] for r in runs] == ["blocked", "blocked"]


def test_nothing_installed_exit_2(tmp_path, monkeypatch, capsys):
    use(monkeypatch, tmp_path, [sd_cand(ready=False)])
    assert selftest.run(args(tmp_path)) == 2
    assert "Run setup first" in capsys.readouterr().out
    r = load_json(tmp_path)["runs"][0]
    assert r["status"] == "skipped" and r["failure_class"] == "not_installed"


def test_plan_candidates(monkeypatch):
    settings = config.Settings()
    # Linux aarch64: no sd.cpp program
    monkeypatch.setattr(install, "chosen_build", lambda o, a, *x: None)
    monkeypatch.setattr(selftest, "decide", lambda *a, **k: decision(supported=False))
    got = selftest.plan_candidates(machine(arch="aarch64"), settings, None)
    assert not [c for c in got if c.engine == "sdcpp"]
    assert any("no stable-diffusion.cpp program" in n for n in got.notes)

    # quick / all_tiers
    monkeypatch.setattr(install, "chosen_build", lambda o, a, *x: "linux-cpu-x64")
    monkeypatch.setattr(install, "binary_cached", lambda b, *x: Path("/x/sd-cli"))
    monkeypatch.setattr(download, "sdcpp_cached", lambda t, b=None: t in ("mid", "high"))
    monkeypatch.setattr(selftest, "decide",
                        lambda m, engine=None, tier=None: decision(tier=tier or "low"))
    allc = selftest.plan_candidates(machine(), settings, None, all_tiers=True)
    assert [(c.tier, c.ready) for c in allc] == [("low", False), ("mid", True), ("high", True)]
    assert "Run setup first" in allc[0].skip_reason
    q = selftest.plan_candidates(machine(), settings, None, all_tiers=True, quick=True)
    assert [c.tier for c in q] == ["mid"]

    # failed device is never chosen
    monkeypatch.setattr(selftest, "decide",
                        lambda m, engine=None, tier=None: decision(device="vulkan0", tier="mid"))
    prof = {"backend": {"name": "sdcpp", "device": "vulkan0",
                        "sdcpp": {"tier": "mid", "build": "linux-cpu-x64", "device_proven": False,
                                  "failed_devices": ["vulkan0"]}}}
    got = selftest.plan_candidates(machine(), settings, prof, engine="sdcpp", tier="mid")
    assert [c.device for c in got] == ["cpu"]

    # engine filter
    monkeypatch.setattr(selftest, "decide",
                        lambda m, engine=None, tier=None: decision("mflux") if engine is None
                        else decision(tier="mid"))
    monkeypatch.setattr(selftest, "_native_candidate",
                        lambda d: selftest.Candidate("mflux", None, None, None, None, True, None, "m"))
    both = selftest.plan_candidates(machine("Darwin", "arm64"), settings, None, tier="mid")
    assert {c.engine for c in both} == {"mflux", "sdcpp"} and both[0].engine == "mflux"
    only = selftest.plan_candidates(machine("Darwin", "arm64"), settings, None, engine="sdcpp",
                                    tier="mid")
    assert {c.engine for c in only} == {"sdcpp"}


class StuckEngine:
    name = "mflux"
    model_id = "stuck"
    loaded = False

    def load(self, on_progress=None):
        self.loaded = True

    def unload(self):
        self.loaded = False

    def generate(self, prompt, seed, steps, width, height, on_progress, should_cancel):
        time.sleep(4)  # ignores cancel
        raise RuntimeError("late")


def test_in_process_timeout_hard_exit(tmp_path, monkeypatch):
    cands = [selftest.Candidate("mflux", None, None, None, None, True, None, "stuck one"),
             selftest.Candidate("diffusers", None, None, None, None, True, None, "second")]
    use(monkeypatch, tmp_path, cands, lambda c: StuckEngine())
    monkeypatch.setattr(selftest, "GRACE_S", 0.3)
    codes = []
    monkeypatch.setattr(selftest, "_hard_exit", codes.append)
    rc = selftest.run(args(tmp_path, timeout=0.3))
    assert codes == [1] and rc == 1
    runs = load_json(tmp_path)["runs"]
    assert runs[0]["status"] == "timeout" and runs[0]["failure_class"] == "timeout"
    assert runs[1]["status"] == "skipped" and "did not stop" in runs[1]["cause"]


def test_no_download_functions_called(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("download attempted")
    monkeypatch.setattr(install, "install_binary", boom)
    monkeypatch.setattr(install, "download_models", boom)
    monkeypatch.setattr(download, "download_sdcpp", boom)
    monkeypatch.setattr(download, "download_mflux", boom)
    assert selftest.run(args(tmp_path, fake_engine=True)) == 0
    use(monkeypatch, tmp_path, [sd_cand()])
    assert selftest.run(args(tmp_path)) == 0


def test_open_folder_respects_flags(tmp_path, monkeypatch, env):
    calls = env
    selftest.run(args(tmp_path, fake_engine=True, no_open=True))
    assert calls == []
    monkeypatch.setenv("CI", "1")
    selftest.run(args(tmp_path, fake_engine=True, no_open=False))
    assert calls == []
    monkeypatch.delenv("CI")
    selftest.run(args(tmp_path, fake_engine=True, no_open=False))
    assert calls == [tmp_path / "out" / "_selftest"]


def test_text_report_plain(tmp_path, capsys):
    selftest.run(args(tmp_path, fake_engine=True))
    out = capsys.readouterr().out
    assert "SELF-TEST REPORT" in out and "Result" in out and "Send both report files" in out
    txt = next((tmp_path / "out" / "_selftest").glob("*.txt")).read_text(encoding="utf-8")
    assert "SELF-TEST REPORT" in txt and "PASS" in txt


def test_git_commit_reads_files(tmp_path):
    g = tmp_path / ".git"
    (g / "refs" / "heads").mkdir(parents=True)
    (g / "HEAD").write_text("ref: refs/heads/main\n")
    assert selftest.git_commit(tmp_path) is None
    (g / "packed-refs").write_text("# x\n" + "a" * 40 + " refs/heads/main\n")
    assert selftest.git_commit(tmp_path) == "a" * 40
    (g / "refs" / "heads" / "main").write_text("b" * 40 + "\n")
    assert selftest.git_commit(tmp_path) == "b" * 40
