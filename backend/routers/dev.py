"""Dev-only routes — never import in production."""
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models.db import User
from database import get_db

router = APIRouter(prefix="/dev", tags=["dev"])


@router.post("/mock-user")
def create_mock_user(db: Session = Depends(get_db)):
    if os.environ.get("ENVIRONMENT") != "development":
        raise HTTPException(404, "Not found")
    user = db.query(User).filter(User.strava_athlete_id == "dev_mock").first()
    if not user:
        user = User(
            strava_athlete_id="dev_mock",
            name="Dev Runner",
            strava_connected=False,
            vdot=45.0,
            current_weekly_mileage=40.0,
            timezone="America/New_York",
            units="km",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return {"user_id": user.id}
