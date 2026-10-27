"""`python -m medimg selftest`: make one small test image per engine/tier and write a report.

Never downloads anything and never writes device_profile.json. Reports go to
<output root>/_selftest/ as a .txt (to read) and a .json (to send to the project owner).
"""
from __future__ import annotations

import dataclasses
import gc
import importlib.util
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psutil

from medimg import config, names, osutil, rules
from medimg.assess import decide, detect, load_profile
from medimg.errors import Blocked, Cancelled, MedimgError, ModelUnavailable
from medimg.sdcpp import install, pins
from medimg.sdcpp.procs import MemSampler

SELFTEST_PROMPT = ("Clinical medical illustration of an adult human hand, neutral grey background, "
                   "sharp detail")
SELFTEST_SEED = 12345
SCHEMA = "medimg-selftest/1"
DEFAULT_TIMEOUT_S = 1800
GRACE_S = 30
RUN_SETUP_FIRST = "Run setup first, then run the self-test again."
NOTHING_MSG = "Nothing is installed to test yet. Run setup first, then run the self-test again."

FIXES = {
    "gpu_oom": "Close other programs and run the self-test again; the processor will be used.",
    "ram_oom": "Close other programs (browsers use a lot of memory) and run the self-test again.",
    "no_model": "Run setup again; it downloads only what is missing.",
    "crash": "Send both report files to the project owner.",
    "timeout": "Try a smaller size or a lower tier, or send both report files to the project owner.",
    "error": "Send both report files to the project owner.",
    "blocked": "This is a bug in the self-test prompt; send both report files to the project owner.",
    "not_installed": RUN_SETUP_FIRST,
}


@dataclass
class Candidate:
    engine: str              # "sdcpp" | "mflux" | "diffusers" | "fake"
    tier: str | None         # sdcpp only
    device: str | None       # sdcpp: requested device; others None
    build: str | None        # sdcpp only
    offload_mode: str | None  # diffusers only
    ready: bool
    skip_reason: str | None
    label: str


class CandidateList(list):
    """A list of candidates that also carries plain-language planning notes."""

    def __init__(self, *a) -> None:
        super().__init__(*a)
        self.notes: list[str] = []


# ---------------------------------------------------------------- planning

def _device_words(device: str | None) -> str:
    if not device or device == "cpu":
        return "on the processor"
    return f"on the graphics chip ({device})"


def _sd_label(tier, device) -> str:
    return f"sd.cpp, tier {tier}, {_device_words(device)}"


def _importable(*mods: str) -> bool:
    try:
        return all(importlib.util.find_spec(m) is not None for m in mods)
    except Exception:
        return False


def _native_candidate(d) -> Candidate:
    from medimg import download
    if d.backend == "mflux":
        ok_mod = _importable("mflux")
        ok_w = ok_mod and download.mflux_cached() is not None
        label = "mflux (Apple silicon graphics)"
        mode = None
    else:
        ok_mod = _importable("diffusers", "torch")
        ok_w = ok_mod and download.diffusers_cached(d.offload_mode or "model_cpu_offload")
        label = f"diffusers (NVIDIA graphics card, {d.offload_mode or 'default'} mode)"
        mode = d.offload_mode
    reason = None
    if not ok_mod:
        reason = f"The {d.backend} program is not installed. {RUN_SETUP_FIRST}"
    elif not ok_w:
        reason = f"The {d.backend} model files are not downloaded. {RUN_SETUP_FIRST}"
    return Candidate(d.backend, None, None, None, mode, ok_mod and ok_w, reason, label)


def _pick_device(machine, settings, profile, d, build, tier, exe_ready) -> str:
    be = (profile or {}).get("backend") or {}
    psd = be.get("sdcpp") or {}
    failed = {str(x).lower() for x in (psd.get("failed_devices") or [])}
    if (be.get("name") == "sdcpp" and psd.get("build") == build and psd.get("tier") == tier
            and psd.get("device_proven") is not False and be.get("device")
            and str(be["device"]).lower() not in failed):
        return str(be["device"])
    device = getattr(settings, "sdcpp_device", None) or (d.device if d else None) or "cpu"
    if str(device).lower() in failed:
        return "cpu"
    if device != "cpu" and exe_ready:
        from medimg import smoke
        device = smoke._confirmed_device(device, tier)
    return device


def _sdcpp_candidates(machine, settings, profile, *, all_tiers, tier, notes) -> list[Candidate]:
    build = install.chosen_build(machine.os_name, machine.arch)
    if build is None:
        notes.append("This computer has no stable-diffusion.cpp program "
                     f"(processor type {machine.arch}).")
        return []
    from medimg import download
    exe_ready = install.binary_cached(build) is not None
    tiers = [tier] if tier else (list(pins.TIERS) if all_tiers else [None])
    out: list[Candidate] = []
    for t in tiers:
        try:
            d = decide(machine, engine="sdcpp", tier=t)
        except Exception:
            d = None
        tt = t or (d.tier if d else None) or pins.tier_for_ram(machine.ram_total_gb)
        if d is not None and not d.supported:
            out.append(Candidate("sdcpp", tt, "cpu", build, None, False,
                                 f"{d.reason} {d.fix}".strip(), _sd_label(tt, "cpu")))
            continue
        device = _pick_device(machine, settings, profile, d, build, tt, exe_ready)
        models_ready = download.sdcpp_cached(tt, None)
        reason = None
        if not exe_ready:
            reason = f"The image program (sd-cli) is not installed. {RUN_SETUP_FIRST}"
        elif not models_ready:
            reason = f"The '{tt}' model files are not downloaded. {RUN_SETUP_FIRST}"
        out.append(Candidate("sdcpp", tt, device, build, None, exe_ready and models_ready,
                             reason, _sd_label(tt, device)))
    return out


def plan_candidates(machine, settings, profile: dict | None, *, quick=False, all_tiers=False,
                    engine: str | None = None, tier: str | None = None,
                    fake=False) -> list[Candidate]:
    out = CandidateList()
    if fake:
        out.append(Candidate("fake", None, None, None, None, True, None,
                             "fake engine (no real model, for testing)"))
        return out
    tier = None if tier in (None, "auto") else tier
    try:
        auto = decide(machine)
    except Exception:
        auto = None
    auto_backend = auto.backend if auto is not None and auto.supported else None
    native: list[Candidate] = []
    sd: list[Candidate] = []
    if engine != "sdcpp" and auto_backend in ("mflux", "diffusers"):
        native.append(_native_candidate(auto))
    if engine != "auto" or auto_backend == "sdcpp":
        sd = _sdcpp_candidates(machine, settings, profile, all_tiers=all_tiers, tier=tier,
                               notes=out.notes)
    elif auto is not None and not auto.supported:
        out.notes.append(f"{auto.reason} {auto.fix}".strip())
    first = ((profile or {}).get("backend") or {}).get("name") or auto_backend
    out.extend(sorted(native + sd, key=lambda c: c.engine != first))
    if quick:
        ready = [c for c in out if c.ready]
        if ready:
            notes = out.notes
            out = CandidateList(ready[:1])
            out.notes = notes
    return out


# ---------------------------------------------------------------- one run

def _gb(n: float) -> float:
    return round(n / 1e9, 2)


def _free_gb() -> float | None:
    try:
        return _gb(psutil.virtual_memory().available)
    except Exception:
        return None


def _out_name(stem: str, index: int, c: Candidate) -> str:
    return f"{stem}_{index}_{c.engine}" + (f"_{c.tier}" if c.tier else "") + ".png"


def _new_run(c: Candidate, index: int, width, height, steps, seed) -> dict:
    return {
        "index": index, "label": c.label, "engine": c.engine, "tier": c.tier, "build": c.build,
        "model_id": None, "device_requested": c.device, "device_used": None, "fell_back": False,
        "width": width, "height": height, "steps": steps, "seed": seed,
        "status": "skipped", "failure_class": None, "cause": None, "fix": None,
        "load_s": None, "total_s": None, "per_step_s": None, "per_step_source": None,
        "phases": None, "peak_mem_gb": None, "ram_free_gb_before": None, "ram_free_gb_after": None,
        "image_path": None, "log_tail": [], "notes": [],
    }


def _default_factory(c: Candidate):
    from medimg.engines import make_engine
    profile = {"backend": {"device": c.device, "offload_mode": c.offload_mode,
                           "sdcpp": {"tier": c.tier, "build": c.build} if c.tier else {}}}
    return make_engine(c.engine, profile, fake=c.engine == "fake", tier=c.tier)


_engine_factory = _default_factory


def _device_used(eng, c: Candidate) -> str | None:
    if eng is None:
        return None
    if c.engine == "sdcpp":
        return getattr(eng, "device", None)
    return {"mflux": "metal (MLX)", "diffusers": "cuda", "fake": "none"}.get(c.engine)


def _classify(exc: BaseException, eng, timed_out: bool) -> tuple[str, str, str]:
    """(status, failure_class, cause) for an exception from load/generate."""
    if isinstance(exc, Cancelled):
        if timed_out:
            return "timeout", "timeout", "The test did not finish in time and was stopped."
        return "failed", "error", "The test was cancelled."
    if isinstance(exc, Blocked):
        return "blocked", "blocked", exc.cause
    if isinstance(exc, MemoryError):
        return "failed", "ram_oom", "The computer ran out of memory while making the image."
    cause = exc.cause if isinstance(exc, MedimgError) else (str(exc) or type(exc).__name__)
    cls = getattr(exc, "failure_class", None)
    if cls is None and isinstance(exc, ModelUnavailable):
        cls = "no_model"
    if cls is None and eng is not None and (getattr(eng, "last_failure", None) or {}).get("class"):
        cls = eng.last_failure["class"]
    if cls == "unknown":
        cls = "crash"
    if cls not in ("gpu_oom", "ram_oom", "no_model", "crash"):
        cls = "error"
    return "failed", cls, cause


def _run_candidate(c: Candidate, *, width, height, steps, seed, timeout_s, out_dir, stem, index,
                   engine_factory=None, say=print) -> tuple[dict, bool]:
    """Returns (run dict, abandoned). abandoned = an in-process engine thread is still alive."""
    run = _new_run(c, index, width, height, steps, seed)
    if rules.check_prompt(SELFTEST_PROMPT) is not None:
        run.update(status="blocked", failure_class="blocked",
                   cause="The self-test prompt was blocked by the adults-only check.",
                   fix=FIXES["blocked"])
        return run, False
    if not c.ready:
        run.update(status="skipped", failure_class="not_installed",
                   cause=c.skip_reason or "Not installed.", fix=RUN_SETUP_FIRST)
        return run, False

    factory = engine_factory or _engine_factory
    holder: dict = {}
    deadline = time.monotonic() + timeout_s
    run["ram_free_gb_before"] = _free_gb()
    sampler = MemSampler(os.getpid())
    sampler.start()
    t_start = time.perf_counter()

    def progress(phase: str, done: int, total: int) -> None:
        if phase == "denoising" and total:
            say(f"  step {done}/{total}")

    def work() -> None:
        try:
            eng = factory(c)
            holder["engine"] = eng
            t0 = time.perf_counter()
            eng.load()
            holder["load_s"] = time.perf_counter() - t0
            holder["result"] = eng.generate(SELFTEST_PROMPT, seed, steps, width, height, progress,
                                            lambda: time.monotonic() > deadline)
        except BaseException as e:  # noqa: BLE001 - reported, never raised
            holder["exc"] = e

    th = threading.Thread(target=work, daemon=True, name="medimg-selftest-run")
    th.start()
    th.join(timeout_s + GRACE_S)
    abandoned = th.is_alive()
    peak = sampler.stop()
    eng = holder.get("engine")
    run["load_s"] = round(holder["load_s"], 2) if "load_s" in holder else None
    run["ram_free_gb_after"] = _free_gb()
    run["model_id"] = getattr(eng, "model_id", None)
    run["device_used"] = _device_used(eng, c)
    run["notes"] = list(getattr(eng, "notes", None) or [])
    run["log_tail"] = list(getattr(eng, "last_log_tail", None) or [])[-40:]
    phases = getattr(eng, "last_phases", None)
    if phases:
        run["phases"] = {k: phases.get(k) for k in ("encode_s", "sample_s", "decode_s")}
    run["fell_back"] = bool(c.engine == "sdcpp" and c.device and run["device_used"]
                            and run["device_used"] != c.device)
    run["peak_mem_gb"] = _gb(peak)

    if abandoned:
        run.update(status="timeout", failure_class="timeout",
                   cause="The test did not stop after its time limit, so it was abandoned.",
                   fix=FIXES["timeout"], total_s=round(time.perf_counter() - t_start, 2))
        return run, True

    try:
        exc = holder.get("exc")
        if exc is not None:
            status, cls, cause = _classify(exc, eng, time.monotonic() > deadline)
            fix = exc.fix if isinstance(exc, MedimgError) and exc.fix else FIXES[cls]
            run.update(status=status, failure_class=cls, cause=cause, fix=fix,
                       total_s=round(time.perf_counter() - t_start, 2))
            return run, False
        res = holder["result"]
        path = out_dir / _out_name(stem, index, c)
        res.image.save(path, format="PNG")
        run["image_path"] = str(path)
        run["peak_mem_gb"] = round(max(run["peak_mem_gb"], float(res.peak_mem_gb or 0.0)), 2)
        run["total_s"] = round(res.time_s, 2)
        timing = getattr(eng, "last_timing", None)
        if timing and timing.get("sample_s"):
            run["per_step_s"] = round(timing["sample_s"] / steps, 2)
            run["per_step_source"] = "engine"
        else:
            run["per_step_s"] = round(res.time_s / steps, 2)
            run["per_step_source"] = "wallclock"
        run["status"] = "ok"
        return run, False
    finally:
        try:
            if eng is not None:
                eng.unload()
        except Exception:
            pass
        gc.collect()


def run_candidate(c: Candidate, *, width: int, height: int, steps: int, seed: int,
                  timeout_s: float, out_dir: Path, stem: str, index: int,
                  engine_factory=None) -> dict:
    return _run_candidate(c, width=width, height=height, steps=steps, seed=seed,
                          timeout_s=timeout_s, out_dir=Path(out_dir), stem=stem, index=index,
                          engine_factory=engine_factory)[0]


# ---------------------------------------------------------------- report

def git_commit(root: Path | None = None) -> str | None:
    """HEAD commit read straight from .git files (never runs git). None on any error."""
    try:
        git = Path(root or config.REPO_ROOT) / ".git"
        if git.is_file():
            txt = git.read_text(encoding="utf-8").strip()
            if not txt.startswith("gitdir:"):
                return None
            git = (git.parent / txt.split(":", 1)[1].strip()).resolve()
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head or None
        ref = head.split(":", 1)[1].strip()
        for base in (git, *([git.parent.parent] if (git / "commondir").exists() else [])):
            f = base / ref
            if f.is_file():
                return f.read_text(encoding="utf-8").strip() or None
        common = git
        if (git / "commondir").is_file():
            common = (git / (git / "commondir").read_text(encoding="utf-8").strip()).resolve()
            f = common / ref
            if f.is_file():
                return f.read_text(encoding="utf-8").strip() or None
        for line in (common / "packed-refs").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref and not line.startswith(("#", "^")):
                return parts[0]
    except Exception:
        return None
    return None


def _summary(runs: list[dict]) -> dict:
    n = {k: sum(1 for r in runs if r["status"] == k)
         for k in ("ok", "failed", "timeout", "skipped", "blocked")}
    bad = n["failed"] + n["timeout"] + n["blocked"]
    if n["ok"] >= 1 and bad == 0:
        verdict = "pass"
    elif n["ok"] == 0 and bad == 0:
        verdict = "nothing_to_test"
    else:
        verdict = "fail"
    return {**n, "verdict": verdict}


def build_report(*, started_at: str, finished_at: str, host: str, command: list[str],
                 options: dict, machine: dict | None, decision: dict | None,
                 profile_summary: dict | None, notes: list[str], runs: list[dict]) -> dict:
    return {
        "schema": SCHEMA, "app_version": config.VERSION, "git_commit": git_commit(),
        "started_at": started_at, "finished_at": finished_at, "host": host, "command": command,
        "options": options, "machine": machine, "decision": decision,
        "profile_summary": profile_summary, "notes": notes, "runs": runs,
        "summary": _summary(runs), "report_txt": None, "report_json": None,
    }


def _dur(s) -> str:
    if s is None:
        return "?"
    s = float(s)
    if s < 60:
        return f"{s:.1f}s"
    m, sec = divmod(int(round(s)), 60)
    return f"{m}m {sec:02d}s"


def _date(iso: str | None) -> str:
    try:
        d = datetime.fromisoformat(iso)
        off = d.strftime("%z")
        return d.strftime("%Y-%m-%d %H:%M") + (f" ({off[:3]}:{off[3:]})" if off else "")
    except Exception:
        return iso or "unknown"


_STATUS_WORD = {"failed": "FAILED", "timeout": "TIMED OUT", "skipped": "SKIPPED",
                "blocked": "BLOCKED"}


def render_text(report: dict) -> str:
    m = report.get("machine") or {}
    gpu = (m.get("gpu") or {}).get("name") or m.get("apple_chip") or "no graphics card found"
    s = report["summary"]
    total = len(report["runs"])
    verdict = {"pass": "PASS", "fail": "FAIL", "nothing_to_test": "NOTHING TO TEST"}[s["verdict"]]
    lines = [
        f"SELF-TEST REPORT — medical-image-gen {report.get('app_version')}",
        f"Computer : {m.get('os_name', '?')} {m.get('os_version', '')} ({m.get('arch', '?')}), "
        f"{m.get('cpu', '?')}, {m.get('ram_total_gb', '?')} GB RAM, {gpu}",
        f"Date     : {_date(report.get('started_at'))}",
        f"Result   : {verdict} — {s['ok']} of {total} test images made",
        "",
    ]
    for n in report.get("notes") or []:
        lines.append(f"Note: {n}")
    if report.get("notes"):
        lines.append("")
    for r in report["runs"]:
        i = r["index"]
        if r["status"] == "ok":
            lines.append(f"{i}. {r['label']}: OK")
            lines.append(f"   {r['width']}x{r['height']} at {r['steps']} steps in {_dur(r['total_s'])} "
                         f"({r['per_step_s']} s per step), model load {_dur(r['load_s'])}, "
                         f"peak memory {r['peak_mem_gb']} GB")
            lines.append(f"   Image: {r['image_path']}")
        else:
            lines.append(f"{i}. {r['label']}: {_STATUS_WORD[r['status']]} — {r['cause']}")
            if r.get("fix"):
                lines.append(f"   Fix: {r['fix']}")
        if r.get("fell_back"):
            lines.append(f"   The graphics chip failed; the test finished on the processor "
                         f"(asked for {r['device_requested']}, used {r['device_used']}).")
        for n in r.get("notes") or []:
            lines.append(f"   Note: {n}")
        if r["status"] != "ok" and r.get("log_tail"):
            lines.append("   Last lines from the image program:")
            lines.extend(f"     {ln}" for ln in r["log_tail"][-15:])
    lines += ["", "Send both report files (.txt and .json) to the project owner."]
    return "\n".join(lines) + "\n"


def write_report(report: dict, out_dir: Path, stem: str) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    txt, js = out_dir / f"{stem}.txt", out_dir / f"{stem}.json"
    report["report_txt"], report["report_json"] = str(txt), str(js)
    txt.write_text(render_text(report), encoding="utf-8")
    js.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
                  encoding="utf-8")
    return txt, js


# ---------------------------------------------------------------- command

def _hard_exit(code: int) -> None:
    """Leave now even if a model thread is stuck. A wrapper so tests can replace it."""
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


def _say(text: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    try:
        print(text, file=stream, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"), file=stream, flush=True)


def _profile_summary(profile: dict | None) -> dict:
    be = (profile or {}).get("backend") or {}
    sd = be.get("sdcpp") or {}
    return {"backend": be.get("name"), "device": be.get("device"),
            "device_proven": sd.get("device_proven"), "tier": sd.get("tier")}


def _decision_dict(machine) -> dict:
    try:
        d = decide(machine)
        return {"backend": d.backend, "supported": d.supported, "reason": d.reason,
                "reason_code": getattr(d, "reason_code", "ok"), "device": d.device, "tier": d.tier}
    except Exception as e:
        return {"backend": None, "supported": None, "reason": f"Could not decide: {e}",
                "reason_code": None, "device": None, "tier": None}


def _cli_args() -> list[str]:
    return sys.argv[sys.argv.index("selftest") + 1:] if "selftest" in sys.argv else []


def run(args) -> int:
    from medimg import smoke
    width, height = smoke.parse_size(getattr(args, "size", None) or "512x512")
    steps = int(getattr(args, "steps", None) or 4)
    timeout_s = float(getattr(args, "timeout", None) or DEFAULT_TIMEOUT_S)
    quick = bool(getattr(args, "quick", False))
    all_tiers = bool(getattr(args, "all_tiers", False))
    engine = getattr(args, "engine", None)
    engine = None if engine in (None, "") else engine
    tier = getattr(args, "tier", None)
    tier = None if tier in (None, "", "auto") else tier
    fake = bool(getattr(args, "fake_engine", False))
    as_json = bool(getattr(args, "json", False))
    no_open = bool(getattr(args, "no_open", False))

    settings = config.load_settings()
    root = Path(getattr(args, "output_root", None) or settings.output_root)
    out_dir = root / "_selftest"
    out_dir.mkdir(parents=True, exist_ok=True)

    def say(text: str) -> None:
        _say(text, err=as_json)

    started = datetime.now().astimezone()
    machine = detect()
    profile = load_profile()
    host_raw = getattr(machine, "hostname", "") or ""
    host = names.safe_component(host_raw) if host_raw.strip() else "computer"
    stem = f"selftest_{host}_{started.strftime('%Y%m%d-%H%M%S')}"
    cands = plan_candidates(machine, settings, profile, quick=quick, all_tiers=all_tiers,
                            engine=engine, tier=tier, fake=fake)
    notes = list(getattr(cands, "notes", []))

    runs: list[dict] = []
    abandoned = False
    for i, c in enumerate(cands, 1):
        if abandoned:
            r = _new_run(c, i, width, height, steps, SELFTEST_SEED)
            r["cause"] = "not run: an earlier test did not stop"
            runs.append(r)
            continue
        say(f"Test {i} of {len(cands)}: {c.label}")
        r, abandoned = _run_candidate(c, width=width, height=height, steps=steps,
                                      seed=SELFTEST_SEED, timeout_s=timeout_s, out_dir=out_dir,
                                      stem=stem, index=i, say=say)
        runs.append(r)
        if r["status"] != "ok":
            say(f"  {r['status']}: {r['cause']}")

    if not cands:
        notes.append("No test could be planned for this computer.")
    options = {"quick": quick, "all_tiers": all_tiers, "engine": engine, "tier": tier,
               "size": f"{width}x{height}", "steps": steps, "timeout_s": timeout_s,
               "fake_engine": fake}
    report = build_report(
        started_at=started.isoformat(timespec="seconds"),
        finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        host=host, command=["python", "-m", "medimg", "selftest", *_cli_args()],
        options=options, machine=dataclasses.asdict(machine),
        decision=_decision_dict(machine), profile_summary=_profile_summary(profile),
        notes=notes, runs=runs)
    txt, js = write_report(report, out_dir, stem)

    verdict = report["summary"]["verdict"]
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        _say(render_text(report))
    if verdict == "nothing_to_test":
        _say(NOTHING_MSG, err=as_json)
    _say(f"Report (text): {txt}", err=as_json)
    _say(f"Report (data): {js}", err=as_json)
    if not no_open and not os.environ.get("CI"):
        osutil.open_folder(out_dir)
    if abandoned:
        _hard_exit(1)
        return 1
    return {"pass": 0, "fail": 1, "nothing_to_test": 2}[verdict]
