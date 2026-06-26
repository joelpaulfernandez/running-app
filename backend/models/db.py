from datetime import datetime, date
from enum import Enum
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Date, DateTime,
    ForeignKey, Text, JSON, Enum as SAEnum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid

Base = declarative_base()


def gen_uuid():
    return str(uuid.uuid4())


class RaceDistance(str, Enum):
    FIVE_K = "5k"
    TEN_K = "10k"
    HALF = "half"
    MARATHON = "marathon"


class SessionType(str, Enum):
    EASY = "easy"
    TEMPO = "tempo"
    LONG = "long"
    INTERVAL = "interval"
    TIME_TRIAL = "time_trial"
    REST = "rest"


class PlanPhase(str, Enum):
    BASE = "base"
    BUILD = "build"
    PEAK = "peak"
    TAPER = "taper"


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    strava_athlete_id = Column(String, unique=True, nullable=False)
    strava_access_token = Column(String)
    strava_refresh_token = Column(String)
    strava_token_expires_at = Column(DateTime)
    strava_connected = Column(Boolean, default=True)

    name = Column(String)
    profile_pic_url = Column(String)
    timezone = Column(String, default="UTC")
    units = Column(String, default="km")  # km or mi

    vdot = Column(Float)  # current VDOT
    current_weekly_mileage = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    plans = relationship("Plan", back_populates="user")
    activities = relationship("Activity", back_populates="user")


class Plan(Base):
    __tablename__ = "plans"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)

    race_distance = Column(SAEnum(RaceDistance), nullable=False)
    race_date = Column(Date, nullable=False)
    target_finish_time_seconds = Column(Integer)  # nullable = no target
    training_days = Column(JSON)  # ["monday", "wednesday", "friday", "sunday"]
    long_run_day = Column(String)  # e.g. "sunday"

    initial_vdot = Column(Float)
    initial_weekly_mileage = Column(Float)
    peak_weekly_mileage = Column(Float)

    is_active = Column(Boolean, default=True)
    is_paused = Column(Boolean, default=False)
    paused_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="plans")
    versions = relationship("PlanVersion", back_populates="plan", order_by="PlanVersion.created_at")
    sessions = relationship("PlannedSession", back_populates="plan")


class PlanVersion(Base):
    """Every adaptation creates a new version — sessions never overwritten in place."""
    __tablename__ = "plan_versions"

    id = Column(String, primary_key=True, default=gen_uuid)
    plan_id = Column(String, ForeignKey("plans.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    trigger = Column(String)  # "acwr_cap" | "missed_session" | "vdot_recalc" | "initial"
    trigger_detail = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

    plan = relationship("Plan", back_populates="versions")


class PlannedSession(Base):
    __tablename__ = "planned_sessions"

    id = Column(String, primary_key=True, default=gen_uuid)
    plan_id = Column(String, ForeignKey("plans.id"), nullable=False)
    plan_version_id = Column(String, ForeignKey("plan_versions.id"), nullable=False)

    scheduled_date = Column(Date, nullable=False)
    session_type = Column(SAEnum(SessionType), nullable=False)
    phase = Column(SAEnum(PlanPhase), nullable=False)
    week_number = Column(Integer, nullable=False)

    distance_km = Column(Float)
    duration_minutes = Column(Integer)
    pace_target_min_per_km = Column(Float)  # easy/tempo pace
    description = Column(Text)

    is_missed = Column(Boolean, default=False)
    linked_activity_id = Column(String, ForeignKey("activities.id"))

    plan = relationship("Plan", back_populates="sessions")
    linked_activity = relationship("Activity", foreign_keys=[linked_activity_id])


class Activity(Base):
    __tablename__ = "activities"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)

    strava_activity_id = Column(String, unique=True)  # null = manual entry
    activity_date = Column(Date, nullable=False)
    distance_km = Column(Float, nullable=False)
    duration_seconds = Column(Integer, nullable=False)
    avg_pace_min_per_km = Column(Float)
    elevation_gain_m = Column(Float)

    is_manual = Column(Boolean, default=False)
    is_merged = Column(Boolean, default=False)  # manual + strava duplicate merged

    raw_strava_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="activities")
