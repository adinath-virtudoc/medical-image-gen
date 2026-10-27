"""FastAPI app: local-only web server around the single generation worker (PLAN 4.9)."""
from __future__ import annotations

import json
import math
import re
import socket
import subprocess
import sys
import tempfile
import threading
import webbrowser
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from medimg import config, names, osutil, rules, sheet
from medimg.assess import (estimate_seconds, estimates_table, load_profile, profile_matches,
                           render_report)
from medimg.errors import (Blocked, Busy, Invalid, MedimgError, ModelUnavailable, NotFound,
                           Unsupported)
from medimg.jobs import JobSpec, RowJob, parse_size, random_seed
from medimg.store import Store
from medimg.worker import GenerationWorker

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ID_RE = re.compile(r"^[0-9a-f]{16}$")
_FILE_PNG_RE = re.compile(r"^([0-9a-f]{16})\.png$")
_SIZE_FIND = re.compile(r"(\d+)\s*[xX×]\s*(\d+)")
FALLBACK_PER_IMAGE_S = 60.0
LOOPBACK = "127.0.0.1"

_STATUS_FOR = {Blocked: 422, Invalid: 400, Busy: 409, NotFound: 404, ModelUnavailable: 503,
               Unsupported: 400}


def _error_body(cause: str, fix: str = "") -> dict:
    return {"error": {"cause": cause, "fix": fix}}


def _err(status: int, cause: str, fix: str = "") -> JSONResponse:
    return JSONResponse(_error_body(cause, fix), status_code=status)


def _open_folder(folder: Path) -> bool:
    """Open a folder in the system file manager (see osutil). Only called with a store-resolved path."""
    return osutil.open_folder(folder)


class _SheetRef:
    """The currently loaded working sheet. All access goes through `lock` (also given to the worker)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.path: Path | None = None
        self.original_name: str = ""


def _default_size(text: str | None) -> tuple[int, int]:
    if text is None or not str(text).strip():
        return config.DEFAULT_WIDTH, config.DEFAULT_HEIGHT
    m = _SIZE_FIND.search(str(text))
    if not m:
        raise Invalid(f"Size {text!r} is not in the form WIDTHxHEIGHT.", "Write the size like 768x1344.")
    return parse_size(f"{m.group(1)}x{m.group(2)}")


def _read_pointer_name(root: Path) -> str:
    try:
        data = json.loads((Path(root) / "_sheets" / "current.json").read_text(encoding="utf-8"))
        return str(data.get("original_name") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def _effective_unload(settings: config.Settings, profile: dict | None) -> bool:
    if settings.unload_after_job is not None:
        return bool(settings.unload_after_job)
    backend = (profile or {}).get("backend") or {}
    if isinstance(backend.get("unload_after_job"), bool):
        return backend["unload_after_job"]
    ram = ((profile or {}).get("machine") or {}).get("ram_total_gb")
    return bool(ram is not None and ram <= 16)


# --------------------------------------------------------------------------- request models
class BatchRequest(BaseModel):
    count: int
    filter: dict[str, str | None] | None = None
    retry_failed: bool = False
    default_size: str | None = None
    steps: int | None = None


class SingleRequest(BaseModel):
    prompt: str
    seed: int | None = None
    steps: int | None = None
    width: int | None = None
    height: int | None = None
    subject: str | None = ""
    unit: str | None = ""
    lecture: str | None = ""
    image_name: str | None = ""


class RegenerateRequest(BaseModel):
    image_id: str


class EstimateRequest(BaseModel):
    count: int
    filter: dict[str, str | None] | None = None
    steps: int | None = None
    default_size: str | None = None



# --------------------------------------------------------------------------- app factory
def _profile_for_engine(saved: dict | None, be: dict) -> dict:
    """Profile for the chosen engine; a profile saved for another engine keeps only the machine."""
    saved = saved or {}
    if (saved.get("backend") or {}).get("name") == be.get("name"):
        return {**saved, "backend": be}
    return {**saved, "backend": be, "benchmark": None, "actuals": [], "notes": []}


def create_app(engine, settings: config.Settings, profile: dict | None, *,
               store: Store | None = None) -> FastAPI:
    store_box = {"store": store or Store(settings.output_root)}
    ref = _SheetRef()
    profile_path = Path(config.PROFILE_PATH)
    worker = GenerationWorker(engine, store_box["store"], profile_path,
                              unload_after_job=_effective_unload(settings, profile),
                              sheet_lock=ref.lock)
    if profile:
        worker._profile = profile  # seed the in-memory profile when the file is missing

    def cur_store() -> Store:
        return store_box["store"]

    def current_profile() -> dict | None:
        try:
            f = load_profile(profile_path)
            return f if (f and profile_matches(f, engine.name)) else profile
        except Exception:
            return profile

    def per_image_s(width: int, height: int, steps: int) -> float:
        p = current_profile()
        if not p:
            return FALLBACK_PER_IMAGE_S
        try:
            est = float(estimate_seconds(p, width, height, steps))
        except Exception:
            return FALLBACK_PER_IMAGE_S
        # a zero/negative estimate (e.g. sub-tick timings) would divide by zero downstream
        return est if est > 0 else FALLBACK_PER_IMAGE_S

    # ---- sheet helpers
    def load_current_from_disk() -> None:
        root = cur_store().root
        path = sheet.current_sheet(root)
        with ref.lock:
            ref.path = path
            ref.original_name = (_read_pointer_name(root) or (path.name if path else "")) if path else ""

    def validated(path: Path, *, retry_failed: bool, size: tuple[int, int]):
        raw_title, raw = sheet.read_rows(path)
        rows = sheet.validate(list(raw), output_root=cur_store().root, default_size=size,
                              retry_failed=retry_failed)
        return raw, rows

    def persist_recomputed(path: Path, raw, rows) -> None:
        """Write recomputed statuses and Error text (and Output Path for file-exists) into the copy."""
        before = {r.idx: r for r in raw}
        updates: dict[int, dict[str, object]] = {}
        for r in rows:
            b = before.get(r.idx)
            if b is None:
                continue
            if r.status != b.status or (r.error or "") != (b.error or ""):
                upd: dict[str, object] = {"Status": r.status, "Error": r.error or None}
                if r.status == "done" and r.system.get("Output Path"):
                    upd["Output Path"] = r.system["Output Path"]
                updates[r.idx] = upd
        sheet.ensure_system_columns(path)
        if updates:
            sheet.write_rows(path, updates)

    def report_json(path: Path, original_name: str, rows, *, size: tuple[int, int], steps: int,
                    flt: dict | None) -> dict:
        counts = {k: 0 for k in ("total", "done", "pending", "blocked", "failed", "invalid")}
        counts["total"] = len(rows)
        problems = []
        for r in rows:
            counts[r.status] = counts.get(r.status, 0) + 1
            if r.status in ("blocked", "invalid"):
                fix = (rules.HINT if "does not state an adult" in r.error else
                       "Rephrase the prompt to describe an adult." if r.status == "blocked"
                       else "Correct the row and upload the sheet again.")
                problems.append({"row": r.idx, "status": r.status, "reason": r.error, "fix": fix})
        filters = {k: sorted({getattr(r, a) for r in rows if getattr(r, a)})
                   for k, a in (("subjects", "subject"), ("units", "unit"), ("lectures", "lecture"))}
        pending = len(sheet.select_batch(rows, len(rows) + 1, flt)) if flt else counts["pending"]
        per = per_image_s(size[0], size[1], steps)
        suggested = min(pending, max(1, math.floor(config.BATCH_TARGET_MINUTES * 60 / per)))
        return {"sheet_id": path.stem, "original_name": original_name, "worksheet": None,
                "counts": counts, "problems": problems, "filters": filters,
                "suggested_batch": suggested, "estimate_per_image_s": per}

    def want_sheet() -> tuple[Path, str]:
        with ref.lock:
            path, name = ref.path, ref.original_name
        if path is None or not path.is_file():
            raise NotFound("No sheet is loaded.", "Upload an .xlsx sheet first.")
        return path, name

    def row_jobs_for(rows, size, steps) -> list[RowJob]:
        return [RowJob(prompt=r.prompt, seed=r.seed, steps=steps,
                       width=(r.size or size)[0], height=(r.size or size)[1],
                       subject=r.subject, unit=r.unit, lecture=r.lecture,
                       image_name=r.image_name, sheet_row=r.idx) for r in rows]

    def settle_busy() -> None:
        if worker.state.active():
            raise Busy("A job is already running.", "Wait for it to finish or press Cancel.")

    try:
        load_current_from_disk()
        if ref.path is not None:
            with ref.lock:
                raw, rows = validated(ref.path, retry_failed=False,
                                      size=(config.DEFAULT_WIDTH, config.DEFAULT_HEIGHT))
                persist_recomputed(ref.path, raw, rows)
    except MedimgError:
        with ref.lock:
            ref.path, ref.original_name = None, ""
    except Exception:
        with ref.lock:
            ref.path, ref.original_name = None, ""

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        worker.start()
        yield
        worker.stop()

    app = FastAPI(title=config.APP_NAME, version=config.VERSION, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)

    allowed_hosts = {f"127.0.0.1:{settings.port}", f"localhost:{settings.port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}

    @app.middleware("http")
    async def _local_only(request: Request, call_next):
        # Defends against DNS rebinding (Host) and cross-site requests (Origin / custom header).
        got = (request.headers.get("host") or "").lower()
        if got not in allowed_hosts:
            return _err(403, "This app only answers requests addressed to this computer.",
                        "Open it at http://127.0.0.1:" + str(settings.port) + ".")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if (origin is not None and origin.lower() not in allowed_origins) \
                    or request.headers.get("x-medimg") != "1":
                return _err(403, "That request did not come from the app page.",
                            "Use the buttons in the app at http://127.0.0.1:" + str(settings.port) + ".")
        return await call_next(request)

    worker.start()
    app.state.worker = worker
    app.state.settings = settings
    app.state.sheet_ref = ref
    app.state.store_box = store_box

    # ---- error handlers
    @app.exception_handler(MedimgError)
    async def _medimg_error(_req: Request, exc: MedimgError):
        status = 400
        for cls, code in _STATUS_FOR.items():
            if isinstance(exc, cls):
                status = code
                break
        return _err(status, exc.cause, exc.fix)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_req: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return _err(404, "That page or file does not exist.", "Go back to the main page.")
        if exc.status_code == 405:
            return _err(405, "That action is not allowed here.", "Use the buttons in the app.")
        return _err(exc.status_code, str(exc.detail), "Try again; if it keeps happening restart the app.")

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError):
        parts = []
        for e in exc.errors()[:3]:
            loc = ".".join(str(x) for x in e.get("loc", ()) if x != "body")
            parts.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
        return _err(400, "The request is not valid (" + "; ".join(parts) + ").",
                    "Check the values you entered and try again.")

    @app.exception_handler(Exception)
    async def _unexpected(_req: Request, exc: Exception):
        return _err(500, f"Unexpected problem: {exc.__class__.__name__}.",
                    "Try again; if it keeps happening restart the app and check the terminal.")

    # ---- config / status
    @app.get("/api/config")
    def api_config():
        is_sdcpp = engine.name == "sdcpp"
        steps_default = settings.steps
        if is_sdcpp and not getattr(settings, "steps_explicit", False):
            steps_default = config.SDCPP_DEFAULT_STEPS
        presets = config.SDCPP_SIZE_PRESETS if is_sdcpp else config.SIZE_PRESETS
        return {
            "version": config.VERSION, "backend": engine.name, "model_id": engine.model_id,
            "defaults": {"steps": steps_default, "width": config.DEFAULT_WIDTH,
                         "height": config.DEFAULT_HEIGHT, "port": settings.port,
                         "output_root": str(cur_store().root),
                         "unload_after_job": worker.unload_after_job},
            "limits": {"steps_min": config.STEPS_MIN, "steps_max": config.STEPS_MAX,
                       "side_min": config.SIDE_MIN, "side_max": config.SIDE_MAX,
                       "max_pixels": config.MAX_PIXELS, "multiple": config.SIZE_MULTIPLE,
                       "seed_max": config.SEED_MAX},
            "size_presets": [{"label": l, "width": w, "height": h} for l, w, h in presets],
            "local_only": True, "nvidia_unverified": engine.name == "diffusers",
            "warn_over_s": config.SDCPP_WARN_OVER_S if is_sdcpp else None,
            "device": getattr(engine, "device", None) if is_sdcpp else None,
            "steps_hint": (f"{config.SDCPP_DEFAULT_STEPS} recommended for this engine"
                           if is_sdcpp else None),
        }

    @app.get("/api/status")
    def api_status():
        return worker.snapshot()

    # ---- sheet
    @app.post("/api/sheet")
    def api_sheet_upload(file: UploadFile = File(...), retry_failed: bool = Form(False),
                         default_size: str | None = Form(None)):
        settle_busy()
        size = _default_size(default_size)
        base = re.split(r"[\\/]", file.filename or "")[-1].strip()
        if not base.lower().endswith(".xlsx"):
            raise Invalid("Only .xlsx files can be uploaded.",
                          "In Excel choose File > Save As > Excel Workbook (.xlsx), then upload that.")
        chunks, total = [], 0
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise Invalid("The file is larger than 20 MB.",
                              "Split the sheet into smaller files and upload them one at a time.")
            chunks.append(chunk)
        if total == 0:
            raise Invalid("The file is empty.", "Choose the sheet you saved from Excel.")
        safe = names.safe_component(base[:-5]) + ".xlsx"
        with tempfile.TemporaryDirectory(prefix="medimg-upload-") as tmp:
            src = Path(tmp) / safe
            src.write_bytes(b"".join(chunks))
            sheet.read_rows(src)               # raises SheetError before anything is imported
            with ref.lock:
                dest = sheet.import_sheet(src, cur_store().root)
        steps = settings.steps
        with ref.lock:
            ref.path, ref.original_name = dest, safe
            raw, rows = validated(dest, retry_failed=retry_failed, size=size)
            persist_recomputed(dest, raw, rows)
        return report_json(dest, safe, rows, size=size, steps=steps, flt=None)

    @app.get("/api/sheet")
    def api_sheet_get(retry_failed: bool = False, default_size: str | None = None,
                      subject: str | None = None, unit: str | None = None,
                      lecture: str | None = None):
        path, name = want_sheet()
        size = _default_size(default_size)
        with ref.lock:
            _raw, rows = validated(path, retry_failed=retry_failed, size=size)
        flt = {k: v for k, v in (("subject", subject), ("unit", unit), ("lecture", lecture)) if v}
        return report_json(path, name, rows, size=size, steps=settings.steps, flt=flt or None)

    @app.get("/api/sheet/download")
    def api_sheet_download():
        path, name = want_sheet()
        with ref.lock:
            data = path.read_bytes()
        ascii_name = re.sub(r'[^\x20-\x7e]', "_", name).replace('"', "'")
        disp = f'attachment; filename="{ascii_name}"'
        if ascii_name != name:
            disp += f"; filename*=UTF-8''{quote(name)}"
        return Response(content=data, headers={"Content-Disposition": disp},
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.post("/api/sheet/estimate")
    def api_sheet_estimate(req: EstimateRequest):
        size = _default_size(req.default_size)
        steps = req.steps or settings.steps
        count = max(0, req.count)
        sizes: list[tuple[int, int]] = []
        with ref.lock:
            path = ref.path
        if path is not None and path.is_file():
            with ref.lock:
                _raw, rows = validated(path, retry_failed=False, size=size)
            flt = {k: v for k, v in (req.filter or {}).items() if v}
            sizes = [r.size or size for r in sheet.select_batch(rows, count, flt or None)]
        sizes += [size] * (count - len(sizes))
        seconds = sum(per_image_s(w, h, steps) for w, h in sizes)
        return {"count": count, "seconds": seconds, "per_image_s": (seconds / count) if count else 0.0}

    # ---- jobs
    @app.post("/api/jobs/batch", status_code=202)
    def api_batch(req: BatchRequest):
        settle_busy()
        if req.count < 1:
            raise Invalid("The number of images must be at least 1.", "Type a number such as 5.")
        path, name = _batch_sheet()
        size = _default_size(req.default_size)
        steps = req.steps or settings.steps
        flt = {k: v for k, v in (req.filter or {}).items() if v}
        with ref.lock:
            raw, rows = validated(path, retry_failed=False, size=size)
            persist_recomputed(path, raw, rows)   # never rewrite unselected failed rows
            if req.retry_failed:
                _raw2, rows = validated(path, retry_failed=True, size=size)
            chosen = sheet.select_batch(rows, req.count, flt or None)
            safe_rows, blocked = [], {}
            for r in chosen:                    # server-side gate, before the worker's own re-check
                reason = rules.check_prompt(r.prompt)
                if reason:
                    blocked[r.idx] = {"Status": "blocked", "Error": reason}
                else:
                    safe_rows.append(r)
            if blocked:
                sheet.write_rows(path, blocked)
        if not safe_rows:
            raise Invalid("There are no pending rows to generate.",
                          "Check the counts: only pending rows with no problems are generated. "
                          "Turn on Retry failed rows to include failed ones.")
        spec = JobSpec(kind="batch", rows=row_jobs_for(safe_rows, size, steps),
                       sheet_path=path, sheet_name=name)
        job_id = worker.submit(spec)
        return {"job_id": job_id, "rows": [r.idx for r in safe_rows]}

    def _batch_sheet() -> tuple[Path, str]:
        with ref.lock:
            path, name = ref.path, ref.original_name
        if path is None or not path.is_file():
            raise Invalid("No sheet is loaded.", "Upload an .xlsx sheet first.")
        return path, name

    @app.post("/api/jobs/single", status_code=202)
    def api_single(req: SingleRequest):
        if not (req.prompt or "").strip():
            raise Invalid("The prompt is empty.", "Write a prompt that describes the image.")
        reason = rules.check_prompt(req.prompt)
        if reason:
            raise Blocked(reason, rules.HINT)
        settle_busy()
        parts = [(x or "").strip() for x in (req.subject, req.unit, req.lecture)]
        if any(parts) and not all(parts):
            raise Invalid("Subject, Unit and Lecture must all be filled, or all left empty.",
                          "Fill all three to save into the gallery tree, or clear them to save under _single.")
        seed = req.seed if req.seed is not None else random_seed()
        name = (req.image_name or "").strip() or datetime.now().strftime("single_%Y%m%d_%H%M%S") + f"_{seed}"
        rel = names.rel_path(parts[0], parts[1], parts[2], name)
        if cur_store().exists(rel):
            raise Invalid(f"{rel} already exists.", "Choose another Image Name, or leave it empty.")
        job = RowJob(prompt=req.prompt, seed=seed, steps=req.steps if req.steps is not None else settings.steps,
                     width=req.width or config.DEFAULT_WIDTH, height=req.height or config.DEFAULT_HEIGHT,
                     subject=parts[0], unit=parts[1], lecture=parts[2], image_name=name)
        job_id = worker.submit(JobSpec(kind="single", rows=[job]))
        return {"job_id": job_id, "rel_path": rel}

    @app.post("/api/jobs/regenerate", status_code=202)
    def api_regenerate(req: RegenerateRequest):
        if not ID_RE.match(req.image_id or ""):
            raise NotFound("No image with that id.", "Refresh the gallery.")
        cur_store().refresh()
        rec = cur_store().load_record(req.image_id)
        if rec is None:
            raise NotFound("No image with that id.", "Refresh the gallery.")
        reason = rules.check_prompt(rec.prompt)
        if reason:
            raise Blocked(reason, rules.HINT)
        settle_busy()
        sheet_row, spec_path, spec_name = None, None, None
        with ref.lock:
            path, name = ref.path, ref.original_name
        if path is not None and path.is_file():
            try:
                with ref.lock:
                    _title, raw = sheet.read_rows(path)
            except MedimgError:
                raw = []
            key = tuple(x.strip().casefold() for x in (rec.subject, rec.unit, rec.lecture, rec.image_name))
            for r in raw:
                if tuple(x.strip().casefold() for x in (r.subject, r.unit, r.lecture, r.image_name)) == key:
                    sheet_row, spec_path, spec_name = r.idx, path, name
                    break
        seed = random_seed()
        job = RowJob(prompt=rec.prompt, seed=seed, steps=rec.steps, width=rec.width, height=rec.height,
                     subject=rec.subject, unit=rec.unit, lecture=rec.lecture,
                     image_name=rec.image_name, sheet_row=sheet_row, overwrite=True)
        job_id = worker.submit(JobSpec(kind="regenerate", rows=[job], sheet_path=spec_path,
                                       sheet_name=spec_name))
        return {"job_id": job_id, "seed": seed, "sheet_row": sheet_row}

    @app.post("/api/jobs/cancel")
    def api_cancel():
        return {"cancelled": worker.cancel()}

    # ---- gallery and files
    @app.get("/api/gallery/tree")
    def api_tree():
        cur_store().refresh()
        return cur_store().tree()

    @app.get("/api/gallery/images")
    def api_images(subject: str | None = None, unit: str | None = None, lecture: str | None = None):
        st = cur_store()
        out = []
        for r in st.list_images(subject or None, unit or None, lecture or None):
            out.append({"id": r.id, "rel_path": r.rel_path, "image_name": r.image_name,
                        "url": f"/files/{r.id}.png", "thumb_url": f"/files/{r.id}/thumb.jpg",
                        "record": asdict(r)})
        return out

    def _record_or_404(image_id: str):
        if not ID_RE.match(image_id or ""):
            raise NotFound("No image with that id.", "Refresh the gallery.")
        rec = cur_store().load_record(image_id)
        if rec is None:
            cur_store().refresh()
            rec = cur_store().load_record(image_id)
        if rec is None:
            raise NotFound("No image with that id.", "Refresh the gallery.")
        return rec

    @app.get("/api/images/{image_id}")
    def api_image(image_id: str):
        return asdict(_record_or_404(image_id))

    @app.get("/files/{name}")
    def file_png(name: str):
        m = _FILE_PNG_RE.match(name)
        if not m:
            raise NotFound("No such file.", "Refresh the gallery.")
        rec = _record_or_404(m.group(1))
        p = cur_store().path_for(rec.rel_path)
        if not p.is_file():
            raise NotFound("The image file is missing.", "Refresh the gallery.")
        return FileResponse(p, media_type="image/png")

    @app.get("/files/{image_id}/thumb.jpg")
    def file_thumb(image_id: str):
        rec = _record_or_404(image_id)
        return FileResponse(cur_store().thumb_path(rec.id), media_type="image/jpeg")

    @app.post("/api/images/{image_id}/open-folder")
    def api_open_folder(image_id: str):
        _record_or_404(image_id)
        return {"ok": bool(_open_folder(cur_store().folder_of(image_id)))}

    # ---- device
    @app.get("/api/device")
    def api_device():
        p = current_profile()
        report, table = "", []
        if p:
            try:
                report = render_report(p)
            except Exception:
                report = ""
            try:
                if engine.name == "sdcpp":
                    table = estimates_table(
                        p, settings.steps if getattr(settings, "steps_explicit", False)
                        else config.SDCPP_DEFAULT_STEPS, presets=config.SDCPP_SIZE_PRESETS)
                else:
                    table = estimates_table(p, settings.steps)
            except Exception:
                table = []
        name = ((p or {}).get("backend") or {}).get("name")
        no_record = engine.name == "sdcpp" and not ((p or {}).get("actuals") or [])
        return {"profile": p, "report": report, "estimates": table,
                "unverified": engine.name == "diffusers" or name == "diffusers" or no_record,
                "unverified_text": ("This engine has no real-run record on this computer yet."
                                    if engine.name == "sdcpp" and no_record else None)}

    @app.post("/api/device/benchmark", status_code=202)
    def api_benchmark():
        settle_busy()
        return {"job_id": worker.submit(JobSpec(kind="benchmark"))}

    # ---- settings
    def settings_json() -> dict:
        return {"output_root": str(cur_store().root), "port": settings.port, "steps": settings.steps,
                "unload_after_job": settings.unload_after_job}

    @app.get("/api/settings")
    def api_settings_get():
        return settings_json()

    @app.put("/api/settings")
    async def api_settings_put(request: Request):
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise Invalid("The settings request is not valid JSON.", "Use the Save button in the app.")
        settle_busy()
        new_root = None
        if body.get("output_root") not in (None, ""):
            if not isinstance(body["output_root"], str):
                raise Invalid("The output folder must be text.", "Type a folder path.")
            new_root = Path(body["output_root"]).expanduser()
        steps = body.get("steps", settings.steps)
        if (isinstance(steps, bool) or not isinstance(steps, int)
                or not config.STEPS_MIN <= steps <= config.STEPS_MAX):
            raise Invalid(f"Steps must be a whole number from {config.STEPS_MIN} to {config.STEPS_MAX}.",
                          "Use 8 or 9 for the best results.")
        unload = settings.unload_after_job
        if "unload_after_job" in body:
            unload = body["unload_after_job"]
            if unload is not None and not isinstance(unload, bool):
                raise Invalid("Unload after each image must be yes, no or automatic.",
                              "Pick one of the three choices.")
        if new_root is not None and new_root.resolve() != cur_store().root.resolve():
            try:
                new_store = Store(new_root)
            except OSError as e:
                raise Invalid(f"Cannot use that output folder: {e.strerror or e}.",
                              "Choose a folder you can write to, for example one inside your home folder.")
            store_box["store"] = new_store
            worker.store = new_store
            settings.output_root = new_root
            load_current_from_disk()
        settings.steps = steps
        settings.steps_explicit = True
        settings.unload_after_job = unload
        worker.unload_after_job = _effective_unload(settings, current_profile())
        try:
            config.save_settings(settings, Path(config.SETTINGS_PATH))
        except OSError as e:
            raise Invalid(f"Settings were applied but could not be saved: {e.strerror or e}.",
                          "They will reset when the app restarts.")
        return settings_json()

    # ---- static
    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


# --------------------------------------------------------------------------- CLI entry
def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((LOOPBACK, port)) == 0


def _next_free_port(start: int) -> int:
    for p in range(start + 1, start + 50):
        if p <= 65535 and not _port_in_use(p):
            return p
    return start + 1


def main(args) -> int:
    import uvicorn

    settings = config.load_settings(Path(config.SETTINGS_PATH))
    if getattr(args, "port", None):
        settings.port = int(args.port)
    if getattr(args, "output_root", None):
        settings.output_root = Path(args.output_root).expanduser()
    port = settings.port

    if _port_in_use(port):
        print(f"port {port} in use; run start --port {_next_free_port(port)}", file=sys.stderr)
        return 1

    fake = bool(getattr(args, "fake_engine", False))
    profile = load_profile(Path(config.PROFILE_PATH))
    from medimg.engines import make_engine
    if fake:
        engine = make_engine("fake", profile, fake=True)
    else:
        want = getattr(args, "engine", None) or settings.engine
        want = want if want in config.ENGINE_CHOICES and want != "auto" else None
        backend = ((profile or {}).get("backend") or {}).get("name")
        if not backend or (want and want != backend):
            from medimg.assess import decide, detect
            decision = decide(detect(disk_path=settings.output_root), engine=want)
            if not decision.supported or not decision.backend:
                print(f"Problem: {decision.reason}", file=sys.stderr)
                if decision.fix:
                    print(f"Fix: {decision.fix}", file=sys.stderr)
                return 1
            backend = decision.backend
            be: dict = {"name": backend, "offload_mode": decision.offload_mode}
            if backend == "sdcpp":
                dev = decision.device
                if dev and dev != "cpu":
                    from medimg.smoke import _confirmed_device
                    dev = _confirmed_device(dev, decision.tier)
                be["device"] = dev
                be["sdcpp"] = {"build": None, "tier": decision.tier}
                try:
                    from medimg.sdcpp import install
                    import platform
                    be["sdcpp"]["build"] = install.chosen_build(platform.system(), platform.machine())
                except Exception:
                    pass
                if not be["sdcpp"]["build"]:
                    be.pop("sdcpp")
            # keep machine/benchmark/actuals of an existing profile; never write it back
            profile = _profile_for_engine(profile, be)
        engine = make_engine(backend, profile)

    app = create_app(engine, settings, profile)
    url = f"http://{LOOPBACK}:{port}"
    print(f"Serving on {url} (local only). Press Ctrl+C to stop.")
    if not getattr(args, "no_browser", False):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, workers=1, reload=False)
    return 0
