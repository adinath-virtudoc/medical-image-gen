"""Pillow 13.0.0 does not import on CPython 3.12.13 (numbers._IntegralLike); keep it pinned below 13."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_pins_pillow_below_13():
    assert re.search(r'"pillow>=12\.3,<13"', (ROOT / "pyproject.toml").read_text())


def test_lock_resolves_pillow_below_13():
    m = re.search(r'name = "pillow"\nversion = "(\d+)\.', (ROOT / "uv.lock").read_text())
    assert m and int(m.group(1)) < 13
