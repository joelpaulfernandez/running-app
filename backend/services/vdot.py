"""
VDOT calculations based on Jack Daniels' Running Formula.
VDOT ≈ VO2max equivalent derived from race performance.
"""
import math
from typing import Optional


# Jack Daniels' VDOT table (race_time_seconds -> vdot) — interpolated via formula
def pace_to_vdot(distance_km: float, time_seconds: int) -> float:
    """Calculate VDOT from a race performance."""
    velocity = distance_km / (time_seconds / 60)  # km/min
    # Daniels' formula: VO2 at pace
    pct_vo2max = 0.8 + 0.1894393 * math.exp(-0.012778 * time_seconds / 60) + \
                 0.2989558 * math.exp(-0.1932605 * time_seconds / 60)
    vo2 = -4.60 + 0.182258 * velocity + 0.000104 * velocity ** 2
    return vo2 / pct_vo2max


def vdot_to_easy_pace_min_per_km(vdot: float) -> float:
    """Easy/recovery pace: 59-74% VO2max. Returns min/km."""
    # 65% VO2max midpoint for easy runs
    target_pct = 0.65
    velocity = _velocity_at_pct_vo2max(vdot, target_pct)
    return 1.0 / velocity  # min/km


def vdot_to_tempo_pace_min_per_km(vdot: float) -> float:
    """Lactate threshold pace: ~88% VO2max. Returns min/km."""
    velocity = _velocity_at_pct_vo2max(vdot, 0.88)
    return 1.0 / velocity


def vdot_to_interval_pace_min_per_km(vdot: float) -> float:
    """Interval/VO2max pace: ~98% VO2max. Returns min/km."""
    velocity = _velocity_at_pct_vo2max(vdot, 0.98)
    return 1.0 / velocity


def _velocity_at_pct_vo2max(vdot: float, pct: float) -> float:
    """Invert Daniels' formula to get velocity (km/min) at a given %VO2max."""
    target_vo2 = vdot * pct
    # Quadratic: 0.000104*v^2 + 0.182258*v - 4.60 = target_vo2
    # 0.000104v² + 0.182258v - (4.60 + target_vo2) = 0
    a = 0.000104
    b = 0.182258
    c = -(4.60 + target_vo2)
    velocity = (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)
    return velocity


def peak_mileage_for_vdot(vdot: float, race_distance: str) -> float:
    """
    Distance-specific peak weekly mileage bands from sports science.
    Returns km/week.
    """
    bands = {
        "5k": {
            "low": (25, 40),   # vdot < 40
            "mid": (40, 55),   # vdot 40-55
            "high": (55, 80),  # vdot > 55
        },
        "10k": {
            "low": (35, 55),
            "mid": (55, 75),
            "high": (75, 100),
        },
        "half": {
            "low": (45, 65),
            "mid": (65, 90),
            "high": (90, 120),
        },
        "marathon": {
            "low": (60, 80),
            "mid": (80, 110),
            "high": (110, 145),
        },
    }
    distance_bands = bands.get(race_distance, bands["half"])
    if vdot < 40:
        lo, hi = distance_bands["low"]
    elif vdot < 55:
        lo, hi = distance_bands["mid"]
    else:
        lo, hi = distance_bands["high"]
    # Interpolate within band based on vdot position
    if vdot < 40:
        t = max(0, (vdot - 25) / 15)
    elif vdot < 55:
        t = (vdot - 40) / 15
    else:
        t = min(1, (vdot - 55) / 20)
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
            f"Only {weeks_available} weeks available — minimum for {race_distance} is {min_weeks[race_distance]}."
        )
    if weeks_available > max_weeks.get(race_distance, 20):
        warnings.append(
            f"{weeks_available} weeks is longer than the {max_weeks[race_distance]}-week maximum — plan will be padded."
        )

    if target_seconds:
        target_vdot = pace_to_vdot(RACE_DISTANCE_KM[race_distance], target_seconds)
        if target_vdot > vdot + 8:
            warnings.append(
                f"Target time implies VDOT {target_vdot:.1f} — current fitness is {vdot:.1f}. "
                f"A {target_vdot - vdot:.1f}-point gain in {weeks_available} weeks is aggressive."
            )
    return warnings
