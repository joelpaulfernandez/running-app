"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { api, DashboardData, PlannedSession, UnlinkedActivity, UserProfile } from "@/lib/api";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

// ─── helpers ────────────────────────────────────────────────────────────────

function fmtPace(pace: number) {
  const min = Math.floor(pace);
  const sec = Math.round((pace - min) * 60);
  return `${min}:${sec.toString().padStart(2, "0")}`;
}

function dayLabel(dateStr: string) {
  // Parse as local date to avoid UTC offset shifting the day
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { weekday: "short" });
}

function greetingTime() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

const TYPE_LABELS: Record<string, string> = {
  easy:       "Easy run",
  tempo:      "Tempo run",
  long:       "Long run",
  interval:   "Intervals",
  time_trial: "Time trial",
  rest:       "Rest",
};

// terracotta tint for highlighted row
const TERRA_BG  = "rgba(180, 95, 55, 0.07)";
const TERRA_CLR = "oklch(0.65 0.13 40)";
const MUTED     = "oklch(0.5 0.02 60)";
const TEXT      = "oklch(0.28 0.02 60)";
const BORDER    = "oklch(0.9 0.012 80)";

// ─── sub-components ─────────────────────────────────────────────────────────


type NavKey = "today" | "plan" | "journal" | "progress";

function Sidebar({
  nav, setNav, syncing, onSync,
}: {
  nav: NavKey;
  setNav: (k: NavKey) => void;
  syncing: boolean;
  onSync: () => void;
}) {
  const items: { key: NavKey; label: string }[] = [
    { key: "today",    label: "Today"         },
    { key: "plan",     label: "Training plan" },
    { key: "journal",  label: "Journal"       },
    { key: "progress", label: "Progress"      },
  ];
  return (
    <aside style={{
      width: 260, flexShrink: 0,
      borderRight: `1px solid ${BORDER}`,
      padding: "36px 24px",
      display: "flex", flexDirection: "column", gap: 0,
      background: "oklch(0.97 0.008 80)",
      position: "sticky", top: 0,
      height: "100vh", overflowY: "auto",
    }}>
      <div style={{
        fontFamily: "var(--font-serif)", fontSize: 26,
        color: TEXT, letterSpacing: "-0.01em", marginBottom: 36,
      }}>
        Tempo
      </div>

      <nav style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {items.map(item => (
          <button
            key={item.key}
            onClick={() => setNav(item.key)}
            style={{
              textAlign: "left", border: "none", cursor: "pointer",
              fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 500,
              padding: "9px 12px", borderRadius: 8,
              color: nav === item.key ? TERRA_CLR : MUTED,
              background: nav === item.key ? TERRA_BG : "transparent",
              transition: "color 0.15s, background 0.15s",
            }}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 12 }}>
        <button
          onClick={onSync}
          disabled={syncing}
          style={{
            background: "none", border: `1px solid ${BORDER}`, borderRadius: 8,
            padding: "8px 12px", cursor: "pointer", fontSize: 12, fontWeight: 500,
            color: syncing ? MUTED : TEXT, opacity: syncing ? 0.5 : 1,
            fontFamily: "var(--font-sans)", display: "flex", alignItems: "center", gap: 6,
          }}
        >
          <svg
            style={{ width: 12, height: 12, animation: syncing ? "spin 1s linear infinite" : "none" }}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          {syncing ? "Syncing…" : "Sync Strava"}
        </button>

        <p style={{
          fontFamily: "var(--font-serif)", fontStyle: "italic",
          fontSize: 13, color: MUTED, lineHeight: 1.7,
        }}>
          &ldquo;Slow is smooth,<br />smooth is fast.&rdquo;
        </p>
      </div>
    </aside>
  );
}

// ─── main page ───────────────────────────────────────────────────────────────

function DashboardPage() {
  const params = useSearchParams();
  const planId = params.get("plan_id") ?? (typeof window !== "undefined" ? localStorage.getItem("plan_id") : "") ?? "";
  const userId = params.get("user_id") ?? (typeof window !== "undefined" ? localStorage.getItem("user_id") : "") ?? "";

  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [sessions, setSessions]   = useState<PlannedSession[]>([]);
  const [unlinked, setUnlinked]   = useState<UnlinkedActivity[]>([]);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [syncing, setSyncing]     = useState(false);
  const [nav, setNav]             = useState<NavKey>("today");
  const [linkingActivity, setLinkingActivity] = useState<UnlinkedActivity | null>(null);
  const [linking, setLinking]     = useState(false);

  useEffect(() => {
    if (!planId) return;
    api.getDashboard(planId).then(setDashboard);
    api.getPlanSessions(planId).then(setSessions);
    if (userId) {
      api.getUnlinkedActivities(userId).then(setUnlinked);
      api.getUser(userId).then(setUserProfile).catch(() => {});
    }
  }, [planId, userId]);

  const refresh = async () => {
    const [d, s, u] = await Promise.all([
      api.getDashboard(planId),
      api.getPlanSessions(planId),
      api.getUnlinkedActivities(userId),
    ]);
    setDashboard(d); setSessions(s); setUnlinked(u);
  };

  const linkActivity = async (sessionId: string) => {
    if (!linkingActivity) return;
    setLinking(true);
    await api.linkActivity(planId, sessionId, linkingActivity.id);
    await refresh();
    setLinkingActivity(null);
    setLinking(false);
  };

  const syncStrava = async () => {
    if (!userId) return;
    setSyncing(true);
    await api.syncStrava(userId);
    await refresh();
    setSyncing(false);
  };

  // ── derived data ─────────────────────────────────────────────────────────
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = dashboard?.upcoming_7_days ?? [];
  const sessionsByDate = Object.fromEntries(upcoming.map(s => [s.date, s]));
  const todaySession = sessionsByDate[today] ?? upcoming[0] ?? null;
  const thisWeekKm = upcoming.reduce((sum, s) => sum + s.distance_km, 0).toFixed(1);

  // weekly goal: from mileage data, last entry
  const mileage = dashboard?.weekly_mileage ?? [];
  const latestWeek = mileage[mileage.length - 1];
  const weeklyGoal = latestWeek?.planned_km
    ? Math.round((latestWeek.actual_km / latestWeek.planned_km) * 100)
    : null;

  // calm note
  const longRun = upcoming.find(s => s.type === "long");
  const calmNote = longRun
    ? `You have a ${longRun.distance_km} km long run on ${dayLabel(longRun.date)} — keep it easy until then.`
    : "A steady week ahead. Stay consistent and trust the process.";

  // 7-day window for the week ahead
  const weekWindow = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(); d.setDate(d.getDate() + i);
    return d.toISOString().slice(0, 10);
  });

  const acwrStatus = dashboard?.acwr_status ?? "ok";
  const acwrColor = acwrStatus === "high" ? "#ef4444" : acwrStatus === "moderate" ? "#f59e0b" : "#22c55e";

  // ── styles ────────────────────────────────────────────────────────────────
  const card: React.CSSProperties = {
    background: "#fff",
    border: `1px solid ${BORDER}`,
    borderRadius: 16,
    padding: "28px 32px",
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 11, fontWeight: 500, letterSpacing: "0.08em",
    textTransform: "uppercase", color: MUTED,
  };

  // ── views ─────────────────────────────────────────────────────────────────

  const TodayView = (
    <div style={{ display: "flex", flexDirection: "column", gap: 36 }}>

      {/* Header */}
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{ ...labelStyle }}>
          {new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
        </span>
        <h1 style={{
          fontFamily: "var(--font-serif)", fontSize: 46,
          color: TEXT, letterSpacing: "-0.02em", lineHeight: 1.05,
        }}>
          {greetingTime()}{userProfile?.firstname ? `, ${userProfile.firstname}` : ""}.
        </h1>
        <p style={{ fontSize: 15, color: MUTED, marginTop: 4, lineHeight: 1.5 }}>
          {dashboard ? calmNote : "Loading your plan…"}
        </p>
      </header>

      {/* Unlinked banner */}
      {unlinked.length > 0 && (
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          background: "rgba(180, 95, 55, 0.05)", border: `1px solid rgba(180, 95, 55, 0.2)`,
          borderRadius: 12, padding: "12px 16px",
        }}>
          <p style={{ fontSize: 13, color: MUTED }}>
            <span style={{ color: TERRA_CLR, fontWeight: 500 }}>
              {unlinked.length} unmatched {unlinked.length === 1 ? "run" : "runs"}
            </span>{" "}from Strava
          </p>
          <button
            onClick={() => setLinkingActivity(unlinked[0])}
            style={{
              background: "none", border: "none", cursor: "pointer",
              fontSize: 12, fontWeight: 500, color: TERRA_CLR,
            }}
          >
            Match →
          </button>
        </div>
      )}

      {/* Today's run card */}
      {todaySession && (
        <div style={card}>
          <div style={{ ...labelStyle, marginBottom: 12 }}>Today&apos;s run</div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <h2 style={{
                fontFamily: "var(--font-serif)", fontSize: 26,
                color: TEXT, letterSpacing: "-0.01em",
              }}>
                {TYPE_LABELS[todaySession.type] ?? todaySession.type} &middot; {todaySession.distance_km} km
              </h2>
              <p style={{ fontSize: 14, color: MUTED }}>
                {todaySession.date === today ? "Scheduled for today" : `Scheduled for ${dayLabel(todaySession.date)}`}
              </p>
            </div>
            <button
              style={{
                background: TERRA_CLR, color: "#fff", border: "none",
                borderRadius: 999, padding: "11px 26px",
                fontSize: 14, fontWeight: 500, cursor: "pointer",
                fontFamily: "var(--font-sans)", whiteSpace: "nowrap", flexShrink: 0,
              }}
            >
              Begin
            </button>
          </div>
        </div>
      )}

      {/* Stat strip */}
      {dashboard && (
        <div style={{
          display: "grid", gridTemplateColumns: "1fr 1fr 1fr",
          background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 16, overflow: "hidden",
        }}>
          {[
            { label: "This week",    value: `${thisWeekKm} km`                                },
            { label: "VDOT",         value: dashboard.current_vdot?.toFixed(1) ?? "—"         },
            { label: "Weekly goal",  value: weeklyGoal !== null ? `${weeklyGoal}%` : "—"      },
          ].map((stat, i) => (
            <div
              key={stat.label}
              style={{
                padding: "26px 28px",
                borderLeft: i > 0 ? `1px solid ${BORDER}` : "none",
                display: "flex", flexDirection: "column", gap: 6,
              }}
            >
              <span style={{ ...labelStyle }}>{stat.label}</span>
              <span style={{
                fontFamily: "var(--font-serif)", fontSize: 36,
                color: TEXT, letterSpacing: "-0.02em", lineHeight: 1,
              }}>
                {stat.value}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Week ahead */}
      {dashboard && (
        <section>
          <h3 style={{ ...labelStyle, marginBottom: 10 }}>The week ahead</h3>
          <div style={{
            background: "#fff", border: `1px solid ${BORDER}`,
            borderRadius: 16, overflow: "hidden",
          }}>
            {weekWindow.map((dateStr, i) => {
              const s = sessionsByDate[dateStr];
              const isToday = dateStr === today;
              const isRest  = !s || s.type === "rest";
              return (
                <div
                  key={dateStr}
                  style={{
                    display: "flex", alignItems: "center", gap: 20,
                    padding: "16px 24px",
                    borderBottom: i < weekWindow.length - 1 ? `1px solid ${BORDER}` : "none",
                    background: isToday ? TERRA_BG : "transparent",
                  }}
                >
                  <span style={{
                    fontSize: 12, fontWeight: 500, width: 96, flexShrink: 0,
                    color: isToday ? TERRA_CLR : MUTED,
                    letterSpacing: "0.02em",
                  }}>
                    {dayLabel(dateStr)}{isToday ? " · Today" : ""}
                  </span>
                  <span style={{
                    fontSize: 14, flex: 1,
                    color: isToday ? TERRA_CLR : isRest ? MUTED : TEXT,
                  }}>
                    {isRest ? "Rest" : (TYPE_LABELS[s.type] ?? s.type)}
                  </span>
                  <span style={{ fontSize: 13, color: isRest ? MUTED : (isToday ? TERRA_CLR : MUTED) }}>
                    {isRest ? "—" : `${s.distance_km} km`}
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );

  const PlanView = (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <h2 style={{ fontFamily: "var(--font-serif)", fontSize: 26, color: TEXT }}>Training plan</h2>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {sessions.map(s => (
          <div
            key={s.id}
            style={{
              ...card,
              padding: "14px 20px",
              display: "flex", alignItems: "center", gap: 16,
              opacity: s.is_missed ? 0.45 : 1,
            }}
          >
            <div style={{
              width: 3, height: 32, borderRadius: 2, flexShrink: 0,
              background: s.type === "tempo" ? TERRA_CLR
                        : s.type === "long"  ? "oklch(0.55 0.12 240)"
                        : s.type === "interval" ? "#ef4444"
                        : "oklch(0.7 0.1 150)",
            }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
                <span style={{
                  fontSize: 11, fontWeight: 500, letterSpacing: "0.06em",
                  textTransform: "uppercase", color: TERRA_CLR,
                  background: TERRA_BG, padding: "2px 8px", borderRadius: 6,
                }}>
                  {(TYPE_LABELS[s.type] ?? s.type)}
                </span>
                {s.is_missed && (
                  <span style={{ fontSize: 11, color: "#ef4444", background: "rgba(239,68,68,0.08)", padding: "2px 8px", borderRadius: 6 }}>
                    Missed
                  </span>
                )}
                {s.linked_activity_id && (
                  <span style={{ fontSize: 11, color: "#22c55e", background: "rgba(34,197,94,0.08)", padding: "2px 8px", borderRadius: 6 }}>
                    Done
                  </span>
                )}
              </div>
              <p style={{ fontSize: 12, color: MUTED }}>
                {s.date} · Wk {s.week} · <span style={{ textTransform: "capitalize" }}>{s.phase}</span>
              </p>
            </div>
            <div style={{ textAlign: "right", flexShrink: 0 }}>
              <p style={{ fontFamily: "var(--font-serif)", fontSize: 18, color: TEXT }}>{s.distance_km} km</p>
              {s.pace_target && (
                <p style={{ fontSize: 12, color: MUTED }}>{fmtPace(s.pace_target)}/km</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );

  const JournalView = (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 300, gap: 8 }}>
      <p style={{ fontFamily: "var(--font-serif)", fontStyle: "italic", fontSize: 22, color: MUTED }}>Coming soon.</p>
      <p style={{ fontSize: 14, color: MUTED }}>Training journal is on the way.</p>
    </div>
  );

  const ProgressView = (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <h2 style={{ fontFamily: "var(--font-serif)", fontSize: 26, color: TEXT }}>Progress</h2>

      {/* ACWR */}
      {dashboard && (
        <div style={{ ...card }}>
          <div style={{ ...labelStyle, marginBottom: 12 }}>Acute : Chronic Workload Ratio</div>
          <p style={{ fontFamily: "var(--font-serif)", fontSize: 52, color: acwrColor, letterSpacing: "-0.02em", lineHeight: 1 }}>
            {dashboard.acwr?.toFixed(2) ?? "—"}
          </p>
          <p style={{ fontSize: 14, color: MUTED, marginTop: 12, lineHeight: 1.6 }}>
            {dashboard.acwr === null
              ? "Need 28 days of history to calculate. Using 10% weekly cap in the meantime."
              : dashboard.acwr_status === "high"
              ? "Above 1.5 — next week's load will be automatically capped."
              : dashboard.acwr_status === "moderate"
              ? "1.3–1.5 range. Elevated but manageable."
              : "Below 1.3. Training load is well balanced."}
          </p>
        </div>
      )}

      {/* Mileage chart */}
      {dashboard && (
        <div style={card}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
            <span style={{ fontSize: 14, fontWeight: 500, color: TEXT }}>Weekly mileage</span>
            <div style={{ display: "flex", gap: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{ width: 10, height: 10, borderRadius: 2, background: BORDER }} />
                <span style={{ fontSize: 12, color: MUTED }}>Planned</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{ width: 10, height: 10, borderRadius: 2, background: TERRA_CLR }} />
                <span style={{ fontSize: 12, color: MUTED }}>Actual</span>
              </div>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={dashboard.weekly_mileage} margin={{ top: 0, right: 0, bottom: 0, left: -24 }} barGap={3} barCategoryGap="30%">
              <XAxis dataKey="week_start" tick={{ fontSize: 10, fill: MUTED }} tickLine={false} axisLine={false} tickFormatter={v => v.slice(5)} />
              <YAxis tick={{ fontSize: 10, fill: MUTED }} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{ background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 10, fontSize: 12, color: TEXT }}
                labelStyle={{ color: MUTED }}
                cursor={{ fill: "rgba(0,0,0,0.03)" }}
              />
              <Bar dataKey="planned_km" fill={BORDER} name="Planned" radius={[3, 3, 0, 0]} />
              <Bar dataKey="actual_km"  fill={TERRA_CLR} name="Actual"  radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: oklch(0.97 0.008 80); min-height: 100vh; }
      `}</style>

      <div style={{ display: "flex", minHeight: "100vh" }}>
        <Sidebar nav={nav} setNav={setNav} syncing={syncing} onSync={syncStrava} />
        <main style={{ flex: 1, padding: "56px 64px", overflowY: "auto" }}>
          <div style={{ maxWidth: 860 }}>
            {nav === "today"    && TodayView}
            {nav === "plan"     && PlanView}
            {nav === "journal"  && JournalView}
            {nav === "progress" && ProgressView}
          </div>
        </main>
      </div>

      {/* Link modal */}
      {linkingActivity && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
          backdropFilter: "blur(4px)", display: "flex",
          alignItems: "center", justifyContent: "center", zIndex: 50, padding: 16,
        }}>
          <div style={{
            background: "#fff", border: `1px solid ${BORDER}`,
            borderRadius: 20, width: "100%", maxWidth: 380, padding: 24,
          }}>
            <h2 style={{ fontFamily: "var(--font-serif)", fontSize: 20, color: TEXT, marginBottom: 4 }}>
              Match to a session
            </h2>
            <p style={{ fontSize: 13, color: MUTED, marginBottom: 20 }}>
              {linkingActivity.date} · {linkingActivity.distance_km} km · {linkingActivity.source}
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 240, overflowY: "auto" }}>
              {sessions.filter(s => !s.linked_activity_id && s.type !== "rest").map(s => (
                <button
                  key={s.id}
                  onClick={() => linkActivity(s.id)}
                  disabled={linking}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    background: "oklch(0.97 0.008 80)", border: `1px solid ${BORDER}`,
                    borderRadius: 12, padding: "12px 16px", cursor: "pointer",
                    opacity: linking ? 0.5 : 1, textAlign: "left",
                  }}
                >
                  <div>
                    <span style={{ fontSize: 13, fontWeight: 500, color: TEXT, textTransform: "capitalize" }}>
                      {TYPE_LABELS[s.type] ?? s.type}
                    </span>
                    <p style={{ fontSize: 12, color: MUTED, marginTop: 2 }}>{s.date} · Wk {s.week}</p>
                  </div>
                  <p style={{ fontFamily: "var(--font-serif)", fontSize: 16, color: TEXT }}>{s.distance_km} km</p>
                </button>
              ))}
              {sessions.filter(s => !s.linked_activity_id && s.type !== "rest").length === 0 && (
                <p style={{ fontSize: 14, color: MUTED, textAlign: "center", padding: "24px 0" }}>No unlinked sessions.</p>
              )}
            </div>
            <button
              onClick={() => setLinkingActivity(null)}
              style={{
                width: "100%", marginTop: 12, padding: "11px 0",
                borderRadius: 12, border: `1px solid ${BORDER}`,
                background: "oklch(0.97 0.008 80)", color: MUTED,
                fontSize: 14, fontWeight: 500, cursor: "pointer",
                fontFamily: "var(--font-sans)",
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </>
  );
}

export default function Page() {
  return <Suspense><DashboardPage /></Suspense>;
}
