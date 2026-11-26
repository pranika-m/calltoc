import { useEffect, useState } from "react";
import { Calendar as CalendarIcon, AlertCircle } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const STATUS_BADGE = {
  booked: "bg-indigo-500/15 text-indigo-300 border-indigo-500/30",
  completed: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  rescheduled: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  cancelled: "bg-rose-500/15 text-rose-300 border-rose-500/30",
};

export function AppointmentsPage({ tenantId, darkMode }) {
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const cardClass = darkMode ? "bg-[#111827]/90 border-white/10" : "bg-white border-slate-200 shadow-sm";

  async function load() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/appointments?tenant_id=${tenantId}`);
      if (!res.ok) throw new Error("Failed to load appointments");
      setAppointments(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [tenantId]);

  async function updateStatus(id, status) {
    await fetch(`${API_BASE}/appointments/${id}?tenant_id=${tenantId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    load();
  }

  const weekDays = Array.from({ length: 7 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() + i);
    return d.toISOString().slice(0, 10);
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Appointments</h1>
        <p className="text-sm text-slate-400">7-day schedule and upcoming demo bookings protected against double-booking.</p>
      </div>

      {error && (
        <div className="p-4 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-400 flex items-center gap-2 text-sm">
          <AlertCircle className="w-4 h-4" /> {error}
        </div>
      )}

      {loading ? (
        <div className="h-48 rounded-2xl bg-white/5 animate-pulse" />
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
            {weekDays.map((day) => {
              const dayAppts = appointments.filter((a) => (a.starts_at || "").slice(0, 10) === day);
              return (
                <div key={day} className={`rounded-2xl border p-3 min-h-[140px] space-y-2 ${cardClass}`}>
                  <div className="font-mono text-xs text-slate-400">{day}</div>
                  {dayAppts.length === 0 ? (
                    <div className="text-xs text-slate-500">Free</div>
                  ) : (
                    dayAppts.map((a) => (
                      <div key={a.id} className="p-2 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-xs space-y-1">
                        <div className="font-mono font-medium">{new Date(a.starts_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</div>
                        <div className="truncate text-slate-300">{a.lead_name || `Lead #${a.lead_id}`}</div>
                      </div>
                    ))
                  )}
                </div>
              );
            })}
          </div>

          <div className={`rounded-2xl border p-5 space-y-3 ${cardClass}`}>
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <CalendarIcon className="w-4 h-4 text-cyan-400" /> Upcoming List
            </h2>
            {appointments.length === 0 ? (
              <p className="text-sm text-slate-400">No appointments booked yet.</p>
            ) : (
              <div className="divide-y divide-white/10">
                {appointments.map((a) => (
                  <div key={a.id} className="py-3 flex flex-wrap items-center justify-between gap-3 text-sm">
                    <div>
                      <div className="font-medium">{a.lead_name || `Lead #${a.lead_id}`} {a.lead_company ? `· ${a.lead_company}` : ""}</div>
                      <div className="font-mono text-xs text-slate-400">{new Date(a.starts_at).toLocaleString()}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`px-2.5 py-1 rounded-full text-xs border capitalize ${STATUS_BADGE[a.status] || STATUS_BADGE.booked}`}>
                        {a.status}
                      </span>
                      <select
                        aria-label={`Change status for appointment ${a.id}`}
                        value={a.status}
                        onChange={(e) => updateStatus(a.id, e.target.value)}
                        className="px-2 py-1 rounded-lg bg-white/5 border border-white/10 text-xs"
                      >
                        <option value="booked">booked</option>
                        <option value="completed">completed</option>
                        <option value="rescheduled">rescheduled</option>
                        <option value="cancelled">cancelled</option>
                      </select>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
