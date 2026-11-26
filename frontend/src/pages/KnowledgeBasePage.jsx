import { useEffect, useState } from "react";
import { RefreshCw, Send, Save, BookOpen } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export function KnowledgeBasePage({ darkMode }) {
  const [docs, setDocs] = useState([]);
  const [selectedName, setSelectedName] = useState("");
  const [content, setContent] = useState("");
  const [statusMsg, setStatusMsg] = useState("");
  const [question, setQuestion] = useState("");
  const [testResult, setTestResult] = useState(null);
  const [testing, setTesting] = useState(false);

  const cardClass = darkMode ? "bg-[#111827]/90 border-white/10" : "bg-white border-slate-200 shadow-sm";

  async function loadDocs() {
    const res = await fetch(`${API_BASE}/rag/documents`);
    if (res.ok) {
      const list = await res.json();
      setDocs(list);
      if (list.length > 0 && !selectedName) {
        setSelectedName(list[0].filename);
        setContent(list[0].content);
      }
    }
  }

  useEffect(() => {
    loadDocs();
  }, []);

  async function saveDoc() {
    if (!selectedName) return;
    setStatusMsg("Saving and re-indexing…");
    const res = await fetch(`${API_BASE}/rag/documents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: selectedName, content }),
    });
    if (res.ok) {
      const data = await res.json();
      setStatusMsg(`Saved ${data.filename} (${data.chunks_indexed} chunks indexed).`);
      loadDocs();
    }
  }

  async function reindex() {
    setStatusMsg("Re-indexing…");
    const res = await fetch(`${API_BASE}/rag/reindex`, { method: "POST" });
    if (res.ok) {
      const data = await res.json();
      setStatusMsg(`Indexed ${data.chunks_indexed} chunks.`);
    }
  }

  async function askQuestion(e) {
    e.preventDefault();
    if (!question.trim()) return;
    setTesting(true);
    try {
      const res = await fetch(`${API_BASE}/rag/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: question }),
      });
      if (res.ok) setTestResult(await res.json());
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Knowledge Base</h1>
          <p className="text-sm text-slate-400">Edit markdown documents, re-index ChromaDB, and test grounded RAG answers.</p>
        </div>
        <button
          type="button"
          onClick={reindex}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-indigo-500 to-cyan-500 text-white text-sm font-medium"
        >
          <RefreshCw className="w-4 h-4" /> Re-index
        </button>
      </div>

      {statusMsg && <p className="text-xs text-cyan-400 font-mono">{statusMsg}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className={`lg:col-span-7 rounded-2xl border p-5 space-y-4 ${cardClass}`}>
          <div className="flex flex-wrap gap-2">
            {docs.map((d) => (
              <button
                key={d.filename}
                type="button"
                onClick={() => {
                  setSelectedName(d.filename);
                  setContent(d.content);
                }}
                className={`px-3 py-1.5 rounded-xl text-xs font-mono border ${
                  selectedName === d.filename ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-300" : "border-white/10"
                }`}
              >
                {d.filename}
              </button>
            ))}
          </div>

          <textarea
            aria-label="Document markdown editor"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={14}
            className="w-full p-3 rounded-xl bg-white/5 border border-white/10 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />

          <button
            type="button"
            onClick={saveDoc}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-white/15 hover:bg-white/10 text-sm"
          >
            <Save className="w-4 h-4" /> Save & Re-index
          </button>
        </div>

        <div className={`lg:col-span-5 rounded-2xl border p-5 space-y-4 ${cardClass}`}>
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <BookOpen className="w-4 h-4 text-cyan-400" /> Test Question Box
          </h2>

          <form onSubmit={askQuestion} className="flex gap-2">
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about pricing, onboarding, or security…"
              className="flex-1 px-3 py-2 rounded-xl bg-white/5 border border-white/10 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <button
              type="submit"
              disabled={testing}
              className="px-4 py-2 rounded-xl bg-indigo-500 text-white text-sm inline-flex items-center gap-1.5"
            >
              <Send className="w-4 h-4" /> Ask
            </button>
          </form>

          {testResult && (
            <div className="space-y-3">
              <div className="p-3.5 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-sm">
                <div className="text-[11px] uppercase text-indigo-300 mb-1">Answer</div>
                <p>{testResult.answer}</p>
              </div>
              <div className="space-y-2">
                <div className="text-xs uppercase text-slate-400">Retrieved Chunks</div>
                {testResult.chunks?.length === 0 ? (
                  <p className="text-xs text-slate-500">No chunks met the relevance threshold.</p>
                ) : (
                  testResult.chunks?.map((c, idx) => (
                    <div key={idx} className="p-3 rounded-xl bg-white/5 border border-white/10 text-xs space-y-1">
                      <div className="flex justify-between font-mono text-cyan-400">
                        <span>{c.source}</span>
                        <span>sim {c.similarity}</span>
                      </div>
                      <p className="text-slate-300">{c.text}</p>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
