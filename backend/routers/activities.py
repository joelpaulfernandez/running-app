from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.db import Activity
from database import get_db

router = APIRouter(prefix="/activities", tags=["activities"])


class ManualActivityRequest(BaseModel):
    user_id: str
    activity_date: date
    distance_km: float
    duration_seconds: int


@router.post("/manual")
def log_manual_activity(req: ManualActivityRequest, db: Session = Depends(get_db)):
    avg_pace = (req.duration_seconds / 60) / req.distance_km if req.distance_km > 0 else None
    activity = Activity(
        user_id=req.user_id,
        activity_date=req.activity_date,
        distance_km=req.distance_km,
        duration_seconds=req.duration_seconds,
        avg_pace_min_per_km=avg_pace,
        is_manual=True,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return {"id": activity.id, "date": activity.activity_date, "distance_km": activity.distance_km}


@router.get("/unlinked/{user_id}")
def get_unlinked_activities(user_id: str, db: Session = Depends(get_db)):
    """Activities not yet linked to a planned session — shown in the match UI."""
    from models.db import PlannedSession, Plan

    linked_ids = {
        s.linked_activity_id
        for s in db.query(PlannedSession).filter(PlannedSession.linked_activity_id != None).all()
    }

    # Only surface runs from after the user's active plan was created
    active_plan = (
        db.query(Plan)
        .filter(Plan.user_id == user_id, Plan.is_active == True)
        .order_by(Plan.created_at.desc())
        .first()
    )
    cutoff = (active_plan.created_at.date() - timedelta(days=7)) if active_plan else date.today() - timedelta(days=28)

    activities = (
        db.query(Activity)
        .filter(
            Activity.user_id == user_id,
            ~Activity.id.in_(linked_ids),
            Activity.activity_date >= cutoff,
        )
        .order_by(Activity.activity_date.desc())
        .all()
    )
    return [
        {
            "id": a.id,
            "date": a.activity_date.isoformat(),
            "distance_km": a.distance_km,
            "duration_seconds": a.duration_seconds,
            "pace_min_per_km": a.avg_pace_min_per_km,
            "source": "strava" if a.strava_activity_id else "manual",
        }
        for a in activities
    ]
