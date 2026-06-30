"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";

const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const DISTANCES = [
  { value: "5k", label: "5K" },
  { value: "10k", label: "10K" },
  { value: "half", label: "Half Marathon" },
  { value: "marathon", label: "Marathon" },
];

function secondsFromTime(h: string, m: string, s: string) {
  return parseInt(h || "0") * 3600 + parseInt(m || "0") * 60 + parseInt(s || "0");
}

function OnboardingPage() {
  const router = useRouter();
  const params = useSearchParams();
  const userId = params.get("user_id") ?? "";

  const [step, setStep] = useState(1);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [pendingPlanId, setPendingPlanId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const [form, setForm] = useState({
    race_distance: "half" as const,
    race_date: "",
    training_days: [] as string[],
    long_run_day: "sunday",
    current_weekly_mileage: "",
    has_target: false,
    target_h: "", target_m: "", target_s: "",
    recent_race_distance_km: "",
    recent_race_h: "", recent_race_m: "", recent_race_s: "",
  });

  const toggleDay = (day: string) => {
    setForm(f => ({
      ...f,
      training_days: f.training_days.includes(day)
        ? f.training_days.filter(d => d !== day)
        : [...f.training_days, day],
    }));
  };

  const handleSubmit = async () => {
    setLoading(true);
    setError("");
    try {
      const body = {
        user_id: userId,
        race_distance: form.race_distance,
        race_date: form.race_date,
        current_weekly_mileage: parseFloat(form.current_weekly_mileage),
        training_days: form.training_days,
        long_run_day: form.long_run_day,
        ...(form.has_target && {
          target_finish_time_seconds: secondsFromTime(form.target_h, form.target_m, form.target_s),
        }),
        ...(form.recent_race_distance_km && {
          recent_race_distance_km: parseFloat(form.recent_race_distance_km),
          recent_race_time_seconds: secondsFromTime(form.recent_race_h, form.recent_race_m, form.recent_race_s),
        }),
      };

      if (pendingPlanId) {
        localStorage.setItem("plan_id", pendingPlanId);
        localStorage.setItem("user_id", userId);
        router.push(`/dashboard?plan_id=${pendingPlanId}&user_id=${userId}`);
        return;
      }
      const result = await api.createPlan(body);
      if (result.warnings.length > 0) {
        setWarnings(result.warnings);
        setPendingPlanId(result.plan_id);
        return;
      }
      localStorage.setItem("plan_id", result.plan_id);
      localStorage.setItem("user_id", userId);
      router.push(`/dashboard?plan_id=${result.plan_id}&user_id=${userId}`);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-lg mx-auto px-6 py-12">
        <div className="mb-8">
          <div className="flex gap-1 mb-6">
            {[1, 2, 3].map(s => (
              <div key={s} className={`h-1 flex-1 rounded-full ${s <= step ? "bg-orange-500" : "bg-gray-700"}`} />
            ))}
          </div>
          <h1 className="text-2xl font-bold">
            {step === 1 && "Your race goal"}
            {step === 2 && "Your training schedule"}
            {step === 3 && "Current fitness"}
          </h1>
        </div>

        {step === 1 && (
          <div className="space-y-6">
            <div>
              <label className="block text-sm text-gray-400 mb-2">Race distance</label>
              <div className="grid grid-cols-2 gap-2">
                {DISTANCES.map(d => (
                  <button
                    key={d.value}
                    onClick={() => setForm(f => ({ ...f, race_distance: d.value as any }))}
                    className={`py-3 rounded-xl border font-medium transition-colors ${
                      form.race_distance === d.value
                        ? "border-orange-500 bg-orange-500/10 text-orange-400"
                        : "border-gray-700 text-gray-300 hover:border-gray-500"
                    }`}
                  >
                    {d.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-2">Race date</label>
              <input
                type="date"
                value={form.race_date}
                onChange={e => setForm(f => ({ ...f, race_date: e.target.value }))}
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-orange-500"
              />
            </div>

            <div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.has_target}
                  onChange={e => setForm(f => ({ ...f, has_target: e.target.checked }))}
                  className="rounded"
                />
                <span className="text-sm text-gray-300">I have a target finish time</span>
              </label>
              {form.has_target && (
                <div className="mt-3 flex gap-2">
                  {[
                    { key: "target_h", placeholder: "H", max: 6 },
                    { key: "target_m", placeholder: "MM", max: 59 },
                    { key: "target_s", placeholder: "SS", max: 59 },
                  ].map(f => (
                    <input
                      key={f.key}
                      type="number"
                      placeholder={f.placeholder}
                      min={0}
                      max={f.max}
                      value={(form as any)[f.key]}
                      onChange={e => setForm(prev => ({ ...prev, [f.key]: e.target.value }))}
                      className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-white text-center focus:outline-none focus:border-orange-500"
                    />
                  ))}
                </div>
              )}
            </div>

            <button
              onClick={() => setStep(2)}
              disabled={!form.race_date || !form.race_distance}
              className="w-full bg-orange-500 hover:bg-orange-400 disabled:opacity-40 text-white font-semibold py-3 rounded-xl transition-colors"
            >
              Next
            </button>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-6">
            <div>
              <label className="block text-sm text-gray-400 mb-2">Training days</label>
              <div className="flex gap-2 flex-wrap">
                {DAYS.map(d => (
                  <button
                    key={d}
                    onClick={() => toggleDay(d)}
                    className={`px-3 py-2 rounded-lg text-sm capitalize font-medium transition-colors ${
                      form.training_days.includes(d)
                        ? "bg-orange-500 text-white"
                        : "bg-gray-800 text-gray-400 hover:bg-gray-700"
                    }`}
                  >
                    {d.slice(0, 3)}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-2">Long run day</label>
              <select
                value={form.long_run_day}
                onChange={e => setForm(f => ({ ...f, long_run_day: e.target.value }))}
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-orange-500"
              >
                {form.training_days.map(d => (
                  <option key={d} value={d}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-2">Current weekly mileage (km)</label>
              <input
                type="number"
                min={0}
                placeholder="e.g. 40"
                value={form.current_weekly_mileage}
                onChange={e => setForm(f => ({ ...f, current_weekly_mileage: e.target.value }))}
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-orange-500"
              />
            </div>

            <div className="flex gap-3">
              <button onClick={() => setStep(1)} className="flex-1 border border-gray-700 text-gray-300 py-3 rounded-xl hover:border-gray-500 transition-colors">Back</button>
              <button
                onClick={() => setStep(3)}
                disabled={form.training_days.length === 0 || !form.current_weekly_mileage}
                className="flex-1 bg-orange-500 hover:bg-orange-400 disabled:opacity-40 text-white font-semibold py-3 rounded-xl transition-colors"
              >
                Next
              </button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-6">
            <p className="text-gray-400 text-sm">
              Enter a recent race time so we can calculate your VDOT fitness score. If you don't have one, your Strava history will be used.
            </p>

            <div>
              <label className="block text-sm text-gray-400 mb-2">Recent race distance (km)</label>
              <input
                type="number"
                placeholder="e.g. 10"
                value={form.recent_race_distance_km}
                onChange={e => setForm(f => ({ ...f, recent_race_distance_km: e.target.value }))}
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-orange-500"
              />
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-2">Finish time (H : MM : SS)</label>
              <div className="flex gap-2">
                {[
                  { key: "recent_race_h", placeholder: "H" },
                  { key: "recent_race_m", placeholder: "MM" },
                  { key: "recent_race_s", placeholder: "SS" },
                ].map(f => (
                  <input
                    key={f.key}
                    type="number"
                    placeholder={f.placeholder}
                    value={(form as any)[f.key]}
                    onChange={e => setForm(prev => ({ ...prev, [f.key]: e.target.value }))}
                    className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-white text-center focus:outline-none focus:border-orange-500"
                  />
                ))}
              </div>
            </div>

            {warnings.length > 0 && (
              <div className="bg-yellow-900/30 border border-yellow-700 rounded-xl p-4 space-y-1">
                <p className="text-yellow-400 font-medium text-sm">Heads up</p>
                {warnings.map((w, i) => <p key={i} className="text-yellow-300 text-sm">{w}</p>)}
                <p className="text-yellow-300 text-sm mt-2">You can still proceed — these are soft warnings.</p>
              </div>
            )}

            {error && <p className="text-red-400 text-sm">{error}</p>}

            <div className="flex gap-3">
              <button onClick={() => setStep(2)} className="flex-1 border border-gray-700 text-gray-300 py-3 rounded-xl hover:border-gray-500 transition-colors">Back</button>
              <button
                onClick={handleSubmit}
                disabled={loading}
                className="flex-1 bg-orange-500 hover:bg-orange-400 disabled:opacity-40 text-white font-semibold py-3 rounded-xl transition-colors"
              >
                {loading ? "Building plan..." : warnings.length > 0 ? "Proceed anyway" : "Build my plan"}
              </button>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

export default function Page() {
  return <Suspense><OnboardingPage /></Suspense>;
}
