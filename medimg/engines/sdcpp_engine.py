"""stable-diffusion.cpp engine: one `sd-cli` child process per image. No heavy imports."""
from __future__ import annotations

import codecs
import logging
import queue
import shutil
import tempfile
import threading
import time
from pathlib import Path

from PIL import Image

from medimg.config import SDCPP_MODEL_ID
from medimg.engines.base import CancelFn, GenResult, ProgressFn
from medimg.errors import Cancelled, Invalid, MedimgError, ModelUnavailable
from medimg.sdcpp.install import SdcppPaths
from medimg.sdcpp.procs import MemSampler, kill_all_live, kill_tree, popen_group
from medimg.sdcpp.progress import (NO_BINARY_CAUSE, NO_BINARY_FIX, ProgressParser,
                                   classify_failure)

log = logging.getLogger("medimg.sdcpp")

FALLBACK_NOTE = "The graphics chip ran out of memory; using the processor."
FALLBACK_NOTE_OTHER = "The graphics chip could not be used; using the processor."


def build_argv(paths: SdcppPaths, device: str, prompt: str, seed: int, steps: int, width: int,
               height: int, out_path: Path, threads: int | None = None) -> list[str]:
    if prompt.startswith("-"):
        prompt = " " + prompt
    argv = [*paths.sd_cli,
            "--diffusion-model", str(paths.diffusion), "--llm", str(paths.llm),
            "--vae", str(paths.vae),
            "-p", prompt, "--cfg-scale", "1.0", "--steps", str(steps),
            "-W", str(width), "-H", str(height),
            "-s", str(seed), "-o", str(out_path), "--backend", device,
            "--offload-to-cpu", "--mmap", "--vae-tiling", "--log-level", "info"]
    if threads:
        argv += ["--threads", str(threads)]
    return argv


def _error_for(cls: str, cause: str, fix: str) -> MedimgError:
    if cls == "no_model":
        return ModelUnavailable(cause, fix)
    return Invalid(cause, fix)


class _Failed(Exception):
    def __init__(self, cls: str, cause: str, fix: str, rc: int | None = None) -> None:
        super().__init__(cause)
        self.cls, self.cause, self.fix, self.rc = cls, cause, fix, rc


class SdcppEngine:
    name = "sdcpp"

    def __init__(self, paths: SdcppPaths, device: str = "cpu", *, threads: int | None = None,
                 popen=popen_group, mem_sampler=MemSampler, poll_s: float = 0.25) -> None:
        self.paths = paths
        self.device = device
        self.threads = threads
        self._popen = popen
        self._mem_sampler = mem_sampler
        self._poll_s = poll_s
        self.model_id = f"{SDCPP_MODEL_ID}/{paths.diffusion.name}"
        self.loaded = False
        self.notes: list[str] = []
        # Set after each generate(): {"sample_s", "steps", "overhead_s"} from sd-cli's own timings,
        # so benchmark() can separate step time from load/encode/decode. None if sd-cli printed none.
        self.last_timing: dict | None = None
        self._last_sample_s: float | None = None
        self.last_failure: dict | None = None
        self.last_log_tail: list[str] = []
        self.last_phases: dict | None = None

    def load(self, on_progress: ProgressFn | None = None) -> None:
        if self.loaded:
            return
        if on_progress:
            on_progress("loading", 0, 0)
        for p in (self.paths.diffusion, self.paths.llm, self.paths.vae):
            if not Path(p).is_file():
                raise ModelUnavailable(f"A model file is missing: {Path(p).name}.",
                                       "Run setup again; it re-downloads only what is missing.")
        self.loaded = True
        if on_progress:
            on_progress("loading", 1, 1)

    def abort(self) -> None:
        """Kill any running sd-cli now (used on shutdown). Never raises."""
        kill_all_live(grace_s=1.0)

    def unload(self) -> None:
        self.loaded = False

    def generate(self, prompt: str, seed: int, steps: int, width: int, height: int,
                 on_progress: ProgressFn, should_cancel: CancelFn) -> GenResult:
        if not self.loaded:
            raise RuntimeError("engine not loaded")
        t0 = time.perf_counter()
        self.last_timing = None
        self.last_failure = None
        self.last_log_tail = []
        self.last_phases = None
        fell_back = False
        attempt = 0
        while True:
            attempt += 1
            try:
                image, peak, ran_steps = self._run_once(prompt, seed, steps, width, height,
                                                        on_progress, should_cancel)
            except _Failed as f:
                self.last_failure = {"class": f.cls, "cause": f.cause, "fix": f.fix,
                                     "returncode": f.rc}
                if f.cls not in ("no_model", "ram_oom") and self.device != "cpu" and attempt == 1:
                    self.device = "cpu"
                    self.notes.append(FALLBACK_NOTE if f.cls == "gpu_oom" else FALLBACK_NOTE_OTHER)
                    fell_back = True
                    continue
                err = _error_for(f.cls, f.cause, f.fix)
                err.failure_class = f.cls
                raise err from None
            break
        total_s = time.perf_counter() - t0
        if self._last_sample_s:
            self.last_timing = {"sample_s": self._last_sample_s, "steps": ran_steps,
                                "overhead_s": max(total_s - self._last_sample_s, 0.0)}
        engine = f"sdcpp {self.paths.release}" + (" (cpu, fallback)" if fell_back else "")
        return GenResult(image=image, seed=seed, time_s=total_s,
                         peak_mem_gb=peak / 1e9, steps=ran_steps, engine=engine,
                         model_id=self.model_id)

    def _run_once(self, prompt, seed, steps, width, height, on_progress, should_cancel):
        on_progress("encoding", 0, 0)
        tmp = Path(tempfile.mkdtemp(prefix="medimg-sdcpp-"))
        proc = None
        sampler = None
        try:
            out = tmp / "out.png"
            argv = build_argv(self.paths, self.device, prompt, seed, steps, width, height,
                              out, self.threads)
            try:
                proc = self._popen(argv, self.paths.cwd, env=None)
            except (FileNotFoundError, PermissionError):
                raise ModelUnavailable(NO_BINARY_CAUSE, NO_BINARY_FIX) from None
            sampler = self._mem_sampler(proc.pid)
            sampler.start()

            q: queue.Queue = queue.Queue()

            def reader() -> None:
                try:
                    while True:
                        chunk = proc.stdout.read(4096)
                        if not chunk:
                            break
                        q.put(chunk)
                except Exception:
                    pass
                finally:
                    q.put(None)

            rt = threading.Thread(target=reader, daemon=True, name="medimg-sdcpp-reader")
            rt.start()
            parser = ProgressParser()
            dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
            seen_n = 0
            while True:
                if should_cancel():
                    kill_tree(proc)
                    raise Cancelled()
                try:
                    chunk = q.get(timeout=self._poll_s)
                except queue.Empty:
                    continue
                eof = chunk is None
                text = dec.decode(b"", final=True) if eof else dec.decode(chunk)
                if eof and not text:
                    break
                for line in text.replace("\r", "\n").split("\n"):
                    line = line.replace("\x1b[K", "").rstrip()
                    if line:
                        log.log(logging.INFO if line.startswith("[E]") else logging.DEBUG,
                                "%s", line)
                for ev in parser.feed(text):
                    if ev[0] == "denoising":
                        seen_n = ev[2]
                    on_progress(*ev)
                    if should_cancel():
                        kill_tree(proc)
                        raise Cancelled()
                if eof:
                    break
            try:
                rc = proc.wait(timeout=30)
            except Exception:
                kill_tree(proc)
                rc = proc.returncode
            rt.join(timeout=2)
            peak = sampler.stop()
            sampler = None
            st = parser.state
            self._last_sample_s = st.sample_s
            self.last_log_tail = list(st.tail)
            self.last_phases = {"encode_s": st.encode_s, "sample_s": st.sample_s,
                                "decode_s": st.decode_s, "total_s": st.total_s}
            if rc == 0 and st.saved_ok and out.is_file():
                with Image.open(out) as im:
                    im.load()
                    image = im.copy()
                return image, peak, seen_n or steps
            cls, cause, fix = classify_failure(rc, st)
            raise _Failed(cls, cause, fix, rc)
        finally:
            if proc is not None:
                if proc.poll() is None:
                    kill_tree(proc)
                try:
                    proc.stdout.close()
                except Exception:
                    pass
            if sampler is not None:
                sampler.stop()
            shutil.rmtree(tmp, ignore_errors=True)
