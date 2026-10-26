"""device_profile.json schema v1, report, and the assess CLI entry."""
from __future__ import annotations

import json
import types

import pytest

import medimg.assess as assess
from medimg.assess import (Decision, Machine, build_profile, fit, load_profile, record_actual,
                           render_report, save_profile)

P1 = {"width": 512, "height": 512, "steps": 4, "total_s": 30.2, "per_step_s": 5.5, "overhead_s": 8.2}
P2 = {"width": 1024, "height": 1024, "steps": 2, "total_s": 62.0, "per_step_s": 23.0, "overhead_s": 16.0}

MACHINE = Machine(hostname="h", os_name="Darwin", os_version="27.0.0", cpu="Apple M2 Pro",
                  apple_chip="Apple M2 Pro", ram_total_gb=16.0, ram_free_gb=3.2,
                  gpu={"vendor": "apple", "name": "Apple M2 Pro", "vram_gb": None, "driver": None, "cuda": None},
                  disk_free_gb=27.1, disk_path="/tmp/out", python="3.12.13", uv="0.11.29", arch="arm64")
DECISION = Decision("mflux", True, "Apple silicon with 16 GB", "", None, True,
                    "filipstrand/Z-Image-Turbo-mflux-4bit", 5.9, 10.9)
BENCH = {"measured_at": "2026-10-26T12:00:00+01:00", "load_s": 8.1, "points": [P1, P2], "fit": fit([P1, P2])}


def test_profile_has_schema_v1_keys():
    p = build_profile(MACHINE, DECISION, BENCH, engine_version="mflux 0.22.0")
    assert list(p) == ["schema_version", "created_at", "app_version", "machine", "backend",
                       "benchmark", "actuals", "notes"]
    assert p["schema_version"] == 1 and p["app_version"] == "0.1.0"
    assert set(p["machine"]) == {"hostname", "os_name", "os_version", "cpu", "apple_chip", "ram_total_gb",
                                 "ram_free_gb", "gpu", "disk_free_gb", "disk_path", "python", "uv", "arch"}
    assert set(p["machine"]["gpu"]) == {"vendor", "name", "vram_gb", "driver", "cuda"}
    assert set(p["backend"]) == {"name", "supported", "reason", "fix", "model_id", "offload_mode",
                                 "unload_after_job", "engine_version"}
    assert set(p["benchmark"]) == {"measured_at", "load_s", "points", "fit"}
    assert p["actuals"] == [] and p["notes"] == []
    json.dumps(p)  # serialisable


def test_save_load_roundtrip_atomic(tmp_path):
    path = tmp_path / "sub" / "device_profile.json"
    p = build_profile(MACHINE, DECISION, BENCH)
    save_profile(p, path)
    assert load_profile(path) == p
    assert [f.name for f in path.parent.iterdir()] == ["device_profile.json"]   # no temp files left
    record_actual(p, 768, 1344, 9, 231.0)
    save_profile(p, path)
    assert load_profile(path)["actuals"][0]["time_s"] == 231.0


def test_load_profile_missing_or_corrupt(tmp_path):
    assert load_profile(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_profile(bad) is None
    bad.write_text(json.dumps({"schema_version": 99}))
    assert load_profile(bad) is None


def test_render_report_contains_estimates_table():
    text = render_report(build_profile(MACHINE, DECISION, BENCH))
    for needle in ("Apple M2 Pro", "mflux", "10 images", "25 images", "50 images",
                   "1024x1024", "768x1344 portrait", "9 steps"):
        assert needle in text
    assert "NO" not in text.split("Supported:")[1].splitlines()[0]


def test_render_report_unsupported_and_no_benchmark():
    d = Decision(None, False, "No NVIDIA GPU found.", "Use a PC with an NVIDIA GPU.", None, False, None, None, None)
    text = render_report(build_profile(MACHINE, d, None))
    assert "Supported: NO" in text and "No NVIDIA GPU found." in text and "Fix" in text
    text = render_report(build_profile(MACHINE, DECISION, None))
    assert "No time estimates yet" in text


@pytest.fixture
def patched(tmp_path, monkeypatch):
    path = tmp_path / "device_profile.json"
    monkeypatch.setattr(assess, "PROFILE_PATH", path)
    monkeypatch.setattr(assess, "detect", lambda **kw: MACHINE)
    monkeypatch.setattr(assess, "decide", lambda m: DECISION)
    return path


def args(**kw):
    return types.SimpleNamespace(**{"no_benchmark": True, "json": True, "output_root": None, **kw})


def test_run_no_benchmark_json_writes_profile(patched, capsys):
    assert assess.run(args()) == 0
    printed = json.loads(capsys.readouterr().out)
    saved = json.loads(patched.read_text())
    assert saved["schema_version"] == 1 and printed["machine"]["cpu"] == "Apple M2 Pro"
    assert saved["benchmark"] is None and saved["backend"]["name"] == "mflux"


def test_run_prints_report_without_json(patched, capsys):
    assert assess.run(args(json=False)) == 0
    assert "DEVICE REPORT" in capsys.readouterr().out and patched.exists()


def test_run_unsupported_returns_1_and_still_saves(patched, monkeypatch, capsys):
    monkeypatch.setattr(assess, "decide", lambda m: Decision(None, False, "nope", "fix it", None, False,
                                                             None, None, None))
    assert assess.run(args()) == 1
    assert json.loads(patched.read_text())["backend"]["supported"] is False


def test_run_with_benchmark_uses_make_engine_and_keeps_actuals(patched, monkeypatch, capsys):
    from medimg.engines import fake_engine
    import medimg.engines as engines
    monkeypatch.setattr(engines, "make_engine", lambda backend, profile, fake=False: fake_engine.FakeEngine(step_s=0))
    old = build_profile(MACHINE, DECISION, None)
    record_actual(old, 768, 1344, 9, 231.0)
    save_profile(old, patched)
    assert assess.run(args(no_benchmark=False)) == 0
    saved = json.loads(patched.read_text())
    assert len(saved["benchmark"]["points"]) == 2 and saved["actuals"][0]["time_s"] == 231.0
    assert saved["backend"]["engine_version"] is None or isinstance(saved["backend"]["engine_version"], str)


def test_run_benchmark_failure_becomes_a_note(patched, monkeypatch, capsys):
    import medimg.engines as engines

    def boom(*a, **k):
        raise RuntimeError("no model")
    monkeypatch.setattr(engines, "make_engine", boom)
    assert assess.run(args(no_benchmark=False)) == 0
    assert "Benchmark failed: no model" in json.loads(patched.read_text())["notes"][0]
