"""Small OS helpers (stdlib only)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def open_folder(folder: Path) -> bool:
    """Open a folder in the system file manager. Only ever called with a store-resolved path."""
    if sys.platform == "darwin":
        cmd = ["open", str(folder)]
    elif sys.platform.startswith("win"):
        cmd = ["explorer", str(folder)]
    else:
        cmd = ["xdg-open", str(folder)]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
