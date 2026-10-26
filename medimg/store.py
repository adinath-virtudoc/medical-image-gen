"""Output store: PNG + JSON sidecar per image, in-memory index, thumbnails."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from .errors import Invalid, NotFound
from .names import image_id

PNG_KEY = "medical-image-gen"
THUMB_SIZE = 256
_SKIP_DIRS = {"_thumbs", "_sheets"}


@dataclass
class ImageRecord:
    id: str
    rel_path: str
    subject: str
    unit: str
    lecture: str
    image_name: str
    prompt: str
    seed: int
    steps: int
    width: int
    height: int
    model_id: str
    engine: str
    time_s: float
    peak_mem_gb: float
    created_at: str
    machine: str
    source: str
    sheet: dict | None = None


_FIELDS = {f.name for f in fields(ImageRecord)}


def _record_from_dict(d: dict) -> ImageRecord:
    return ImageRecord(**{k: v for k, v in d.items() if k in _FIELDS})


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser()
        self._lock = threading.RLock()
        self._index: dict[str, ImageRecord] = {}
        self.root.mkdir(parents=True, exist_ok=True)
        for d in ("_sheets", "_thumbs", "_single"):
            (self.root / d).mkdir(exist_ok=True)
        self.refresh()

    # -- paths ---------------------------------------------------------
    def path_for(self, rel: str) -> Path:
        root = self.root.resolve()
        if not rel or Path(rel).is_absolute() or rel.startswith(("/", "\\")):
            raise Invalid(f"Path {rel!r} is not a relative path.", "Use a name without folders.")
        p = (root / rel).resolve()
        if p == root or not p.is_relative_to(root):
            raise Invalid(f"Path {rel!r} escapes the output folder.", "Use a plain file name.")
        return p

    def exists(self, rel: str) -> bool:
        return self.path_for(rel).exists()

    # -- save / load -----------------------------------------------------
    def save(self, image: Image.Image, record: ImageRecord, *, overwrite: bool) -> ImageRecord:
        png = self.path_for(record.rel_path)
        with self._lock:
            if png.exists() and not overwrite:
                raise Invalid(
                    f"{record.rel_path} already exists.",
                    "Pick another Image Name or allow overwriting.",
                )
            record = replace(record, id=image_id(record.rel_path))
            payload = json.dumps(asdict(record), ensure_ascii=False)
            png.parent.mkdir(parents=True, exist_ok=True)
            info = PngInfo()
            info.add_text(PNG_KEY, payload)
            tmp = png.with_name(png.name + ".tmp")
            image.save(tmp, format="PNG", pnginfo=info)
            os.replace(tmp, png)
            side = png.with_suffix(".json")
            tmp_j = side.with_name(side.name + ".tmp")
            tmp_j.write_text(payload, encoding="utf-8")
            os.replace(tmp_j, side)
            self.refresh()
        return record

    def load_record(self, image_id: str) -> ImageRecord | None:
        with self._lock:
            return self._index.get(image_id)

    def read_png_record(self, path: Path) -> dict | None:
        try:
            with Image.open(path) as im:
                text = getattr(im, "text", {}) or {}
                raw = text.get(PNG_KEY)
            return json.loads(raw) if raw else None
        except (OSError, ValueError):
            return None

    # -- index -----------------------------------------------------------
    def refresh(self) -> None:
        index: dict[str, ImageRecord] = {}
        root = self.root
        for side in root.rglob("*.json"):
            rel_parts = side.relative_to(root).parts
            if rel_parts[0] in _SKIP_DIRS:
                continue
            png = side.with_suffix(".png")
            if not png.exists():
                continue
            try:
                rec = _record_from_dict(json.loads(side.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                continue
            index[rec.id] = rec
        with self._lock:
            self._index = index

    def _records(self) -> list[ImageRecord]:
        with self._lock:
            return list(self._index.values())

    def tree(self) -> dict:
        subjects: dict[str, dict[str, dict[str, int]]] = {}
        single = 0
        for r in self._records():
            parts = r.rel_path.split("/")
            if parts[0] == "_single":
                single += 1
            elif len(parts) == 4:
                lec = subjects.setdefault(parts[0], {}).setdefault(parts[1], {})
                lec[parts[2]] = lec.get(parts[2], 0) + 1
        out = [
            {
                "name": s,
                "units": [
                    {
                        "name": u,
                        "lectures": [
                            {"name": l, "count": c} for l, c in sorted(lecs.items())
                        ],
                    }
                    for u, lecs in sorted(units.items())
                ],
            }
            for s, units in sorted(subjects.items())
        ]
        return {"subjects": out, "single_count": single}

    def list_images(self, subject, unit, lecture) -> list[ImageRecord]:
        want = [x for x in (subject, unit, lecture)]
        res = []
        for r in self._records():
            parts = r.rel_path.split("/")[:-1]
            if subject == "_single":
                if parts != ["_single"]:
                    continue
            else:
                ok = True
                for w, p in zip(want, parts):
                    if w is not None and w != p:
                        ok = False
                        break
                if not ok or parts == ["_single"] and any(w is not None for w in want):
                    continue
            res.append(r)
        res.sort(key=lambda r: (r.created_at, r.rel_path), reverse=True)
        return res

    def folder_of(self, image_id: str) -> Path:
        r = self.load_record(image_id)
        if r is None:
            raise NotFound(f"No image with id {image_id}.", "Refresh the gallery.")
        return self.path_for(r.rel_path).parent

    def thumb_path(self, image_id: str) -> Path:
        r = self.load_record(image_id)
        if r is None:
            raise NotFound(f"No image with id {image_id}.", "Refresh the gallery.")
        png = self.path_for(r.rel_path)
        thumb = self.root / "_thumbs" / f"{image_id}.jpg"
        with self._lock:
            if not thumb.exists() or thumb.stat().st_mtime < png.stat().st_mtime:
                with Image.open(png) as im:
                    im = im.convert("RGB")
                    im.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
                    tmp = thumb.with_name(thumb.name + ".tmp")
                    im.save(tmp, format="JPEG", quality=85)
                os.replace(tmp, thumb)
        return thumb
