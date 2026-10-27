"""API flow with the sd.cpp engine driven through the fake sd-cli (no weights, no GPU, no network)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import psutil

from medimg import config
from medimg.engines.sdcpp_engine import SdcppEngine
from medimg.sdcpp.install import SdcppPaths
from medimg.sdcpp.procs import popen_group
from tests.test_api_flow import (OK_PROMPT, SAMPLE, build_sheet, make_client, profile_dict,
                                 sheet_rows_from_bytes, simple_rows, upload, wait_for, wait_job)

STUB = Path(__file__).parent / "stubs" / "fake_sd_cli.py"


def fake_paths(tmp_path) -> SdcppPaths:
    d = tmp_path / "models"
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for n in ("z_image_turbo-Q3_K.gguf", "qwen3-q3.gguf", "ae.safetensors"):
        (d / n).write_bytes(b"x")
        files.append(d / n)
    return SdcppPaths(sd_cli=(sys.executable, "-I", str(STUB)), cwd=tmp_path,
                      diffusion=files[0], llm=files[1], vae=files[2],
                      build="mac-arm64", tier="mid")


def sd_profile(actuals=None) -> dict:
    p = profile_dict()
    p["backend"] = {"name": "sdcpp", "device": "cpu", "sdcpp": {"build": "mac-arm64", "tier": "mid"}}
    p["actuals"] = actuals or []
    return p


def sd_client(monkeypatch, tmp_path, *, profile=None, popen=None, steps=4):
    kw = {"popen": popen, "poll_s": 0.05} if popen else {}
    engine = SdcppEngine(fake_paths(tmp_path), "cpu", **kw)
    client, app, engine, root = make_client(monkeypatch, tmp_path, engine=engine,
                                            profile=profile or sd_profile(), steps=steps)
    return client, engine, root


def calls(path: Path) -> int:
    return len(path.read_text().splitlines()) if path.exists() else 0


def test_full_flow(monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_SD_CLI_STEP_S", "0.001")
    client, engine, root = sd_client(monkeypatch, tmp_path)
    with client:
        r = upload(client, SAMPLE)
        assert r.status_code == 200, r.text
        assert r.json()["counts"]["pending"] == 3
        r = client.post("/api/jobs/batch", json={"count": 2, "steps": 4, "default_size": "512x512"})
        assert r.status_code == 202
        end = wait_job(client, r.json()["job_id"], timeout=60)
        assert end["last_job"]["outcome"] == "done"
        imgs = client.get("/api/gallery/images").json()
        assert len(imgs) == 2
        for im in imgs:
            assert im["record"]["engine"].startswith("sdcpp")
            assert (root / im["rel_path"]).exists()
        rows = sheet_rows_from_bytes(client.get("/api/sheet/download").content)
        done = [x for x in rows if x["Status"] == "done"]
        assert len(done) == 2
        for x in done:
            assert x["Seed Used"] is not None and x["Generation Time (s)"] is not None and x["Machine"]

        # single image
        r = client.post("/api/jobs/single", json={"prompt": OK_PROMPT, "steps": 4, "width": 512, "height": 512})
        assert r.status_code == 202, r.text
        wait_job(client, r.json()["job_id"], timeout=60)
        assert len(client.get("/api/gallery/images").json()) == 3

        # regenerate a sheet image: new seed, still 3 images
        img = [i for i in client.get("/api/gallery/images").json()
                if i["rel_path"].startswith("_single") is False][0]
        r = client.post("/api/jobs/regenerate", json={"image_id": img["id"]})
        assert r.status_code == 202, r.text
        wait_job(client, r.json()["job_id"], timeout=60)
        assert client.get(f"/api/images/{img['id']}").json()["seed"] == r.json()["seed"]
        assert len(client.get("/api/gallery/images").json()) == 3


def test_cancel_mid_batch_kills_child(monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_SD_CLI_STEP_S", "0.001")
    pids: list[int] = []

    def spy(argv, cwd, env=None):
        p = popen_group(argv, cwd, env=env)
        pids.append(p.pid)
        return p

    src = build_sheet(tmp_path / "w.xlsx", simple_rows(3))
    client, engine, root = sd_client(monkeypatch, tmp_path, popen=spy)
    with client:
        upload(client, src)
        r = client.post("/api/jobs/batch", json={"count": 3, "steps": 4})
        assert r.status_code == 202
        # first image completes normally, then hang the second one
        wait_for(lambda: len(client.get("/api/gallery/images").json()) >= 1, timeout=60)
        monkeypatch.setenv("FAKE_SD_CLI_HANG", "1")

        def hanging():
            j = client.get("/api/status").json()["job"]
            return j and j["image_index"] >= 2 and j["phase"] == "denoising" and j["step"] >= 1

        try:
            wait_for(hanging, timeout=60)
        finally:
            client.post("/api/jobs/cancel")
        end = wait_job(client, r.json()["job_id"], timeout=30)
        assert end["last_job"]["outcome"] == "cancelled"
        rows = sheet_rows_from_bytes(client.get("/api/sheet/download").content)
        statuses = [x["Status"] for x in rows]
        assert statuses[0] == "done" and statuses[1] == "pending" and statuses[2] == "pending"
        assert len(client.get("/api/gallery/images").json()) == 1
    end_t = time.monotonic() + 5
    while time.monotonic() < end_t and any(psutil.pid_exists(p) and _alive(p) for p in pids):
        time.sleep(0.05)
    assert not any(psutil.pid_exists(p) and _alive(p) for p in pids)


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def test_blocked_prompts_never_start_a_process(monkeypatch, tmp_path):
    count = tmp_path / "count.txt"
    monkeypatch.setenv("FAKE_SD_CLI_COUNT_FILE", str(count))
    rows = simple_rows(1)
    rows[0][3] = "a young boy with a fracture"
    src = build_sheet(tmp_path / "w.xlsx", rows)
    client, engine, root = sd_client(monkeypatch, tmp_path)
    with client:
        rep = upload(client, src).json()
        assert rep["counts"]["blocked"] == 1
        client.post("/api/jobs/batch", json={"count": 1, "steps": 4})
        # single prompt: minor term, and no stated age
        assert client.post("/api/jobs/single", json={"prompt": "a young boy with a fracture",
                                                     "steps": 4}).status_code == 422
        assert client.post("/api/jobs/single", json={"prompt": "a man with a swollen knee",
                                                     "steps": 4}).status_code == 422
        time.sleep(0.3)
        assert calls(count) == 0
        assert client.get("/api/gallery/images").json() == []


def test_config_for_sdcpp(monkeypatch, tmp_path):
    client, engine, root = sd_client(monkeypatch, tmp_path)
    with client:
        c = client.get("/api/config").json()
        assert c["backend"] == "sdcpp" and c["defaults"]["steps"] == 8
        assert c["size_presets"][0] == {"label": "512x512 draft", "width": 512, "height": 512}
        assert len(c["size_presets"]) == len(config.SDCPP_SIZE_PRESETS)
        assert c["warn_over_s"] == 900 and c["device"] == "cpu"
        assert "8" in c["steps_hint"]
        assert c["nvidia_unverified"] is False
        for k in ("version", "model_id", "limits", "local_only"):
            assert k in c


def test_config_keeps_saved_steps(monkeypatch, tmp_path):
    client, engine, root = sd_client(monkeypatch, tmp_path)
    from medimg.server import create_app
    settings = config.Settings(output_root=root, steps=6, unload_after_job=False)
    settings.steps_explicit = True
    from fastapi.testclient import TestClient
    app = create_app(SdcppEngine(fake_paths(tmp_path), "cpu"), settings, sd_profile())
    with TestClient(app, base_url="http://127.0.0.1:8750", headers={"X-Medimg": "1"}) as c2:
        assert c2.get("/api/config").json()["defaults"]["steps"] == 6


def test_device_unverified_until_an_actual(monkeypatch, tmp_path):
    client, engine, root = sd_client(monkeypatch, tmp_path)
    with client:
        d = client.get("/api/device").json()
        assert d["unverified"] is True
        assert "no real-run record" in d["unverified_text"]
        assert len(d["estimates"]) == len(config.SDCPP_SIZE_PRESETS)
        assert d["estimates"][0]["width"] == 512
    actual = {"width": 512, "height": 512, "steps": 8, "time_s": 300.0, "at": "x"}
    client, engine, root = sd_client(monkeypatch, tmp_path / "b", profile=sd_profile([actual]))
    with client:
        d = client.get("/api/device").json()
        assert d["unverified"] is False and d["unverified_text"] is None


def test_profile_for_engine():
    from medimg import server
    saved = {"machine": {"x": 1}, "backend": {"name": "mflux"},
             "benchmark": {"fit": 1}, "actuals": [{"a": 1}], "notes": ["n"]}
    be = {"name": "sdcpp", "device": "cpu"}
    out = server._profile_for_engine(saved, be)
    assert out["backend"] == be and out["machine"] == {"x": 1}
    assert out["benchmark"] is None and out["actuals"] == [] and out["notes"] == []
    same = server._profile_for_engine({**saved, "backend": {"name": "sdcpp"}}, be)
    assert same["backend"] == be and same["actuals"] == [{"a": 1}] and same["benchmark"] == {"fit": 1}
    assert server._profile_for_engine(None, be)["backend"] == be


def test_foreign_profile_not_used_or_written(monkeypatch, tmp_path):
    import json
    from medimg import server
    monkeypatch.setenv("FAKE_SD_CLI_STEP_S", "0.001")
    foreign = profile_dict()
    foreign["actuals"] = [{"width": 512, "height": 512, "steps": 4, "time_s": 9.0, "at": "x"}] * 2
    pfile = tmp_path / "device_profile.json"
    pfile.write_text(json.dumps(foreign))
    before = pfile.read_bytes()
    be = {"name": "sdcpp", "device": "cpu", "sdcpp": {"build": "mac-arm64", "tier": "mid"}}
    prof = server._profile_for_engine(json.loads(before), be)
    engine = SdcppEngine(fake_paths(tmp_path), "cpu")
    client, app, engine, root = make_client(monkeypatch, tmp_path, engine=engine, profile=prof)
    assert pfile.read_bytes() == before
    with client:
        d = client.get("/api/device").json()
        assert d["estimates"] == [] and d["unverified"] is True
        assert d["profile"]["backend"]["name"] == "sdcpp"
        r = client.post("/api/jobs/single", json={"prompt": OK_PROMPT, "steps": 4, "width": 512, "height": 512})
        assert r.status_code == 202, r.text
        end = wait_job(client, r.json()["job_id"], timeout=60)
        assert end["last_job"]["outcome"] == "done"
    assert pfile.read_bytes() == before


def test_device_table_uses_shared_estimates(monkeypatch, tmp_path):
    from medimg import server
    assert not hasattr(server, "_sdcpp_table")
    seen = []

    def rec(p, steps=None, presets=None):
        seen.append(presets)
        return []
    monkeypatch.setattr(server, "estimates_table", rec)
    client, engine, root = sd_client(monkeypatch, tmp_path)
    with client:
        client.get("/api/device")
    assert seen and seen[-1] == config.SDCPP_SIZE_PRESETS
