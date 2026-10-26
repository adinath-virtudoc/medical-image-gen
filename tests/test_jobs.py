import pytest

from medimg import config
from medimg.errors import Blocked, Invalid
from medimg.jobs import (JobSpec, RowJob, normalise_size, parse_size, random_seed,
                         validate_row_job)


def job(**kw):
    base = dict(prompt="a 45-year-old adult man, clinic photo", seed=None, steps=9, width=1024,
                height=1024, subject="S", unit="U", lecture="L", image_name="n")
    base.update(kw)
    return RowJob(**base)


def test_normalise_rounds_down():
    assert normalise_size(770, 1350) == (768, 1344)
    assert normalise_size(1344, 768) == (1344, 768)


@pytest.mark.parametrize("w,h", [(100, 100), (2000, 512), (1536, 1536), (255, 1024)])
def test_normalise_rejects_out_of_range(w, h):
    with pytest.raises(Invalid):
        normalise_size(w, h)


@pytest.mark.parametrize("text", ["768x1344", "768 x 1344", "768×1344", " 768X1344 "])
def test_parse_size_variants(text):
    assert parse_size(text) == (768, 1344)


@pytest.mark.parametrize("text", ["", "768", "axb", "768x", "-1x5"])
def test_parse_size_bad(text):
    with pytest.raises(Invalid):
        parse_size(text)


def test_validate_fills_seed_and_rounds():
    v = validate_row_job(job(width=770, height=1350))
    assert (v.width, v.height) == (768, 1344)
    assert 0 <= v.seed <= config.SEED_MAX
    assert validate_row_job(job(seed=5)).seed == 5
    assert 0 <= random_seed() <= config.SEED_MAX


def test_validate_blocks_minor_and_unstated_age():
    with pytest.raises(Blocked) as e:
        validate_row_job(job(prompt="a teen boy at the clinic"))
    assert e.value.cause.startswith("Blocked: ")
    with pytest.raises(Blocked):
        validate_row_job(job(prompt="a woman holding her knee"))


@pytest.mark.parametrize("kw", [dict(steps=3), dict(steps=16), dict(seed=-1),
                                dict(seed=config.SEED_MAX + 1), dict(prompt="  "),
                                dict(width=100, height=100)])
def test_validate_invalid(kw):
    with pytest.raises(Invalid):
        validate_row_job(job(**kw))


def test_validate_step_bounds_ok():
    assert validate_row_job(job(steps=4)).steps == 4
    assert validate_row_job(job(steps=15)).steps == 15


def test_jobspec_defaults():
    s = JobSpec(kind="single", rows=[job()])
    assert s.sheet_path is None and s.sheet_name is None
