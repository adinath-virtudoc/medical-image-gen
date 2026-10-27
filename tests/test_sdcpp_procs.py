import subprocess
import sys
import time

import psutil

from medimg.sdcpp.procs import MemSampler, kill_tree, popen_group


def test_kill_tree_on_exited_process_does_not_raise(tmp_path):
    p = popen_group([sys.executable, "-c", "pass"], tmp_path)
    p.wait()
    kill_tree(p)
    kill_tree(p)


def test_kill_tree_kills_running_child(tmp_path):
    p = popen_group([sys.executable, "-c", "import time; time.sleep(60)"], tmp_path)
    pid = p.pid
    time.sleep(0.2)
    t0 = time.time()
    kill_tree(p, grace_s=2.0)
    assert time.time() - t0 < 15
    assert p.poll() is not None
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    p.stdout.close()


def test_popen_group_merges_stderr_and_no_stdin(tmp_path):
    p = popen_group([sys.executable, "-c",
                     "import sys; print('a'); sys.stderr.write('b\\n'); sys.stdin.read()"],
                    tmp_path)
    data = p.stdout.read()
    p.wait()
    p.stdout.close()
    assert b"a" in data and b"b" in data and p.returncode == 0


def test_mem_sampler_current_process():
    import os
    s = MemSampler(os.getpid(), interval_s=0.05)
    s.start()
    time.sleep(0.15)
    assert s.stop() > 0


def test_mem_sampler_vanished_process_returns_float(tmp_path):
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    s = MemSampler(p.pid, interval_s=0.05)
    s.start()
    assert s.stop() >= 0.0


def test_kill_all_live_kills_running_child(tmp_path):
    from medimg.sdcpp.procs import kill_all_live
    p = popen_group([sys.executable, "-c", "import time; time.sleep(60)"], tmp_path)
    time.sleep(0.2)
    kill_all_live(grace_s=1.0)
    assert p.poll() is not None
    p.stdout.close()


def test_worker_stop_aborts_engine():
    from medimg.worker import GenerationWorker
    calls = []

    class E:
        loaded = True
        def abort(self): calls.append(1)

    w = GenerationWorker(E(), None, "x", unload_after_job=False, sheet_lock=__import__("threading").Lock())
    w.stop()
    assert calls == [1] and w._cancel.is_set()
