"""Defaults, pinned constants and user settings. No heavy imports."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

APP_NAME = "medical-image-gen"
VERSION = "0.1.0"
DEFAULT_PORT = 8750
DEFAULT_STEPS = 9
STEPS_MIN, STEPS_MAX = 4, 15
DEFAULT_WIDTH, DEFAULT_HEIGHT = 1024, 1024
SIZE_MULTIPLE = 16
SIDE_MIN, SIDE_MAX = 256, 1536
MAX_PIXELS = 1_048_576
SEED_MAX = 2_147_483_647
BATCH_TARGET_MINUTES = 30
SIZE_PRESETS = [  # label, width, height
    ("1024x1024", 1024, 1024), ("768x1344 portrait", 768, 1344), ("1344x768 landscape", 1344, 768),
    ("832x1216", 832, 1216), ("1216x832", 1216, 832), ("768x768 low-memory", 768, 768)]
MFLUX_MODEL_ID = "filipstrand/Z-Image-Turbo-mflux-4bit"
MFLUX_MODEL_REVISION = "b3a8f31115a11f2f9e2fa0bfbc8d78dcc3e6568b"
MFLUX_MODEL_GB = 5.9
DIFFUSERS_MODEL_ID = "Tongyi-MAI/Z-Image-Turbo"
DIFFUSERS_MODEL_REVISION = "f332072aa78be7aecdf3ee76d5c247082da564a6"
DIFFUSERS_MODEL_GB = 32.9
GGUF_REPO_ID = "unsloth/Z-Image-Turbo-GGUF"
GGUF_FILES = {"q8_0": ("z-image-turbo-Q8_0.gguf", 7.3), "q4_k_m": ("z-image-turbo-Q4_K_M.gguf", 5.1)}  # (file, GB)
DISK_MARGIN_GB = 5
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
PROFILE_PATH = REPO_ROOT / "device_profile.json"
SETTINGS_PATH = Path.home() / ".medical-image-gen" / "config.json"
DEFAULT_OUTPUT_ROOT = Path.home() / "medical-image-gen-output"


@dataclass
class Settings:
    output_root: Path = DEFAULT_OUTPUT_ROOT
    port: int = DEFAULT_PORT
    steps: int = DEFAULT_STEPS
    unload_after_job: bool | None = None  # None = decide from RAM (D17)


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    """Read settings; a missing or corrupt file gives defaults."""
    defaults = Settings()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return defaults
        out = Settings()
        if isinstance(data.get("output_root"), str) and data["output_root"].strip():
            out.output_root = Path(data["output_root"]).expanduser()
        port = data.get("port")
        if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535:
            out.port = port
        steps = data.get("steps")
        if isinstance(steps, int) and not isinstance(steps, bool) and STEPS_MIN <= steps <= STEPS_MAX:
            out.steps = steps
        unload = data.get("unload_after_job")
        if unload is None or isinstance(unload, bool):
            out.unload_after_job = unload
        return out
    except (OSError, ValueError):
        return defaults


def save_settings(s: Settings, path: Path = SETTINGS_PATH) -> None:
    """Atomic write: temp file in the same directory, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(s)
    data["output_root"] = str(s.output_root)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
