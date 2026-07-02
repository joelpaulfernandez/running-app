"""
Plan generation: VDOT pace zones + Daniels periodization.

Core is a pure function: generate_week(phase, week_km, week_in_phase, zones, ...) → sessions.
Re-runnable deterministically whenever VDOT recalibrates or ACWR cap fires — caller deletes
future unscheduled sessions then calls generate_plan() from the affected week forward.
"""
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from services.vdot import PaceZone, pace_zones, fmt_pace, peak_mileage_for_vdot, RACE_DISTANCE_KM
from models.db import SessionType, PlanPhase


DAYS_OF_WEEK = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_SHAPES: dict = json.loads((Path(__file__).parent / "workout_shapes.json").read_text())["shapes"]


# ─── slot structure ───────────────────────────────────────────────────────────

def _quality_slot_count(days: int, phase: str) -> int:
    """
    Deterministic table: (days_per_week, phase) → quality session count.
    Remaining days after 1 long + quality slots are filled with easy.
    """
    if phase == "base":
        # 3-day: no dedicated quality slot (strides added to easy runs instead)
        return 1 if days >= 4 else 0
    elif phase in ("build", "peak"):
        # 4-day or fewer: 1 quality; 5+ days: 2 quality
        return 2 if days >= 5 else 1
    else:  # taper
        return 1


def _quality_shape(phase: str, slot_idx: int, race_distance: str) -> str:
    """Select shape name for the nth quality slot in this phase."""
    if race_distance == "5k":
        by_phase: dict[str, list[str]] = {
            "base":  ["interval_800", "strides"],
            "build": ["interval_1000", "rep_400"],
            "peak":  ["interval_800", "rep_200"],
            "taper": ["interval_800"],
        }
    else:
        by_phase = {
            "base":  ["tempo_cruise"],
            "build": ["tempo_cruise", "interval_800"],
            "peak":  ["interval_1000", "tempo_cruise"],
            "taper": ["tempo_cruise"],
        }
    options = by_phase.get(phase, ["tempo_cruise"])
    return options[min(slot_idx, len(options) - 1)]


# ─── pace zone formatting ─────────────────────────────────────────────────────

def _fmt_zone(zone: PaceZone) -> str:
    return f"{fmt_pace(zone.lo)}–{fmt_pace(zone.hi)}/km"


# ─── session resolvers ────────────────────────────────────────────────────────
# Each returns a partial dict: {session_type, distance_km, pace_target_min_per_km, description}

def _resolve_tempo_cruise(zones: dict, week_km: float, intensity_scale: float) -> dict:
    shape = _SHAPES["tempo_cruise"]
    quality_km = min(
        week_km * shape["quality_pct_of_week"] * intensity_scale,
        shape["quality_max_km"],
    )
    t = zones["T"]
    total_t_min = quality_km * t.mid
    rep_min = min(shape["rep_duration_min_max"], max(shape["rep_duration_min_base"], total_t_min / 3))
    reps = max(shape["reps_min"], min(shape["reps_max"], round(total_t_min / rep_min)))
    rep_min_actual = max(shape["rep_duration_min_base"], min(shape["rep_duration_min_max"], round(total_t_min / reps)))
    total_km = round(quality_km + shape["warmup_cooldown_km"], 1)
    desc = (
        f"Warm up 1 km, then {reps} × {rep_min_actual} min @ T ({_fmt_zone(t)}), "
        f"{shape['recovery_min']} min jog recovery. Cool down 1 km."
    )
    return {
        "session_type": SessionType.TEMPO,
        "distance_km": total_km,
        "pace_target_min_per_km": round(t.mid, 3),
        "description": desc,
    }


def _resolve_interval(shape_name: str, zones: dict, week_km: float, intensity_scale: float) -> dict:
    shape = _SHAPES[shape_name]
    quality_km = min(
        week_km * shape["quality_pct_of_week"] * intensity_scale,
        shape["quality_max_km"],
    )
    i = zones["I"]
    rep_km = shape["rep_dist_m"] / 1000.0
    reps = max(shape["reps_min"], min(shape["reps_max"], round(quality_km / rep_km)))
    total_km = round(reps * rep_km + shape["warmup_cooldown_km"], 1)
    if shape.get("recovery_type") == "equal_time":
        recovery_desc = "equal-time jog recovery"
    else:
        recovery_desc = f"{shape.get('recovery_sec', 90)} s jog recovery"
    desc = (
        f"Warm up 1–2 km, then {reps} × {shape['rep_dist_m']} m @ I ({_fmt_zone(i)}), "
        f"{recovery_desc}. Cool down 1 km."
    )
    return {
        "session_type": SessionType.INTERVAL,
        "distance_km": total_km,
        "pace_target_min_per_km": round(i.mid, 3),
        "description": desc,
    }


def _resolve_rep(shape_name: str, zones: dict, week_km: float, intensity_scale: float) -> dict:
    shape = _SHAPES[shape_name]
    quality_km = min(
        week_km * shape["quality_pct_of_week"] * intensity_scale,
        shape["quality_max_km"],
    )
    r = zones["R"]
    rep_km = shape["rep_dist_m"] / 1000.0
    reps = max(shape["reps_min"], min(shape["reps_max"], round(quality_km / rep_km)))
    total_km = round(reps * rep_km + shape["warmup_cooldown_km"], 1)
    rec_m = shape.get("recovery_dist_m", shape["rep_dist_m"])
    desc = (
        f"Warm up 1 km, then {reps} × {shape['rep_dist_m']} m @ R ({_fmt_zone(r)}), "
        f"{rec_m} m jog recovery. Cool down 1 km."
    )
    return {
        "session_type": SessionType.INTERVAL,
        "distance_km": total_km,
        "pace_target_min_per_km": round(r.lo, 3),  # target the faster end for reps
        "description": desc,
    }


def _resolve_strides(zones: dict, easy_km: float) -> dict:
    shape = _SHAPES["strides"]
    r = zones["R"]
    reps = (shape["reps_min"] + shape["reps_max"]) // 2  # middle of range
    desc = (
        f"Easy run, then {reps} × 100 m strides ({_fmt_zone(r)}) "
        f"with full recovery between. Keep the easy portion conversational."
    )
    return {
        "session_type": SessionType.EASY,
        "distance_km": round(max(4.0, easy_km), 1),
        "pace_target_min_per_km": round(zones["E"].mid, 3),
        "description": desc,
    }


def _resolve_long(zones: dict, distance_km: float, phase: str) -> dict:
    e, m = zones["E"], zones["M"]
    if phase in ("build", "peak"):
        mp_km = round(distance_km * 0.25, 1)
        easy_km = round(distance_km - mp_km, 1)
        desc = (
            f"Long run: first {easy_km} km @ easy ({_fmt_zone(e)}), "
            f"last {mp_km} km @ M pace ({_fmt_zone(m)})."
        )
    else:
        desc = f"Long run at easy effort ({_fmt_zone(e)}). Stay fully conversational throughout."
    return {
        "session_type": SessionType.LONG,
        "distance_km": round(distance_km, 1),
        "pace_target_min_per_km": round(e.mid, 3),
        "description": desc,
    }


def _resolve_easy(zones: dict, distance_km: float, with_strides: bool = False) -> dict:
    e = zones["E"]
    km = round(max(4.0, min(distance_km, 15.0)), 1)  # cap: no single easy run > 15 km
    if with_strides:
        desc = f"Easy run at {_fmt_zone(e)} with 4–6 × 100 m strides at the end."
    else:
        desc = f"Easy recovery run at {_fmt_zone(e)}. Keep effort fully conversational."
    return {
        "session_type": SessionType.EASY,
        "distance_km": km,
        "pace_target_min_per_km": round(e.mid, 3),
        "description": desc,
    }


def _resolve_time_trial(race_distance: str) -> dict:
    tt_km = min(RACE_DISTANCE_KM[race_distance], 5.0)
    desc = f"{tt_km:.1f} km time trial at max sustainable effort. Result recalibrates your VDOT."
    return {
        "session_type": SessionType.TIME_TRIAL,
        "distance_km": tt_km,
        "pace_target_min_per_km": None,
        "description": desc,
    }


def _resolve_quality_slot(
    shape_name: str,
    zones: dict,
    week_km: float,
    intensity_scale: float,
    easy_km_for_strides: float = 6.0,
) -> dict:
    if shape_name == "tempo_cruise":
        return _resolve_tempo_cruise(zones, week_km, intensity_scale)
    elif shape_name in ("interval_800", "interval_1000"):
        return _resolve_interval(shape_name, zones, week_km, intensity_scale)
    elif shape_name in ("rep_200", "rep_400"):
        return _resolve_rep(shape_name, zones, week_km, intensity_scale)
    elif shape_name == "strides":
        return _resolve_strides(zones, easy_km_for_strides)
    return _resolve_tempo_cruise(zones, week_km, intensity_scale)


# ─── week generation (pure function) ─────────────────────────────────────────

def generate_week(
    week_number: int,
    phase: str,
    week_km: float,
    week_in_phase: int,
    training_days: list[str],
    long_run_day: str,
    zones: dict,
    race_distance: str,
    is_time_trial_week: bool,
    week_start: date,
    long_run_km_override: Optional[float] = None,
) -> list[dict]:
    """
    Pure function: (phase, week_km, week_in_phase, zones, ...) → session dicts.
    No DB interaction, no side effects.

    Intensity scaling grows from 0.75 → 1.0 over 5 weeks within each phase,
    resetting to 0.75 at every phase transition.
    """
    days = len(training_days)
    quality_count = _quality_slot_count(days, phase)

    # Intensity within phase: ramps 0.75 → 1.0 over ≥5 weeks
    intensity_scale = min(1.0, 0.75 + 0.05 * week_in_phase)

    long_run_km = long_run_km_override if long_run_km_override is not None else week_km * 0.30

    # Resolve quality sessions up front so we know their volumes for easy distribution
    quality_resolved: list[dict] = []
    quality_total_km = 0.0

    for slot_idx in range(quality_count):
        if is_time_trial_week and slot_idx == 0:
            resolved = _resolve_time_trial(race_distance)
        else:
            shape_name = _quality_shape(phase, slot_idx, race_distance)
            resolved = _resolve_quality_slot(shape_name, zones, week_km, intensity_scale)
        quality_resolved.append(resolved)
        quality_total_km += resolved["distance_km"]

    # Easy sessions fill remaining volume
    other_days = [d for d in training_days if d != long_run_day]
    n_easy = max(0, len(other_days) - quality_count)
    easy_total_km = max(0.0, week_km - long_run_km - quality_total_km)

    # Greedy easy slot fill: up to 15 km per slot, overflow goes to next slot
    # rather than disappearing silently (avoids hard-cap truncation bug).
    easy_slot_kms: list[float] = []
    remaining_easy = easy_total_km
    for j in range(n_easy):
        slots_left = n_easy - j
        target = remaining_easy / slots_left
        actual = min(target, 15.0)
        easy_slot_kms.append(actual)
        remaining_easy -= actual

    # Pick quality days: spread across other_days at 1/3 and 2/3 positions
    quality_days: list[str] = []
    if quality_count >= 1 and other_days:
        quality_days.append(other_days[len(other_days) // 3])
    if quality_count >= 2 and len(other_days) >= 3:
        idx2 = min((2 * len(other_days)) // 3, len(other_days) - 1)
        candidate = other_days[idx2]
        if candidate == quality_days[0]:
            candidate = other_days[min(idx2 + 1, len(other_days) - 1)]
        quality_days.append(candidate)

    # Add strides to first easy day in build/peak when quality_count == 0
    strides_on_easy_idx = 0 if (quality_count == 0 and phase in ("build", "peak")) else -1

    q_idx = 0
    e_idx = 0
    sessions: list[dict] = []

    for day_name in training_days:
        day_offset = DAYS_OF_WEEK.index(day_name)
        session_date = week_start + timedelta(days=day_offset)

        if day_name == long_run_day:
            resolved = _resolve_long(zones, long_run_km, phase)
        elif day_name in quality_days and q_idx < len(quality_resolved):
            resolved = quality_resolved[q_idx]
            q_idx += 1
        else:
            slot_km = easy_slot_kms[e_idx] if e_idx < len(easy_slot_kms) else 0.0
            with_strides = (e_idx == strides_on_easy_idx)
            resolved = _resolve_easy(zones, slot_km, with_strides=with_strides)
            e_idx += 1

        sessions.append({
            "scheduled_date": session_date,
            "session_type": resolved["session_type"],
            "phase": PlanPhase(phase),
            "week_number": week_number,
            "distance_km": resolved["distance_km"],
            "pace_target_min_per_km": resolved.get("pace_target_min_per_km"),
            "description": resolved["description"],
        })

    return sessions


# ─── long run curve ──────────────────────────────────────────────────────────

def _build_long_run_curve(
    weekly_mileages: list[float],
    phase_map: list,
    race_distance: str,
) -> list[float]:
    """
    Long run km per week, coupled to weekly volume via a ramping percentage.

    Non-marathon: fixed fraction of weekly volume; taper flows through because
    weekly_mileages already has taper factors applied.

    Marathon: ramps 30% → 50% of weekly volume across non-taper weeks.
    At 62 km peak × 50% = 31 km — no independent S-curve needed.
    Taper: directly computed as peak_long × taper_factor so the long run
    DECREASES in taper rather than following the rolling cap into higher values.

    Jump cap on non-taper increases: max(prev×1.15, prev+2 km) — allows either
    15% OR 2 km absolute growth, whichever is larger. This prevents S-curve step-back
    rebounds while still permitting the long run to reach 30 km within 15 weeks.
    """
    FIXED_PCTS = {"5k": 0.25, "10k": 0.28, "half": 0.30}
    # Marathon taper is more aggressive: last long run must land at 8–12 km (race-week shakeout)
    TAPER_LONG_PCTS = (
        [0.75, 0.55, 0.30, 0.20] if race_distance == "marathon"
        else [0.85, 0.70, 0.55, 0.45]
    )

    non_taper_indices = [i for i, p in enumerate(phase_map) if p != PlanPhase.TAPER]
    n_build = max(1, len(non_taper_indices))

    # --- pass 1: non-taper weeks with rolling jump cap ---
    non_taper_raw: list[float] = []
    for rank, i in enumerate(non_taper_indices):
        wk = weekly_mileages[i]
        if race_distance == "marathon":
            t = rank / (n_build - 1) if n_build > 1 else 1.0
            pct = 0.30 + 0.20 * t  # 30% → 50%
        else:
            pct = FIXED_PCTS.get(race_distance, 0.30)
        non_taper_raw.append(wk * pct)

    # rolling cap: allow max(+15%, +2 km) increase per week
    non_taper_clamped: list[float] = [non_taper_raw[0]]
    for km in non_taper_raw[1:]:
        prev = non_taper_clamped[-1]
        if km > prev:
            cap = max(prev * 1.15, prev + 2.0)
            non_taper_clamped.append(min(km, cap))
        else:
            non_taper_clamped.append(km)  # step-back: allow freely

    # Hard cap: marathon long runs top out at 32 km
    if race_distance == "marathon":
        non_taper_clamped = [min(km, 32.0) for km in non_taper_clamped]

    peak_long = non_taper_clamped[-1]

    # --- pass 2: assemble full curve including taper weeks ---
    result: list[float] = []
    non_taper_iter = iter(non_taper_clamped)
    taper_idx = 0
    for phase in phase_map:
        if phase == PlanPhase.TAPER:
            pct = TAPER_LONG_PCTS[min(taper_idx, len(TAPER_LONG_PCTS) - 1)]
            result.append(round(peak_long * pct, 1))
            taper_idx += 1
        else:
            result.append(round(next(non_taper_iter), 1))

    return result


# ─── plan-level entry points ──────────────────────────────────────────────────

def generate_plan(
    race_distance: str,
    race_date: date,
    vdot: float,
    current_weekly_mileage: float,
    training_days: list[str],
    long_run_day: str,
    start_date: Optional[date] = None,
    week_number_offset: int = 0,
) -> list[dict]:
    """
    Generate all planned sessions from start_date to race_date.
    week_number_offset allows mid-plan regeneration to keep week numbers continuous.
    """
    if start_date is None:
        start_date = date.today()

    weeks_total = max(1, (race_date - start_date).days // 7)
    peak_km = peak_mileage_for_vdot(vdot, race_distance)
    zones = pace_zones(vdot)

    phase_map = _5k_phase_map(weeks_total) if race_distance == "5k" else _standard_phase_map(weeks_total, race_distance)
    weekly_mileages = _build_mileage_curve(current_weekly_mileage, peak_km, weeks_total, phase_map)

    long_run_kms = _build_long_run_curve(weekly_mileages, phase_map, race_distance)

    # Advance start_date to Monday of first week
    week_start = start_date
    while week_start.strftime("%A").lower() != "monday":
        week_start += timedelta(days=1)

    phase_week_count: dict[str, int] = {}
    sessions: list[dict] = []

    for week_idx, (week_km, phase, long_km) in enumerate(zip(weekly_mileages, phase_map, long_run_kms)):
        phase_key = phase.value
        week_in_phase = phase_week_count.get(phase_key, 0)
        phase_week_count[phase_key] = week_in_phase + 1

        week_number = week_idx + 1 + week_number_offset

        # Time trial every 3rd week in base/build (replaces first quality slot)
        is_time_trial_week = (
            (week_idx % 3 == 2)
            and phase in (PlanPhase.BASE, PlanPhase.BUILD)
        )

        week_sessions = generate_week(
            week_number=week_number,
            phase=phase_key,
            week_km=week_km,
            long_run_km_override=long_km,
            week_in_phase=week_in_phase,
            training_days=training_days,
            long_run_day=long_run_day,
            zones=zones,
            race_distance=race_distance,
            is_time_trial_week=is_time_trial_week,
            week_start=week_start,
        )
        sessions.extend(week_sessions)
        week_start += timedelta(weeks=1)

    # Post-process race week: replace long-run slot with the race, cap other sessions
    race_distance_km = RACE_DISTANCE_KM[race_distance]
    race_week_number = next(
        (s["week_number"] for s in sessions if s["scheduled_date"] == race_date),
        None,
    )
    for s in sessions:
        if s["scheduled_date"] == race_date:
            s["session_type"] = SessionType.TIME_TRIAL
            s["distance_km"] = race_distance_km
            s["pace_target_min_per_km"] = None
            race_label = "Half Marathon" if race_distance == "half" else race_distance.upper()
            s["description"] = (
                f"Race day! {race_distance_km:.1f} km {race_label}. "
                f"Trust your training, go out controlled, finish strong."
            )
        elif race_week_number and s["week_number"] == race_week_number:
            # Shakeout days: cap at 5 km, easy only, no quality sessions
            if s["session_type"] not in (SessionType.REST,):
                s["session_type"] = SessionType.EASY
                s["distance_km"] = 5.0
                e = zones["E"]
                s["pace_target_min_per_km"] = round(e.mid, 3)
                s["description"] = (
                    f"Pre-race shakeout at {_fmt_zone(e)}. 5 km max, legs loose, effort minimal."
                )

    return sessions


# ─── mileage curve ────────────────────────────────────────────────────────────

def _build_mileage_curve(
    start_km: float,
    peak_km: float,
    weeks_total: int,
    phase_map: list,
) -> list[float]:
    """
    S-curve from start_km → peak_km over base/build/peak, then taper.
    Every 4th non-taper week is a scheduled step-back (~18% reduction).
    """
    taper_count = sum(1 for p in phase_map if p == PlanPhase.TAPER)
    build_count = weeks_total - taper_count
    mileages: list[float] = []

    for i, phase in enumerate(phase_map):
        if phase == PlanPhase.TAPER:
            taper_idx = i - build_count
            # Volume drops starting week 1 of taper: 85% → 70% → 55% → 45%
            # Coupled to long run taper so total load drops in the same week.
            taper_pcts = [0.85, 0.70, 0.55, 0.45]
            pct = taper_pcts[min(taper_idx, len(taper_pcts) - 1)]
            mileages.append(round(peak_km * pct, 1))
        else:
            t = i / max(1, build_count - 1)
            # S-curve: smooth acceleration into peak
            t_smooth = t * t * (3 - 2 * t)
            km = start_km + (peak_km - start_km) * t_smooth
            # Scheduled step-back: every 4th week drops ~18% — only in base/build, not peak
            if (i + 1) % 4 == 0 and i < build_count - 1 and phase != PlanPhase.PEAK:
                km *= 0.82
            mileages.append(round(km, 1))

    return mileages


# ─── phase maps ──────────────────────────────────────────────────────────────

def _standard_phase_map(weeks: int, race_distance: str = "") -> list:
    """base → build → peak → taper for 10K / half / marathon."""
    # Marathon needs a 3-week taper (vs 2) — the extra week is essential at these volumes.
    if race_distance == "marathon":
        taper = min(3, max(2, weeks // 5))
    else:
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
    """5K: compressed cycle, I/R introduced earlier, less pure E base."""
    taper = 1
    peak = min(2, weeks // 5)
    remaining = weeks - taper - peak
    base = remaining // 3   # shorter base than standard
    build = remaining - base
    return (
        [PlanPhase.BASE] * base
        + [PlanPhase.BUILD] * build
        + [PlanPhase.PEAK] * peak
        + [PlanPhase.TAPER] * taper
    )
