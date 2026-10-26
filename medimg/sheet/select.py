"""Batch selection: first N pending rows in sheet order after the optional filter."""
from __future__ import annotations

from .reader import Row


def select_batch(rows: list[Row], n: int, flt: dict[str, str] | None) -> list[Row]:
    flt = {k.casefold(): str(v).strip().casefold() for k, v in (flt or {}).items() if v and str(v).strip()}
    out: list[Row] = []
    for r in rows:
        if len(out) >= n:
            break
        if r.status != "pending":
            continue
        if any(getattr(r, k).strip().casefold() != v for k, v in flt.items()
               if k in ("subject", "unit", "lecture")):
            continue
        out.append(r)
    return out
