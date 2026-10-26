"""Acceptance 4: user A generates 2 of 5 and downloads; user B on a fresh root continues with the rest."""
from __future__ import annotations

from medimg.engines.fake_engine import FakeEngine
from tests.test_api_flow import (build_sheet, make_client, sheet_rows_from_bytes, simple_rows, upload,
                                 wait_job)


def test_handoff_two_users(monkeypatch, tmp_path):
    src = build_sheet(tmp_path / "work.xlsx", simple_rows(5))
    a_client, _, a_engine, a_root = make_client(monkeypatch, tmp_path / "A")
    with a_client:
        assert upload(a_client, src).json()["counts"]["pending"] == 5
        r = a_client.post("/api/jobs/batch", json={"count": 2, "steps": 4})
        assert r.status_code == 202
        wait_job(a_client, r.json()["job_id"])
        assert a_engine.calls == 2
        dl = a_client.get("/api/sheet/download")
        handed = tmp_path / "handed.xlsx"
        handed.write_bytes(dl.content)
    assert [r["Status"] for r in sheet_rows_from_bytes(dl.content)] == ["done", "done"] + ["pending"] * 3

    b_engine = FakeEngine(step_s=0.002)
    b_client, _, _, b_root = make_client(monkeypatch, tmp_path / "B", engine=b_engine)
    assert not any(b_root.rglob("*.png"))
    with b_client:
        rep = upload(b_client, handed, name="work.xlsx").json()
        assert rep["counts"] == {"total": 5, "done": 2, "pending": 3, "blocked": 0, "failed": 0, "invalid": 0}
        r = b_client.post("/api/jobs/batch", json={"count": 10, "steps": 4})
        assert r.status_code == 202 and r.json()["rows"] == [4, 5, 6]
        wait_job(b_client, r.json()["job_id"])
        assert b_engine.calls == 3
        assert len(b_client.get("/api/gallery/images").json()) == 3      # only B's images exist on B
        final = sheet_rows_from_bytes(b_client.get("/api/sheet/download").content)
        assert all(r["Status"] == "done" for r in final)
        assert b_client.get("/api/sheet").json()["counts"]["done"] == 5
