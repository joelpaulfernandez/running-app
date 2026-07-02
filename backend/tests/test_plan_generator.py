"""Tests for plan_generator: mileage curve, phase maps, long-run curve, week generation."""
import pytest
from datetime import date
from models.db import PlanPhase, SessionType
from services.plan_generator import (
    _standard_phase_map,
    _5k_phase_map,
    _build_mileage_curve,
    _build_long_run_curve,
    generate_week,
    generate_plan,
)
from services.vdot import pace_zones, peak_mileage_for_vdot


# ─── phase maps ──────────────────────────────────────────────────────────────

def test_standard_phase_map_length():
    for weeks in (8, 10, 12, 14, 16, 18, 20):
        pm = _standard_phase_map(weeks)
        assert len(pm) == weeks


def test_standard_phase_map_order():
    pm = _standard_phase_map(16, "marathon")
    phases = [p.value for p in pm]
    # Must be base → build → peak → taper, no phase appearing after a later one
    order = ["base", "build", "peak", "taper"]
    prev_idx = -1
    for phase in phases:
        idx = order.index(phase)
        assert idx >= prev_idx
        prev_idx = idx


def test_marathon_gets_3_taper_weeks():
    pm = _standard_phase_map(16, "marathon")
    taper_count = sum(1 for p in pm if p == PlanPhase.TAPER)
    assert taper_count == 3


def test_non_marathon_gets_fewer_taper_weeks():
    pm = _standard_phase_map(16, "half")
    taper_count = sum(1 for p in pm if p == PlanPhase.TAPER)
    assert taper_count <= 2


def test_5k_phase_map_length():
    for weeks in (6, 8, 10):
        pm = _5k_phase_map(weeks)
        assert len(pm) == weeks


# ─── mileage curve ───────────────────────────────────────────────────────────

def test_mileage_curve_length():
    pm = _standard_phase_map(16, "marathon")
    mileages = _build_mileage_curve(50, 90, 16, pm)
    assert len(mileages) == 16


def test_mileage_curve_starts_near_start_km():
    pm = _standard_phase_map(16, "marathon")
    mileages = _build_mileage_curve(50, 90, 16, pm)
    assert mileages[0] == pytest.approx(50.0, abs=2)


def test_mileage_curve_peak_at_end_of_nontaper():
    pm = _standard_phase_map(16, "marathon")
    mileages = _build_mileage_curve(50, 90, 16, pm)
    # Last non-taper week should hit peak_km
    last_nontaper_idx = max(i for i, p in enumerate(pm) if p != PlanPhase.TAPER)
    assert mileages[last_nontaper_idx] == pytest.approx(90.0, abs=1)


def test_mileage_curve_taper_descends():
    pm = _standard_phase_map(16, "marathon")
    mileages = _build_mileage_curve(50, 90, 16, pm)
    taper_mileages = [mileages[i] for i, p in enumerate(pm) if p == PlanPhase.TAPER]
    for i in range(len(taper_mileages) - 1):
        assert taper_mileages[i] > taper_mileages[i + 1]


def test_no_stepback_in_peak_phase():
    """Bug fix: step-backs must not fire in peak phase — 16-week marathon triggers index 11."""
    pm = _standard_phase_map(16, "marathon")
    mileages = _build_mileage_curve(55, 90, 16, pm)
    peak_indices = [i for i, p in enumerate(pm) if p == PlanPhase.PEAK]
    peak_mileages = [mileages[i] for i in peak_indices]
    # Both peak weeks should be above 80% of peak_km (a step-back would drop to ~73 km)
    for km in peak_mileages:
        assert km >= 90.0 * 0.80, f"Peak week dropped to {km:.1f} — step-back fired in peak phase"


def test_taper_never_exceeds_any_peak_week():
    pm = _standard_phase_map(16, "marathon")
    mileages = _build_mileage_curve(55, 90, 16, pm)
    peak_max = max(mileages[i] for i, p in enumerate(pm) if p == PlanPhase.PEAK)
    taper_max = max(mileages[i] for i, p in enumerate(pm) if p == PlanPhase.TAPER)
    assert taper_max < peak_max


def test_stepback_fires_in_base_and_build():
    pm = _standard_phase_map(16, "marathon")
    mileages = _build_mileage_curve(40, 90, 16, pm)
    # Week 4 (index 3) is in base — should dip below week 5
    assert mileages[3] < mileages[4], "Step-back in base phase not firing"
    # Week 8 (index 7) is in build — should dip below week 9
    assert mileages[7] < mileages[8], "Step-back in build phase not firing"


# ─── long run curve ──────────────────────────────────────────────────────────

def test_long_run_curve_length():
    pm = _standard_phase_map(16, "marathon")
    mileages = _build_mileage_curve(55, 90, 16, pm)
    long_runs = _build_long_run_curve(mileages, pm, "marathon")
    assert len(long_runs) == 16


def test_marathon_long_run_hard_cap():
    pm = _standard_phase_map(16, "marathon")
    mileages = _build_mileage_curve(55, 90, 16, pm)
    long_runs = _build_long_run_curve(mileages, pm, "marathon")
    assert max(long_runs) <= 32.0


def test_marathon_taper_long_run_uses_aggressive_pcts():
    """Marathon taper long-run should use 75/55/30/20%, not 85/70/55/45%."""
    pm = _standard_phase_map(16, "marathon")
    mileages = _build_mileage_curve(55, 90, 16, pm)
    long_runs = _build_long_run_curve(mileages, pm, "marathon")

    taper_lrs = [long_runs[i] for i, p in enumerate(pm) if p == PlanPhase.TAPER]
    peak_long = 32.0  # hard cap for marathon

    # First taper week: should be 75% (24 km), not 85% (27.2 km)
    assert taper_lrs[0] == pytest.approx(peak_long * 0.75, abs=1.0)
    assert taper_lrs[1] == pytest.approx(peak_long * 0.55, abs=1.0)


def test_long_run_jump_cap_per_week():
    """Consecutive non-taper long-run increases must not exceed max(+15%, +2 km)."""
    for race in ("5k", "10k", "half", "marathon"):
        pm = _standard_phase_map(16, race)
        mileages = _build_mileage_curve(40, 90, 16, pm)
        long_runs = _build_long_run_curve(mileages, pm, race)

        non_taper_lrs = [long_runs[i] for i, p in enumerate(pm) if p != PlanPhase.TAPER]
        for i in range(1, len(non_taper_lrs)):
            prev = non_taper_lrs[i - 1]
            curr = non_taper_lrs[i]
            if curr > prev:
                cap = max(prev * 1.15, prev + 2.0)
                assert curr <= cap + 0.2, (  # +0.2 for rounding
                    f"{race} Wk{i}→Wk{i+1}: long run jumped {prev:.1f}→{curr:.1f} km, "
                    f"exceeds cap of {cap:.1f}"
                )


def test_long_run_taper_descends():
    for race in ("5k", "10k", "half", "marathon"):
        pm = _standard_phase_map(14, race)
        mileages = _build_mileage_curve(40, 70, 14, pm)
        long_runs = _build_long_run_curve(mileages, pm, race)
        taper_lrs = [long_runs[i] for i, p in enumerate(pm) if p == PlanPhase.TAPER]
        if len(taper_lrs) > 1:
            assert taper_lrs[0] > taper_lrs[-1], f"{race} taper long run doesn't descend"


def test_long_run_fraction_of_weekly_volume():
    pm = _standard_phase_map(12, "half")
    mileages = _build_mileage_curve(40, 70, 12, pm)
    long_runs = _build_long_run_curve(mileages, pm, "half")
    # Half marathon: long run = 30% of weekly volume (non-taper)
    for i, (wk, ph, lr) in enumerate(zip(mileages, pm, long_runs)):
        if ph != PlanPhase.TAPER:
            assert lr == pytest.approx(wk * 0.30, abs=2.0), f"Week {i+1} long run ratio off"


# ─── week generation ─────────────────────────────────────────────────────────

TRAINING_DAYS = ["monday", "tuesday", "thursday", "friday", "saturday", "sunday"]
LONG_RUN_DAY = "sunday"
ZONES = pace_zones(50)


def _gen_week(phase="build", week_km=60.0, week_in_phase=2, is_tt=False):
    return generate_week(
        week_number=5,
        phase=phase,
        week_km=week_km,
        week_in_phase=week_in_phase,
        training_days=TRAINING_DAYS,
        long_run_day=LONG_RUN_DAY,
        zones=ZONES,
        race_distance="half",
        is_time_trial_week=is_tt,
        week_start=date(2025, 1, 6),
    )


def test_week_session_count():
    sessions = _gen_week()
    assert len(sessions) == len(TRAINING_DAYS)


def test_week_total_volume_matches_target():
    week_km = 65.0
    sessions = _gen_week(week_km=week_km)
    total = sum(s["distance_km"] for s in sessions)
    assert total == pytest.approx(week_km, abs=1.5)


def test_week_has_exactly_one_long_run():
    sessions = _gen_week()
    long_runs = [s for s in sessions if s["session_type"] == SessionType.LONG]
    assert len(long_runs) == 1
    assert long_runs[0]["scheduled_date"].strftime("%A").lower() == LONG_RUN_DAY


def test_build_phase_has_two_quality_sessions():
    sessions = _gen_week(phase="build")
    quality = [s for s in sessions if s["session_type"] in (SessionType.TEMPO, SessionType.INTERVAL)]
    assert len(quality) == 2


def test_taper_phase_has_one_quality_session():
    sessions = _gen_week(phase="taper")
    quality = [s for s in sessions if s["session_type"] in (SessionType.TEMPO, SessionType.INTERVAL)]
    assert len(quality) == 1


def test_time_trial_week_replaces_first_quality():
    sessions = _gen_week(is_tt=True)
    tt = [s for s in sessions if s["session_type"] == SessionType.TIME_TRIAL]
    assert len(tt) == 1


def test_interval_quality_work_capped_at_8km():
    """
    interval_800 and interval_1000 both have quality_max_km=8.0.
    Actual rep volume (reps × rep_dist) must not exceed that cap regardless of week_km.
    Tests high week_km to pressure the cap.
    """
    import json
    from pathlib import Path
    shapes = json.loads((Path("services/workout_shapes.json")).read_text())["shapes"]

    for shape_name, rep_km in (("interval_800", 0.8), ("interval_1000", 1.0)):
        shape = shapes[shape_name]
        quality_max = shape["quality_max_km"]

        for week_km in (40, 80, 120, 200):
            quality_km = min(week_km * shape["quality_pct_of_week"], quality_max)
            reps = max(shape["reps_min"], min(shape["reps_max"], round(quality_km / rep_km)))
            actual_rep_km = reps * rep_km
            assert actual_rep_km <= quality_max + 0.01, (
                f"{shape_name} at week_km={week_km}: rep volume {actual_rep_km:.1f} km "
                f"exceeds quality_max_km={quality_max}"
            )


def test_easy_runs_are_capped_at_15km():
    sessions = _gen_week(week_km=120.0)
    easy = [s for s in sessions if s["session_type"] == SessionType.EASY]
    for s in easy:
        assert s["distance_km"] <= 15.0


def test_easy_runs_have_minimum_distance():
    sessions = _gen_week(week_km=20.0)
    easy = [s for s in sessions if s["session_type"] == SessionType.EASY]
    for s in easy:
        assert s["distance_km"] >= 4.0


def test_all_sessions_have_scheduled_dates():
    sessions = _gen_week()
    for s in sessions:
        assert s["scheduled_date"] is not None


def test_all_sessions_have_descriptions():
    sessions = _gen_week()
    for s in sessions:
        assert s["description"] and len(s["description"]) > 10


# ─── full plan generation ─────────────────────────────────────────────────────

@pytest.mark.parametrize("race_distance", ["5k", "10k", "half", "marathon"])
def test_full_plan_has_sessions(race_distance):
    sessions = generate_plan(
        race_distance=race_distance,
        race_date=date(2025, 10, 1),
        vdot=45,
        current_weekly_mileage=50,
        training_days=["monday", "wednesday", "friday", "saturday", "sunday"],
        long_run_day="sunday",
        start_date=date(2025, 6, 1),
    )
    assert len(sessions) > 0


def test_plan_race_day_is_time_trial():
    race_date = date(2025, 10, 1)
    sessions = generate_plan(
        race_distance="half",
        race_date=race_date,
        vdot=50,
        current_weekly_mileage=50,
        training_days=["monday", "wednesday", "friday", "saturday", "sunday"],
        long_run_day="sunday",
        start_date=date(2025, 7, 1),
    )
    race_sessions = [s for s in sessions if s["scheduled_date"] == race_date]
    assert len(race_sessions) == 1
    assert race_sessions[0]["session_type"] == SessionType.TIME_TRIAL


def test_plan_no_taper_week_exceeds_peak():
    """Taper volume must always be less than the peak week volume."""
    sessions = generate_plan(
        race_distance="marathon",
        race_date=date(2026, 4, 1),
        vdot=45,
        current_weekly_mileage=55,
        training_days=["monday", "tuesday", "thursday", "friday", "saturday", "sunday"],
        long_run_day="sunday",
        start_date=date(2025, 12, 1),
    )
    by_week: dict[int, list] = {}
    for s in sessions:
        by_week.setdefault(s["week_number"], []).append(s)

    week_totals = {wk: (sum(s["distance_km"] for s in ss), ss[0]["phase"]) for wk, ss in by_week.items()}
    peak_max = max(total for total, phase in week_totals.values() if phase == PlanPhase.PEAK)
    for total, phase in week_totals.values():
        if phase == PlanPhase.TAPER:
            assert total < peak_max, f"Taper week volume {total:.1f} exceeds peak max {peak_max:.1f}"


def test_plan_week_numbers_are_sequential():
    sessions = generate_plan(
        race_distance="half",
        race_date=date(2025, 10, 1),
        vdot=48,
        current_weekly_mileage=45,
        training_days=["monday", "wednesday", "saturday", "sunday"],
        long_run_day="sunday",
        start_date=date(2025, 7, 1),
    )
    week_nums = sorted(set(s["week_number"] for s in sessions))
    assert week_nums == list(range(1, len(week_nums) + 1))
