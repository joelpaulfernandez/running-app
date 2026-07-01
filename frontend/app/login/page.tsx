"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

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
    <main className="min-h-screen bg-[#0a0a0a] flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-10">
          <div className="w-8 h-8 bg-orange-500 rounded-lg mb-6" />
          <h1 className="text-2xl font-semibold text-white tracking-tight">Running Coach</h1>
          <p className="text-[#666] text-sm mt-2 leading-relaxed">
            Adaptive training plans powered by VDOT science.
          </p>
        </div>

        <button
          onClick={handleStravaLogin}
          className="w-full flex items-center justify-center gap-3 bg-orange-500 hover:bg-orange-400 active:bg-orange-600 text-white font-medium py-3 px-5 rounded-xl transition-colors text-sm"
        >
          <svg viewBox="0 0 24 24" className="w-4 h-4 fill-current flex-shrink-0">
            <path d="M15.387 17.944l-2.089-4.116h-3.065L15.387 24l5.15-10.172h-3.066l-2.024 4.116z" />
            <path d="M11.109 13.828l2.089-4.116h-3.065L5.984 19.884h3.065l2.06-4.116zM10.001 0L4.851 10.172h3.065L10.001 6.056l2.085 4.116h3.065L10.001 0z" />
          </svg>
          Continue with Strava
        </button>

        <p className="text-[#444] text-xs mt-5 text-center leading-relaxed">
          Strava is required. Your activity data powers your adaptive plan.
        </p>

        {process.env.NODE_ENV === "development" && (
          <>
            <div className="flex items-center gap-3 my-5">
              <div className="h-px flex-1 bg-[#1a1a1a]" />
              <span className="text-[#333] text-xs">dev</span>
              <div className="h-px flex-1 bg-[#1a1a1a]" />
            </div>
            <button
              onClick={async () => {
                const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/dev/mock-user`, { method: "POST" });
                const { user_id } = await res.json();
                window.location.href = `/onboarding?user_id=${user_id}`;
              }}
              className="w-full py-2.5 rounded-xl border border-[#1f1f1f] text-[#444] hover:text-[#888] hover:border-[#2a2a2a] text-xs transition-colors"
            >
              Skip login
            </button>
          </>
        )}
      </div>
    </main>
  );
}
