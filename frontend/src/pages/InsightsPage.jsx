import { useEffect, useState } from "react";
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";
import { AlertCircle } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const PIE_COLORS = ["#fb7185", "#f59e0b", "#38bdf8"];

export function InsightsPage({ tenantId, darkMode }) {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const cardClass = darkMode ? "bg-[#111827]/90 border-white/10" : "bg-white border-slate-200 shadow-sm";

  useEffect(() => {
    setLoading(true);
    setError("");
    fetch(`${API_BASE}/analytics?tenant_id=${tenantId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("Failed to load analytics"))))
      .then(setStats)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [tenantId]);

  if (loading) return <div className="h-64 rounded-2xl bg-white/5 animate-pulse" />;
  if (error) {
    return (
      <div className="p-4 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-400 flex items-center gap-2 text-sm">
        <AlertCircle className="w-4 h-4" /> {error}
      </div>
    );
  }
  if (!stats) return null;

  const pieData = [
    { name: "Hot", value: stats.lead_counts?.hot || 0 },
    { name: "Warm", value: stats.lead_counts?.warm || 0 },
    { name: "Cold", value: stats.lead_counts?.cold || 0 },
  ];

  const kpis = [
    ["Total Calls", stats.total_calls, "All recorded voice and chat conversations."],
    ["Qualified", stats.qualified_conversations, "Leads scoring Warm (40+) or Hot (70+)."],
    ["Hot Leads", stats.lead_counts?.hot || 0, "High-intent prospects ready for immediate follow-up."],
    ["Booked", stats.appointments_booked, "Confirmed or rescheduled demo meetings."],
    ["Booking Rate", `${stats.booking_rate}%`, "Share of calls converting to a booked meeting."],
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Insights</h1>
        <p className="text-sm text-slate-400">Live pipeline performance, call volume, and customer objections.</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        {kpis.map(([label, value, takeaway]) => (
          <div key={label} className={`rounded-2xl border p-4 space-y-1.5 ${cardClass}`}>
            <div className="text-xs uppercase tracking-wider text-slate-400">{label}</div>
            <div className="text-2xl font-mono font-semibold">{value}</div>
            <p className="text-xs text-slate-400">{takeaway}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className={`rounded-2xl border p-5 space-y-3 ${cardClass}`}>
          <h2 className="text-sm font-semibold">Lead Distribution</h2>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80}>
                  {pieData.map((_, idx) => (
                    <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-slate-400">Hot leads need immediate sales follow-up; Warm leads need nurturing.</p>
        </div>

        <div className={`rounded-2xl border p-5 space-y-3 ${cardClass}`}>
          <h2 className="text-sm font-semibold">Calls Per Day</h2>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={stats.calls_per_day || []}>
                <XAxis dataKey="date" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} allowDecimals={false} />
                <Tooltip />
                <Line type="monotone" dataKey="count" stroke="#38bdf8" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-slate-400">Daily conversation trend across voice and chat sessions.</p>
        </div>

        <div className={`rounded-2xl border p-5 space-y-3 ${cardClass}`}>
          <h2 className="text-sm font-semibold">Top Requirements & Objections</h2>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={[...(stats.top_requirements || []), ...(stats.top_objections || [])].slice(0, 6)}>
                <XAxis dataKey="label" stroke="#94a3b8" fontSize={11} />
                <YAxis stroke="#94a3b8" fontSize={12} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill="#6366f1" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-slate-400">Most frequent prospect needs and blockers captured by call summaries.</p>
        </div>

        <div className={`rounded-2xl border p-5 space-y-3 ${cardClass}`}>
          <h2 className="text-sm font-semibold">Sentiment Breakdown</h2>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stats.sentiment_breakdown || []}>
                <XAxis dataKey="sentiment" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill="#22d3ee" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-slate-400">Track customer tone to spot hesitant or frustrated conversations early.</p>
        </div>
      </div>
    </div>
  );
}
