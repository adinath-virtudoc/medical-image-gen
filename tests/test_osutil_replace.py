"""replace_retry: Windows refuses os.replace while another handle holds the target open."""
from __future__ import annotations

import pytest

from medimg import osutil


def test_retries_through_transient_permission_error(tmp_path, monkeypatch):
    src, dst = tmp_path / "a.tmp", tmp_path / "a.xlsx"
    src.write_text("new")
    dst.write_text("old")
    real, calls = osutil.os.replace, []

    def flaky(a, b):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(5, "Access is denied")
        real(a, b)

    monkeypatch.setattr(osutil.os, "replace", flaky)
    monkeypatch.setattr(osutil, "REPLACE_DELAY_S", 0)
    osutil.replace_retry(src, dst)
    assert len(calls) == 3 and dst.read_text() == "new" and not src.exists()


def test_gives_up_and_reraises_when_lock_persists(tmp_path, monkeypatch):
    def locked(a, b):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(osutil.os, "replace", locked)
    monkeypatch.setattr(osutil, "REPLACE_DELAY_S", 0)
    with pytest.raises(PermissionError):
        osutil.replace_retry(tmp_path / "a", tmp_path / "b")
