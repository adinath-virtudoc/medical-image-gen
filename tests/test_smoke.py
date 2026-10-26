from argparse import Namespace

import pytest
from PIL import Image

from medimg import smoke
from medimg.errors import Invalid


def test_fake_engine_writes_png_and_prints(tmp_path, capsys):
    rc = smoke.run(Namespace(size="512x512", steps=4, fake_engine=True, output_root=str(tmp_path)))
    assert rc == 0
    pngs = list((tmp_path / "_smoke").glob("*.png"))
    assert len(pngs) == 1
    Image.open(pngs[0]).verify()
    out = capsys.readouterr().out
    assert str(pngs[0]) in out
    assert " s" in out and "generate" in out


def test_default_root_from_settings(tmp_path, monkeypatch):
    from medimg import config
    monkeypatch.setattr(config, "load_settings", lambda *a, **k: config.Settings(output_root=tmp_path))
    assert smoke.run(Namespace(size="256x256", steps=4, fake_engine=True)) == 0
    assert list((tmp_path / "_smoke").glob("*.png"))


@pytest.mark.parametrize("bad", ["abc", "512", "64x64", "9999x512"])
def test_bad_size(bad):
    with pytest.raises(Invalid):
        smoke.parse_size(bad)


def test_size_rounds_down():
    assert smoke.parse_size("1000x520") == (992, 512)
