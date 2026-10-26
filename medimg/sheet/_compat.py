"""Lazy access to T1 (rules) and T3 (names) with fallbacks for use before they land."""
from __future__ import annotations

import re
from pathlib import Path

_MINOR = re.compile(
    r"\b(child|children|kids?|kiddos?|teens?|teenagers?|teenaged?|preteens?|tweens?|boys?|girls?|"
    r"infants?|baby|babies|toddlers?|minors?|underage|newborns?|neonates?|adolescents?|"
    r"juveniles?|pediatric|paediatric|youngsters?|youths?)\b", re.I)
_AGE = re.compile(r"(\d{1,3})\s*(?:-|\s)?\s*(?:year|yr|y/o|yo)", re.I)


def _fallback_check_prompt(prompt: str) -> str | None:
    for m in _AGE.finditer(prompt or ""):
        if int(m.group(1)) < 18:
            return "Blocked: the prompt states an age under 18. Images are adults only."
    m = _MINOR.search(prompt or "")
    if m:
        return f"Blocked: '{m.group(0)}' suggests a minor. Images are adults only; rephrase."
    if _AGE.search(prompt or "") or re.search(r"\badults?\b", prompt or "", re.I):
        return None
    return ("Blocked: the prompt does not state an adult. "
            "State an adult age (for example 45-year-old) or the word adult.")


def check_prompt(prompt: str) -> str | None:
    try:
        from medimg.rules import check_prompt as real
    except ImportError:
        return _fallback_check_prompt(prompt)
    return real(prompt)


def _fallback_safe(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(s))
    s = " ".join(s.split()).rstrip(". ")
    return s or "untitled"


def rel_path(subject: str, unit: str, lecture: str, image_name: str) -> str:
    try:
        from medimg.names import rel_path as real
    except ImportError:
        name = _fallback_safe(image_name)
        if name.lower().endswith(".png"):
            name = name[:-4] or "untitled"
        if not (subject or unit or lecture):
            return f"_single/{name}.png"
        return "/".join(_fallback_safe(p) for p in (subject, unit, lecture)) + f"/{name}.png"
    return real(subject, unit, lecture, image_name)


def path_too_long(root: Path, rel: str, limit: int = 240) -> bool:
    try:
        from medimg.names import path_too_long as real
    except ImportError:
        return len(str(Path(root) / rel)) > limit
    return real(root, rel, limit)
