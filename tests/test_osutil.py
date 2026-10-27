from pathlib import Path

import pytest

from medimg import osutil


@pytest.mark.parametrize("plat,exe", [("darwin", "open"), ("win32", "explorer"), ("linux", "xdg-open")])
def test_open_folder_command(monkeypatch, plat, exe):
    calls = []
    monkeypatch.setattr(osutil.sys, "platform", plat)
    monkeypatch.setattr(osutil.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd))
    assert osutil.open_folder(Path("/tmp/x")) is True
    assert calls == [[exe, str(Path("/tmp/x"))]]


def test_open_folder_oserror(monkeypatch):
    def boom(*a, **k):
        raise OSError("nope")
    monkeypatch.setattr(osutil.subprocess, "Popen", boom)
    assert osutil.open_folder(Path("/tmp/x")) is False
