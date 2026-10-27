from pathlib import Path

from medimg import config
from medimg.config import Settings, load_settings, save_settings


def test_constants():
    assert config.DEFAULT_PORT == 8750 and config.DEFAULT_STEPS == 9
    assert (config.STEPS_MIN, config.STEPS_MAX) == (4, 15)
    assert config.MAX_PIXELS == 1024 * 1024 and config.SIZE_MULTIPLE == 16
    assert config.MFLUX_MODEL_ID == "filipstrand/Z-Image-Turbo-mflux-4bit"
    assert config.DIFFUSERS_MODEL_ID == "Tongyi-MAI/Z-Image-Turbo"
    assert config.GGUF_FILES["q8_0"][0].endswith("Q8_0.gguf")
    assert config.PROFILE_PATH == config.REPO_ROOT / "device_profile.json"
    assert (config.REPO_ROOT / "pyproject.toml").exists()
    assert len(config.SIZE_PRESETS) == 6


def test_round_trip(tmp_path):
    p = tmp_path / "sub" / "config.json"
    s = Settings(output_root=tmp_path / "out", port=9000, steps=8, unload_after_job=True)
    save_settings(s, p)
    assert load_settings(p) == s
    assert not list(p.parent.glob("*.tmp"))


def test_missing_and_corrupt_give_defaults(tmp_path):
    assert load_settings(tmp_path / "nope.json") == Settings()
    p = tmp_path / "c.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_settings(p) == Settings()
    p.write_text("[1,2]", encoding="utf-8")
    assert load_settings(p) == Settings()


def test_bad_values_fall_back(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"port": 99999, "steps": 2, "unload_after_job": "x"}', encoding="utf-8")
    s = load_settings(p)
    assert s.port == config.DEFAULT_PORT and s.steps == config.DEFAULT_STEPS and s.unload_after_job is None


def test_defaults_types():
    assert isinstance(Settings().output_root, Path)


def test_sdcpp_constants():
    assert config.SDCPP_RELEASE_TAG == "master-1015-e41fbcf"
    assert config.SDCPP_DEFAULT_STEPS == 8 and config.SDCPP_WARN_OVER_S == 900
    assert config.SDCPP_MIN_RAM_GB == 7.0 and config.ENGINE_CHOICES == ("auto", "sdcpp")
    assert len(config.SDCPP_SIZE_PRESETS) == 7
    assert config.TOOLS_DIR == Path.home() / ".medical-image-gen" / "tools"


def test_sdcpp_settings_round_trip(tmp_path):
    p = tmp_path / "c.json"
    s = Settings(engine="sdcpp", sdcpp_device="vulkan0", sdcpp_tier="mid", sdcpp_threads=4)
    save_settings(s, p)
    assert load_settings(p) == s
    d = Settings()
    assert (d.engine, d.sdcpp_device, d.sdcpp_tier, d.sdcpp_threads) == (None, None, None, None)
    save_settings(d, p)
    assert load_settings(p) == d


def test_sdcpp_settings_bad_values(tmp_path):
    import json
    p = tmp_path / "c.json"
    for bad in ({"engine": "auto"}, {"engine": 3}, {"sdcpp_device": "cuda0"}, {"sdcpp_tier": "ultra"},
                {"sdcpp_threads": 0}, {"sdcpp_threads": -2}, {"sdcpp_threads": True}, {"sdcpp_threads": "4"}):
        p.write_text(json.dumps(bad), encoding="utf-8")
        assert load_settings(p) == Settings(), bad


def test_steps_explicit(tmp_path):
    import json
    p = tmp_path / "c.json"
    assert Settings().steps_explicit is False
    assert load_settings(tmp_path / "missing.json").steps_explicit is False
    p.write_text(json.dumps({"port": 9000}), encoding="utf-8")
    assert load_settings(p).steps_explicit is False
    p.write_text(json.dumps({"steps": 99}), encoding="utf-8")
    assert load_settings(p).steps_explicit is False
    p.write_text(json.dumps({"steps": 8}), encoding="utf-8")
    assert load_settings(p).steps_explicit is True
    s = load_settings(p)
    out = tmp_path / "o.json"
    save_settings(s, out)
    assert "steps_explicit" not in json.loads(out.read_text())
    assert load_settings(out).steps_explicit is True  # steps itself is saved
