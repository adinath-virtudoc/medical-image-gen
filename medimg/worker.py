"""One generation worker thread: owns the engine, runs one job at a time."""
from __future__ import annotations

import logging
import queue
import socket
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from medimg import names, sheet
from medimg.assess import benchmark as run_benchmark
from medimg.assess import estimate_seconds, load_profile, record_actual, save_profile
from medimg.engines.base import Engine
from medimg.errors import Blocked, Busy, Cancelled, Invalid, MedimgError, ModelUnavailable
from medimg.jobs import JobSpec, RowJob, validate_row_job
from medimg.store import ImageRecord, Store

log = logging.getLogger(__name__)

ACTIVE = ("queued", "loading", "encoding", "denoising", "decoding", "saving")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def machine_string(profile: dict | None) -> str:
    m = (profile or {}).get("machine") or {}
    host = m.get("hostname") or socket.gethostname()
    gpu = m.get("gpu") or {}
    chip = m.get("apple_chip") or gpu.get("name") or m.get("cpu")
    if not chip:
        import platform
        chip = platform.processor() or platform.machine() or "unknown"
    return f"{host} · {chip}"


class State:
    """Thread-safe status holder. Every change bumps `version`."""

    def __init__(self, model_state: str = "not_loaded"):
        self.lock = threading.RLock()
        self.version = 0
        self.gallery_version = 0
        self.model_state = model_state
        self.model_error: str | None = None
        self.job: dict | None = None
        self.last_job: dict | None = None

    def _bump(self) -> None:
        self.version += 1

    def set_model(self, state: str, error: str | None = None) -> None:
        with self.lock:
            self.model_state, self.model_error = state, error
            self._bump()

    def start_job(self, job_id: str, kind: str, image_count: int) -> None:
        with self.lock:
            self.job = {"id": job_id, "kind": kind, "phase": "queued", "step": 0, "step_total": 0,
                        "image_index": 0, "image_count": image_count, "eta_s": None,
                        "current": None, "done_ids": [], "errors": []}
            self._bump()

    def update(self, **kw) -> None:
        with self.lock:
            if self.job is not None:
                self.job.update(kw)
                self._bump()

    def add_done(self, image_id: str) -> None:
        with self.lock:
            if self.job is not None:
                self.job["done_ids"].append(image_id)
                self.gallery_version += 1
                self._bump()

    def add_error(self, row, reason: str) -> None:
        with self.lock:
            if self.job is not None:
                self.job["errors"].append({"row": row, "reason": reason})
                self._bump()

    def finish_job(self, outcome: str) -> None:
        with self.lock:
            if self.job is not None:
                self.last_job = {"id": self.job["id"], "kind": self.job["kind"], "outcome": outcome,
                                 "finished_at": _now_iso()}
            self.job = None
            self._bump()

    def active(self) -> bool:
        with self.lock:
            return self.job is not None

    def snapshot(self) -> dict:
        with self.lock:
            job = None
            if self.job is not None:
                job = dict(self.job)
                job["current"] = dict(job["current"]) if job["current"] else None
                job["done_ids"] = list(job["done_ids"])
                job["errors"] = [dict(e) for e in job["errors"]]
            return {"version": self.version,
                    "model": {"state": self.model_state, "error": self.model_error},
                    "job": job,
                    "last_job": dict(self.last_job) if self.last_job else None,
                    "gallery_version": self.gallery_version,
                    "local_only": True}


class GenerationWorker:
    def __init__(self, engine: Engine, store: Store, profile_path: Path, *,
                 unload_after_job: bool, sheet_lock: threading.Lock):
        self.engine = engine
        self.store = store
        self.profile_path = Path(profile_path)
        self.unload_after_job = unload_after_job
        self.sheet_lock = sheet_lock
        self.state = State("ready" if getattr(engine, "loaded", False) else "not_loaded")
        self._queue: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._submit_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._profile: dict | None = None
        self._job_start = 0.0

    # -- public API ---------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="generation-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout)

    def submit(self, spec: JobSpec) -> str:
        with self._submit_lock:
            if self.state.active():
                raise Busy("A job is already running.", "Wait for it to finish or cancel it.")
            snap = self.state.snapshot()["model"]
            if snap["state"] == "error":
                raise ModelUnavailable(f"The model is not available: {snap['error']}",
                                       "Restart the app; if it happens again run the assessment and check the setup.")
            rows = list(spec.rows)
            if spec.kind != "benchmark":
                rows = [self._precheck(spec.kind, r) for r in rows]
            spec = JobSpec(kind=spec.kind, rows=rows, sheet_path=spec.sheet_path, sheet_name=spec.sheet_name)
            job_id = uuid.uuid4().hex[:12]
            self._cancel.clear()
            self.state.start_job(job_id, spec.kind, len(rows))
            self._queue.put((job_id, spec))
            return job_id

    def cancel(self) -> bool:
        if not self.state.active():
            return False
        self._cancel.set()
        return True

    def snapshot(self) -> dict:
        snap = self.state.snapshot()
        return snap

    def clear_model_error(self) -> None:
        """Let the next submit retry loading after a load error."""
        if self.state.snapshot()["model"]["state"] == "error":
            self.state.set_model("ready" if getattr(self.engine, "loaded", False) else "not_loaded")

    # -- internals ----------------------------------------------------
    @staticmethod
    def _precheck(kind: str, row: RowJob) -> RowJob:
        try:
            return validate_row_job(row)
        except Blocked:
            if kind == "batch":
                return row          # the loop writes it as blocked, never generates it
            raise

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            job_id, spec = item
            outcome = "failed"
            try:
                outcome = self._run_job(spec)
            except Exception as e:  # never let the thread die
                log.exception("job %s crashed", job_id)
                self.state.add_error(None, str(e))
            finally:
                if self.unload_after_job:
                    try:
                        self.engine.unload()
                        if self.state.snapshot()["model"]["state"] == "ready":
                            self.state.set_model("not_loaded")
                    except Exception:
                        log.exception("unload failed")
                self.state.finish_job(outcome)

    def _ensure_loaded(self) -> bool:
        if getattr(self.engine, "loaded", False):
            self.state.set_model("ready")
            return True
        self.state.set_model("loading")
        self.state.update(phase="loading")
        try:
            self.engine.load(lambda phase, k, n: self.state.update(phase="loading", step=k, step_total=n))
        except Exception as e:
            self.state.set_model("error", str(e) or e.__class__.__name__)
            self.state.add_error(None, f"Model failed to load: {e}")
            return False
        self.state.set_model("ready")
        return True

    def _run_job(self, spec: JobSpec) -> str:
        self._job_start = time.monotonic()
        self._profile = load_profile(self.profile_path) or self._profile
        if spec.kind == "benchmark":
            return self._run_benchmark()
        if not self._ensure_loaded():
            return "failed"
        rows = spec.rows
        outcome = "done"
        for i, row in enumerate(rows):
            if self._cancel.is_set():
                return "cancelled"
            res = self._run_row(spec, rows, i, row)
            if res == "cancelled":
                return "cancelled"
        return outcome

    def _run_benchmark(self) -> str:
        self.state.set_model("loading" if not getattr(self.engine, "loaded", False) else "ready")
        self.state.update(phase="loading")
        try:
            result = run_benchmark(self.engine)
        except Exception as e:
            self.state.set_model("error", str(e) or e.__class__.__name__)
            self.state.add_error(None, f"Benchmark failed: {e}")
            return "failed"
        self.state.set_model("ready")
        profile = load_profile(self.profile_path) or self._profile or {
            "schema_version": 1, "created_at": _now_iso(), "app_version": None,
            "machine": {}, "backend": {}, "benchmark": None, "actuals": [], "notes": []}
        profile["benchmark"] = result
        save_profile(profile, self.profile_path)
        self._profile = profile
        return "done"

    # -- one row --------------------------------------------------------
    def _sheet_write(self, spec: JobSpec, row: RowJob, updates: dict) -> None:
        if row.sheet_row is None or spec.sheet_path is None:
            return
        with self.sheet_lock:
            sheet.write_row(spec.sheet_path, row.sheet_row, updates)

    def _fail_row(self, spec: JobSpec, row: RowJob, status: str, reason: str) -> None:
        self.state.add_error(row.sheet_row, reason)
        try:
            self._sheet_write(spec, row, {"Status": status, "Error": reason})
        except Exception as e:
            log.exception("sheet write failed")
            self.state.add_error(row.sheet_row, f"Could not update the sheet: {e}")

    def _eta(self, rows: list[RowJob], i: int, fraction: float) -> float | None:
        if not self._profile:
            return None
        try:
            total = 0.0
            for k in range(i, len(rows)):
                r = rows[k]
                est = estimate_seconds(self._profile, r.width, r.height, r.steps)
                total += est * (1 - fraction) if k == i else est
            return max(0.0, total)
        except Exception:
            return None

    def _run_row(self, spec: JobSpec, rows: list[RowJob], i: int, raw: RowJob) -> str:
        name = raw.image_name.strip() or datetime.now().strftime("image_%Y%m%d_%H%M%S")
        self.state.update(
            image_index=i + 1, phase="queued", step=0, step_total=raw.steps,
            current={"subject": raw.subject, "unit": raw.unit, "lecture": raw.lecture,
                     "image_name": name, "sheet_row": raw.sheet_row},
            eta_s=self._eta(rows, i, 0.0))
        try:
            row = validate_row_job(raw)
        except Blocked as e:
            self._fail_row(spec, raw, "blocked", e.cause)
            return "blocked"
        except Invalid as e:
            self._fail_row(spec, raw, "invalid", e.cause)
            return "invalid"

        def on_progress(phase: str, k: int, n: int) -> None:
            kw = {"phase": phase}
            if phase == "denoising" or phase == "decoding":
                kw.update(step=k, step_total=n)
                if n:
                    kw["eta_s"] = self._eta(rows, i, k / n)
            self.state.update(**kw)

        try:
            result = self.engine.generate(row.prompt, row.seed, row.steps, row.width, row.height,
                                          on_progress, self._cancel.is_set)
        except Cancelled:
            return "cancelled"
        except Exception as e:
            self._fail_row(spec, row, "failed", str(e) or e.__class__.__name__)
            return "failed"

        self.state.update(phase="saving")
        rel = names.rel_path(row.subject, row.unit, row.lecture, name)
        machine = machine_string(self._profile)
        source = {"batch": "batch", "regenerate": "regenerate"}.get(spec.kind, "single")
        record = ImageRecord(
            id=names.image_id(rel), rel_path=rel, subject=row.subject, unit=row.unit,
            lecture=row.lecture, image_name=name, prompt=row.prompt, seed=result.seed,
            steps=result.steps, width=row.width, height=row.height, model_id=result.model_id,
            engine=result.engine, time_s=round(result.time_s, 3),
            peak_mem_gb=round(result.peak_mem_gb, 3), created_at=_now_iso(), machine=machine,
            source=source,
            sheet=({"name": spec.sheet_name, "row": row.sheet_row}
                   if row.sheet_row is not None and spec.sheet_name else None))
        try:
            # D14: PNG -> sidecar (inside save) -> sheet row.
            saved = self.store.save(result.image, record, overwrite=row.overwrite)
        except Exception as e:
            self._fail_row(spec, row, "failed", e.cause if isinstance(e, MedimgError) else str(e))
            return "failed"
        self.state.add_done(saved.id)
        try:
            self._sheet_write(spec, row, {
                "Status": "done", "Seed": result.seed, "Seed Used": result.seed,
                "Steps": result.steps, "Generated At": saved.created_at, "Machine": machine,
                "Model": result.model_id, "Generation Time (s)": round(result.time_s, 2),
                "Output Path": rel, "Error": None})
        except Exception as e:
            log.exception("sheet write failed")
            self.state.add_error(row.sheet_row, f"Image saved but the sheet could not be updated: {e}")
        self._record_actual(row, result.time_s)
        return "done"

    def _record_actual(self, row: RowJob, time_s: float) -> None:
        profile = self._profile
        if profile is None:
            return
        try:
            record_actual(profile, row.width, row.height, row.steps, time_s)
            save_profile(profile, self.profile_path)
        except Exception:
            log.exception("could not save the device profile")
