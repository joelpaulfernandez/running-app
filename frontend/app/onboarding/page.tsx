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

const inputCls = "w-full bg-[#111] border border-[#1f1f1f] rounded-xl px-4 py-3 text-white text-sm placeholder-[#333] focus:outline-none focus:border-[#333] transition-colors";
const selectCls = "w-full bg-[#111] border border-[#1f1f1f] rounded-xl px-4 py-3 text-white text-sm focus:outline-none focus:border-[#333] transition-colors";

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
      if (pendingPlanId) {
        localStorage.setItem("plan_id", pendingPlanId);
        localStorage.setItem("user_id", userId);
        router.push(`/dashboard?plan_id=${pendingPlanId}&user_id=${userId}`);
        return;
      }
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

  const STEP_LABELS = ["Race goal", "Schedule", "Fitness"];

  return (
    <main className="min-h-screen bg-[#0a0a0a] text-white">
      <div className="max-w-md mx-auto px-6 py-12">

        {/* Header */}
        <div className="mb-10">
          <div className="flex items-center gap-2 mb-8">
            {STEP_LABELS.map((label, i) => (
              <div key={i} className="flex items-center gap-2">
                <div className={`flex items-center gap-1.5 ${i + 1 <= step ? "text-white" : "text-[#333]"}`}>
                  <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-medium border ${
                    i + 1 < step ? "bg-orange-500 border-orange-500 text-white"
                    : i + 1 === step ? "border-orange-500 text-orange-400"
                    : "border-[#222] text-[#333]"
                  }`}>{i + 1}</div>
                  <span className="text-xs">{label}</span>
                </div>
                {i < 2 && <div className={`w-6 h-px ${i + 1 < step ? "bg-orange-500/50" : "bg-[#1a1a1a]"}`} />}
              </div>
            ))}
          </div>
          <h1 className="text-xl font-semibold tracking-tight">
            {step === 1 && "What are you training for?"}
            {step === 2 && "When do you train?"}
            {step === 3 && "What's your current fitness?"}
          </h1>
        </div>

        {/* Step 1 */}
        {step === 1 && (
          <div className="space-y-5">
            <div>
              <label className="block text-xs text-[#555] mb-2 uppercase tracking-wider">Distance</label>
              <div className="grid grid-cols-2 gap-2">
                {DISTANCES.map(d => (
                  <button
                    key={d.value}
                    onClick={() => setForm(f => ({ ...f, race_distance: d.value as any }))}
                    className={`py-3 rounded-xl border text-sm font-medium transition-colors ${
                      form.race_distance === d.value
                        ? "border-orange-500/50 bg-orange-500/10 text-orange-400"
                        : "border-[#1f1f1f] text-[#666] hover:border-[#2a2a2a] hover:text-[#999]"
                    }`}
                  >
                    {d.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs text-[#555] mb-2 uppercase tracking-wider">Race date</label>
              <input
                type="date"
                value={form.race_date}
                onChange={e => setForm(f => ({ ...f, race_date: e.target.value }))}
                className={inputCls}
              />
            </div>

            <div>
              <label className="flex items-center gap-3 cursor-pointer group">
                <div className={`w-4 h-4 rounded border flex items-center justify-center transition-colors ${
                  form.has_target ? "bg-orange-500 border-orange-500" : "border-[#333] group-hover:border-[#444]"
                }`}>
                  {form.has_target && <svg className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" /></svg>}
                </div>
                <input type="checkbox" checked={form.has_target} onChange={e => setForm(f => ({ ...f, has_target: e.target.checked }))} className="sr-only" />
                <span className="text-sm text-[#666]">I have a target finish time</span>
              </label>
              {form.has_target && (
                <div className="mt-3 flex gap-2">
                  {[
                    { key: "target_h", placeholder: "H" },
                    { key: "target_m", placeholder: "MM" },
                    { key: "target_s", placeholder: "SS" },
                  ].map(f => (
                    <input
                      key={f.key}
                      type="number"
                      placeholder={f.placeholder}
                      min={0}
                      value={(form as any)[f.key]}
                      onChange={e => setForm(prev => ({ ...prev, [f.key]: e.target.value }))}
                      className="flex-1 bg-[#111] border border-[#1f1f1f] rounded-xl px-3 py-2.5 text-white text-sm text-center focus:outline-none focus:border-[#333] transition-colors"
                    />
                  ))}
                </div>
              )}
            </div>

            <button
              onClick={() => setStep(2)}
              disabled={!form.race_date}
              className="w-full bg-white hover:bg-gray-100 disabled:opacity-20 text-black font-medium py-3 rounded-xl transition-colors text-sm mt-2"
            >
              Continue
            </button>
          </div>
        )}

        {/* Step 2 */}
        {step === 2 && (
          <div className="space-y-5">
            <div>
              <label className="block text-xs text-[#555] mb-2 uppercase tracking-wider">Training days</label>
              <div className="flex gap-1.5 flex-wrap">
                {DAYS.map(d => (
                  <button
                    key={d}
                    onClick={() => toggleDay(d)}
                    className={`px-3 py-2 rounded-lg text-xs capitalize font-medium transition-colors ${
                      form.training_days.includes(d)
                        ? "bg-orange-500 text-white"
                        : "bg-[#111] border border-[#1f1f1f] text-[#555] hover:text-[#888]"
                    }`}
                  >
                    {d.slice(0, 3)}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs text-[#555] mb-2 uppercase tracking-wider">Long run day</label>
              <select
                value={form.long_run_day}
                onChange={e => setForm(f => ({ ...f, long_run_day: e.target.value }))}
                className={selectCls}
              >
                {form.training_days.map(d => (
                  <option key={d} value={d}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs text-[#555] mb-2 uppercase tracking-wider">Weekly mileage (km)</label>
              <input
                type="number"
                min={0}
                placeholder="40"
                value={form.current_weekly_mileage}
                onChange={e => setForm(f => ({ ...f, current_weekly_mileage: e.target.value }))}
                className={inputCls}
              />
            </div>

            <div className="flex gap-2 mt-2">
              <button onClick={() => setStep(1)} className="flex-1 border border-[#1f1f1f] text-[#555] py-3 rounded-xl hover:border-[#2a2a2a] hover:text-[#888] transition-colors text-sm">Back</button>
              <button
                onClick={() => setStep(3)}
                disabled={form.training_days.length === 0 || !form.current_weekly_mileage}
                className="flex-1 bg-white hover:bg-gray-100 disabled:opacity-20 text-black font-medium py-3 rounded-xl transition-colors text-sm"
              >
                Continue
              </button>
            </div>
          </div>
        )}

        {/* Step 3 */}
        {step === 3 && (
          <div className="space-y-5">
            <p className="text-sm text-[#555] leading-relaxed">
              Enter a recent race to calculate your VDOT score. Skip if you don't have one — Strava history will be used.
            </p>

            <div>
              <label className="block text-xs text-[#555] mb-2 uppercase tracking-wider">Recent race distance (km)</label>
              <input
                type="number"
                placeholder="10"
                value={form.recent_race_distance_km}
                onChange={e => setForm(f => ({ ...f, recent_race_distance_km: e.target.value }))}
                className={inputCls}
              />
            </div>

            <div>
              <label className="block text-xs text-[#555] mb-2 uppercase tracking-wider">Finish time</label>
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
                    className="flex-1 bg-[#111] border border-[#1f1f1f] rounded-xl px-3 py-2.5 text-white text-sm text-center focus:outline-none focus:border-[#333] transition-colors"
                  />
                ))}
              </div>
            </div>

            {warnings.length > 0 && (
              <div className="bg-yellow-500/5 border border-yellow-500/20 rounded-xl p-4 space-y-1">
                <p className="text-yellow-400 font-medium text-xs uppercase tracking-wider mb-2">Heads up</p>
                {warnings.map((w, i) => <p key={i} className="text-[#999] text-sm">{w}</p>)}
              </div>
            )}

            {error && <p className="text-red-400 text-sm">{error}</p>}

            <div className="flex gap-2 mt-2">
              <button onClick={() => setStep(2)} className="flex-1 border border-[#1f1f1f] text-[#555] py-3 rounded-xl hover:border-[#2a2a2a] hover:text-[#888] transition-colors text-sm">Back</button>
              <button
                onClick={handleSubmit}
                disabled={loading}
                className="flex-1 bg-white hover:bg-gray-100 disabled:opacity-20 text-black font-medium py-3 rounded-xl transition-colors text-sm"
              >
                {loading ? "Building..." : warnings.length > 0 ? "Proceed anyway" : "Build my plan"}
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
