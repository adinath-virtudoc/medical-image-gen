"""The decide() table (PLAN 4.7 / D6)."""
from __future__ import annotations

import pytest

from medimg.assess import Machine, decide
import importlib

decide_module = importlib.import_module("medimg.assess.decide")

ORIG_CACHED = decide_module._mflux_cached


@pytest.fixture(autouse=True)
def not_cached(monkeypatch):
    monkeypatch.setattr(decide_module, "_mflux_cached", lambda: False)


def machine(**kw) -> Machine:
    base = dict(hostname="h", os_name="Windows", os_version="11", cpu="cpu", apple_chip=None,
                ram_total_gb=32.0, ram_free_gb=20.0, gpu=None, disk_free_gb=200.0,
                disk_path="C:/out", python="3.12", uv="0.11", arch="x86_64")
    base.update(kw)
    return Machine(**base)


def nv(vram, driver="572.16", name="NVIDIA GeForce RTX X"):
    return {"vendor": "nvidia", "name": name, "vram_gb": vram, "driver": driver, "cuda": "12.8"}


def mac(ram=16.0, **kw):
    return machine(os_name="Darwin", arch="arm64", apple_chip="Apple M2 Pro", ram_total_gb=ram,
                   gpu={"vendor": "apple", "name": "Apple M2 Pro", "vram_gb": None, "driver": None,
                        "cuda": None}, **kw)


def test_m2_pro_16gb():
    d = decide(mac())
    assert d.supported and d.backend == "mflux" and d.unload_after_job is True
    assert d.model_id == "filipstrand/Z-Image-Turbo-mflux-4bit" and d.download_gb == 5.9
    assert d.min_disk_gb == pytest.approx(10.9) and d.offload_mode is None


def test_mac_32gb_keeps_model_loaded():
    assert decide(mac(32.0)).unload_after_job is False


def test_mac_8gb_unsupported():
    d = decide(mac(8.0))
    assert not d.supported and "16 GB" in d.reason


def test_intel_mac():
    d = decide(machine(os_name="Darwin", arch="x86_64"))
    assert not d.supported and d.backend is None and d.reason.startswith("Intel Mac: Apple-silicon only")


def test_mac_low_disk_has_numbers():
    d = decide(mac(disk_free_gb=7.0))
    assert not d.supported and "7.0 GB free" in d.reason and "10.9 GB" in d.reason


def test_mac_low_disk_ok_when_cached(monkeypatch):
    monkeypatch.setattr(decide_module, "_mflux_cached", lambda: True)
    d = decide(mac(disk_free_gb=1.0))
    assert d.supported and d.download_gb == 0.0


@pytest.mark.parametrize("vram,mode", [(24.0, "resident"), (16.0, "model_cpu_offload"),
                                       (12.0, "gguf_q8_offload"), (8.0, "gguf_q4_sequential")])
def test_nvidia_modes(vram, mode):
    d = decide(machine(gpu=nv(vram)))
    assert d.supported and d.backend == "diffusers" and d.offload_mode == mode
    assert d.unload_after_job is False and d.model_id == "Tongyi-MAI/Z-Image-Turbo"


def test_download_sizes_by_mode():
    assert decide(machine(gpu=nv(24.0))).download_gb == 32.9
    assert decide(machine(gpu=nv(24.0))).min_disk_gb == pytest.approx(37.9)
    assert decide(machine(gpu=nv(12.0))).download_gb < 20
    assert decide(machine(gpu=nv(8.0))).download_gb < decide(machine(gpu=nv(12.0))).download_gb


def test_6gb_unsupported():
    d = decide(machine(gpu=nv(6.0)))
    assert not d.supported and "6 GB" in d.reason and "8 GB" in d.reason


@pytest.mark.parametrize("os_name,driver,ok", [("Windows", "560.94", False), ("Windows", "570.64", False),
                                               ("Windows", "570.65", True), ("Linux", "570.26", True),
                                               ("Linux", "560.35", False), ("Linux", "575.1", True)])
def test_driver_check(os_name, driver, ok):
    d = decide(machine(os_name=os_name, gpu=nv(24.0, driver)))
    assert d.supported is ok
    if not ok:
        assert "update the nvidia driver" in d.fix.lower()


def test_amd():
    d = decide(machine(gpu={"vendor": "amd", "name": "Radeon RX 7900", "vram_gb": None,
                            "driver": None, "cuda": None}))
    assert not d.supported and d.reason.startswith("AMD GPUs are not supported in v1")


def test_no_gpu():
    d = decide(machine(gpu=None))
    assert not d.supported and "no nvidia gpu found" in d.reason.lower()


def test_intel_igpu_only_is_unsupported():
    d = decide(machine(gpu={"vendor": "intel", "name": "UHD", "vram_gb": None, "driver": None, "cuda": None}))
    assert not d.supported and "no nvidia gpu found" in d.reason.lower()


def test_nvidia_without_smi():
    d = decide(machine(gpu={"vendor": "nvidia", "name": "GeForce RTX 4070", "vram_gb": None,
                            "driver": None, "cuda": None}))
    assert not d.supported and "install the nvidia driver" in d.fix.lower()


def test_low_disk_numbers_nvidia():
    d = decide(machine(gpu=nv(24.0), disk_free_gb=20.0))
    assert not d.supported and "20.0 GB free" in d.reason and "37.9 GB" in d.reason


def test_low_ram_is_a_warning_not_a_block():
    d = decide(machine(gpu=nv(16.0), ram_total_gb=16.0))
    assert d.supported and "Warning" in d.reason and "32 GB" in d.reason


def test_mflux_cache_check_is_offline(monkeypatch):
    """_mflux_cached must call huggingface_hub with local_files_only=True."""
    import huggingface_hub
    seen = {}

    def fake(*a, **kw):
        seen.update(kw)
        raise OSError("not cached")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake)
    assert ORIG_CACHED() is False
    assert seen["local_files_only"] is True


def test_mflux_cache_check_uses_allow_patterns(monkeypatch):
    """R5: share download.mflux_cached so a partial-folder snapshot still counts as cached."""
    import huggingface_hub
    from medimg import download
    seen = {}

    def fake(*a, **kw):
        seen.update(kw)
        return "/fake/snapshot"

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake)
    assert ORIG_CACHED() is True
    assert seen["allow_patterns"] == download.MFLUX_PATTERNS
