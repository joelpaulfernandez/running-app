"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

const TERRA  = "oklch(0.65 0.13 40)";
const TEXT   = "oklch(0.28 0.02 60)";
const MUTED  = "oklch(0.5 0.02 60)";
const BORDER = "oklch(0.9 0.012 80)";
const BG     = "oklch(0.97 0.008 80)";

export default function LoginPage() {
  const router = useRouter();

  useEffect(() => {
    const planId = localStorage.getItem("plan_id");
    const userId = localStorage.getItem("user_id");
    if (planId && userId) {
      router.replace(`/dashboard?plan_id=${planId}&user_id=${userId}`);
    }
  }, []);

  const handleStravaLogin = () => {
    window.location.href = `${process.env.NEXT_PUBLIC_API_URL}/strava/login`;
  };

  return (
    <>
      <style>{`* { box-sizing: border-box; margin: 0; padding: 0; } body { background: ${BG}; }`}</style>
      <main style={{
        minHeight: "100vh", background: BG,
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: "0 24px",
      }}>
        <div style={{ width: "100%", maxWidth: 380 }}>

          {/* Wordmark */}
          <div style={{ marginBottom: 48 }}>
            <div style={{
              fontFamily: "var(--font-serif)", fontSize: 36,
              color: TEXT, letterSpacing: "-0.02em", lineHeight: 1,
              marginBottom: 12,
            }}>
              Tempo
            </div>
            <p style={{ fontSize: 15, color: MUTED, lineHeight: 1.6 }}>
              Adaptive training plans built on VDOT science.<br />
              Personalized to your fitness, updated as you run.
            </p>
          </div>

          {/* Card */}
          <div style={{
            background: "#fff",
            border: `1px solid ${BORDER}`,
            borderRadius: 20,
            padding: "32px 28px",
            display: "flex", flexDirection: "column", gap: 20,
          }}>
            <div>
              <p style={{ fontSize: 11, fontWeight: 500, letterSpacing: "0.08em", textTransform: "uppercase", color: MUTED, marginBottom: 6 }}>
                Get started
              </p>
              <p style={{ fontSize: 14, color: TEXT, lineHeight: 1.6 }}>
                Connect your Strava account to generate your plan and sync your runs automatically.
              </p>
            </div>

            <button
              onClick={handleStravaLogin}
              style={{
                display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
                background: TERRA, color: "#fff", border: "none",
                borderRadius: 12, padding: "14px 0",
                fontSize: 14, fontWeight: 500, cursor: "pointer",
                fontFamily: "var(--font-sans)", width: "100%",
                transition: "opacity 0.15s",
              }}
              onMouseEnter={e => (e.currentTarget.style.opacity = "0.88")}
              onMouseLeave={e => (e.currentTarget.style.opacity = "1")}
            >
              <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, fill: "currentColor", flexShrink: 0 }}>
                <path d="M15.387 17.944l-2.089-4.116h-3.065L15.387 24l5.15-10.172h-3.066l-2.024 4.116z" />
                <path d="M11.109 13.828l2.089-4.116h-3.065L5.984 19.884h3.065l2.06-4.116zM10.001 0L4.851 10.172h3.065L10.001 6.056l2.085 4.116h3.065L10.001 0z" />
              </svg>
              Continue with Strava
            </button>

            <p style={{ fontSize: 12, color: MUTED, lineHeight: 1.6, textAlign: "center" }}>
              Strava is required — your activity history powers ACWR calculations and VDOT calibration.
            </p>
          </div>

          {/* Dev bypass */}
          {process.env.NODE_ENV === "development" && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "20px 0" }}>
                <div style={{ flex: 1, height: 1, background: BORDER }} />
                <span style={{ fontSize: 11, color: MUTED, letterSpacing: "0.06em" }}>DEV</span>
                <div style={{ flex: 1, height: 1, background: BORDER }} />
              </div>
              <button
                onClick={async () => {
                  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/dev/mock-user`, { method: "POST" });
                  const { user_id } = await res.json();
                  window.location.href = `/onboarding?user_id=${user_id}`;
                }}
                style={{
                  width: "100%", padding: "11px 0", borderRadius: 12,
                  border: `1px solid ${BORDER}`, background: "transparent",
                  color: MUTED, fontSize: 13, fontWeight: 500, cursor: "pointer",
                  fontFamily: "var(--font-sans)",
                }}
              >
                Skip login (dev)
              </button>
            </>
          )}

          {/* Footer quote */}
          <p style={{
            fontFamily: "var(--font-serif)", fontStyle: "italic",
            fontSize: 13, color: MUTED, lineHeight: 1.7,
            textAlign: "center", marginTop: 36,
          }}>
            &ldquo;Slow is smooth, smooth is fast.&rdquo;
          </p>
        </div>
      </main>
    </>
  );
}
