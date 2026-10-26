"""benchmark() against FakeEngine only. Never a real engine."""
from __future__ import annotations

from medimg.assess import benchmark
from medimg.engines.fake_engine import FakeEngine


def test_benchmark_runs_both_sizes_with_fake_engine():
    eng = FakeEngine(step_s=0.002)
    out = benchmark(eng)
    assert eng.loaded and eng.calls == 2
    assert [(p["width"], p["height"], p["steps"]) for p in out["points"]] == [(512, 512, 4), (1024, 1024, 2)]
    for p in out["points"]:
        assert set(p) == {"width", "height", "steps", "total_s", "per_step_s", "overhead_s"}
        assert p["total_s"] > 0 and p["per_step_s"] > 0 and p["overhead_s"] >= 0
    assert out["load_s"] >= 0 and out["measured_at"]
    assert set(out["fit"]) == {"ref_pixels", "ref_per_step_s", "alpha", "overhead_s"}


def test_benchmark_custom_sizes():
    eng = FakeEngine(step_s=0.0)
    out = benchmark(eng, sizes=((256, 256, 2),))
    assert len(out["points"]) == 1 and eng.calls == 1
