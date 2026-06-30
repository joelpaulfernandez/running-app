from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.db import Plan, PlanVersion, PlannedSession, Activity, User
from services.plan_generator import generate_plan
from services.vdot import (
    pace_to_vdot, feasibility_warnings, RACE_DISTANCE_KM, vdot_from_target_time,
    peak_mileage_for_vdot,
)
from services.adaptation_engine import (
    compute_acwr, apply_acwr_cap, reschedule_missed_session,
    maybe_recalc_vdot, is_session_missed, flat_10pct_mileage_cap,
)
from database import get_db

router = APIRouter(prefix="/plans", tags=["plans"])


class CreatePlanRequest(BaseModel):
    user_id: str
    race_distance: str
    race_date: date
    target_finish_time_seconds: Optional[int] = None
    current_weekly_mileage: float
    training_days: list[str]
    long_run_day: str
    recent_race_distance_km: Optional[float] = None
    recent_race_time_seconds: Optional[int] = None


class LinkActivityRequest(BaseModel):
    session_id: str
    activity_id: str


@router.post("/")
def create_plan(req: CreatePlanRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    # Compute initial VDOT
    if req.recent_race_distance_km and req.recent_race_time_seconds:
        vdot = pace_to_vdot(req.recent_race_distance_km, req.recent_race_time_seconds)
    elif user.vdot:
        vdot = user.vdot
    else:
        raise HTTPException(400, "Need current fitness data (recent race time or VDOT)")

    weeks_available = max(1, (req.race_date - date.today()).days // 7)

    warnings = feasibility_warnings(
        vdot=vdot,
        race_distance=req.race_distance,
        target_seconds=req.target_finish_time_seconds,
        weeks_available=weeks_available,
    )

    peak_km = peak_mileage_for_vdot(vdot, req.race_distance)

    plan = Plan(
        user_id=req.user_id,
        race_distance=req.race_distance,
        race_date=req.race_date,
        target_finish_time_seconds=req.target_finish_time_seconds,
        training_days=req.training_days,
        long_run_day=req.long_run_day,
        initial_vdot=vdot,
        initial_weekly_mileage=req.current_weekly_mileage,
        peak_weekly_mileage=peak_km,
    )
    db.add(plan)
    db.flush()

    version = PlanVersion(
        plan_id=plan.id,
        version_number=1,
        trigger="initial",
        trigger_detail={"vdot": vdot, "weeks": weeks_available},
    )
    db.add(version)
    db.flush()

    sessions_data = generate_plan(
        race_distance=req.race_distance,
        race_date=req.race_date,
        vdot=vdot,
        current_weekly_mileage=req.current_weekly_mileage,
        training_days=req.training_days,
        long_run_day=req.long_run_day,
    )

    for s in sessions_data:
        db.add(PlannedSession(
            plan_id=plan.id,
            plan_version_id=version.id,
            **s,
        ))

    user.vdot = vdot
    db.commit()

    return {
        "plan_id": plan.id,
        "version_id": version.id,
        "vdot": vdot,
        "peak_weekly_km": peak_km,
        "weeks": weeks_available,
        "warnings": warnings,
        "sessions_generated": len(sessions_data),
    }


@router.get("/{plan_id}/sessions")
def get_plan_sessions(plan_id: str, db: Session = Depends(get_db)):
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")

    sessions = (
        db.query(PlannedSession)
        .filter(PlannedSession.plan_id == plan_id)
        .order_by(PlannedSession.scheduled_date)
        .all()
    )

    return [
        {
            "id": s.id,
            "date": s.scheduled_date.isoformat(),
            "type": s.session_type,
            "phase": s.phase,
            "week": s.week_number,
            "distance_km": s.distance_km,
            "pace_target": s.pace_target_min_per_km,
            "description": s.description,
            "is_missed": s.is_missed,
            "linked_activity_id": s.linked_activity_id,
        }
        for s in sessions
    ]


@router.get("/{plan_id}/dashboard")
def get_dashboard(plan_id: str, db: Session = Depends(get_db)):
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")

    today = date.today()
    next_7 = [
        s for s in plan.sessions
        if today <= s.scheduled_date <= today + __import__("datetime").timedelta(days=7)
    ]

    activities = db.query(Activity).filter(Activity.user_id == plan.user_id).all()
    activities_dicts = [{"activity_date": a.activity_date, "distance_km": a.distance_km} for a in activities]

    acwr = compute_acwr(activities_dicts, today)

    # Weekly mileage: planned vs actual (last 8 weeks)
    weekly_stats = []
    for week_offset in range(8):
        week_start = today - __import__("datetime").timedelta(weeks=week_offset + 1)
        week_end = week_start + __import__("datetime").timedelta(days=6)
        planned = sum(
            s.distance_km or 0
            for s in plan.sessions
            if week_start <= s.scheduled_date <= week_end
        )
        actual = sum(
            a["distance_km"]
            for a in activities_dicts
            if week_start <= a["activity_date"] <= week_end
        )
        weekly_stats.append({
            "week_start": week_start.isoformat(),
            "planned_km": round(planned, 1),
            "actual_km": round(actual, 1),
        })

    return {
        "upcoming_7_days": [
            {"date": s.scheduled_date.isoformat(), "type": s.session_type, "distance_km": s.distance_km}
            for s in sorted(next_7, key=lambda x: x.scheduled_date)
        ],
        "acwr": acwr,
        "acwr_status": "high" if (acwr or 0) > 1.5 else "moderate" if (acwr or 0) > 1.3 else "ok",
        "current_vdot": plan.user.vdot,
        "weekly_mileage": list(reversed(weekly_stats)),
    }


@router.post("/{plan_id}/link-activity")
def link_activity(plan_id: str, req: LinkActivityRequest, db: Session = Depends(get_db)):
    session = db.query(PlannedSession).filter(PlannedSession.id == req.session_id).first()
    activity = db.query(Activity).filter(Activity.id == req.activity_id).first()
    if not session or not activity:
        raise HTTPException(404, "Session or activity not found")

    session.linked_activity_id = req.activity_id

    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    user = plan.user

    # Maybe recalc VDOT
    new_vdot, explanation = maybe_recalc_vdot(
        current_vdot=user.vdot,
        session={"session_type": session.session_type},
        linked_activity={"distance_km": activity.distance_km, "duration_seconds": activity.duration_seconds},
    )

    coach_note = None
    if explanation:
        user.vdot = new_vdot
        # Create new plan version
        latest_version = max(plan.versions, key=lambda v: v.version_number)
        new_version = PlanVersion(
            plan_id=plan_id,
            version_number=latest_version.version_number + 1,
            trigger="vdot_recalc",
            trigger_detail={"old_vdot": user.vdot, "new_vdot": new_vdot, "explanation": explanation},
        )
        db.add(new_version)
        coach_note = explanation  # In prod: call coach_agent.get_coach_note()

    db.commit()
    return {"linked": True, "vdot_updated": explanation is not None, "coach_note": coach_note}


@router.post("/{plan_id}/pause")
def pause_plan(plan_id: str, db: Session = Depends(get_db)):
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    plan.is_paused = True
    plan.paused_at = datetime.utcnow()
    db.commit()
    return {"status": "paused"}


@router.post("/{plan_id}/resume")
def resume_plan(plan_id: str, db: Session = Depends(get_db)):
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")

    weeks_remaining = max(1, (plan.race_date - date.today()).days // 7)
    warnings = feasibility_warnings(
        vdot=plan.user.vdot,
        race_distance=plan.race_distance,
        target_seconds=plan.target_finish_time_seconds,
        weeks_available=weeks_remaining,
    )

    plan.is_paused = False
    plan.paused_at = None
    db.commit()
    return {"status": "resumed", "weeks_remaining": weeks_remaining, "warnings": warnings}


@router.post("/{plan_id}/race-result")
def capture_race_result(plan_id: str, finish_time_seconds: int, db: Session = Depends(get_db)):
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")

    distance_km = RACE_DISTANCE_KM[plan.race_distance]
    new_vdot = pace_to_vdot(distance_km, finish_time_seconds)

    user = plan.user
    old_vdot = user.vdot
    user.vdot = new_vdot  # Race result = best data point, straight update (not blended)

    plan.is_active = False
    db.commit()

    return {
        "old_vdot": old_vdot,
        "new_vdot": new_vdot,
        "vdot_delta": new_vdot - old_vdot,
    }
