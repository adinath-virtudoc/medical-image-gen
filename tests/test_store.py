import os
import threading
from dataclasses import replace

import pytest
from PIL import Image

from medimg.errors import Invalid
from medimg.names import image_id
from medimg.store import PNG_KEY, ImageRecord, Store


def rec(rel="Anat/Upper/Hand/x.png", created="2026-01-01T00:00:00", **kw):
    parts = rel.split("/")
    s, u, l = (parts[:3] if len(parts) == 4 else ("", "", ""))
    base = dict(
        id="", rel_path=rel, subject=s, unit=u, lecture=l, image_name=parts[-1][:-4],
        prompt="p", seed=1, steps=4, width=64, height=48, model_id="m", engine="fake",
        time_s=0.1, peak_mem_gb=0.0, created_at=created, machine="h", source="batch", sheet=None,
    )
    base.update(kw)
    return ImageRecord(**base)


def img(w=64, h=48):
    return Image.new("RGB", (w, h), (200, 10, 10))


def test_init_dirs(tmp_path):
    Store(tmp_path / "out")
    for d in ("_sheets", "_thumbs", "_single"):
        assert (tmp_path / "out" / d).is_dir()


def test_path_escape(tmp_path):
    s = Store(tmp_path)
    for bad in ("../x.png", "a/../../x.png", "/etc/passwd"):
        with pytest.raises(Invalid):
            s.path_for(bad)


def test_save_and_text_chunk(tmp_path):
    s = Store(tmp_path)
    r = s.save(img(), rec(), overwrite=False)
    p = s.path_for(r.rel_path)
    assert p.exists() and p.with_suffix(".json").exists()
    assert s.exists(r.rel_path)
    with Image.open(p) as im:
        txt = im.text[PNG_KEY]
    import json
    assert json.loads(txt)["prompt"] == "p"
    assert s.read_png_record(p)["id"] == r.id == image_id(r.rel_path)
    assert s.load_record(r.id) == r


def test_overwrite_flag(tmp_path):
    s = Store(tmp_path)
    s.save(img(), rec(), overwrite=False)
    with pytest.raises(Invalid):
        s.save(img(), rec(), overwrite=False)
    r = s.save(img(), rec(prompt="new"), overwrite=True)
    assert s.load_record(r.id).prompt == "new"


def test_tree_and_list(tmp_path):
    s = Store(tmp_path)
    s.save(img(), rec("A/U1/L1/a.png", "2026-01-01"), overwrite=False)
    s.save(img(), rec("A/U1/L1/b.png", "2026-02-01"), overwrite=False)
    s.save(img(), rec("A/U2/L2/c.png", "2026-03-01"), overwrite=False)
    s.save(img(), rec("_single/z.png", "2026-04-01"), overwrite=False)
    t = s.tree()
    assert t["single_count"] == 1
    assert t["subjects"] == [{"name": "A", "units": [
        {"name": "U1", "lectures": [{"name": "L1", "count": 2}]},
        {"name": "U2", "lectures": [{"name": "L2", "count": 1}]},
    ]}]
    assert [r.image_name for r in s.list_images("A", "U1", "L1")] == ["b", "a"]
    assert [r.image_name for r in s.list_images("A", None, None)] == ["c", "b", "a"]
    assert [r.image_name for r in s.list_images(None, None, None)] == ["z", "c", "b", "a"]
    assert [r.rel_path for r in s.list_images("_single", None, None)] == ["_single/z.png"]


def test_ignores_png_without_sidecar_and_dirs(tmp_path):
    s = Store(tmp_path)
    s.save(img(), rec(), overwrite=False)
    img().save(tmp_path / "A.png")
    (tmp_path / "_sheets" / "s.json").write_text("{}")
    (tmp_path / "bad.json").write_text("not json")
    s.refresh()
    assert len(s.list_images(None, None, None)) == 1


def test_id_stable_across_instances(tmp_path):
    r = Store(tmp_path).save(img(), rec(), overwrite=False)
    s2 = Store(tmp_path)
    assert s2.load_record(r.id) == r
    assert s2.folder_of(r.id) == tmp_path.resolve() / "Anat/Upper/Hand"


def test_thumb(tmp_path):
    s = Store(tmp_path)
    r = s.save(img(1024, 512), rec(), overwrite=False)
    t = s.thumb_path(r.id)
    with Image.open(t) as im:
        assert im.format == "JPEG" and max(im.size) == 256
    # regenerated when the PNG is newer
    png = s.path_for(r.rel_path)
    os.utime(png, (t.stat().st_mtime + 10,) * 2)
    s.save(img(100, 100), rec(), overwrite=True)
    os.utime(png, (t.stat().st_mtime + 20,) * 2)
    with Image.open(s.thumb_path(r.id)) as im:
        assert max(im.size) == 100


def test_concurrent_reads_during_save(tmp_path):
    s = Store(tmp_path)
    errs = []

    def reader():
        try:
            for _ in range(200):
                s.tree(); s.list_images(None, None, None)
        except Exception as e:  # pragma: no cover
            errs.append(e)

    ts = [threading.Thread(target=reader) for _ in range(3)]
    [t.start() for t in ts]
    for i in range(10):
        s.save(img(), rec(f"A/B/C/{i}.png"), overwrite=False)
    [t.join() for t in ts]
    assert not errs and len(s.list_images(None, None, None)) == 10
