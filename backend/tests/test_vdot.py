"""Tests for VDOT calculations."""
import pytest
from services.vdot import (
    pace_to_vdot,
    pace_zones,
    blend_vdot,
    peak_mileage_for_vdot,
    feasibility_warnings,
    fmt_pace,
    RACE_DISTANCE_KM,
)


def test_fmt_pace_basic():
    assert fmt_pace(4.0) == "4:00"
    assert fmt_pace(4.5) == "4:30"
    assert fmt_pace(5.533) == "5:32"


def test_fmt_pace_rollover():
    # 59.5 seconds rounds to 60 → should carry into next minute
    assert fmt_pace(4 + 59.5 / 60) == "5:00"


def test_pace_to_vdot_known_values():
    # Sub-20 5k (19:59) ≈ VDOT 49-51 per Daniels tables
    vdot = pace_to_vdot(5.0, 19 * 60 + 59)
    assert 48 < vdot < 52

    # 3:30 marathon ≈ VDOT 44-46 per Daniels formula
    vdot = pace_to_vdot(42.195, 3 * 3600 + 30 * 60)
    assert 43 < vdot < 47

    # Very slow 5k → VDOT clamped at minimum 20
    vdot = pace_to_vdot(5.0, 60 * 60)
    assert vdot == 20.0


def test_pace_zones_ordering():
    zones = pace_zones(50)
    # Each zone: lo (faster) < hi (slower) in min/km
    for name, z in zones.items():
        assert z.lo < z.hi, f"Zone {name}: lo should be faster (lower) than hi"


def test_pace_zones_intensity_ordering():
    zones = pace_zones(50)
    # E slowest, R fastest: E.lo > M.lo > T.lo > I.lo > R.lo
    assert zones["E"].lo > zones["M"].lo
    assert zones["M"].lo > zones["T"].lo
    assert zones["T"].lo > zones["I"].lo
    assert zones["I"].lo > zones["R"].lo


def test_pace_zones_scale_with_vdot():
    z30 = pace_zones(30)
    z60 = pace_zones(60)
    # Higher VDOT → faster paces (lower min/km)
    for name in ("E", "M", "T", "I", "R"):
        assert z60[name].mid < z30[name].mid, f"Zone {name} should be faster at higher VDOT"


def test_blend_vdot():
    result = blend_vdot(50.0, 60.0)
    assert result == pytest.approx(0.7 * 50.0 + 0.3 * 60.0)


def test_peak_mileage_increases_with_vdot():
    for race in ("5k", "10k", "half", "marathon"):
        km_low = peak_mileage_for_vdot(30, race)
        km_high = peak_mileage_for_vdot(60, race)
        assert km_high > km_low


def test_peak_mileage_increases_with_distance():
    vdot = 45
    assert peak_mileage_for_vdot(vdot, "5k") < peak_mileage_for_vdot(vdot, "10k")
    assert peak_mileage_for_vdot(vdot, "10k") < peak_mileage_for_vdot(vdot, "half")
    assert peak_mileage_for_vdot(vdot, "half") < peak_mileage_for_vdot(vdot, "marathon")


def test_feasibility_warnings_too_few_weeks():
    warnings = feasibility_warnings(50, "marathon", None, 8)
    assert any("minimum" in w for w in warnings)


def test_feasibility_warnings_too_many_weeks():
    warnings = feasibility_warnings(50, "5k", None, 15)
    assert any("exceeds" in w for w in warnings)


def test_feasibility_warnings_aggressive_target():
    # VDOT 40 trying to hit a VDOT-55 pace in 10 weeks
    target_vdot55_5k_seconds = int(pace_to_vdot.__wrapped__(5.0, 1) if False else 0) or None
    # Manually construct: VDOT 55 ≈ sub-18 5k (~17:30)
    warnings = feasibility_warnings(40, "5k", 17 * 60 + 30, 10)
    assert any("aggressive" in w for w in warnings)


def test_feasibility_no_warnings_normal():
    warnings = feasibility_warnings(50, "half", None, 12)
    assert warnings == []
