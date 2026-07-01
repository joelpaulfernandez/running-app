const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `API error ${res.status}`);
  }
  return res.json();
}

export const api = {
  createPlan: (body: CreatePlanBody) =>
    req<PlanCreatedResponse>("/plans/", { method: "POST", body: JSON.stringify(body) }),

  getPlanSessions: (planId: string) =>
    req<PlannedSession[]>(`/plans/${planId}/sessions`),

  getDashboard: (planId: string) =>
    req<DashboardData>(`/plans/${planId}/dashboard`),

  linkActivity: (planId: string, sessionId: string, activityId: string) =>
    req(`/plans/${planId}/link-activity`, {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, activity_id: activityId }),
    }),

  pausePlan: (planId: string) =>
    req(`/plans/${planId}/pause`, { method: "POST" }),

  resumePlan: (planId: string) =>
    req(`/plans/${planId}/resume`, { method: "POST" }),

  captureRaceResult: (planId: string, finishTimeSeconds: number) =>
    req(`/plans/${planId}/race-result?finish_time_seconds=${finishTimeSeconds}`, { method: "POST" }),

  logManualActivity: (body: ManualActivityBody) =>
    req("/activities/manual", { method: "POST", body: JSON.stringify(body) }),

  getUnlinkedActivities: (userId: string) =>
    req<UnlinkedActivity[]>(`/activities/unlinked/${userId}`),

  syncStrava: (userId: string) =>
    req(`/strava/sync/${userId}`, { method: "POST" }),

  getUser: (userId: string) =>
    req<UserProfile>(`/users/${userId}`),
};

// Types
export interface CreatePlanBody {
  user_id: string;
  race_distance: "5k" | "10k" | "half" | "marathon";
  race_date: string;
  target_finish_time_seconds?: number;
  current_weekly_mileage: number;
  training_days: string[];
  long_run_day: string;
  recent_race_distance_km?: number;
  recent_race_time_seconds?: number;
}

export interface PlanCreatedResponse {
  plan_id: string;
  vdot: number;
  peak_weekly_km: number;
  weeks: number;
  warnings: string[];
  sessions_generated: number;
}

export interface PlannedSession {
  id: string;
  date: string;
  type: "easy" | "tempo" | "long" | "interval" | "time_trial" | "rest";
  phase: "base" | "build" | "peak" | "taper";
  week: number;
  distance_km: number;
  pace_target?: number;
  description: string;
  is_missed: boolean;
  linked_activity_id?: string;
}

export interface DashboardData {
  upcoming_7_days: { date: string; type: string; distance_km: number }[];
  acwr: number | null;
  acwr_status: "ok" | "moderate" | "high";
  current_vdot: number;
  weekly_mileage: { week_start: string; planned_km: number; actual_km: number }[];
}

export interface ManualActivityBody {
  user_id: string;
  activity_date: string;
  distance_km: number;
  duration_seconds: number;
}

export interface UserProfile {
  id: string;
  firstname: string | null;
  name: string;
  profile_pic_url: string | null;
}

export interface UnlinkedActivity {
  id: string;
  date: string;
  distance_km: number;
  duration_seconds: number;
  pace_min_per_km?: number;
  source: "strava" | "manual";
}
