"""409 while a job is running: batch, single, regenerate, benchmark (and sheet upload)."""
from __future__ import annotations

from tests.test_api_flow import (OK_PROMPT, build_sheet, make_client, simple_rows, upload, wait_for,
                                 wait_job)


def assert_error_body(resp, status):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body) == {"error"} and set(body["error"]) == {"cause", "fix"}
    assert body["error"]["cause"] and body["error"]["fix"]


def test_409_while_busy(monkeypatch, tmp_path):
    src = build_sheet(tmp_path / "work.xlsx", simple_rows(3))
    client, _, engine, _ = make_client(monkeypatch, tmp_path)
    with client:
        upload(client, src)
        r = client.post("/api/jobs/single", json={"prompt": OK_PROMPT, "steps": 4, "width": 512,
                                                   "height": 512, "image_name": "seedimg"})
        assert r.status_code == 202
        wait_job(client, r.json()["job_id"])
        image_id = client.get("/api/gallery/images").json()[0]["id"]

        engine.step_s = 0.1
        job = client.post("/api/jobs/batch", json={"count": 3, "steps": 4})
        assert job.status_code == 202
        wait_for(lambda: client.get("/api/status").json()["job"] is not None)

        assert_error_body(client.post("/api/jobs/batch", json={"count": 1, "steps": 4}), 409)
        assert_error_body(client.post("/api/jobs/single", json={"prompt": OK_PROMPT, "steps": 4,
                                                                 "width": 512, "height": 512}), 409)
        assert_error_body(client.post("/api/jobs/regenerate", json={"image_id": image_id}), 409)
        assert_error_body(client.post("/api/device/benchmark"), 409)
        assert_error_body(upload(client, src), 409)

        client.post("/api/jobs/cancel")
        wait_job(client, job.json()["job_id"])
        # idle again: the same calls are accepted
        r = client.post("/api/jobs/regenerate", json={"image_id": image_id})
        assert r.status_code == 202
        wait_job(client, r.json()["job_id"])
