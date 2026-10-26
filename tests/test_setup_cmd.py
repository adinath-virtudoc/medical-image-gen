import os
from argparse import Namespace
from pathlib import Path

import pytest

import medimg.assess as assess_pkg
from medimg import config, download, setup_cmd, smoke
from medimg.assess.decide import Decision
from medimg.assess.detect import Machine


def _machine(disk=100.0):
    return Machine(hostname="h", os_name="Darwin", os_version="27", cpu="Apple M2 Pro",
                   apple_chip="Apple M2 Pro", ram_total_gb=16.0, ram_free_gb=4.0,
                   gpu={"vendor": "apple", "name": "Apple M2 Pro", "vram_gb": None,
                        "driver": None, "cuda": None},
                   disk_free_gb=disk, disk_path="/x", python="3.12.13", uv="0.11", arch="arm64")


def _decision(supported=True):
    if not supported:
        return Decision(None, False, "Intel Mac: Apple-silicon only.", "Use an M1 Mac.",
                        None, False, None, None, None)
    return Decision("mflux", True, "Apple silicon with 16 GB", "", None, True,
                    config.MFLUX_MODEL_ID, config.MFLUX_MODEL_GB, config.MFLUX_MODEL_GB + 5)


class World:
    """Mutable fake of everything setup touches: cache, packages, profile, smoke image."""

    def __init__(self, monkeypatch, tmp_path, disk=100.0, supported=True):
        self.root = tmp_path / "root"
        self.cached = False
        self.installed = False
        self.profile = None
        self.calls = []
        self.disk = disk
        monkeypatch.setattr(assess_pkg, "detect", lambda **kw: _machine(self.disk))
        monkeypatch.setattr(assess_pkg, "decide", lambda m: _decision(supported))
        monkeypatch.setattr(assess_pkg, "load_profile", lambda *a, **k: self.profile)
        monkeypatch.setattr(download, "mflux_cached", lambda *a, **k: Path("/c") if self.cached else None)
        monkeypatch.setattr(download, "download_mflux", self._download)
        monkeypatch.setattr(setup_cmd, "_module_present", lambda name: self.installed)
        monkeypatch.setattr(setup_cmd, "_uv_sync", self._sync)
        monkeypatch.setattr(smoke, "run", self._smoke)
        monkeypatch.setattr(assess_pkg, "run", self._assess)
        monkeypatch.setattr(config, "load_settings", lambda *a, **k: config.Settings(output_root=self.root))
        monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)

    def _download(self, progress=print):
        self.calls.append("download")
        self.cached = True
        return Path("/c")

    def _sync(self, extra):
        self.calls.append(f"sync:{extra}")
        self.installed = True
        return 0

    def _smoke(self, args):
        self.calls.append("smoke")
        (self.root / "_smoke").mkdir(parents=True, exist_ok=True)
        (self.root / "_smoke" / "a.png").write_bytes(b"png")
        return 0

    def _assess(self, args):
        self.calls.append("assess")
        assert args.no_benchmark is False
        self.profile = {"benchmark": {"points": []}, "backend": {"name": "mflux"},
                        "machine": {"cpu": "Apple M2 Pro"}}
        return 0


ARGS = Namespace(skip_smoke=False, skip_assess=False, yes=True)


def test_second_run_skips_everything(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path)
    assert setup_cmd.run(ARGS) == 0
    assert w.calls == ["sync:mac", "download", "smoke", "assess"]
    first = capsys.readouterr().out
    assert setup_cmd._next_command() in first

    w.calls.clear()
    assert setup_cmd.run(ARGS) == 0
    assert w.calls == []
    second = capsys.readouterr().out
    assert second.count("✔ already done") >= 5
    assert setup_cmd._next_command() in second
    assert "HF_HUB_OFFLINE" not in os.environ


def test_skip_flags(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path)
    assert setup_cmd.run(Namespace(skip_smoke=True, skip_assess=True, yes=True)) == 0
    assert w.calls == ["sync:mac", "download"]


def test_disk_check_aborts_with_plain_message(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, disk=8.0)
    assert setup_cmd.run(ARGS) == 1
    out = capsys.readouterr().out
    assert "Not enough disk space" in out and "8.0 GB free" in out and "10.9 GB" in out
    assert w.calls == []


def test_disk_requirement_skipped_when_cached(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, disk=1.0)
    w.cached = True
    assert setup_cmd.run(ARGS) == 0
    assert "download" not in w.calls


def test_unsupported_machine(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path, supported=False)
    assert setup_cmd.run(ARGS) == 1
    assert "Intel Mac" in capsys.readouterr().out
    assert w.calls == []


def test_declined_download(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path)
    monkeypatch.setattr(setup_cmd, "_confirm", lambda q: False)
    assert setup_cmd.run(Namespace(skip_smoke=False, skip_assess=False, yes=False)) == 1
    assert "download" not in w.calls


def test_failed_install_stops(monkeypatch, tmp_path, capsys):
    w = World(monkeypatch, tmp_path)
    monkeypatch.setattr(setup_cmd, "_uv_sync", lambda extra: 1)
    assert setup_cmd.run(ARGS) == 1
    assert "uv sync --extra mac" in capsys.readouterr().out
