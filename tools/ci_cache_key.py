"""Print the CI cache key for the sd.cpp tools and model files.

    python tools/ci_cache_key.py [--tier low]

Prints ``key=sdcpp-<16 hex>`` and, when the GITHUB_OUTPUT variable is set,
appends the same line to that file.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from medimg.sdcpp import pins  # noqa: E402


def cache_key(tier: str = "low") -> str:
    shas = sorted(a.sha256 for a in pins.ASSETS.values())
    shas += sorted(m.sha256 for m in pins.TIERS[tier].values())
    digest = hashlib.sha256("\n".join(shas).encode("utf-8")).hexdigest()
    return "sdcpp-" + digest[:16]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Print the CI cache key.")
    ap.add_argument("--tier", default="low", choices=sorted(pins.TIERS))
    args = ap.parse_args(argv)
    line = f"key={cache_key(args.tier)}"
    print(line)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
