import { useEffect, useState } from "react";
import { LayoutGrid, List, X, Calendar, MessageSquare, AlertCircle } from "lucide-react";
import { CategoryBadge, SentimentChip } from "../components/ScoreGauge";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export function LeadsPage({ tenantId, searchQuery, darkMode }) {
  const [leads, setLeads] = useState([]);
  const [view, setView] = useState("table");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [sentimentFilter, setSentimentFilter] = useState("");
  const [dateFilter, setDateFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedLead, setSelectedLead] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const cardClass = darkMode ? "bg-[#111827]/90 border-white/10" : "bg-white border-slate-200 shadow-sm";
  const inputClass = darkMode ? "bg-white/5 border-white/10 text-slate-100" : "bg-slate-100 border-slate-200 text-slate-900";

  async function loadLeads() {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ tenant_id: String(tenantId) });
      if (categoryFilter) params.set("category", categoryFilter);
      if (sentimentFilter) params.set("sentiment", sentimentFilter);
      if (searchQuery) params.set("search", searchQuery);
      const res = await fetch(`${API_BASE}/leads?${params.toString()}`);
      if (!res.ok) throw new Error("Failed to load leads");
      setLeads(await res.json());
    } catch (err) {
      setError(err.message || "Unable to fetch leads");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadLeads();
  }, [tenantId, categoryFilter, sentimentFilter, searchQuery]);

  async function openDrawer(leadId) {
    setDetailLoading(true);
    try {
      const res = await fetch(`${API_BASE}/leads/${leadId}?tenant_id=${tenantId}`);
      if (res.ok) setSelectedLead(await res.json());
    } finally {
      setDetailLoading(false);
    }
  }

  async function moveLeadCategory(leadId, newCategory) {
    setLeads((prev) => prev.map((l) => (l.id === leadId ? { ...l, category: newCategory } : l)));
    await fetch(`${API_BASE}/leads/${leadId}?tenant_id=${tenantId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category: newCategory }),
    });
  }

  const visibleLeads = dateFilter
    ? leads.filter((l) => (l.created_at || "").slice(0, 10) >= dateFilter)
    : leads;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Leads</h1>
          <p className="text-sm text-slate-400">Qualified prospects scored automatically by Python rules.</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Filter by category"
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className={`px-3 py-2 rounded-xl text-sm border ${inputClass}`}
          >
            <option value="">All Categories</option>
            <option value="hot">Hot</option>
            <option value="warm">Warm</option>
            <option value="cold">Cold</option>
          </select>

          <select
            aria-label="Filter by sentiment"
            value={sentimentFilter}
            onChange={(e) => setSentimentFilter(e.target.value)}
            className={`px-3 py-2 rounded-xl text-sm border ${inputClass}`}
          >
            <option value="">All Sentiments</option>
            <option value="positive">Positive</option>
            <option value="interested">Interested</option>
            <option value="neutral">Neutral</option>
            <option value="hesitant">Hesitant</option>
            <option value="frustrated">Frustrated</option>
          </select>

          <input
            type="date"
            aria-label="Filter from date"
            value={dateFilter}
            onChange={(e) => setDateFilter(e.target.value)}
            className={`px-3 py-2 rounded-xl text-sm border ${inputClass}`}
          />

          <div className="inline-flex rounded-xl border border-white/10 overflow-hidden">
            <button
              type="button"
              onClick={() => setView("table")}
              aria-label="Table view"
              className={`px-3 py-2 text-sm inline-flex items-center gap-1.5 ${view === "table" ? "bg-indigo-500 text-white" : "hover:bg-white/5"}`}
            >
              <List className="w-4 h-4" /> Table
            </button>
            <button
              type="button"
              onClick={() => setView("kanban")}
              aria-label="Kanban view"
              className={`px-3 py-2 text-sm inline-flex items-center gap-1.5 ${view === "kanban" ? "bg-indigo-500 text-white" : "hover:bg-white/5"}`}
            >
              <LayoutGrid className="w-4 h-4" /> Kanban
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-400 flex items-center gap-2 text-sm">
          <AlertCircle className="w-4 h-4" /> {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((n) => (
            <div key={n} className="h-14 rounded-xl bg-white/5 animate-pulse" />
          ))}
        </div>
      ) : visibleLeads.length === 0 ? (
        <div className={`rounded-2xl border p-10 text-center text-slate-400 ${cardClass}`}>
          No leads yet. Start a voice call in the Live Call Console to capture and score your first lead.
        </div>
      ) : view === "table" ? (
        <div className={`rounded-2xl border overflow-x-auto ${cardClass}`}>
          <table className="w-full text-sm text-left">
            <thead className="text-xs uppercase text-slate-400 border-b border-white/10">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Company</th>
                <th className="px-4 py-3">Score</th>
                <th className="px-4 py-3">Category</th>
                <th className="px-4 py-3">Sentiment</th>
                <th className="px-4 py-3">Last Call</th>
                <th className="px-4 py-3">Next Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10">
              {visibleLeads.map((lead) => (
                <tr
                  key={lead.id}
                  onClick={() => openDrawer(lead.id)}
                  className="hover:bg-white/5 cursor-pointer transition"
                >
                  <td className="px-4 py-3 font-medium">{lead.name || `Lead #${lead.id}`}</td>
                  <td className="px-4 py-3 text-slate-400">{lead.company || "—"}</td>
                  <td className="px-4 py-3 w-36">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 rounded-full bg-white/10 overflow-hidden">
                        <div className="h-full bg-gradient-to-r from-indigo-500 to-cyan-400" style={{ width: `${lead.score}%` }} />
                      </div>
                      <span className="font-mono text-xs">{lead.score}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3"><CategoryBadge category={lead.category} /></td>
                  <td className="px-4 py-3"><SentimentChip sentiment={lead.sentiment} /></td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-400">
                    {lead.last_call ? new Date(lead.last_call).toLocaleDateString() : "—"}
                  </td>
                  <td className="px-4 py-3 text-slate-300 max-w-xs truncate">{lead.next_action || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {["hot", "warm", "cold"].map((col) => {
            const colLeads = visibleLeads.filter((l) => l.category === col);
            return (
              <div
                key={col}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  const id = Number(e.dataTransfer.getData("text/plain"));
                  if (id) moveLeadCategory(id, col);
                }}
                className={`rounded-2xl border p-4 space-y-3 min-h-[360px] ${cardClass}`}
              >
                <div className="flex items-center justify-between">
                  <CategoryBadge category={col} />
                  <span className="font-mono text-xs text-slate-400">{colLeads.length}</span>
                </div>
                {colLeads.map((lead) => (
                  <div
                    key={lead.id}
                    draggable
                    onDragStart={(e) => e.dataTransfer.setData("text/plain", String(lead.id))}
                    onClick={() => openDrawer(lead.id)}
                    className="p-3.5 rounded-xl bg-white/5 border border-white/10 hover:border-indigo-400/50 cursor-grab space-y-2 transition"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-sm">{lead.name || `Lead #${lead.id}`}</span>
                      <span className="font-mono text-xs text-cyan-400">{lead.score}/100</span>
                    </div>
                    <p className="text-xs text-slate-400 truncate">{lead.company || lead.requirement || "No details yet"}</p>
                    <div className="flex items-center justify-between pt-1">
                      <SentimentChip sentiment={lead.sentiment} />
                    </div>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}

      {/* Side Drawer */}
      {(selectedLead || detailLoading) && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-xs">
          <div className={`w-full max-w-lg h-full overflow-y-auto p-6 border-l space-y-6 ${cardClass}`}>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">
                {detailLoading ? "Loading…" : selectedLead.lead.name || `Lead #${selectedLead.lead.id}`}
              </h2>
              <button type="button" aria-label="Close drawer" onClick={() => setSelectedLead(null)} className="p-1.5 rounded-lg hover:bg-white/10">
                <X className="w-5 h-5" />
              </button>
            </div>

            {selectedLead && (
              <>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  {[
                    ["Company", selectedLead.lead.company],
                    ["Budget", selectedLead.lead.budget],
                    ["Timeline", selectedLead.lead.timeline],
                    ["Requirement", selectedLead.lead.requirement],
                  ].map(([lbl, val]) => (
                    <div key={lbl} className="p-3 rounded-xl bg-white/5 border border-white/10">
                      <div className="text-[11px] uppercase text-slate-400">{lbl}</div>
                      <div className="mt-0.5 font-medium">{val || "—"}</div>
                    </div>
                  ))}
                </div>

                <div className="space-y-2">
                  <h3 className="text-sm font-semibold flex items-center gap-2"><Calendar className="w-4 h-4 text-cyan-400" /> Appointments</h3>
                  {selectedLead.appointments.length === 0 ? (
                    <p className="text-xs text-slate-400">No appointments booked.</p>
                  ) : (
                    selectedLead.appointments.map((a) => (
                      <div key={a.id} className="p-3 rounded-xl bg-white/5 border border-white/10 flex justify-between text-xs">
                        <span className="font-mono">{new Date(a.starts_at).toLocaleString()}</span>
                        <span className="capitalize text-emerald-400">{a.status}</span>
                      </div>
                    ))
                  )}
                </div>

                <div className="space-y-3">
                  <h3 className="text-sm font-semibold flex items-center gap-2"><MessageSquare className="w-4 h-4 text-indigo-400" /> Call Transcripts</h3>
                  {selectedLead.calls.map((c) => (
                    <div key={c.call.id} className="p-3 rounded-xl bg-white/5 border border-white/10 space-y-2">
                      <div className="flex justify-between text-xs text-slate-400">
                        <span>Call #{c.call.id}</span>
                        <span>{new Date(c.call.started_at).toLocaleString()}</span>
                      </div>
                      {c.messages.map((m) => (
                        <p key={m.id} className="text-xs font-mono leading-relaxed">
                          <strong className="uppercase text-slate-400 mr-1.5">{m.role}:</strong>{m.text}
                        </p>
                      ))}
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
