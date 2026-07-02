"""
VDOT calculations based on Jack Daniels' Running Formula.
VDOT ≈ VO2max equivalent derived from race performance.
"""
import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class PaceZone:
    """Pace range in min/km. lo = faster bound (lower number), hi = slower bound."""
    lo: float
    hi: float

    @property
    def mid(self) -> float:
        return (self.lo + self.hi) / 2


def fmt_pace(min_per_km: float) -> str:
    """Convert decimal min/km to 'M:SS' string. 4.533 → '4:32'."""
    m = int(min_per_km)
    s = round((min_per_km - m) * 60)
    if s == 60:
        m += 1
        s = 0
    return f"{m}:{s:02d}"


# Zone %VO2max bounds: (slower_pct, faster_pct)
# Higher %VO2max → faster velocity → lower min/km
_ZONE_PCTS: dict[str, tuple[float, float]] = {
    "E": (0.59, 0.74),   # Easy/recovery: aerobic base
    "M": (0.75, 0.84),   # Marathon pace
    "T": (0.83, 0.88),   # Threshold: comfortably hard, sustained
    "I": (0.95, 1.00),   # Interval: VO2max work
    "R": (1.05, 1.10),   # Repetition: speed/economy, short reps
}


def pace_zones(vdot: float) -> dict[str, PaceZone]:
    """
    Derive all 5 Daniels training pace zones for a given VDOT.
    Returns {E, M, T, I, R} → PaceZone(lo, hi) in min/km.
    lo = faster pace (lower min/km), hi = slower pace (higher min/km).
    """
    result: dict[str, PaceZone] = {}
    for name, (slow_pct, fast_pct) in _ZONE_PCTS.items():
        v_fast = _velocity_at_pct_vo2max(vdot, fast_pct)
        v_slow = _velocity_at_pct_vo2max(vdot, slow_pct)
        result[name] = PaceZone(
            lo=round(1000.0 / v_fast, 4),
            hi=round(1000.0 / v_slow, 4),
        )
    return result


def pace_to_vdot(distance_km: float, time_seconds: int) -> float:
    """Calculate VDOT from a race performance."""
    t = time_seconds / 60  # minutes
    velocity = (distance_km * 1000) / t  # m/min
    pct_vo2max = (
        0.8
        + 0.1894393 * math.exp(-0.012778 * t)
        + 0.2989558 * math.exp(-0.1932605 * t)
    )
    vo2 = -4.60 + 0.182258 * velocity + 0.000104 * velocity ** 2
    return max(vo2 / pct_vo2max, 20.0)


def _velocity_at_pct_vo2max(vdot: float, pct: float) -> float:
    """Invert Daniels' formula to get velocity in m/min at a given %VO2max."""
    target_vo2 = vdot * pct
    a, b = 0.000104, 0.182258
    c = -(4.60 + target_vo2)
    return (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)


# Legacy single-value helpers kept for backward compatibility
def vdot_to_easy_pace_min_per_km(vdot: float) -> float:
    return pace_zones(vdot)["E"].mid

def vdot_to_tempo_pace_min_per_km(vdot: float) -> float:
    return pace_zones(vdot)["T"].mid

def vdot_to_interval_pace_min_per_km(vdot: float) -> float:
    return pace_zones(vdot)["I"].mid


def peak_mileage_for_vdot(vdot: float, race_distance: str) -> float:
    """Distance-specific peak weekly mileage bands. Returns km/week."""
    bands = {
        "5k":      {"low": (25, 40),  "mid": (40, 55),  "high": (55, 80)},
        "10k":     {"low": (35, 55),  "mid": (55, 75),  "high": (75, 100)},
        "half":    {"low": (45, 65),  "mid": (65, 90),  "high": (90, 120)},
        "marathon":{"low": (60, 80),  "mid": (80, 110), "high": (110, 145)},
    }
    d = bands.get(race_distance, bands["half"])
    if vdot < 40:
        lo, hi = d["low"]
        t = max(0.0, (vdot - 25) / 15)
    elif vdot < 55:
        lo, hi = d["mid"]
        t = (vdot - 40) / 15
    else:
        lo, hi = d["high"]
        t = min(1.0, (vdot - 55) / 20)
    return lo + t * (hi - lo)


def blend_vdot(old_vdot: float, new_vdot: float) -> float:
    """70/30 blend — never a straight overwrite."""
    return 0.7 * old_vdot + 0.3 * new_vdot


def vdot_from_target_time(distance_km: float, target_seconds: int) -> float:
    return pace_to_vdot(distance_km, target_seconds)


RACE_DISTANCE_KM = {
    "5k": 5.0,
    "10k": 10.0,
    "half": 21.0975,
    "marathon": 42.195,
}


def feasibility_warnings(
    vdot: float,
    race_distance: str,
    target_seconds: Optional[int],
    weeks_available: int,
) -> list[str]:
    warnings = []
    min_weeks = {"5k": 6, "10k": 6, "half": 8, "marathon": 12}
    max_weeks = {"5k": 10, "10k": 10, "half": 14, "marathon": 20}
    if weeks_available < min_weeks.get(race_distance, 6):
        warnings.append(
            f"Only {weeks_available} weeks — minimum for {race_distance} is {min_weeks[race_distance]}."
        )
    if weeks_available > max_weeks.get(race_distance, 20):
        warnings.append(
            f"{weeks_available} weeks exceeds the {max_weeks[race_distance]}-week maximum."
        )
    if target_seconds:
        target_vdot = pace_to_vdot(RACE_DISTANCE_KM[race_distance], target_seconds)
        if target_vdot > vdot + 8:
            warnings.append(
                f"Target implies VDOT {target_vdot:.1f} vs current {vdot:.1f} — "
                f"a {target_vdot - vdot:.1f}-point gain in {weeks_available} weeks is aggressive."
            )
    return warnings
