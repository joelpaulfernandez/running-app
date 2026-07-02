"""Tests for adaptation_engine."""
import pytest
from datetime import date, timedelta
from models.db import SessionType
from services.adaptation_engine import (
    compute_acwr,
    apply_acwr_cap,
    reschedule_missed_session,
    maybe_recalc_vdot,
    compute_volume_adherence,
)


def _activities(n_days: int, km_per_day: float, as_of: date) -> list[dict]:
    return [
        {"activity_date": as_of - timedelta(days=i), "distance_km": km_per_day}
        for i in range(n_days)
    ]


# ─── ACWR ────────────────────────────────────────────────────────────────────

def test_acwr_returns_none_under_28_days():
    as_of = date(2025, 6, 1)
    acts = _activities(20, 10, as_of)
    assert compute_acwr(acts, as_of) is None


def test_acwr_balanced_load():
    as_of = date(2025, 6, 1)
    # Need 29 days so earliest = as_of-28 → (as_of - earliest).days == 28, passes the ≥28 check
    acts = _activities(29, 10, as_of)
    ratio = compute_acwr(acts, as_of)
    # Acute covers 8 days inclusive (as_of-7 to as_of), chronic 29 days / 4 weeks → ratio ≈ 1.10
    assert ratio is not None
    assert 0.9 < ratio < 1.2


def test_acwr_spike_detects_high():
    as_of = date(2025, 6, 1)
    # Low chronic, high acute — oldest activity must be 28 days back
    old = [{"activity_date": as_of - timedelta(days=i), "distance_km": 5} for i in range(8, 29)]
    recent = [{"activity_date": as_of - timedelta(days=i), "distance_km": 20} for i in range(7)]
    ratio = compute_acwr(old + recent, as_of)
    assert ratio is not None
    assert ratio > 1.5


def test_acwr_cap_not_triggered_below_threshold():
    sessions = [{"scheduled_date": date(2025, 6, 10), "distance_km": 10.0}]
    modified, msg = apply_acwr_cap(sessions, 1.3, date(2025, 6, 9))
    assert msg is None
    assert modified[0]["distance_km"] == 10.0


def test_acwr_cap_scales_down_sessions():
    sessions = [{"scheduled_date": date(2025, 6, 10), "distance_km": 15.0}]
    modified, msg = apply_acwr_cap(sessions, 2.0, date(2025, 6, 9))
    assert msg is not None
    assert modified[0]["distance_km"] < 15.0
    # cap_factor = 1.3 / 2.0 = 0.65
    assert modified[0]["distance_km"] == pytest.approx(15.0 * 0.65, abs=0.1)


# ─── missed session reschedule ────────────────────────────────────────────────

def _make_session(session_type, on: date) -> dict:
    return {
        "session_type": session_type,
        "scheduled_date": on,
        "distance_km": 10.0,
        "linked_activity_id": None,
    }


def test_reschedule_finds_next_free_day():
    missed = _make_session(SessionType.TEMPO, date(2025, 6, 2))
    upcoming = [_make_session(SessionType.EASY, date(2025, 6, 4))]
    rescheduled, msg = reschedule_missed_session(missed, upcoming)
    assert rescheduled is not None
    assert rescheduled["scheduled_date"] == date(2025, 6, 3)


def test_reschedule_drops_when_no_slot():
    missed = _make_session(SessionType.TEMPO, date(2025, 6, 2))
    # Hard session tomorrow — no room
    upcoming = [_make_session(SessionType.INTERVAL, date(2025, 6, 3))]
    rescheduled, msg = reschedule_missed_session(missed, upcoming)
    assert rescheduled is None
    assert "dropped" in msg


# ─── VDOT recalc ─────────────────────────────────────────────────────────────

def test_vdot_recalc_skips_easy_session():
    session = {"session_type": SessionType.EASY}
    activity = {"distance_km": 8.0, "duration_seconds": 45 * 60}
    new_vdot, msg = maybe_recalc_vdot(50.0, session, activity)
    assert new_vdot == 50.0
    assert msg is None


def test_vdot_recalc_skips_small_deviation():
    # A 3 km jog won't deviate enough
    session = {"session_type": SessionType.TEMPO}
    activity = {"distance_km": 1.5, "duration_seconds": 10 * 60}
    new_vdot, msg = maybe_recalc_vdot(50.0, session, activity)
    assert new_vdot == 50.0
    assert msg is None


def test_vdot_recalc_blends_on_large_deviation():
    # A fast tempo that implies significant fitness improvement
    session = {"session_type": SessionType.TIME_TRIAL}
    # 5k in 17:00 → VDOT ~58
    activity = {"distance_km": 5.0, "duration_seconds": 17 * 60}
    new_vdot, msg = maybe_recalc_vdot(50.0, session, activity)
    assert new_vdot != 50.0
    assert msg is not None
    # Should be blended, not full new value
    assert 50.0 < new_vdot < 58.0


# ─── volume adherence ────────────────────────────────────────────────────────

def test_volume_adherence_no_trigger_mixed():
    sessions = [
        {"planned_km": 10, "actual_km": 9},
        {"planned_km": 10, "actual_km": 11},
        {"planned_km": 10, "actual_km": 8},
    ]
    scale, msg = compute_volume_adherence(sessions)
    assert scale is None


def test_volume_adherence_consistently_under():
    sessions = [{"planned_km": 10, "actual_km": 8} for _ in range(3)]
    scale, msg = compute_volume_adherence(sessions)
    assert scale == pytest.approx(0.90)
    assert "Scaling" in msg


def test_volume_adherence_consistently_over():
    sessions = [{"planned_km": 10, "actual_km": 12} for _ in range(3)]
    scale, msg = compute_volume_adherence(sessions)
    assert scale == pytest.approx(1.10)


def test_volume_adherence_needs_min_sessions():
    sessions = [{"planned_km": 10, "actual_km": 8} for _ in range(2)]
    scale, msg = compute_volume_adherence(sessions, min_sessions=3)
    assert scale is None
