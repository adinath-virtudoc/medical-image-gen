"""Download, verify and locate the sd-cli binary and its model files.

The only module that downloads binaries. Nothing downloaded is ever executed here.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from medimg.config import SDCPP_RELEASE_TAG, TOOLS_DIR
from medimg.errors import ModelUnavailable
from medimg.sdcpp import pins
from medimg.sdcpp.pins import binary_dir, build_for

CHOSEN_BUILD_FILE = "chosen_build.txt"
_CHUNK = 8 * 1024 * 1024
_FIX_SETUP = "Run setup again; it downloads only what is missing."


@dataclass
class SdcppPaths:
    sd_cli: tuple[str, ...]
    cwd: Path
    diffusion: Path
    llm: Path
    vae: Path
    build: str
    tier: str
    release: str = SDCPP_RELEASE_TAG


def hf_hub_download(*args, **kwargs):
    """Lazy wrapper so importing this module stays light (and tests can patch it)."""
    from huggingface_hub import hf_hub_download as _dl
    return _dl(*args, **kwargs)


def _exe_path(build: str, tools_dir: Path) -> Path:
    return binary_dir(build, tools_dir) / pins.ASSETS[build].exe


def binary_cached(build: str, tools_dir: Path = TOOLS_DIR) -> Path | None:
    if build not in pins.ASSETS:
        return None
    exe = _exe_path(build, tools_dir)
    if exe.is_file() and (os.name == "nt" or os.access(exe, os.X_OK)):
        return exe
    return None


def verify_sha256(path: Path, expected: str, progress=None) -> None:
    h = hashlib.sha256()
    path = Path(path)
    total = path.stat().st_size or 1
    done = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(f"Checking {path.name}: {done * 100 // total}%")
    if h.hexdigest().lower() != expected.lower():
        raise ModelUnavailable(f"The file {path.name} does not match its expected checksum.",
                               "Run setup again.")


def _download(asset, part: Path, progress, opener) -> None:
    part.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.exists() else 0
    if have > asset.size:
        part.unlink()
        have = 0
    if have == asset.size:
        return
    headers = {"User-Agent": "medical-image-gen"}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(asset.url, headers=headers)
    try:
        resp = opener(req)
    except Exception as e:  # network errors, HTTP errors
        raise ModelUnavailable(f"Could not download {asset.name}: {e}",
                               "Check the internet connection and run setup again.") from e
    try:
        status = getattr(resp, "status", None)
        mode = "ab"
        if have and status != 206:  # server ignored Range: restart
            mode, have = "wb", 0
        done = have
        with open(part, mode) as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                progress(f"Downloading {asset.name}: {done * 100 // asset.size}%")
    except OSError as e:
        raise ModelUnavailable(f"The download of {asset.name} was interrupted: {e}",
                               "Run setup again; it resumes where it stopped.") from e
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for info in zf.infolist():
        name = info.filename
        if name.startswith(("/", "\\")) or (len(name) > 1 and name[1] == ":") \
                or ".." in Path(name.replace("\\", "/")).parts:
            raise ModelUnavailable(f"The download contains an unsafe file path ({name}).",
                                   "Run setup again; if it repeats, report it.")
        target = (dest / name).resolve()
        if root != target and root not in target.parents:
            raise ModelUnavailable(f"The download contains an unsafe file path ({name}).",
                                   "Run setup again; if it repeats, report it.")
    zf.extractall(dest)


def install_binary(build: str, progress=print, *, tools_dir: Path = TOOLS_DIR,
                   opener=urllib.request.urlopen) -> Path:
    if build not in pins.ASSETS:
        raise ModelUnavailable(f"Unknown sd-cli build '{build}'.", "Run setup again.")
    asset = pins.ASSETS[build]
    cached = binary_cached(build, tools_dir)
    if cached:
        return cached
    dl_dir = Path(tools_dir) / "sdcpp" / SDCPP_RELEASE_TAG / "downloads"
    part = dl_dir / (asset.name + ".part")
    _download(asset, part, progress, opener)
    size = part.stat().st_size
    ok = size == asset.size
    if ok:
        try:
            verify_sha256(part, asset.sha256)
        except ModelUnavailable:
            ok = False
    if not ok:
        part.unlink(missing_ok=True)
        raise ModelUnavailable(f"The downloaded file {asset.name} was damaged or incomplete.",
                               "Run setup again.")
    target = binary_dir(build, tools_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{build}.", suffix=".tmp", dir=target.parent))
    try:
        with zipfile.ZipFile(part) as zf:
            _safe_extract(zf, tmp)
        if not (tmp / asset.exe).is_file():
            raise ModelUnavailable(f"The download did not contain {asset.exe}.",
                                   "Run setup again; if it repeats, report it.")
        if os.name != "nt":
            exe = tmp / asset.exe
            exe.chmod(exe.stat().st_mode | 0o111)
        if target.exists():
            shutil.rmtree(target)
        os.replace(tmp, target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    part.unlink(missing_ok=True)
    progress(f"Installed {asset.exe} ({build}).")
    return _exe_path(build, tools_dir)


def models_cached(tier: str) -> dict[str, Path] | None:
    out: dict[str, Path] = {}
    for role, m in pins.TIERS[tier].items():
        try:
            out[role] = Path(hf_hub_download(m.repo, m.filename, revision=m.revision,
                                             local_files_only=True))
        except Exception:
            return None
    return out


def download_models(tier: str, progress=print) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for role, m in pins.TIERS[tier].items():
        progress(f"Downloading {m.filename} ({m.gb:.2f} GB)")
        try:
            path = Path(hf_hub_download(m.repo, m.filename, revision=m.revision))
        except Exception as e:
            raise ModelUnavailable(f"Could not download {m.filename}: {e}",
                                   "Check the internet connection and run setup again.") from e
        try:
            verify_sha256(path, m.sha256, progress)
        except ModelUnavailable as e:
            # Remove the cached blob too, so a rerun fetches a fresh copy.
            try:
                real = path.resolve()
                path.unlink(missing_ok=True)
                real.unlink(missing_ok=True)
            except OSError:
                pass
            raise ModelUnavailable("A model file was damaged while downloading.",
                                   "Run setup again.") from e
        out[role] = path
    return out


_VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
_DLL_NOT_FOUND = (0xC0000135, 0xC000007B)  # STATUS_DLL_NOT_FOUND, STATUS_INVALID_IMAGE_FORMAT


def _nt_code(rc: int) -> int:
    return rc & 0xFFFFFFFF if rc < 0 else rc


def _run_list_devices(sd_cli: tuple[str, ...], cwd: Path, run=subprocess.run):
    """The ONE place that runs ``sd-cli --list-devices``; raises ModelUnavailable with rich messages.

    ``--version`` exits before any ggml backend DLL is loaded, so it cannot catch a broken Vulkan
    driver. ``--list-devices`` initialises the backends.
    """
    try:
        r = run([*sd_cli, "--list-devices"], cwd=str(cwd), capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as e:
        raise ModelUnavailable("sd-cli did not answer in time.", "Run setup again.") from e
    except OSError as e:
        raise ModelUnavailable(f"Could not run sd-cli: {e}", _FIX_SETUP) from e
    rc = r.returncode
    if rc != 0:
        code = _nt_code(rc)
        if os.name == "nt" and code in _DLL_NOT_FOUND:
            raise ModelUnavailable(
                f"sd-cli could not start because a Windows system library is missing (exit code {code}).",
                "Install the Microsoft Visual C++ Redistributable (x64) from "
                f"{_VCREDIST_URL}, then run setup again.")
        detail = next((ln.strip() for ln in ((getattr(r, "stderr", "") or "") + "\n" + (r.stdout or "")).splitlines()
                       if ln.strip()), "")
        shown = f"{rc} / 0x{code:08X}" if code >= 0x80000000 else str(rc)
        raise ModelUnavailable(f"sd-cli could not start (exit code {shown})"
                               + (f": {detail[:300]}" if detail else "") + ".",
                               "Run setup again.")
    return r


def list_devices(sd_cli: tuple[str, ...], cwd: Path, run=subprocess.run) -> list[tuple[str, str]]:
    r = _run_list_devices(sd_cli, cwd, run)
    devices = []
    for line in (r.stdout or "").splitlines():
        if "\t" in line:
            name, desc = line.split("\t", 1)
            if name.strip():
                devices.append((name.strip(), desc.strip()))
    return devices


def health_check(sd_cli: tuple[str, ...], cwd: Path, run=subprocess.run) -> str:
    """Start sd-cli far enough to load its backends; a healthy build always lists a CPU device."""
    devices = list_devices(sd_cli, cwd, run)
    names = [n for n, _ in devices]
    if not any(n.upper().startswith("CPU") for n in names):
        raise ModelUnavailable("sd-cli started but did not list a processor device.",
                               "Run setup again; if it repeats, report it.")
    return "devices: " + ", ".join(names)


def resolve_paths(build: str, tier: str, *, tools_dir: Path = TOOLS_DIR) -> SdcppPaths:
    exe = binary_cached(build, tools_dir)
    if exe is None:
        raise ModelUnavailable(f"The image program (sd-cli, build {build}) is not installed.", _FIX_SETUP)
    models = models_cached(tier)
    if models is None:
        raise ModelUnavailable(f"The '{tier}' model files are not all downloaded.", _FIX_SETUP)
    return SdcppPaths(sd_cli=(str(exe),), cwd=binary_dir(build, tools_dir),
                      diffusion=models["diffusion"], llm=models["llm"], vae=models["vae"],
                      build=build, tier=tier)


def record_chosen_build(build: str, tools_dir: Path = TOOLS_DIR) -> None:
    d = Path(tools_dir) / "sdcpp" / SDCPP_RELEASE_TAG
    d.mkdir(parents=True, exist_ok=True)
    (d / CHOSEN_BUILD_FILE).write_text(build, encoding="utf-8")


def chosen_build(os_name: str, arch: str, tools_dir: Path = TOOLS_DIR) -> str | None:
    f = Path(tools_dir) / "sdcpp" / SDCPP_RELEASE_TAG / CHOSEN_BUILD_FILE
    try:
        key = f.read_text(encoding="utf-8").strip()
    except OSError:
        key = ""
    if key in pins.ASSETS and binary_cached(key, tools_dir) is not None:
        return key
    return build_for(os_name, arch)
