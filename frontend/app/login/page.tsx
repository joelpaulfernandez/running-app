"use client";

export default function LoginPage() {
  const handleStravaLogin = () => {
    window.location.href = `${process.env.NEXT_PUBLIC_API_URL}/strava/login`;
  };

  return (
    <main className="min-h-screen flex items-center justify-center bg-gray-950">
      <div className="max-w-sm w-full p-8 rounded-2xl bg-gray-900 border border-gray-800">
        <h1 className="text-2xl font-bold text-white mb-2">Running Coach</h1>
        <p className="text-gray-400 text-sm mb-8">
          Adaptive training plans powered by VDOT science.
        </p>

        <button
          onClick={handleStravaLogin}
          className="w-full flex items-center justify-center gap-3 bg-orange-500 hover:bg-orange-400 text-white font-semibold py-3 px-6 rounded-xl transition-colors"
        >
          <svg viewBox="0 0 24 24" className="w-5 h-5 fill-current">
            <path d="M15.387 17.944l-2.089-4.116h-3.065L15.387 24l5.15-10.172h-3.066l-2.024 4.116z" />
            <path d="M11.109 13.828l2.089-4.116h-3.065L5.984 19.884h3.065l2.06-4.116zM10.001 0L4.851 10.172h3.065L10.001 6.056l2.085 4.116h3.065L10.001 0z" />
          </svg>
          Connect with Strava
        </button>

        <p className="text-xs text-gray-500 mt-4 text-center">
          Strava is required to sign in. Your activity data powers your adaptive plan.
        </p>

        {process.env.NODE_ENV === "development" && (
          <button
            onClick={async () => {
              const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/dev/mock-user`, { method: "POST" });
              const { user_id } = await res.json();
              window.location.href = `/onboarding?user_id=${user_id}`;
            }}
            className="w-full mt-3 py-2 rounded-xl border border-gray-700 text-gray-500 hover:text-gray-300 hover:border-gray-500 text-xs transition-colors"
          >
            Skip login (dev)
          </button>
        )}
      </div>
    </main>
  );
}
