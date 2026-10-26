"""Acceptance 5 (part 1): cancel mid-batch keeps finished rows done and the current row pending."""
from __future__ import annotations

from medimg.engines.fake_engine import FakeEngine
from tests.test_api_flow import (build_sheet, make_client, sheet_rows_from_bytes, simple_rows, upload,
                                 wait_for, wait_job)


def test_cancel_mid_batch(monkeypatch, tmp_path):
    src = build_sheet(tmp_path / "work.xlsx", simple_rows(4))
    engine = FakeEngine(step_s=0.05)
    client, _, _, root = make_client(monkeypatch, tmp_path, engine=engine)
    with client:
        upload(client, src)
        r = client.post("/api/jobs/batch", json={"count": 4, "steps": 8})
        assert r.status_code == 202

        def in_row_two():
            j = client.get("/api/status").json()["job"]
            return j and j["image_index"] == 2 and j["phase"] == "denoising" and j["step"] >= 1

        wait_for(in_row_two)
        assert client.post("/api/jobs/cancel").json() == {"cancelled": True}
        end = wait_job(client, r.json()["job_id"])
        assert end["last_job"]["outcome"] == "cancelled"

        rows = sheet_rows_from_bytes(client.get("/api/sheet/download").content)
        assert [x["Status"] for x in rows] == ["done", "pending", "pending", "pending"]
        assert (root / "Anat/Hand/L1/img0.png").exists()
        assert not (root / "Anat/Hand/L1/img1.png").exists()
        assert not (root / "Anat/Hand/L1/img1.json").exists()
        assert len(client.get("/api/gallery/images").json()) == 1
        assert client.post("/api/jobs/cancel").json() == {"cancelled": False}   # nothing running now
