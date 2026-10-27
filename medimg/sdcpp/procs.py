"""Child-process control for sd-cli: spawn in its own group, kill the whole tree, sample memory."""
from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

import psutil

_WIN = sys.platform == "win32"


_LIVE: set = set()
_LIVE_LOCK = threading.Lock()
_JOB = None  # Windows job handle (kept open for the life of the process)


def _make_job():
    """Windows: a Job Object that kills its members when this process dies. Best effort."""
    global _JOB
    if _JOB is not None:
        return _JOB
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE

        class _Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in
                        ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]

        class _Ext(ctypes.Structure):
            _fields_ = [("Basic", _Basic), ("IO", _IO),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _Ext()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info),
                                           ctypes.sizeof(info)):
            return None
        _JOB = job
        return job
    except Exception:
        return None


def _assign_to_job(proc: subprocess.Popen) -> None:
    try:
        import ctypes
        from ctypes import wintypes

        job = _make_job()
        if job:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(proc._handle)))
    except Exception:
        pass


def _pdeathsig() -> None:
    """Linux preexec: SIGKILL this child if the parent dies."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
    except Exception:
        pass


def kill_all_live(grace_s: float = 1.0) -> None:
    """Kill every sd-cli still running that this process started. Idempotent; never raises."""
    with _LIVE_LOCK:
        procs = list(_LIVE)
    for p in procs:
        try:
            if p.poll() is None:
                kill_tree(p, grace_s=grace_s)
        except Exception:
            pass


atexit.register(kill_all_live)


def popen_group(argv: list[str], cwd: Path, *, env: dict | None = None) -> subprocess.Popen:
    kwargs: dict = {}
    if _WIN:
        kwargs["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP
                                   | subprocess.CREATE_NO_WINDOW)
    else:
        kwargs["start_new_session"] = True
        if sys.platform.startswith("linux"):
            kwargs["preexec_fn"] = _pdeathsig
    proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            bufsize=0, **kwargs)
    if _WIN:
        _assign_to_job(proc)
    with _LIVE_LOCK:
        _LIVE.difference_update([p for p in _LIVE if p.poll() is not None])
        _LIVE.add(proc)
    return proc


def _children(pid: int) -> list[psutil.Process]:
    try:
        return psutil.Process(pid).children(recursive=True)
    except Exception:
        return []


def _wait(proc: subprocess.Popen, timeout: float) -> bool:
    try:
        proc.wait(timeout=timeout)
        return True
    except Exception:
        return False


def kill_tree(proc: subprocess.Popen, grace_s: float = 3.0) -> None:
    """Stop the process and everything it started. Idempotent; never raises."""
    try:
        kids = _children(proc.pid) if proc.poll() is None else []
        if _WIN:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
            if not _wait(proc, grace_s):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        for k in kids:
            try:
                if k.is_running():
                    k.kill()
            except Exception:
                pass
        _wait(proc, 10.0)
    except Exception:
        pass


class MemSampler:
    """Thread that tracks the peak summed RSS of a process and its children."""

    def __init__(self, pid: int, interval_s: float = 0.5) -> None:
        self._pid = pid
        self._interval = interval_s
        self._peak = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="medimg-memsampler")

    def _sample(self) -> None:
        try:
            p = psutil.Process(self._pid)
            total = p.memory_info().rss
            for c in p.children(recursive=True):
                try:
                    total += c.memory_info().rss
                except Exception:
                    pass
            if total > self._peak:
                self._peak = float(total)
        except Exception:
            pass

    def _run(self) -> None:
        while True:
            self._sample()
            if self._stop.wait(self._interval):
                break

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> float:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)
        return self._peak
