import { useEffect, useState } from "react";
import { Save } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export function SettingsPage({ tenantId, tenants, onUpdated, darkMode }) {
  const current = tenants.find((t) => t.id === tenantId);
  const cfg = current?.agent_config || {};

  const [agentName, setAgentName] = useState(cfg.agent_name || "Aria");
  const [greeting, setGreeting] = useState(cfg.greeting || "");
  const [voice, setVoice] = useState(cfg.voice_id || "EXAVITQu4vr4xnSDxMaL");
  const [language, setLanguage] = useState(cfg.language || "en");
  const [hotThreshold, setHotThreshold] = useState(cfg.hot_threshold ?? 70);
  const [warmThreshold, setWarmThreshold] = useState(cfg.warm_threshold ?? 40);
  const [businessHours, setBusinessHours] = useState(cfg.business_hours || "09:00-18:00");
  const [savedMsg, setSavedMsg] = useState("");

  useEffect(() => {
    const c = (tenants.find((t) => t.id === tenantId)?.agent_config) || {};
    setAgentName(c.agent_name || "Aria");
    setGreeting(c.greeting || "");
    setVoice(c.voice_id || "EXAVITQu4vr4xnSDxMaL");
    setLanguage(c.language || "en");
    setHotThreshold(c.hot_threshold ?? 70);
    setWarmThreshold(c.warm_threshold ?? 40);
    setBusinessHours(c.business_hours || "09:00-18:00");
  }, [tenantId, tenants]);

  async function save(e) {
    e.preventDefault();
    setSavedMsg("");
    const res = await fetch(`${API_BASE}/tenants/${tenantId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agent_config: {
          agent_name: agentName,
          greeting,
          voice_id: voice,
          language,
          hot_threshold: Number(hotThreshold),
          warm_threshold: Number(warmThreshold),
          business_hours: businessHours,
        },
      }),
    });
    if (res.ok) {
      setSavedMsg("Settings saved.");
      onUpdated();
    }
  }

  const cardClass = darkMode ? "bg-[#111827]/90 border-white/10" : "bg-white border-slate-200 shadow-sm";
  const inputClass = "w-full px-3 py-2 rounded-xl bg-white/5 border border-white/10 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500";

  return (
    <div className="max-w-2xl space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-slate-400">Configure voice agent persona, language, scoring thresholds, and business hours.</p>
      </div>

      <form onSubmit={save} className={`rounded-2xl border p-6 space-y-4 ${cardClass}`}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="space-y-1 text-sm">
            <span className="text-xs text-slate-400">Agent Name</span>
            <input value={agentName} onChange={(e) => setAgentName(e.target.value)} className={inputClass} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-xs text-slate-400">Language</span>
            <select value={language} onChange={(e) => setLanguage(e.target.value)} className={inputClass}>
              <option value="en">English (en)</option>
              <option value="hi">Hindi (hi)</option>
            </select>
          </label>
        </div>

        <label className="block space-y-1 text-sm">
          <span className="text-xs text-slate-400">Greeting</span>
          <input value={greeting} onChange={(e) => setGreeting(e.target.value)} className={inputClass} />
        </label>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="space-y-1 text-sm">
            <span className="text-xs text-slate-400">ElevenLabs Voice ID</span>
            <input value={voice} onChange={(e) => setVoice(e.target.value)} className={`${inputClass} font-mono`} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-xs text-slate-400">Business Hours (UTC)</span>
            <input value={businessHours} onChange={(e) => setBusinessHours(e.target.value)} className={`${inputClass} font-mono`} />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <label className="space-y-1 text-sm">
            <span className="text-xs text-slate-400">Hot Threshold</span>
            <input type="number" value={hotThreshold} onChange={(e) => setHotThreshold(e.target.value)} className={`${inputClass} font-mono`} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-xs text-slate-400">Warm Threshold</span>
            <input type="number" value={warmThreshold} onChange={(e) => setWarmThreshold(e.target.value)} className={`${inputClass} font-mono`} />
          </label>
        </div>

        <div className="flex items-center gap-3 pt-2">
          <button type="submit" className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-indigo-500 to-cyan-500 text-white text-sm font-medium">
            <Save className="w-4 h-4" /> Save Settings
          </button>
          {savedMsg && <span className="text-xs text-emerald-400">{savedMsg}</span>}
        </div>
      </form>
    </div>
  );
}
