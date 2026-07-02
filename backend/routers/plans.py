from datetime import date, datetime, timedelta
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
    compute_volume_adherence,
)
from database import get_db

router = APIRouter(prefix="/plans", tags=["plans"])


def _regenerate_future_sessions(
    plan: Plan,
    new_vdot: float,
    new_version: PlanVersion,
    db: Session,
) -> None:
    """
    Delete all future unscheduled sessions and regenerate them with the new VDOT.
    Past sessions (with linked activities) are preserved as historical record.
    """
    today = date.today()

    future_unlinked = (
        db.query(PlannedSession)
        .filter(
            PlannedSession.plan_id == plan.id,
            PlannedSession.scheduled_date >= today,
            PlannedSession.linked_activity_id == None,
        )
        .all()
    )
    if not future_unlinked:
        return

    for s in future_unlinked:
        db.delete(s)

    # Compute week offset so week numbers stay continuous from plan start
    plan_origin = plan.created_at.date()
    while plan_origin.weekday() != 0:  # advance to Monday
        plan_origin += timedelta(days=1)
    week_number_offset = (today - plan_origin).days // 7

    new_sessions = generate_plan(
        race_distance=plan.race_distance,
        race_date=plan.race_date,
        vdot=new_vdot,
        current_weekly_mileage=plan.initial_weekly_mileage,
        training_days=plan.training_days,
        long_run_day=plan.long_run_day,
        start_date=today,
        week_number_offset=week_number_offset,
    )
    for s in new_sessions:
        db.add(PlannedSession(
            plan_id=plan.id,
            plan_version_id=new_version.id,
            **s,
        ))


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

    if req.race_distance == "marathon" and len(req.training_days) < 4:
        warnings.append(
            "Marathon training on 3 days/week is thin — long runs climb to 30+ km while easy volume is limited. "
            "Consider adding a 4th training day."
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
        old_vdot = user.vdot
        user.vdot = new_vdot
        # Create new plan version
        latest_version = max(plan.versions, key=lambda v: v.version_number)
        new_version = PlanVersion(
            plan_id=plan_id,
            version_number=latest_version.version_number + 1,
            trigger="vdot_recalc",
            trigger_detail={"old_vdot": old_vdot, "new_vdot": new_vdot, "explanation": explanation},
        )
        db.add(new_version)
        db.flush()

        # Propagate new VDOT into all future unscheduled sessions
        _regenerate_future_sessions(plan, new_vdot, new_version, db)
        coach_note = explanation

    # Volume adherence check — scale future sessions if consistently over/under
    linked_sessions = [
        s for s in plan.sessions
        if s.linked_activity_id and s.session_type != "rest" and s.distance_km
    ]
    completed = []
    for ls in linked_sessions:
        act = db.query(Activity).filter(Activity.id == ls.linked_activity_id).first()
        if act:
            completed.append({"planned_km": ls.distance_km, "actual_km": act.distance_km})

    volume_scale, volume_note = compute_volume_adherence(completed)
    if volume_scale is not None:
        today = date.today()
        future_unlinked = (
            db.query(PlannedSession)
            .filter(
                PlannedSession.plan_id == plan_id,
                PlannedSession.scheduled_date >= today,
                PlannedSession.linked_activity_id == None,
                PlannedSession.session_type != "rest",
            )
            .all()
        )
        if future_unlinked:
            # Only create a new version if VDOT didn't already create one this request
            if not explanation:
                latest_version = max(plan.versions, key=lambda v: v.version_number)
                new_version = PlanVersion(
                    plan_id=plan_id,
                    version_number=latest_version.version_number + 1,
                    trigger="volume_adjustment",
                    trigger_detail={"scale": volume_scale, "reason": volume_note},
                )
                db.add(new_version)
                db.flush()
            for s in future_unlinked:
                s.distance_km = round(s.distance_km * volume_scale, 1)
            if coach_note:
                coach_note = coach_note + " " + volume_note
            else:
                coach_note = volume_note

    db.commit()
    return {"linked": True, "vdot_updated": explanation is not None, "coach_note": coach_note}


class UpdateTrainingDaysRequest(BaseModel):
    training_days: list[str]
    long_run_day: str


@router.patch("/{plan_id}/training-days")
def update_training_days(plan_id: str, req: UpdateTrainingDaysRequest, db: Session = Depends(get_db)):
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    if req.long_run_day not in req.training_days:
        raise HTTPException(400, "long_run_day must be one of training_days")
    if len(req.training_days) < 2:
        raise HTTPException(400, "Need at least 2 training days")

    plan.training_days = req.training_days
    plan.long_run_day = req.long_run_day

    today = date.today()
    future_unlinked = (
        db.query(PlannedSession)
        .filter(
            PlannedSession.plan_id == plan.id,
            PlannedSession.scheduled_date >= today,
            PlannedSession.linked_activity_id == None,
        )
        .all()
    )
    for s in future_unlinked:
        db.delete(s)
    db.flush()

    plan_origin = plan.created_at.date()
    while plan_origin.weekday() != 0:
        plan_origin += timedelta(days=1)
    week_number_offset = (today - plan_origin).days // 7

    latest_version = max(plan.versions, key=lambda v: v.version_number)
    new_version = PlanVersion(
        plan_id=plan.id,
        version_number=latest_version.version_number + 1,
        trigger="training_days_change",
        trigger_detail={"training_days": req.training_days, "long_run_day": req.long_run_day},
    )
    db.add(new_version)
    db.flush()

    new_sessions = generate_plan(
        race_distance=plan.race_distance,
        race_date=plan.race_date,
        vdot=plan.user.vdot,
        current_weekly_mileage=plan.initial_weekly_mileage,
        training_days=req.training_days,
        long_run_day=req.long_run_day,
        start_date=today,
        week_number_offset=week_number_offset,
    )
    for s in new_sessions:
        db.add(PlannedSession(
            plan_id=plan.id,
            plan_version_id=new_version.id,
            **s,
        ))

    db.commit()
    return {"updated": True, "sessions_regenerated": len(new_sessions)}


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
