"""Adults-only gate. Pure function: no configuration, no env, no file reads."""
from __future__ import annotations

import re

HINT = "State an adult age (for example 45-year-old) or the word adult."

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_ONES = {k: v for k, v in _UNITS.items() if 1 <= v <= 9}


def _alt(words) -> str:
    return "|".join(sorted(words, key=len, reverse=True))


_WORD_NUM = (
    rf"(?:(?P<tens>{_alt(_TENS)})(?:[-\s]+(?P<ones>{_alt(_ONES)}))?|(?P<unit>{_alt(_UNITS)}))"
)
_DIGIT_NUM = r"(?P<digits>\d+(?:\.\d+)?)"
_NUM = rf"(?<![\w.])(?:{_DIGIT_NUM}|{_WORD_NUM})"

_AGE_SUFFIX = (
    r"(?:[-\s]?(?:years?|yrs?)\b"   # 16 years, 16-year-old, 16 yrs, 16 years of age
    r"|\s?y\.?\s?o\.?(?!\w)"       # 16 yo, 16 y.o., 16 y/o handled below
    r"|\s?y/o\b)"
)
_AGE_FORMS = [
    re.compile(rf"{_NUM}{_AGE_SUFFIX}", re.I),
    re.compile(rf"\bage[ds]?\s*[-:]?\s*{_NUM}(?![\d]|\.\d)", re.I),
    # "(16)" and "of 16" (e.g. "young lady of 16", "woman (16)")
    re.compile(rf"\(\s*{_NUM}\s*\)", re.I),
    re.compile(rf"\bof\s+{_NUM}(?=\s*(?:[,.;)!]|$))", re.I),
]


def _value(m: re.Match) -> float:
    if m.group("digits") is not None:
        return float(m.group("digits"))
    if m.group("unit") is not None:
        return float(_UNITS[m.group("unit").lower()])
    v = _TENS[m.group("tens").lower()]
    if m.group("ones"):
        v += _ONES[m.group("ones").lower()]
    return float(v)


def _ages(prompt: str) -> list[float]:
    out: list[float] = []
    for rx in _AGE_FORMS:
        out.extend(_value(m) for m in rx.finditer(prompt))
    return out


_MINOR_TERMS = [
    r"child(?:ren)?", r"kids?", r"kiddos?", r"teens?", r"teenagers?", r"teenaged?",
    r"preteens?", r"tweens?", r"boys?", r"girls?", r"infants?", r"baby", r"babies",
    r"toddlers?", r"minors?", r"underage", r"newborns?", r"neonates?",
    r"adolescents?", r"adolescence", r"juveniles?", r"pediatrics?", r"paediatrics?",
    r"schoolchild(?:ren)?", r"schoolboys?", r"schoolgirls?", r"schoolkids?",
    r"school", r"youngsters?", r"youths?", r"childlike", r"highschool(?:ers?)?",
]
_MINOR_RE = re.compile(r"\b(?:" + "|".join(_MINOR_TERMS) + r")\b", re.I)
_ADULT_RE = re.compile(
    r"\b(?:adults?|middle[-\s]aged|elderly|older\s+(?:man|woman))\b", re.I
)


def check_prompt(prompt: str) -> str | None:
    """Return None if the prompt passes, else a reason starting with 'Blocked: '."""
    text = prompt or ""
    ages = _ages(text)
    if any(a < 18 for a in ages):
        return "Blocked: the prompt states an age under 18. Images are adults only."
    m = _MINOR_RE.search(text)
    if m:
        return (
            f"Blocked: '{m.group(0).lower()}' suggests a minor. "
            "Images are adults only; rephrase."
        )
    if ages or _ADULT_RE.search(text):
        return None
    return "Blocked: the prompt does not state an adult. " + HINT
