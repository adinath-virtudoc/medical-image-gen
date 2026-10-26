"""File-name safety: sanitise path components, build relative paths and ids."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

WINDOWS_RESERVED = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WS = re.compile(r"\s+")


def safe_component(s: str) -> str:
    s = _BAD_CHARS.sub("", s or "")
    s = _WS.sub(" ", s).strip()
    s = s.rstrip(". ").strip()
    if not s:
        return "untitled"
    stem, dot, rest = s.partition(".")
    if stem.strip().upper() in WINDOWS_RESERVED:
        s = stem + "_" + dot + rest
    return s


def image_file_name(image_name: str) -> str:
    name = (image_name or "").strip()
    if name.lower().endswith(".png"):
        name = name[:-4]
    return safe_component(name) + ".png"


def rel_path(subject: str, unit: str, lecture: str, image_name: str) -> str:
    fname = image_file_name(image_name)
    if not any((x or "").strip() for x in (subject, unit, lecture)):
        return f"_single/{fname}"
    return "/".join(
        [safe_component(subject), safe_component(unit), safe_component(lecture), fname]
    )


def path_too_long(root: Path, rel: str, limit: int = 240) -> bool:
    return len(str(Path(root) / rel)) > limit


def image_id(rel: str) -> str:
    return hashlib.sha1(rel.encode()).hexdigest()[:16]
