"""Acceptance 5 (part 2): crash-resume. A PNG on disk with a pending row becomes done; a new app resumes."""
from __future__ import annotations

from PIL import Image

from medimg import sheet
from medimg.engines.fake_engine import FakeEngine
from tests.test_api_flow import (build_sheet, make_client, sheet_rows_from_bytes, simple_rows, upload,
                                 wait_job)


def _png(root, rel):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), "white").save(p)


def test_existing_png_marks_row_done_on_upload(monkeypatch, tmp_path):
    src = build_sheet(tmp_path / "work.xlsx", simple_rows(3))
    client, _, engine, root = make_client(monkeypatch, tmp_path)
    _png(root, "Anat/Hand/L1/img0.png")
    with client:
        rep = upload(client, src).json()
        assert rep["counts"]["done"] == 1 and rep["counts"]["pending"] == 2
        rows = sheet_rows_from_bytes(client.get("/api/sheet/download").content)   # written at upload time
        assert rows[0]["Status"] == "done" and rows[0]["Output Path"] == "Anat/Hand/L1/img0.png"
        r = client.post("/api/jobs/batch", json={"count": 5, "steps": 4})
        assert r.json()["rows"] == [3, 4]
        wait_job(client, r.json()["job_id"])
        assert engine.calls == 2


def test_new_instance_autoloads_current_sheet_and_continues(monkeypatch, tmp_path):
    src = build_sheet(tmp_path / "work.xlsx", simple_rows(4))
    c1, _, e1, root = make_client(monkeypatch, tmp_path)
    with c1:
        upload(c1, src)
        r = c1.post("/api/jobs/batch", json={"count": 1, "steps": 4})
        wait_job(c1, r.json()["job_id"])
        assert e1.calls == 1
    assert (root / "_sheets" / "current.json").exists()

    e2 = FakeEngine(step_s=0.002)
    c2, _, _, _ = make_client(monkeypatch, tmp_path, root=root, engine=e2)      # "restart"
    with c2:
        rep = c2.get("/api/sheet").json()                                       # no re-upload
        assert rep["original_name"] == "work.xlsx"
        assert rep["counts"]["done"] == 1 and rep["counts"]["pending"] == 3
        r = c2.post("/api/jobs/batch", json={"count": 10, "steps": 4})
        assert r.status_code == 202 and r.json()["rows"] == [3, 4, 5]
        wait_job(c2, r.json()["job_id"])
        assert e2.calls == 3
        assert c2.get("/api/sheet/download").status_code == 200
        assert len(c2.get("/api/gallery/images").json()) == 4


def test_startup_revalidates_after_crash_between_png_and_sheet_write(monkeypatch, tmp_path):
    """Killed after the PNG was saved but before the row was written: restart marks it done."""
    root = tmp_path / "root"
    src = build_sheet(tmp_path / "work.xlsx", simple_rows(2))
    sheet.import_sheet(src, root)
    _png(root, "Anat/Hand/L1/img1.png")
    client, *_ = make_client(monkeypatch, tmp_path, root=root)
    with client:
        assert client.get("/api/sheet").json()["counts"]["done"] == 1
        rows = sheet_rows_from_bytes(client.get("/api/sheet/download").content)
        assert [r["Status"] for r in rows] == ["pending", "done"]
