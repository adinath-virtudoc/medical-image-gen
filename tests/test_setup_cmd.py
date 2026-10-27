import os
from argparse import Namespace
from pathlib import Path

import pytest

import medimg.assess as assess_pkg
from medimg import config, download, setup_cmd, smoke
from medimg.assess.decide import Decision
from medimg.assess.detect import Machine


def _machine(disk=100.0, os_name="Darwin", arch="arm64"):
    return Machine(hostname="h", os_name=os_name, os_version="27", cpu="Apple M2 Pro",
                   apple_chip="Apple M2 Pro", ram_total_gb=16.0, ram_free_gb=4.0,
                   gpu={"vendor": "apple", "name": "Apple M2 Pro", "vram_gb": None,
                        "driver": None, "cuda": None},
                   disk_free_gb=disk, disk_path="/x", python="3.12.13", uv="0.11", arch=arch)


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
        monkeypatch.setattr(assess_pkg, "decide", lambda m, **kw: _decision(supported))
        monkeypatch.setattr(assess_pkg, "load_profile", lambda *a, **k: self.profile)
        monkeypatch.setattr(download, "mflux_cached", lambda *a, **k: Path("/c") if self.cached else None)
        monkeypatch.setattr(download, "download_mflux", self._download)
        monkeypatch.setattr(setup_cmd, "_module_present", lambda name: self.installed)
        monkeypatch.setattr(setup_cmd, "_uv_sync", self._sync)
        monkeypatch.setattr(smoke, "run", self._smoke)
        monkeypatch.setattr(assess_pkg, "run", self._assess)
        self.settings = config.Settings(output_root=self.root)
        self.saved = []
        self.saved_tiers = []

        def _save(s, *a, **k):
            self.saved.append(s.engine)
            self.saved_tiers.append(s.sdcpp_tier)
        monkeypatch.setattr(config, "load_settings", lambda *a, **k: self.settings)
        monkeypatch.setattr(config, "save_settings", _save)
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


# ---------------------------------------------------------------- sdcpp

from medimg.errors import ModelUnavailable  # noqa: E402
from medimg.sdcpp import install  # noqa: E402


class SdcppWorld(World):
    """Windows PC without NVIDIA, engine sdcpp. Records every install-layer call in order."""

    def __init__(self, monkeypatch, tmp_path, disk=100.0, vulkan_ok=True, build="win-vulkan-x64"):
        super().__init__(monkeypatch, tmp_path, disk)
        self.binary = False
        self.models = False
        self.vulkan_ok = vulkan_ok
        self.build = build
        self.chosen = None
        self.sha_error = False
        self.tiers_seen = []
        monkeypatch.setattr(assess_pkg, "detect", lambda **kw: _machine(self.disk, "Windows", "AMD64"))
        monkeypatch.setattr(assess_pkg, "decide", self._decide)
        monkeypatch.setattr(download, "mflux_cached", lambda *a, **k: pytest.fail("mflux touched"))
        monkeypatch.setattr(install, "chosen_build", lambda os_name, arch, *a, **k: self.chosen or self.build)
        monkeypatch.setattr(install, "binary_cached", lambda b, *a, **k: Path("/x/sd-cli") if b in self.bins else None)
        monkeypatch.setattr(install, "install_binary", self._install_binary)
        monkeypatch.setattr(install, "models_cached", lambda t, *a, **k: {"x": Path("/m")} if self.models else None)
        monkeypatch.setattr(install, "download_models", self._download_models)
        monkeypatch.setattr(install, "health_check", self._health)
        monkeypatch.setattr(install, "record_chosen_build", self._record)
        monkeypatch.setattr(install, "resolve_paths", lambda b, t, *a, **k: ("paths", b, t))
        self.bins = set()
        self.engine_seen = []
        self.decide_kw = []

    def _decide(self, m, **kw):
        self.engine_seen.append(kw.get("engine"))
        self.decide_kw.append(kw)
        return Decision("sdcpp", True, "No NVIDIA card: using sd.cpp.", "", None, False,
                        None, 5.0, 10.0, device="cpu", tier="low")

    def _install_binary(self, build, progress=print, **kw):
        self.calls.append(f"binary:{build}")
        self.bins.add(build)

    def _download_models(self, tier, progress=print):
        self.tiers_seen.append(tier)
        if self.sha_error:
            raise ModelUnavailable("A model file was damaged while downloading.", "Run setup again.")
        self.calls += ["models", "sha"]
        self.models = True

    def _health(self, sd_cli, cwd, *a, **k):
        self.calls.append("health")
        if "vulkan" in str(cwd) and not self.vulkan_ok:
            raise ModelUnavailable("sd-cli failed its self-check (exit code 3221225781).", "Run setup again.")
        return "stable-diffusion.cpp version x"

    def _record(self, build, *a, **k):
        self.calls.append(f"record:{build}")
        self.chosen = build

    def _assess(self, args):
        self.calls.append("assess")
        self.profile = {"benchmark": {"points": []},
                        "backend": {"name": "sdcpp", "device": "cpu", "sdcpp": {"tier": "low"}},
                        "machine": {"cpu": "Apple M2 Pro"}}
        return 0


def _sd_args(**kw):
    return Namespace(skip_smoke=False, skip_assess=False, yes=True, engine="sdcpp", **kw)


def test_sdcpp_first_run_order_and_no_uv(monkeypatch, tmp_path, capsys):
    w = SdcppWorld(monkeypatch, tmp_path)
    monkeypatch.setattr(setup_cmd, "_uv_sync", lambda extra: pytest.fail("uv must not run"))
    assert setup_cmd.run(_sd_args()) == 0
    assert w.calls == ["binary:win-vulkan-x64", "models", "sha", "health",
                       "record:win-vulkan-x64", "smoke", "assess"]
    out = capsys.readouterr().out
    assert "✔ already done (no extra Python packages needed)" in out
    assert "nvidia" not in out
    assert w.tiers_seen == ["low"] and w.engine_seen == ["sdcpp"]
    assert "HF_HUB_OFFLINE" not in os.environ


def test_sdcpp_second_run_downloads_nothing(monkeypatch, tmp_path, capsys):
    w = SdcppWorld(monkeypatch, tmp_path)
    assert setup_cmd.run(_sd_args()) == 0
    w.calls.clear()
    capsys.readouterr()
    assert setup_cmd.run(_sd_args()) == 0
    assert w.calls == []
    assert capsys.readouterr().out.count("✔ already done") >= 5


def test_sdcpp_binary_present_models_missing_runs_only_models(monkeypatch, tmp_path):
    w = SdcppWorld(monkeypatch, tmp_path)
    w.bins.add("win-vulkan-x64")
    assert setup_cmd.run(_sd_args()) == 0
    assert w.calls[:4] == ["models", "sha", "health", "record:win-vulkan-x64"]
    assert not any(c.startswith("binary") for c in w.calls)


def test_sdcpp_wrong_sha_plain_message(monkeypatch, tmp_path, capsys):
    w = SdcppWorld(monkeypatch, tmp_path)
    w.sha_error = True
    assert setup_cmd.run(_sd_args()) == 1
    out = capsys.readouterr().out
    assert "Problem: A model file was damaged while downloading." in out and "Fix: Run setup again." in out
    assert "smoke" not in w.calls and "assess" not in w.calls


def test_sdcpp_vulkan_health_failure_uses_cpu_build(monkeypatch, tmp_path, capsys):
    w = SdcppWorld(monkeypatch, tmp_path, vulkan_ok=False)
    assert setup_cmd.run(_sd_args()) == 0
    assert "binary:win-cpu-x64" in w.calls
    assert w.calls.index("binary:win-cpu-x64") < w.calls.index("record:win-cpu-x64")
    assert w.chosen == "win-cpu-x64"
    assert "processor-only" in capsys.readouterr().out


def test_sdcpp_disk_check_uses_tier_gb(monkeypatch, tmp_path, capsys):
    w = SdcppWorld(monkeypatch, tmp_path, disk=9.0)
    assert setup_cmd.run(_sd_args()) == 1
    out = capsys.readouterr().out
    assert "Not enough disk space" in out and "need 10.0 GB" in out and "5 GB model" in out
    assert w.calls == []


def test_sdcpp_no_build_for_this_computer(monkeypatch, tmp_path, capsys):
    w = SdcppWorld(monkeypatch, tmp_path)
    monkeypatch.setattr(install, "chosen_build", lambda *a, **k: None)
    assert setup_cmd.run(_sd_args()) == 1
    assert "no sd.cpp build for this computer" in capsys.readouterr().out
    assert w.calls == []


def test_sdcpp_declined_download(monkeypatch, tmp_path, capsys):
    w = SdcppWorld(monkeypatch, tmp_path)
    asked = []
    monkeypatch.setattr(setup_cmd, "_confirm", lambda q: asked.append(q) or False)
    assert setup_cmd.run(Namespace(skip_smoke=False, skip_assess=False, yes=False, engine="sdcpp")) == 1
    assert "5 GB" in asked[0] and w.calls == []


def test_sdcpp_assess_redone_when_tier_or_device_differs(monkeypatch, tmp_path, capsys):
    w = SdcppWorld(monkeypatch, tmp_path)
    assert setup_cmd.run(_sd_args()) == 0
    w.calls.clear()
    w.profile["backend"]["sdcpp"]["tier"] = "mid"
    assert setup_cmd.run(_sd_args()) == 0
    assert w.calls == ["assess"]
    w.calls.clear()
    w.settings.sdcpp_device = "vulkan0"
    assert setup_cmd.run(_sd_args()) == 0
    assert w.calls == ["assess"]
    w.calls.clear()
    w.profile["backend"]["device"] = None
    w.settings.sdcpp_device = None
    assert setup_cmd.run(_sd_args()) == 0
    assert w.calls == ["assess"]


def test_engine_flag_saved_and_cleared(monkeypatch, tmp_path):
    w = SdcppWorld(monkeypatch, tmp_path)
    setup_cmd.run(_sd_args())
    assert w.saved == ["sdcpp"]
    setup_cmd.run(Namespace(skip_smoke=True, skip_assess=True, yes=True, engine="auto"))
    assert w.saved == ["sdcpp", None] and w.engine_seen[-1] is None


def test_saved_engine_setting_is_used(monkeypatch, tmp_path):
    w = SdcppWorld(monkeypatch, tmp_path)
    w.settings.engine = "sdcpp"
    setup_cmd.run(Namespace(skip_smoke=True, skip_assess=True, yes=True))
    assert w.engine_seen == ["sdcpp"] and w.saved == []


def test_extra_for_mapping():
    assert setup_cmd._extra_for("mflux") == ("mac", "mflux")
    assert setup_cmd._extra_for("diffusers") == ("nvidia", "diffusers")
    assert setup_cmd._extra_for("sdcpp") is None


def test_setup_smoke_and_assess_get_engine(monkeypatch, tmp_path):
    w = SdcppWorld(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(smoke, "run", lambda a: seen.append(a.engine) or 0)
    monkeypatch.setattr(assess_pkg, "run", lambda a: seen.append(a.engine) or 0)
    setup_cmd.run(_sd_args())
    assert seen == ["sdcpp", "sdcpp"]


def test_engine_save_does_not_make_steps_explicit(tmp_path):
    p = tmp_path / "settings.json"
    s = config.load_settings(p)
    s.engine = "sdcpp"
    config.save_settings(s, p)
    assert "steps" not in p.read_text()
    again = config.load_settings(p)
    assert again.engine == "sdcpp" and again.steps_explicit is False
    again.steps, again.steps_explicit = 12, True
    config.save_settings(again, p)
    assert config.load_settings(p).steps == 12


def test_sdcpp_mac_needs_macos_26(monkeypatch, tmp_path, capsys):
    w = SdcppWorld(monkeypatch, tmp_path)
    monkeypatch.setattr(install, "chosen_build", lambda *a, **k: "mac-arm64")
    monkeypatch.setattr(setup_cmd.platform, "mac_ver", lambda: ("15.4", ("", "", ""), "arm64"))
    assert setup_cmd.run(_sd_args()) == 1
    assert "macOS 26 or newer" in capsys.readouterr().out
    assert w.calls == []


def test_engine_choice_saved_only_after_success(monkeypatch, tmp_path, capsys):
    w = SdcppWorld(monkeypatch, tmp_path)
    monkeypatch.setattr(install, "chosen_build", lambda *a, **k: None)
    assert setup_cmd.run(_sd_args()) == 1
    assert config.load_settings().engine != "sdcpp"


def test_auto_engine_passed_to_smoke_and_assess(monkeypatch, tmp_path):
    w = SdcppWorld(monkeypatch, tmp_path)
    w.settings.engine = "sdcpp"
    seen = []
    monkeypatch.setattr(smoke, "run", lambda a: seen.append(a.engine) or 0)
    monkeypatch.setattr(assess_pkg, "run", lambda a: seen.append(a.engine) or 0)
    setup_cmd.run(Namespace(skip_smoke=False, skip_assess=False, yes=True, engine="auto"))
    assert seen == ["auto", "auto"]


def test_tier_reaches_decide_smoke_and_assess(monkeypatch, tmp_path):
    w = SdcppWorld(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(smoke, "run", lambda a: seen.append(("smoke", a.tier)) or 0)
    monkeypatch.setattr(assess_pkg, "run", lambda a: seen.append(("assess", a.tier, a.retry_gpu)) or 0)
    assert setup_cmd.run(_sd_args(tier="low")) == 0
    assert w.decide_kw[0]["tier"] == "low"
    assert seen == [("smoke", "low"), ("assess", "low", False)]


def test_tier_saved_only_after_success_and_auto_clears(monkeypatch, tmp_path):
    w = SdcppWorld(monkeypatch, tmp_path)
    monkeypatch.setattr(install, "chosen_build", lambda *a, **k: None)
    assert setup_cmd.run(_sd_args(tier="mid")) == 1
    assert w.saved_tiers == []
    monkeypatch.setattr(install, "chosen_build", lambda os_name, arch, *a, **k: w.build)
    assert setup_cmd.run(_sd_args(tier="mid")) == 0
    assert w.saved_tiers == ["mid"]
    assert setup_cmd.run(_sd_args(tier="auto")) == 0
    assert w.saved_tiers == ["mid", None] and w.decide_kw[-1]["tier"] is None


def test_assess_done_false_when_device_not_proven(monkeypatch, tmp_path):
    World(monkeypatch, tmp_path)

    def prof(proven):
        sd = {"tier": "low"}
        if proven is not None:
            sd["device_proven"] = proven
        return {"benchmark": {"points": []}, "backend": {"name": "sdcpp", "device": "cpu", "sdcpp": sd},
                "machine": {"cpu": "c"}}
    for proven, want in ((False, False), (True, True), (None, True)):
        monkeypatch.setattr(assess_pkg, "load_profile", lambda *a, p=prof(proven), **k: p)
        assert setup_cmd._assess_done("sdcpp", "c") is want
