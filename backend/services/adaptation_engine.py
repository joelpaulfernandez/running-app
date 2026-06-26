"""
Combined adaptation engine — three triggers in priority order:
1. ACWR cap (overrides everything)
2. Missed-session reschedule
3. VDOT recalculation (blended 70/30)
"""
from datetime import date, timedelta, datetime
from typing import Optional
import pytz

from services.vdot import blend_vdot, pace_to_vdot, RACE_DISTANCE_KM
from models.db import SessionType, PlanPhase


def compute_acwr(activities: list[dict], as_of: date) -> Optional[float]:
    """
    Acute (last 7 days) : Chronic (last 28 days avg of 4 weeks) load ratio.
    activities: list of {activity_date: date, distance_km: float}
    Returns None if fewer than 28 days of data exist.
    """
    dates_set = {a["activity_date"] for a in activities}
    earliest = min(dates_set) if dates_set else as_of
    if (as_of - earliest).days < 28:
        return None

    acute_start = as_of - timedelta(days=7)
    chronic_start = as_of - timedelta(days=28)

    acute_load = sum(
        a["distance_km"]
        for a in activities
        if acute_start <= a["activity_date"] <= as_of
    )
    chronic_load = sum(
        a["distance_km"]
        for a in activities
        if chronic_start <= a["activity_date"] <= as_of
    ) / 4  # weekly average

    if chronic_load == 0:
        return None
    return acute_load / chronic_load


def apply_acwr_cap(
    planned_sessions: list[dict],
    current_acwr: float,
    week_start: date,
) -> tuple[list[dict], Optional[str]]:
    """
    If ACWR > 1.5, scale next week's session distances down so ACWR stays ≤ 1.3.
    Returns (modified_sessions, explanation_if_capped).
    """
    if current_acwr is None or current_acwr <= 1.5:
        return planned_sessions, None

    # Cap factor: bring projected week volume to ≤ 85% of what it is
    cap_factor = 1.3 / current_acwr
    modified = []
    for s in planned_sessions:
        if s["scheduled_date"] >= week_start and s.get("distance_km"):
            s = {**s, "distance_km": round(s["distance_km"] * cap_factor, 1)}
        modified.append(s)

    return modified, (
        f"ACWR is {current_acwr:.2f} — above the 1.5 safety threshold. "
        f"Next week's mileage capped to {cap_factor*100:.0f}% of planned to reduce injury risk."
    )


def reschedule_missed_session(
    missed_session: dict,
    upcoming_sessions: list[dict],
    user_timezone: str = "UTC",
) -> tuple[Optional[dict], str]:
    """
    Push missed key session forward if a slot exists before the next hard day.
    Otherwise drop it and protect the long run.
    Returns (rescheduled_session_or_None, explanation).
    """
    hard_types = {SessionType.TEMPO, SessionType.INTERVAL, SessionType.TIME_TRIAL, SessionType.LONG}
    missed_date = missed_session["scheduled_date"]

    next_hard_date = None
    for s in sorted(upcoming_sessions, key=lambda x: x["scheduled_date"]):
        if s["session_type"] in hard_types and s["scheduled_date"] > missed_date:
            next_hard_date = s["scheduled_date"]
            break

    # Find first gap day after missed_date
    booked_dates = {s["scheduled_date"] for s in upcoming_sessions}
    candidate = missed_date + timedelta(days=1)

    while candidate < (next_hard_date or missed_date + timedelta(days=5)):
        if candidate not in booked_dates:
            rescheduled = {**missed_session, "scheduled_date": candidate}
            return rescheduled, (
                f"Missed {missed_session['session_type'].value} on {missed_date} rescheduled to {candidate}."
            )
        candidate += timedelta(days=1)

    # No room — drop it, protect long run
    return None, (
        f"Missed {missed_session['session_type'].value} on {missed_date} dropped — "
        f"no slot before next hard session on {next_hard_date}. Long run protected."
    )


def maybe_recalc_vdot(
    current_vdot: float,
    session: dict,
    linked_activity: dict,
) -> tuple[float, Optional[str]]:
    """
    Only recalculates after key sessions (tempo/long/time_trial).
    Only if deviation > ±3% sustained.
    Blends 70% old / 30% new.
    """
    key_types = {SessionType.TEMPO, SessionType.LONG, SessionType.TIME_TRIAL}
    if session["session_type"] not in key_types:
        return current_vdot, None

    actual_distance = linked_activity["distance_km"]
    actual_seconds = linked_activity["duration_seconds"]

    if actual_distance < 2.0:
        return current_vdot, None

    new_vdot = pace_to_vdot(actual_distance, actual_seconds)
    deviation = abs(new_vdot - current_vdot) / current_vdot

    if deviation < 0.03:
        return current_vdot, None

    blended = blend_vdot(current_vdot, new_vdot)
    direction = "improved" if new_vdot > current_vdot else "declined"
    return blended, (
        f"Fitness {direction}: performance implies VDOT {new_vdot:.1f} vs current {current_vdot:.1f} "
        f"({deviation*100:.1f}% deviation). Updated to {blended:.1f} (70/30 blend)."
    )


def is_session_missed(session: dict, user_timezone: str = "UTC") -> bool:
    """
    Session is missed at end-of-day the day AFTER it was scheduled (user's local tz).
    """
    tz = pytz.timezone(user_timezone)
    now_local = datetime.now(tz).date()
    cutoff = session["scheduled_date"] + timedelta(days=1)
    return now_local > cutoff and session.get("linked_activity_id") is None


def flat_10pct_mileage_cap(
    planned_sessions: list[dict],
    prev_week_actual_km: float,
    week_start: date,
) -> list[dict]:
    """
    Cold-start fallback: cap weekly volume at 10% increase over previous week.
    Used until 28 days of in-app history exists.
    """
    cap_km = prev_week_actual_km * 1.10
    week_sessions = [
        s for s in planned_sessions
        if week_start <= s["scheduled_date"] < week_start + timedelta(weeks=1)
    ]
    planned_total = sum(s.get("distance_km", 0) for s in week_sessions)

    if planned_total <= cap_km:
        return planned_sessions

    scale = cap_km / planned_total
    result = []
    for s in planned_sessions:
        if week_start <= s["scheduled_date"] < week_start + timedelta(weeks=1):
            s = {**s, "distance_km": round(s.get("distance_km", 0) * scale, 1)}
        result.append(s)
    return result
