"""fit / estimate_seconds / estimates_table (D24)."""
from __future__ import annotations

import pytest

from medimg.assess import estimate_seconds, estimates_table, fit, record_actual

# M2 Pro reference points (PLAN 4.7 example profile)
P1 = {"width": 512, "height": 512, "steps": 4, "total_s": 30.2, "per_step_s": 5.5, "overhead_s": 8.2}
P2 = {"width": 1024, "height": 1024, "steps": 2, "total_s": 62.0, "per_step_s": 23.0, "overhead_s": 16.0}


def m2_profile(actuals=None) -> dict:
    return {"benchmark": {"points": [P1, P2], "fit": fit([P1, P2])}, "actuals": list(actuals or [])}


def test_fit_reproduces_reference_points():
    f = fit([P1, P2])
    assert f["ref_pixels"] == 262144
    assert f["ref_per_step_s"] == pytest.approx(5.5, rel=1e-3)
    assert f["alpha"] == pytest.approx(1.03, abs=0.01)
    assert f["overhead_s"] == pytest.approx(8.2)
    for p in (P1, P2):
        per_step = f["ref_per_step_s"] * (p["width"] * p["height"] / f["ref_pixels"]) ** f["alpha"]
        assert per_step == pytest.approx(p["per_step_s"], rel=1e-3)


def test_fit_order_independent_and_single_point():
    assert fit([P2, P1]) == fit([P1, P2])
    one = fit([P1])
    assert one["alpha"] == 1.0 and one["ref_per_step_s"] == pytest.approx(5.5)
    with pytest.raises(ValueError):
        fit([])


def test_estimate_768x1344_within_30_percent_of_231():
    est = estimate_seconds(m2_profile(), 768, 1344, 9)
    assert 231 * 0.7 <= est <= 231 * 1.3


def test_estimate_grows_with_size_and_steps():
    p = m2_profile()
    assert estimate_seconds(p, 512, 512, 9) < estimate_seconds(p, 1024, 1024, 9)
    assert estimate_seconds(p, 1024, 1024, 4) < estimate_seconds(p, 1024, 1024, 9)


def test_actuals_override_the_curve():
    p = m2_profile()
    curve = estimate_seconds(p, 768, 1344, 9)
    record_actual(p, 768, 1344, 9, 231.0)
    assert estimate_seconds(p, 768, 1344, 9) == pytest.approx(231.0)
    assert estimate_seconds(p, 768, 1344, 9) != pytest.approx(curve)


def test_actuals_rolling_last_10():
    p = m2_profile()
    for t in [1000.0] * 5 + [100.0] * 10:
        record_actual(p, 768, 1344, 9, t)
    assert estimate_seconds(p, 768, 1344, 9) == pytest.approx(100.0)


def test_actual_is_adjusted_for_step_count():
    p = m2_profile()
    record_actual(p, 1024, 1024, 9, 200.0)
    assert estimate_seconds(p, 1024, 1024, 4) < 200.0 < estimate_seconds(p, 1024, 1024, 12)


def test_refit_with_two_distinct_sizes_in_actuals():
    p = m2_profile()
    # machine twice as slow as the benchmark said, at two sizes
    record_actual(p, 512, 512, 9, 8.2 + 9 * 11.0)
    record_actual(p, 1024, 1024, 9, 8.2 + 9 * 46.0)
    est = estimate_seconds(p, 768, 768, 9)          # no actual at this size -> refitted curve
    bench_only = estimate_seconds(m2_profile(), 768, 768, 9)
    assert est == pytest.approx(2 * bench_only, rel=0.1)


def test_no_refit_with_a_single_size():
    p = m2_profile()
    record_actual(p, 512, 512, 9, 500.0)
    assert estimate_seconds(p, 1024, 1024, 9) == pytest.approx(estimate_seconds(m2_profile(), 1024, 1024, 9))


def test_record_actual_keeps_last_50():
    p = {"actuals": []}
    for i in range(60):
        record_actual(p, 512, 512, 9, float(i))
    assert len(p["actuals"]) == 50
    assert p["actuals"][0]["time_s"] == 10.0 and p["actuals"][-1]["time_s"] == 59.0
    assert set(p["actuals"][0]) == {"at", "width", "height", "steps", "time_s"}


def test_estimate_without_basis_raises_and_table_empty():
    with pytest.raises(ValueError):
        estimate_seconds({}, 512, 512, 9)
    assert estimates_table({"benchmark": None, "actuals": []}) == []


def test_estimates_table_rows():
    rows = estimates_table(m2_profile())
    assert [r["label"] for r in rows][:2] == ["1024x1024", "768x1344 portrait"]
    assert len(rows) == 6
    r = rows[1]
    assert r["for_10"] == pytest.approx(r["seconds"] * 10) and r["for_50"] == pytest.approx(r["seconds"] * 50)
    assert set(r) >= {"label", "width", "height", "seconds", "for_10", "for_25", "for_50"}


def test_estimates_table_presets():
    from medimg import config
    prof = m2_profile()
    rows = estimates_table(prof, config.SDCPP_DEFAULT_STEPS, presets=config.SDCPP_SIZE_PRESETS)
    assert len(rows) == 7 and rows[0]["label"] == "512x512 draft"
    assert len(estimates_table(prof)) == 6
    assert estimates_table({"benchmark": None, "actuals": []}, presets=config.SDCPP_SIZE_PRESETS) == []
