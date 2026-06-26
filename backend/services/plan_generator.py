"""
Plan generation: VDOT + periodization templates.
5K uses a separate speed-focused template.
10K/half/marathon share base→build→peak→taper.
"""
from datetime import date, timedelta
from typing import Optional
import math

from services.vdot import (
    vdot_to_easy_pace_min_per_km,
    vdot_to_tempo_pace_min_per_km,
    vdot_to_interval_pace_min_per_km,
    peak_mileage_for_vdot,
    RACE_DISTANCE_KM,
)
from models.db import SessionType, PlanPhase


DAYS_OF_WEEK = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def generate_plan(
    race_distance: str,
    race_date: date,
    vdot: float,
    current_weekly_mileage: float,
    training_days: list[str],
    long_run_day: str,
    start_date: Optional[date] = None,
) -> list[dict]:
    """
    Returns list of planned session dicts (not DB objects — caller saves them).
    Each dict maps to PlannedSession columns.
    """
    if start_date is None:
        start_date = date.today()

    weeks_total = max(1, (race_date - start_date).days // 7)
    peak_km = peak_mileage_for_vdot(vdot, race_distance)

    if race_distance == "5k":
        phase_map = _5k_phase_map(weeks_total)
    else:
        phase_map = _standard_phase_map(weeks_total)

    # Week-by-week mileage progression
    weekly_mileages = _build_mileage_curve(
        current_weekly_mileage, peak_km, weeks_total, phase_map
    )

    sessions = []
    current_date = start_date
    # Advance to Monday of the first week
    while current_date.strftime("%A").lower() != "monday":
        current_date += timedelta(days=1)

    for week_idx, (week_km, phase) in enumerate(zip(weekly_mileages, phase_map)):
        week_number = week_idx + 1
        is_time_trial_week = (week_idx % 3 == 2) and phase in (PlanPhase.BASE, PlanPhase.BUILD)

        week_sessions = _assign_week_sessions(
            week_number=week_number,
            phase=phase,
            week_km=week_km,
            training_days=training_days,
            long_run_day=long_run_day,
            vdot=vdot,
            race_distance=race_distance,
            is_time_trial_week=is_time_trial_week,
            week_start=current_date,
        )
        sessions.extend(week_sessions)
        current_date += timedelta(weeks=1)

    return sessions


def _assign_week_sessions(
    week_number: int,
    phase: str,
    week_km: float,
    training_days: list[str],
    long_run_day: str,
    vdot: float,
    race_distance: str,
    is_time_trial_week: bool,
    week_start: date,
) -> list[dict]:
    easy_pace = vdot_to_easy_pace_min_per_km(vdot)
    tempo_pace = vdot_to_tempo_pace_min_per_km(vdot)
    interval_pace = vdot_to_interval_pace_min_per_km(vdot)

    # Long run is 30-35% of weekly volume
    long_run_km = round(week_km * 0.33, 1)
    remaining_km = week_km - long_run_km

    # Identify non-long-run training days
    other_days = [d for d in training_days if d != long_run_day]
    key_session_day = other_days[len(other_days) // 2] if other_days else None

    sessions = []

    for day_name in training_days:
        day_offset = DAYS_OF_WEEK.index(day_name)
        session_date = week_start + timedelta(days=day_offset)

        if day_name == long_run_day:
            sessions.append({
                "scheduled_date": session_date,
                "session_type": SessionType.LONG,
                "phase": phase,
                "week_number": week_number,
                "distance_km": long_run_km,
                "pace_target_min_per_km": easy_pace,
                "description": f"Long run at easy effort. Stay conversational.",
            })
        elif day_name == key_session_day:
            if is_time_trial_week:
                tt_distance = min(RACE_DISTANCE_KM[race_distance], 5.0)
                sessions.append({
                    "scheduled_date": session_date,
                    "session_type": SessionType.TIME_TRIAL,
                    "phase": phase,
                    "week_number": week_number,
                    "distance_km": tt_distance,
                    "pace_target_min_per_km": None,
                    "description": f"Time trial: {tt_distance:.1f}km at max effort. Used for VDOT recalibration.",
                })
            elif phase == PlanPhase.BASE:
                km = min(remaining_km * 0.5, 12.0)
                sessions.append({
                    "scheduled_date": session_date,
                    "session_type": SessionType.TEMPO,
                    "phase": phase,
                    "week_number": week_number,
                    "distance_km": round(km, 1),
                    "pace_target_min_per_km": tempo_pace,
                    "description": f"Tempo run at threshold pace ({tempo_pace:.2f} min/km). Comfortably hard.",
                })
            elif phase == PlanPhase.BUILD:
                km = min(remaining_km * 0.45, 10.0)
                sessions.append({
                    "scheduled_date": session_date,
                    "session_type": SessionType.INTERVAL,
                    "phase": phase,
                    "week_number": week_number,
                    "distance_km": round(km, 1),
                    "pace_target_min_per_km": interval_pace,
                    "description": f"Intervals at VO2max pace ({interval_pace:.2f} min/km). 4×1km with 90s recovery.",
                })
            elif phase in (PlanPhase.PEAK, PlanPhase.TAPER):
                km = min(remaining_km * 0.4, 8.0)
                sessions.append({
                    "scheduled_date": session_date,
                    "session_type": SessionType.TEMPO,
                    "phase": phase,
                    "week_number": week_number,
                    "distance_km": round(km, 1),
                    "pace_target_min_per_km": tempo_pace,
                    "description": "Race-pace tempo. Controlled but fast.",
                })
        else:
            # Easy filler runs for remaining days
            n_other = max(1, len(other_days) - 1)
            km = round(remaining_km / (n_other + 1), 1)
            sessions.append({
                "scheduled_date": session_date,
                "session_type": SessionType.EASY,
                "phase": phase,
                "week_number": week_number,
                "distance_km": max(4.0, km),
                "pace_target_min_per_km": easy_pace,
                "description": "Easy recovery run. Keep HR low.",
            })

    return sessions


def _build_mileage_curve(
    start_km: float, peak_km: float, weeks_total: int, phase_map: list
) -> list[float]:
    """
    Scale from start_km to peak_km over the build/peak phase,
    then taper. 10% cap per week enforced by adaptation engine later.
    """
    mileages = []
    taper_weeks = sum(1 for p in phase_map if p == PlanPhase.TAPER)
    build_weeks = weeks_total - taper_weeks

    for i, phase in enumerate(phase_map):
        if phase == PlanPhase.TAPER:
            taper_idx = i - (weeks_total - taper_weeks)
            # Taper: 100% → 85% → 70% → 50%
            taper_pct = [1.0, 0.85, 0.70, 0.50]
            pct = taper_pct[min(taper_idx, len(taper_pct) - 1)]
            mileages.append(round(peak_km * pct, 1))
        else:
            t = i / max(1, build_weeks - 1)
            # S-curve progression
            t_smooth = t * t * (3 - 2 * t)
            km = start_km + (peak_km - start_km) * t_smooth
            # Every 4th week is a recovery week at 80%
            if (i + 1) % 4 == 0 and i < build_weeks - 1:
                km *= 0.80
            mileages.append(round(km, 1))

    return mileages


def _standard_phase_map(weeks: int) -> list:
    """base → build → peak → taper for 10K/half/marathon."""
    taper = min(2, max(1, weeks // 6))
    peak = min(2, max(1, weeks // 5))
    remaining = weeks - taper - peak
    base = remaining // 2
    build = remaining - base
    return (
        [PlanPhase.BASE] * base
        + [PlanPhase.BUILD] * build
        + [PlanPhase.PEAK] * peak
        + [PlanPhase.TAPER] * taper
    )


def _5k_phase_map(weeks: int) -> list:
    """5K: speed-focused, more VO2max work, shorter base."""
    taper = 1
    peak = min(2, weeks // 5)
    remaining = weeks - taper - peak
    base = remaining // 3
    build = remaining - base
    return (
        [PlanPhase.BASE] * base
        + [PlanPhase.BUILD] * build
        + [PlanPhase.PEAK] * peak
        + [PlanPhase.TAPER] * taper
    )
