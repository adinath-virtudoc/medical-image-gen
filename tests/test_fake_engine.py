import pytest

from medimg.engines import make_engine
from medimg.engines.fake_engine import FakeEngine
from medimg.errors import Cancelled


def run(eng, seed=1, steps=4, w=64, h=32, cancel=lambda: False):
    events = []
    res = eng.generate("p", seed, steps, w, h, lambda *a: events.append(a), cancel)
    return res, events


def test_not_loaded_raises():
    with pytest.raises(RuntimeError, match="engine not loaded"):
        run(FakeEngine(step_s=0))


def test_progress_sequence(fake_engine):
    res, ev = run(fake_engine, steps=3)
    assert ev == [("encoding", 0, 0), ("denoising", 1, 3), ("denoising", 2, 3), ("denoising", 3, 3),
                  ("decoding", 3, 3)]
    assert res.engine == "fake" and res.peak_mem_gb == 0.0 and res.steps == 3 and res.seed == 1


def test_cancel_polled_each_step(fake_engine):
    polls = []
    def cancel():
        polls.append(1)
        return len(polls) >= 2
    events = []
    with pytest.raises(Cancelled):
        fake_engine.generate("p", 1, 5, 64, 64, lambda *a: events.append(a), cancel)
    assert len(polls) == 2
    assert ("decoding", 5, 5) not in events


def test_size_passthrough_and_divisor():
    eng = FakeEngine(step_s=0, image_size_divisor=8)
    eng.load()
    res, _ = run(eng, w=128, h=64)
    assert res.image.size == (16, 8)


def test_deterministic_colour_by_seed(fake_engine):
    a, _ = run(fake_engine, seed=7)
    b, _ = run(fake_engine, seed=7)
    c, _ = run(fake_engine, seed=8)
    assert a.image.getpixel((a.image.width - 1, a.image.height - 1)) == b.image.getpixel(
        (b.image.width - 1, b.image.height - 1))
    assert a.image.tobytes() == b.image.tobytes()
    assert a.image.tobytes() != c.image.tobytes()


def test_fail_on_nth_call():
    eng = FakeEngine(step_s=0, fail_on={2})
    eng.load()
    run(eng)
    with pytest.raises(RuntimeError, match="fake failure"):
        run(eng)
    run(eng)


def test_load_idempotent_unload_noop():
    eng = FakeEngine(step_s=0)
    eng.load(); eng.load()
    assert eng.loaded
    eng.unload(); eng.unload()
    assert not eng.loaded


def test_make_engine_fake():
    assert make_engine("mflux", None, fake=True).name == "fake"
    with pytest.raises(ValueError):
        make_engine("bogus", None)
