"""Parsers on recorded fixtures, and detect() with injected tools."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from medimg.assess import (detect, parse_nvidia_smi, parse_sysctl, parse_system_profiler,
                           parse_wmic_or_powershell)

FIX = Path(__file__).parent / "fixtures" / "assess"


def fx(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("stem,name,vram,driver,cuda", [
    ("rtx4070_12gb", "NVIDIA GeForce RTX 4070", 12.0, "572.16", "12.8"),
    ("rtx3090_24gb", "NVIDIA GeForce RTX 3090", 24.0, "576.02", "12.9"),
    ("rtx4060_laptop_8gb", "NVIDIA GeForce RTX 4060 Laptop GPU", 8.0, "572.83", "12.8"),
    ("rtx4060ti_16gb", "NVIDIA GeForce RTX 4060 Ti", 16.0, "572.16", "12.8"),
    ("gtx1660_6gb", "NVIDIA GeForce GTX 1660", 6.0, "572.16", "12.8"),
    ("rtx4070_old_driver", "NVIDIA GeForce RTX 4070", 12.0, "560.94", "12.6"),
])
def test_nvidia_smi_fixtures(stem, name, vram, driver, cuda):
    g = parse_nvidia_smi(fx(f"nvidia_smi_{stem}.csv"), fx(f"nvidia_smi_{stem}_header.txt"))
    assert g == {"vendor": "nvidia", "name": name, "vram_gb": vram, "driver": driver, "cuda": cuda}


def test_nvidia_smi_garbage_and_header_row():
    assert parse_nvidia_smi("", "") is None
    assert parse_nvidia_smi("not csv at all", "") is None
    g = parse_nvidia_smi("name, memory.total [MiB], driver_version\nRTX A, 8192 MiB, 570.1\n", "")
    assert g["vram_gb"] == 8.0 and g["driver"] == "570.1" and g["cuda"] is None


def test_nvidia_smi_picks_biggest_gpu():
    g = parse_nvidia_smi("Small, 6144, 570.1\nBig, 24576, 570.1\n", "")
    assert g["name"] == "Big"


def test_system_profiler_m2_pro():
    r = parse_system_profiler(fx("system_profiler_m2pro_16gb.json"))
    assert r["chip"] == "Apple M2 Pro" and r["memory_gb"] == 16.0 and r["model"] == "Mac mini"
    assert parse_system_profiler("garbage") == {"chip": None, "memory_gb": None, "model": None}


def test_sysctl():
    r = parse_sysctl(fx("sysctl_m2pro.txt"))
    assert r == {"cpu": "Apple M2 Pro", "ram_bytes": 17179869184, "arm64": True}
    r = parse_sysctl(fx("sysctl_intel.txt"))
    assert r["arm64"] is False and "i7-9750H" in r["cpu"]
    assert parse_sysctl("") == {"cpu": None, "ram_bytes": None, "arm64": None}


def test_wmic_and_powershell():
    assert parse_wmic_or_powershell(fx("wmic_cpu.txt"))["cpu"] == "Intel(R) Core(TM) i7-13700K"
    assert parse_wmic_or_powershell(fx("powershell_cpu.txt"))["cpu"] == "13th Gen Intel(R) Core(TM) i5-13400F"
    assert parse_wmic_or_powershell("AMD Ryzen 7 5800X\r\n")["cpu"] == "AMD Ryzen 7 5800X"
    assert parse_wmic_or_powershell(fx("wmic_gpu.txt"))["names"][0] == "NVIDIA GeForce RTX 4070"
    assert parse_wmic_or_powershell("")["cpu"] is None


# ---- detect() with injected tools ------------------------------------------------------------

class FakePlatform:
    def __init__(self, system, machine, release="1.0", node="host"):
        self._s, self._m, self._r, self._n = system, machine, release, node

    def system(self): return self._s
    def machine(self): return self._m
    def release(self): return self._r
    def node(self): return self._n
    def processor(self): return ""
    def python_version(self): return "3.12.1"


class FakePsutil:
    def virtual_memory(self):
        return SimpleNamespace(total=16 * 1024 ** 3, available=4 * 1024 ** 3)

    def disk_usage(self, path):
        return SimpleNamespace(free=100 * 10 ** 9)


def runner(table):
    def run(cmd, **kw):
        out = table.get(cmd[0])
        if out is None:
            raise FileNotFoundError(cmd[0])
        return SimpleNamespace(returncode=0, stdout=out)
    return run


def test_detect_mac_arm64():
    run = runner({"sysctl": fx("sysctl_m2pro.txt"), "system_profiler": fx("system_profiler_m2pro_16gb.json"),
                  "uv": "uv 0.11.29 (abc 2026-01-01)\n"})
    m = detect(run, FakePlatform("Darwin", "arm64", "27.0.0"), FakePsutil())
    assert m.apple_chip == "Apple M2 Pro" and m.cpu == "Apple M2 Pro" and m.arch == "arm64"
    assert m.gpu["vendor"] == "apple" and m.ram_total_gb == 16.0 and m.ram_free_gb == 4.0
    assert m.uv == "0.11.29" and m.disk_free_gb == 100.0 and m.python == "3.12.1"


def test_detect_windows_nvidia():
    run = runner({"wmic": fx("wmic_cpu.txt"),
                  "nvidia-smi": fx("nvidia_smi_rtx4070_12gb.csv")})
    m = detect(run, FakePlatform("Windows", "AMD64"), FakePsutil())
    assert m.arch == "x86_64" and m.cpu.startswith("Intel(R) Core")
    assert m.gpu["name"].endswith("RTX 4070") and m.gpu["vram_gb"] == 12.0 and m.uv is None


def test_detect_never_crashes_without_any_tool():
    m = detect(runner({}), FakePlatform("Linux", "x86_64"), FakePsutil())
    assert m.gpu is None and m.uv is None and m.cpu == "unknown"


def test_detect_nvidia_device_string_without_smi():
    run = runner({"lspci": "01:00.0 VGA compatible controller: NVIDIA Corporation AD104 [GeForce RTX 4070]\n"})
    m = detect(run, FakePlatform("Linux", "x86_64"), FakePsutil())
    assert m.gpu["vendor"] == "nvidia" and m.gpu["driver"] is None and m.gpu["vram_gb"] is None


def test_detect_tolerates_broken_psutil():
    class Broken:
        def virtual_memory(self): raise OSError("no")
        def disk_usage(self, p): raise OSError("no")
    m = detect(runner({}), FakePlatform("Linux", "x86_64"), Broken())
    assert m.ram_total_gb == 0.0 and m.disk_free_gb == 0.0
