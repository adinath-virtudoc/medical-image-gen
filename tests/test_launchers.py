import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NAMES = ["setup", "start", "assess"]
CMD = {"setup": "setup", "start": "serve", "assess": "assess"}


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("ext", ["sh", "command"])
def test_posix_launchers(name, ext):
    p = ROOT / f"{name}.{ext}"
    assert p.exists()
    assert os.access(p, os.X_OK), f"{p.name} is not executable"
    assert subprocess.run(["sh", "-n", str(p)]).returncode == 0
    text = p.read_text()
    assert text.startswith("#!/bin/sh")
    assert 'cd "$(dirname "$0")"' in text
    assert "https://astral.sh/uv/install.sh" in text
    assert f'uv run python -m medimg {CMD[name]} "$@"' in text
    assert "uv sync --extra" not in text
    assert ("uv sync\n" in text or "uv sync;" in text or "if ! uv sync" in text) == (name == "setup")


@pytest.mark.parametrize("name", NAMES)
def test_sh_and_command_match(name):
    assert (ROOT / f"{name}.sh").read_bytes() == (ROOT / f"{name}.command").read_bytes()


def test_setup_does_not_install_gpu_extra_before_checks():
    text = (ROOT / "setup.sh").read_text()
    assert "EXTRA=" not in text and "--extra" not in text


@pytest.mark.parametrize("name", NAMES)
def test_bat_launchers(name):
    raw = (ROOT / f"{name}.bat").read_bytes()
    text = raw.decode("ascii")
    assert "%~dp0" in text and "uv run" in text
    assert f"python -m medimg {CMD[name]} %*" in text
    assert "install.ps1" in text and "pause" in text
    assert raw.count(b"\r\n") == raw.count(b"\n"), "bare LF found"
    assert "--extra" not in text
    assert ("uv sync\r\n" in text) == (name == "setup")


@pytest.mark.parametrize("ext", ["sh", "command"])
def test_selftest_posix_launcher(ext):
    p = ROOT / f"selftest.{ext}"
    assert os.access(p, os.X_OK)
    assert subprocess.run(["sh", "-n", str(p)]).returncode == 0
    text = p.read_text()
    assert text.startswith("#!/bin/sh")
    assert 'cd "$(dirname "$0")"' in text
    assert 'uv run --no-sync python -m medimg selftest "$@"' in text
    assert "install.sh" not in text and "curl" not in text
    assert ".venv" in text


def test_selftest_sh_and_command_match():
    assert (ROOT / "selftest.sh").read_bytes() == (ROOT / "selftest.command").read_bytes()


def test_selftest_bat_launcher():
    raw = (ROOT / "selftest.bat").read_bytes()
    text = raw.decode("ascii")
    for needle in ("%~dp0", "python -m medimg selftest %*", "PYTHONUTF8=1", "pause"):
        assert needle in text
    assert "install.ps1" not in text and "curl" not in text and "irm" not in text
    assert raw.count(b"\r\n") == raw.count(b"\n"), "bare LF found"


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell only")
def test_selftest_refuses_without_setup(tmp_path):
    import shutil

    script = tmp_path / "selftest.sh"
    shutil.copy(ROOT / "selftest.sh", script)
    r = subprocess.run(
        ["/bin/sh", str(script)],
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1
    assert "Run setup first" in r.stdout
