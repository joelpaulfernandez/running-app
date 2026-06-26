"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, DashboardData, PlannedSession, UnlinkedActivity } from "@/lib/api";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line } from "recharts";

const SESSION_COLORS: Record<string, string> = {
  easy: "bg-green-700",
  tempo: "bg-yellow-600",
  long: "bg-blue-700",
  interval: "bg-red-700",
  time_trial: "bg-purple-700",
  rest: "bg-gray-700",
};

export default function DashboardPage() {
  const params = useSearchParams();
  const planId = params.get("plan_id") ?? "";
  const userId = params.get("user_id") ?? "";

  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [sessions, setSessions] = useState<PlannedSession[]>([]);
  const [unlinked, setUnlinked] = useState<UnlinkedActivity[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [tab, setTab] = useState<"upcoming" | "plan" | "mileage" | "acwr">("upcoming");

  useEffect(() => {
    if (!planId) return;
    api.getDashboard(planId).then(setDashboard);
    api.getPlanSessions(planId).then(setSessions);
    if (userId) api.getUnlinkedActivities(userId).then(setUnlinked);
  }, [planId, userId]);

  const syncStrava = async () => {
    if (!userId) return;
    setSyncing(true);
    await api.syncStrava(userId);
    const [d, s, u] = await Promise.all([
      api.getDashboard(planId),
      api.getPlanSessions(planId),
      api.getUnlinkedActivities(userId),
    ]);
    setDashboard(d);
    setSessions(s);
    setUnlinked(u);
    setSyncing(false);
  };

  const acwrColor = {
    ok: "text-green-400",
    moderate: "text-yellow-400",
    high: "text-red-400",
  }[dashboard?.acwr_status ?? "ok"];

  return (
    <main className="min-h-screen bg-gray-950 text-white">
      <header className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <h1 className="font-bold text-lg">Running Coach</h1>
        <button
          onClick={syncStrava}
          disabled={syncing}
          className="text-sm text-orange-400 hover:text-orange-300 disabled:opacity-40"
        >
          {syncing ? "Syncing..." : "Sync Strava"}
        </button>
      </header>

      {/* VDOT + ACWR summary bar */}
      {dashboard && (
        <div className="grid grid-cols-2 gap-4 px-6 py-4 border-b border-gray-800">
          <div className="bg-gray-900 rounded-xl p-4">
            <p className="text-xs text-gray-500 mb-1">VDOT</p>
            <p className="text-2xl font-bold">{dashboard.current_vdot?.toFixed(1)}</p>
          </div>
          <div className="bg-gray-900 rounded-xl p-4">
            <p className="text-xs text-gray-500 mb-1">ACWR</p>
            <p className={`text-2xl font-bold ${acwrColor}`}>
              {dashboard.acwr?.toFixed(2) ?? "—"}
            </p>
            <p className={`text-xs ${acwrColor}`}>{dashboard.acwr_status}</p>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-gray-800 px-6">
        {(["upcoming", "plan", "mileage", "acwr"] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`py-3 px-4 text-sm font-medium capitalize transition-colors border-b-2 ${
              tab === t ? "border-orange-500 text-white" : "border-transparent text-gray-500 hover:text-gray-300"
            }`}
          >
            {t === "upcoming" ? "Next 7 days" : t === "acwr" ? "Load" : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      <div className="px-6 py-6">
        {tab === "upcoming" && dashboard && (
          <div className="space-y-3">
            {dashboard.upcoming_7_days.map((s, i) => (
              <div key={i} className="flex items-center gap-4 bg-gray-900 rounded-xl p-4">
                <div className={`w-2 h-10 rounded-full ${SESSION_COLORS[s.type] ?? "bg-gray-600"}`} />
                <div>
                  <p className="font-medium capitalize">{s.type.replace("_", " ")}</p>
                  <p className="text-sm text-gray-400">{s.date} · {s.distance_km} km</p>
                </div>
              </div>
            ))}
            {dashboard.upcoming_7_days.length === 0 && (
              <p className="text-gray-500 text-center py-8">No sessions in the next 7 days.</p>
            )}
          </div>
        )}

        {tab === "plan" && (
          <div className="space-y-2">
            {sessions.map(s => (
              <div
                key={s.id}
                className={`flex items-start gap-4 bg-gray-900 rounded-xl p-4 ${s.is_missed ? "opacity-50" : ""}`}
              >
                <div className={`w-2 h-10 mt-1 rounded-full flex-shrink-0 ${SESSION_COLORS[s.type] ?? "bg-gray-600"}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="font-medium capitalize">{s.type.replace("_", " ")}</p>
                    {s.is_missed && <span className="text-xs text-red-400 bg-red-900/30 px-2 py-0.5 rounded-full">Missed</span>}
                    {s.linked_activity_id && <span className="text-xs text-green-400 bg-green-900/30 px-2 py-0.5 rounded-full">Done</span>}
                  </div>
                  <p className="text-sm text-gray-400">{s.date} · Wk {s.week} · {s.phase}</p>
                  <p className="text-xs text-gray-500 mt-1 truncate">{s.description}</p>
                </div>
                <div className="text-right flex-shrink-0">
                  <p className="font-medium">{s.distance_km} km</p>
                  {s.pace_target && (
                    <p className="text-xs text-gray-400">{s.pace_target.toFixed(2)} /km</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === "mileage" && dashboard && (
          <div>
            <h2 className="text-sm text-gray-400 mb-4">Weekly mileage: actual vs planned</h2>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={dashboard.weekly_mileage} margin={{ top: 0, right: 0, bottom: 0, left: -20 }}>
                <XAxis
                  dataKey="week_start"
                  tick={{ fontSize: 10, fill: "#6b7280" }}
                  tickFormatter={v => v.slice(5)}
                />
                <YAxis tick={{ fontSize: 10, fill: "#6b7280" }} />
                <Tooltip
                  contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: 8 }}
                  labelStyle={{ color: "#9ca3af" }}
                />
                <Bar dataKey="planned_km" fill="#374151" name="Planned" radius={[2, 2, 0, 0]} />
                <Bar dataKey="actual_km" fill="#f97316" name="Actual" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {tab === "acwr" && dashboard && (
          <div className="space-y-4">
            <div className={`rounded-xl p-4 border ${
              dashboard.acwr_status === "high"
                ? "bg-red-900/20 border-red-700"
                : dashboard.acwr_status === "moderate"
                ? "bg-yellow-900/20 border-yellow-700"
                : "bg-green-900/20 border-green-700"
            }`}>
              <p className="text-sm font-medium text-gray-300">Acute:Chronic Load Ratio</p>
              <p className={`text-3xl font-bold mt-1 ${acwrColor}`}>
                {dashboard.acwr?.toFixed(2) ?? "Not enough data"}
              </p>
              <p className="text-xs text-gray-400 mt-2">
                {dashboard.acwr === null
                  ? "Need 28 days of history. Using 10% weekly cap in the meantime."
                  : dashboard.acwr_status === "high"
                  ? "Above 1.5 — next week's load will be capped to reduce injury risk."
                  : dashboard.acwr_status === "moderate"
                  ? "Between 1.3–1.5. Training load is high but within range."
                  : "Below 1.3. Load is well managed."}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Unlinked activities */}
      {unlinked.length > 0 && (
        <div className="px-6 pb-8">
          <h2 className="text-sm font-medium text-gray-400 mb-3">Unlinked activities</h2>
          <div className="space-y-2">
            {unlinked.slice(0, 5).map(a => (
              <div key={a.id} className="flex items-center justify-between bg-gray-900 rounded-xl p-4">
                <div>
                  <p className="text-sm font-medium">{a.date} · {a.distance_km} km</p>
                  <p className="text-xs text-gray-500 capitalize">{a.source}</p>
                </div>
                <button className="text-xs text-orange-400 hover:text-orange-300">Link</button>
              </div>
            ))}
          </div>
        </div>
      )}
    </main>
  );
}
