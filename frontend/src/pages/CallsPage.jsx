import { useEffect, useState } from "react";
import { Clock, Wrench, FileText, AlertCircle } from "lucide-react";
import { SentimentChip } from "../components/ScoreGauge";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export function CallsPage({ tenantId, darkMode }) {
  const [calls, setCalls] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const cardClass = darkMode ? "bg-[#111827]/90 border-white/10" : "bg-white border-slate-200 shadow-sm";

  useEffect(() => {
    setLoading(true);
    setError("");
    fetch(`${API_BASE}/calls?tenant_id=${tenantId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("Failed to load calls"))))
      .then((data) => {
        setCalls(data);
        if (data.length > 0) loadDetail(data[0].id);
        else setSelected(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [tenantId]);

  async function loadDetail(callId) {
    const res = await fetch(`${API_BASE}/calls/${callId}?tenant_id=${tenantId}`);
    if (res.ok) setSelected(await res.json());
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Call History</h1>
        <p className="text-sm text-slate-400">Transcript timelines, structured AI summaries, and tool executions.</p>
      </div>

      {error && (
        <div className="p-4 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-400 flex items-center gap-2 text-sm">
          <AlertCircle className="w-4 h-4" /> {error}
        </div>
      )}

      {loading ? (
        <div className="h-48 rounded-2xl bg-white/5 animate-pulse" />
      ) : calls.length === 0 ? (
        <div className={`rounded-2xl border p-10 text-center text-slate-400 ${cardClass}`}>
          No calls recorded yet.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          <div className={`lg:col-span-5 rounded-2xl border divide-y divide-white/10 max-h-[600px] overflow-y-auto ${cardClass}`}>
            {calls.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => loadDetail(c.id)}
                className={`w-full text-left p-4 hover:bg-white/5 transition space-y-2 ${
                  selected?.call?.id === c.id ? "bg-indigo-500/10" : ""
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-sm">{c.lead_name || `Call #${c.id}`}</span>
                  <span className="font-mono text-xs text-slate-400 flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5" /> {c.duration ?? 0}s
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <SentimentChip sentiment={c.sentiment || "neutral"} />
                  <span className="font-mono text-cyan-400">Score {c.lead_score ?? 0}</span>
                  <span className="capitalize text-slate-400">{c.status}</span>
                </div>
              </button>
            ))}
          </div>

          <div className={`lg:col-span-7 rounded-2xl border p-5 space-y-5 ${cardClass}`}>
            {!selected ? (
              <p className="text-sm text-slate-400">Select a call to view its transcript and summary.</p>
            ) : (
              <>
                <div className="rounded-xl bg-white/5 border border-white/10 p-4 space-y-3">
                  <h2 className="text-sm font-semibold flex items-center gap-2">
                    <FileText className="w-4 h-4 text-indigo-400" /> Structured Summary
                  </h2>
                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div><span className="text-slate-400">Requirement:</span> {selected.summary?.requirement || "—"}</div>
                    <div><span className="text-slate-400">Budget:</span> {selected.summary?.insights?.budget || "—"}</div>
                    <div><span className="text-slate-400">Timeline:</span> {selected.summary?.insights?.timeline || "—"}</div>
                    <div><span className="text-slate-400">Objection:</span> {selected.summary?.objection || "None"}</div>
                    <div className="col-span-2"><span className="text-slate-400">Next Action:</span> {selected.summary?.next_action || "—"}</div>
                  </div>
                </div>

                {selected.tool_actions?.length > 0 && (
                  <div className="space-y-2">
                    <h3 className="text-xs uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                      <Wrench className="w-3.5 h-3.5" /> Agent Tool Actions
                    </h3>
                    <div className="flex flex-wrap gap-2">
                      {selected.tool_actions.map((act, idx) => (
                        <span key={idx} className="px-2.5 py-1 rounded-lg bg-cyan-500/10 border border-cyan-500/20 font-mono text-xs text-cyan-300">
                          {act.tool}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div className="space-y-2.5 max-h-80 overflow-y-auto pr-1">
                  <h3 className="text-xs uppercase tracking-wider text-slate-400">Audio Transcript Timeline</h3>
                  {selected.messages.map((m) => (
                    <div key={m.id} className="p-3 rounded-xl bg-white/5 border border-white/10 text-xs font-mono">
                      <span className="text-slate-400 mr-2">[{new Date(m.created_at).toLocaleTimeString()}] {m.role}:</span>
                      <span>{m.text}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
