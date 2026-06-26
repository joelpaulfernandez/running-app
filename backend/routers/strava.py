"""
Strava OAuth + activity sync.
OAuth is mandatory login — no email/password path.
"""
import httpx
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import os

from models.db import User, Activity
from database import get_db

router = APIRouter(prefix="/strava", tags=["strava"])

STRAVA_CLIENT_ID = os.environ["STRAVA_CLIENT_ID"]
STRAVA_CLIENT_SECRET = os.environ["STRAVA_CLIENT_SECRET"]
STRAVA_REDIRECT_URI = os.environ.get("STRAVA_REDIRECT_URI", "http://localhost:8000/strava/callback")
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"


@router.get("/login")
def strava_login():
    params = {
        "client_id": STRAVA_CLIENT_ID,
        "redirect_uri": STRAVA_REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "read,activity:read_all",
    }
    from urllib.parse import urlencode
    return RedirectResponse(f"{STRAVA_AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def strava_callback(code: str, db: Session = Depends(get_db)):
    async with httpx.AsyncClient() as client:
        resp = await client.post(STRAVA_TOKEN_URL, data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        })
    if resp.status_code != 200:
        raise HTTPException(400, "Strava token exchange failed")

    token_data = resp.json()
    athlete = token_data["athlete"]
    strava_id = str(athlete["id"])

    user = db.query(User).filter(User.strava_athlete_id == strava_id).first()
    if not user:
        user = User(strava_athlete_id=strava_id)
        db.add(user)

    user.strava_access_token = token_data["access_token"]
    user.strava_refresh_token = token_data["refresh_token"]
    user.strava_token_expires_at = datetime.utcfromtimestamp(token_data["expires_at"])
    user.strava_connected = True
    user.name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()
    user.profile_pic_url = athlete.get("profile")
    db.commit()
    db.refresh(user)

    # Return JWT or session token to frontend
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    return RedirectResponse(f"{frontend_url}/onboarding?user_id={user.id}")


async def _refresh_token_if_needed(user: User, db: Session) -> str:
    if user.strava_token_expires_at and datetime.utcnow() < user.strava_token_expires_at - timedelta(minutes=5):
        return user.strava_access_token

    async with httpx.AsyncClient() as client:
        resp = await client.post(STRAVA_TOKEN_URL, data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "refresh_token": user.strava_refresh_token,
            "grant_type": "refresh_token",
        })

    if resp.status_code != 200:
        # Token revoked — fall back to manual-only mode
        user.strava_connected = False
        db.commit()
        raise HTTPException(401, "Strava token expired and refresh failed. Please reconnect.")

    token_data = resp.json()
    user.strava_access_token = token_data["access_token"]
    user.strava_refresh_token = token_data["refresh_token"]
    user.strava_token_expires_at = datetime.utcfromtimestamp(token_data["expires_at"])
    db.commit()
    return user.strava_access_token


@router.post("/sync/{user_id}")
async def sync_strava_activities(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.strava_connected:
        raise HTTPException(404, "User not found or Strava not connected")

    try:
        token = await _refresh_token_if_needed(user, db)
    except HTTPException:
        return {"status": "disconnected", "message": "Strava disconnected — manual logging mode active"}

    # Fetch last 60 days of activities
    after_ts = int((datetime.utcnow() - timedelta(days=60)).timestamp())
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{STRAVA_API_BASE}/athlete/activities",
            headers={"Authorization": f"Bearer {token}"},
            params={"after": after_ts, "per_page": 200, "type": "Run"},
        )

    if resp.status_code != 200:
        raise HTTPException(502, "Strava API error")

    strava_activities = resp.json()
    synced = 0

    for act in strava_activities:
        if act.get("type") != "Run":
            continue

        strava_id = str(act["id"])
        existing = db.query(Activity).filter(Activity.strava_activity_id == strava_id).first()
        if existing:
            continue

        activity_date = datetime.strptime(act["start_date_local"][:10], "%Y-%m-%d").date()
        distance_km = act["distance"] / 1000
        duration_s = act["moving_time"]
        avg_pace = (duration_s / 60) / distance_km if distance_km > 0 else None

        # Check for manual duplicate within ±5% distance on same date
        manual_dup = db.query(Activity).filter(
            Activity.user_id == user_id,
            Activity.activity_date == activity_date,
            Activity.is_manual == True,
            Activity.strava_activity_id == None,
        ).first()

        if manual_dup and abs(manual_dup.distance_km - distance_km) / max(distance_km, 0.01) < 0.05:
            # Merge: update manual entry with Strava data
            manual_dup.strava_activity_id = strava_id
            manual_dup.duration_seconds = duration_s
            manual_dup.avg_pace_min_per_km = avg_pace
            manual_dup.elevation_gain_m = act.get("total_elevation_gain")
            manual_dup.is_merged = True
            manual_dup.raw_strava_data = act
            db.commit()
        else:
            new_activity = Activity(
                user_id=user_id,
                strava_activity_id=strava_id,
                activity_date=activity_date,
                distance_km=distance_km,
                duration_seconds=duration_s,
                avg_pace_min_per_km=avg_pace,
                elevation_gain_m=act.get("total_elevation_gain"),
                is_manual=False,
                raw_strava_data=act,
            )
            db.add(new_activity)
            synced += 1

    db.commit()
    return {"synced": synced, "total_strava": len(strava_activities)}


@router.delete("/disconnect/{user_id}")
def disconnect_strava(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.strava_connected = False
    db.commit()
    return {"status": "disconnected"}
