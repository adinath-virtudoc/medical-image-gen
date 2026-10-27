"""Small OS helpers (stdlib only)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
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


# Windows refuses os.replace while another handle has the target open (Excel preview,
# antivirus scan, a reader in another thread). These locks clear within a moment.
REPLACE_ATTEMPTS = 10
REPLACE_DELAY_S = 0.05


def replace_retry(src: str | os.PathLike, dst: str | os.PathLike) -> None:
    """os.replace that retries briefly on PermissionError, then re-raises the last one."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_DELAY_S * (attempt + 1))
