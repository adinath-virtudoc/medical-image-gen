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
