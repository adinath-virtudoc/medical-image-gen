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


def test_fake_engine_wins_over_engine_flag(tmp_path, capsys):
    rc = smoke.run(Namespace(size="256x256", steps=4, fake_engine=True, engine="sdcpp",
                             output_root=str(tmp_path)))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Loading the model (fake)" in out and "sdcpp" not in out


def test_sdcpp_prints_device_and_passes_engine_to_decide(tmp_path, monkeypatch, capsys):
    import medimg.assess as assess_pkg
    import medimg.engines as engines
    from medimg import config
    from medimg.assess.decide import Decision
    from medimg.engines.fake_engine import FakeEngine

    seen = {}

    def fake_decide(m, **kw):
        seen["engine"] = kw.get("engine")
        return Decision("sdcpp", True, "", "", None, False, None, 5.0, 10.0, device="cpu", tier="low")

    class Sd(FakeEngine):
        name = "sdcpp"
        device = "cpu"

    def fake_make(backend, profile, **kw):
        seen["backend"], seen["profile"] = backend, profile
        return Sd()

    monkeypatch.setattr(assess_pkg, "detect", lambda **kw: object())
    monkeypatch.setattr(assess_pkg, "decide", fake_decide)
    monkeypatch.setattr(assess_pkg, "load_profile", lambda *a, **k: None)
    monkeypatch.setattr(engines, "make_engine", fake_make)
    monkeypatch.setattr(config, "load_settings", lambda *a, **k: config.Settings(output_root=tmp_path))
    assert smoke.run(Namespace(size="256x256", steps=4, fake_engine=False, engine="sdcpp",
                               output_root=str(tmp_path))) == 0
    assert seen["engine"] == "sdcpp" and seen["backend"] == "sdcpp"
    assert seen["profile"]["backend"]["device"] == "cpu"
    assert seen["profile"]["backend"]["sdcpp"] == {"tier": "low"}
    assert "Loading the model (sdcpp on cpu)..." in capsys.readouterr().out


def test_profile_of_other_backend_ignored_when_engine_forced(tmp_path, monkeypatch):
    import medimg.assess as assess_pkg
    import medimg.engines as engines
    from medimg import config
    from medimg.assess.decide import Decision
    from medimg.engines.fake_engine import FakeEngine

    made = []
    monkeypatch.setattr(assess_pkg, "detect", lambda **kw: object())
    monkeypatch.setattr(assess_pkg, "decide", lambda m, **kw: Decision(
        "sdcpp", True, "", "", None, False, None, 5.0, 10.0, device="metal", tier="mid"))
    monkeypatch.setattr(assess_pkg, "load_profile", lambda *a, **k: {"backend": {"supported": True, "name": "mflux"}})
    monkeypatch.setattr(engines, "make_engine", lambda b, p, **kw: made.append(b) or FakeEngine())
    monkeypatch.setattr(config, "load_settings", lambda *a, **k: config.Settings(output_root=tmp_path))
    smoke.run(Namespace(size="256x256", steps=4, fake_engine=False, engine="sdcpp", output_root=str(tmp_path)))
    assert made == ["sdcpp"]
