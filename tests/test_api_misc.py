"""Config, status shape, device, settings, estimate, upload validation, folder open, port-in-use."""
from __future__ import annotations

import socket
import sys
from types import SimpleNamespace

import pytest

from medimg import config, server
from tests.test_api_flow import (OK_PROMPT, build_sheet, make_client, profile_dict, simple_rows, upload,
                                 wait_for, wait_job)

STATUS_KEYS = {"version", "model", "job", "last_job", "gallery_version", "local_only"}
JOB_KEYS = {"id", "kind", "phase", "step", "step_total", "image_index", "image_count", "eta_s", "current",
            "done_ids", "errors"}


def err_ok(resp, status):
    assert resp.status_code == status, resp.text
    e = resp.json()["error"]
    assert set(e) == {"cause", "fix"} and e["cause"] and e["fix"]


def test_config(monkeypatch, tmp_path):
    client, *_ = make_client(monkeypatch, tmp_path)
    with client:
        c = client.get("/api/config").json()
        assert set(c) == {"version", "backend", "model_id", "defaults", "limits", "size_presets",
                          "local_only", "nvidia_unverified", "warn_over_s", "device",
                          "steps_hint"}
        assert c["warn_over_s"] is None and c["device"] is None and c["steps_hint"] is None
        assert c["version"] == config.VERSION and c["backend"] == "fake" and c["local_only"] is True
        assert c["nvidia_unverified"] is False
        assert set(c["defaults"]) == {"steps", "width", "height", "port", "output_root", "unload_after_job"}
        assert set(c["limits"]) == {"steps_min", "steps_max", "side_min", "side_max", "max_pixels",
                                    "multiple", "seed_max"}
        assert [p["label"] for p in c["size_presets"]][0] == "1024x1024" and len(c["size_presets"]) == 6
        assert set(c["size_presets"][0]) == {"label", "width", "height"}


def test_status_shape_idle_and_running(monkeypatch, tmp_path):
    src = build_sheet(tmp_path / "w.xlsx", simple_rows(2))
    client, _, engine, _ = make_client(monkeypatch, tmp_path)
    engine.step_s = 0.05
    with client:
        s = client.get("/api/status").json()
        assert set(s) == STATUS_KEYS and s["job"] is None and s["last_job"] is None
        assert set(s["model"]) == {"state", "error"} and s["model"]["state"] == "not_loaded"
        assert s["local_only"] is True and isinstance(s["version"], int) and s["gallery_version"] == 0
        upload(client, src)
        client.post("/api/jobs/batch", json={"count": 2, "steps": 6})
        job = wait_for(lambda: (client.get("/api/status").json()["job"] or {}).get("phase") == "denoising"
                       and client.get("/api/status").json()["job"])
        assert set(job) == JOB_KEYS and job["kind"] == "batch" and job["image_count"] == 2
        assert set(job["current"]) == {"subject", "unit", "lecture", "image_name", "sheet_row"}
        client.post("/api/jobs/cancel")
        end = wait_job(client)
        assert set(end) == STATUS_KEYS and set(end["last_job"]) == {"id", "kind", "outcome", "finished_at"}
        assert end["last_job"]["outcome"] == "cancelled"


def test_device_with_and_without_profile(monkeypatch, tmp_path):
    client, *_ = make_client(monkeypatch, tmp_path)
    with client:
        d = client.get("/api/device").json()
        assert set(d) == {"profile", "report", "estimates", "unverified", "unverified_text"}
        assert d["profile"] is None and d["estimates"] == [] and d["unverified"] is False
    client, *_ = make_client(monkeypatch, tmp_path, profile=profile_dict())
    with client:
        d = client.get("/api/device").json()
        assert d["profile"]["backend"]["name"] == "mflux" and len(d["estimates"]) == 6 and d["report"]
        assert set(d["estimates"][0]) == {"label", "width", "height", "seconds", "for_10", "for_25", "for_50"}


def test_benchmark_runs_and_updates_profile(monkeypatch, tmp_path):
    client, *_ = make_client(monkeypatch, tmp_path, profile=profile_dict())
    with client:
        r = client.post("/api/device/benchmark")
        assert r.status_code == 202
        end = wait_job(client, r.json()["job_id"])
        assert end["last_job"]["kind"] == "benchmark" and end["last_job"]["outcome"] == "done"
        assert (tmp_path / "device_profile.json").exists()
        assert client.get("/api/device").json()["profile"]["benchmark"]["points"]


def test_settings_get_put(monkeypatch, tmp_path):
    client, *_ = make_client(monkeypatch, tmp_path)
    with client:
        s = client.get("/api/settings").json()
        assert s == {"output_root": str(tmp_path / "root"), "port": config.DEFAULT_PORT, "steps": 4,
                     "unload_after_job": False}
        new_root = tmp_path / "elsewhere" / "out"
        r = client.put("/api/settings", json={"output_root": str(new_root), "steps": 8, "unload_after_job": None})
        assert r.status_code == 200 and r.json()["steps"] == 8 and r.json()["unload_after_job"] is None
        assert new_root.is_dir() and (new_root / "_sheets").is_dir()
        assert client.get("/api/config").json()["defaults"]["output_root"] == str(new_root)
        assert client.get("/api/settings").json()["output_root"] == str(new_root)
        saved = config.load_settings(tmp_path / "cfg" / "config.json")
        assert saved.output_root == new_root and saved.steps == 8
        # the store was re-pointed: a single image lands in the new root
        r = client.post("/api/jobs/single", json={"prompt": OK_PROMPT, "width": 512, "height": 512,
                                                   "image_name": "moved"})
        wait_job(client, r.json()["job_id"])
        assert (new_root / "_single" / "moved.png").exists()
        err_ok(client.put("/api/settings", json={"steps": 99}), 400)
        err_ok(client.put("/api/settings", json={"steps": 8, "unload_after_job": "maybe"}), 400)
        err_ok(client.put("/api/settings", content=b"not json"), 400)


def test_estimate_endpoint(monkeypatch, tmp_path):
    client, *_ = make_client(monkeypatch, tmp_path, profile=profile_dict())
    with client:
        r = client.post("/api/sheet/estimate", json={"count": 3, "steps": 9, "default_size": "1024x1024"})
        assert r.status_code == 200
        b = r.json()
        assert b["count"] == 3 and b["per_image_s"] > 0 and abs(b["seconds"] - 3 * b["per_image_s"]) < 1e-6
        r2 = client.post("/api/sheet/estimate", json={"count": 6, "steps": 9, "default_size": "1024x1024"}).json()
        assert abs(r2["seconds"] - 2 * b["seconds"]) < 1e-6
    client, *_ = make_client(monkeypatch, tmp_path / "np")           # no profile: 60 s per image
    with client:
        b = client.post("/api/sheet/estimate", json={"count": 2}).json()
        assert b == {"count": 2, "seconds": 120.0, "per_image_s": 60.0}
        err_ok(client.post("/api/sheet/estimate", json={"count": "x"}), 400)


def test_suggested_batch_uses_estimate(monkeypatch, tmp_path):
    src = build_sheet(tmp_path / "w.xlsx", simple_rows(40))
    client, *_ = make_client(monkeypatch, tmp_path)
    with client:
        rep = upload(client, src).json()
        assert rep["suggested_batch"] == 30 and rep["estimate_per_image_s"] == 60.0   # 1800 / 60
        rep = client.get("/api/sheet", params={"subject": "Nope"}).json()
        assert rep["suggested_batch"] == 0


def test_no_sheet_and_upload_validation(monkeypatch, tmp_path):
    client, _, _, root = make_client(monkeypatch, tmp_path)
    with client:
        err_ok(client.get("/api/sheet"), 404)
        err_ok(client.get("/api/sheet/download"), 404)
        err_ok(client.post("/api/jobs/batch", json={"count": 1}), 400)
        err_ok(client.post("/api/jobs/batch", json={"count": 0}), 400)
        err_ok(client.post("/api/sheet", files={"file": ("notes.csv", b"a,b", "text/csv")}), 400)
        err_ok(client.post("/api/sheet", files={"file": ("bad.xlsx", b"this is not a zip", "application/octet-stream")}), 400)
        err_ok(client.post("/api/sheet", files={"file": ("empty.xlsx", b"", "application/octet-stream")}), 400)
        err_ok(client.post("/api/sheet", files={"file": ("big.xlsx", b"\0" * (20 * 1024 * 1024 + 1), "x/y")}), 400)
        err_ok(client.post("/api/sheet", data={"x": "1"}), 400)
        assert not (root / "_sheets" / "current.json").exists()          # rejected files are never imported
        # a workbook without the required headers
        from openpyxl import Workbook
        wb = Workbook(); wb.active.append(["a", "b"]); wb.save(tmp_path / "nohead.xlsx")
        err_ok(upload(client, tmp_path / "nohead.xlsx"), 400)
        err_ok(upload(client, build_sheet(tmp_path / "ok.xlsx", simple_rows(1)), default_size="wide"), 400)
        assert not (root / "_sheets" / "current.json").exists()


def test_retry_failed_and_filter(monkeypatch, tmp_path):
    rows = simple_rows(2)
    rows[1][2] = "L2"
    rows[0][5] = "failed"
    src = build_sheet(tmp_path / "w.xlsx", rows)
    client, _, engine, _ = make_client(monkeypatch, tmp_path)
    with client:
        rep = upload(client, src).json()
        assert rep["counts"]["failed"] == 1 and rep["counts"]["pending"] == 1
        assert client.get("/api/sheet", params={"retry_failed": "true"}).json()["counts"]["pending"] == 2
        r = client.post("/api/jobs/batch", json={"count": 5, "steps": 4, "filter": {"lecture": "L2"}})
        assert r.json()["rows"] == [3]
        wait_job(client, r.json()["job_id"])
        r = client.post("/api/jobs/batch", json={"count": 5, "steps": 4, "retry_failed": True})
        assert r.json()["rows"] == [2]
        wait_job(client, r.json()["job_id"])
        assert engine.calls == 2


def test_single_into_tree_and_open_folder(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(server, "_open_folder", lambda p: opened.append(p) or True)
    client, _, _, root = make_client(monkeypatch, tmp_path)
    with client:
        r = client.post("/api/jobs/single", json={"prompt": OK_PROMPT, "steps": 4, "width": 770, "height": 530,
                                                   "subject": "S", "unit": "U", "lecture": "L",
                                                   "image_name": "pic.png", "seed": 7})
        assert r.status_code == 202 and r.json()["rel_path"] == "S/U/L/pic.png"
        wait_job(client, r.json()["job_id"])
        img = client.get("/api/gallery/images", params={"subject": "S", "unit": "U", "lecture": "L"}).json()[0]
        assert img["record"]["seed"] == 7 and (img["record"]["width"], img["record"]["height"]) == (768, 528)
        assert client.post(f"/api/images/{img['id']}/open-folder").json() == {"ok": True}
        assert opened == [(root / "S" / "U" / "L").resolve()]
        err_ok(client.post("/api/jobs/single", json={"prompt": OK_PROMPT, "subject": "S"}), 400)    # partial tree
        err_ok(client.post("/api/jobs/single", json={"prompt": OK_PROMPT, "subject": "S", "unit": "U",
                                                      "lecture": "L", "image_name": "pic"}), 400)   # exists
        err_ok(client.post("/api/jobs/single", json={"prompt": "  "}), 400)
        err_ok(client.post("/api/jobs/single", json={"prompt": OK_PROMPT, "width": 64, "height": 64}), 400)
        err_ok(client.post("/api/jobs/single", json={"prompt": OK_PROMPT, "steps": 99}), 400)
        err_ok(client.post("/api/jobs/single", json={}), 400)
        r = client.post("/api/jobs/single", json={"prompt": OK_PROMPT, "width": 512, "height": 512})   # defaults
        assert r.json()["rel_path"].startswith("_single/single_")
        wait_job(client, r.json()["job_id"])


def test_static_index(monkeypatch, tmp_path):
    client, *_ = make_client(monkeypatch, tmp_path)
    with client:
        r = client.get("/")
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]
        assert client.get("/static/app.js").status_code == 200


def test_port_in_use_message(capsys):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        rc = server.main(SimpleNamespace(port=port, fake_engine=True, no_browser=True, output_root=None))
    finally:
        s.close()
    assert rc == 1
    msg = capsys.readouterr().err
    assert f"port {port} in use; run start --port " in msg


def test_main_binds_loopback_via_uvicorn(monkeypatch, tmp_path):
    import uvicorn
    monkeypatch.setattr(config, "PROFILE_PATH", tmp_path / "p.json")
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "cfg.json")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    rc = server.main(SimpleNamespace(port=port, fake_engine=True, no_browser=True,
                                     output_root=str(tmp_path / "out")))
    assert rc == 0
    assert seen == {"host": "127.0.0.1", "port": port, "workers": 1, "reload": False}
    assert (tmp_path / "out" / "_sheets").is_dir()


def test_open_folder_delegates_to_osutil(monkeypatch, tmp_path):
    from medimg import osutil
    got = []
    monkeypatch.setattr(osutil, "open_folder", lambda f: got.append(f) or True)
    assert server._open_folder(tmp_path) is True
    assert got == [tmp_path]


@pytest.mark.parametrize("versioned", [True, False])
def test_main_rebuilds_profile_missing_machine_section(monkeypatch, tmp_path, versioned):
    """A profile saved without a machine section (old benchmark path) must not reach the
    Device report as 'Computer : ?' / 'Supported: NO'. A readable one keeps its benchmark;
    the unversioned file the old path wrote is unreadable and is replaced."""
    import json
    import uvicorn
    import medimg.assess as assess
    import medimg.engines as engines
    from medimg.engines.fake_engine import FakeEngine
    pfile = tmp_path / "p.json"
    bench = {"fit": {"ref_pixels": 262144, "ref_per_step_s": 4.0, "alpha": 1.0, "overhead_s": 5.0}}
    skeleton = {"backend": {"name": "mflux", "offload_mode": None},
                "benchmark": bench, "actuals": [], "notes": []}
    if versioned:
        skeleton["schema_version"] = 1
    pfile.write_text(json.dumps(skeleton))
    monkeypatch.setattr(config, "PROFILE_PATH", pfile)
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "cfg.json")
    mac = assess.Machine(hostname="mac", os_name="Darwin", os_version="26", cpu="Apple M2 Pro",
                         apple_chip="Apple M2 Pro", ram_total_gb=16.0, ram_free_gb=8.0, gpu=None,
                         disk_free_gb=100.0, disk_path=str(tmp_path), python="3.12", uv="0.11",
                         arch="arm64")
    monkeypatch.setattr(assess, "detect", lambda disk_path=None: mac)
    monkeypatch.setattr(assess, "decide", lambda m, engine=None: SimpleNamespace(
        supported=True, backend="mflux", reason="Apple Silicon Mac", fix=None, model_id="m",
        offload_mode=None, unload_after_job=True, device=None, tier=None, reason_code="ok"))
    monkeypatch.setattr(engines, "make_engine", lambda *a, **k: FakeEngine())
    seen = {}
    monkeypatch.setattr(server, "create_app", lambda engine, settings, profile: seen.update(p=profile))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: None)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert server.main(SimpleNamespace(port=port, fake_engine=False, no_browser=True,
                                       output_root=str(tmp_path / "out"))) == 0
    p = seen["p"]
    assert p["machine"]["cpu"] == "Apple M2 Pro" and p["machine"]["ram_total_gb"] == 16.0
    assert p["backend"]["name"] == "mflux" and p["backend"]["supported"] is True
    assert p["benchmark"] == (bench if versioned else None)
