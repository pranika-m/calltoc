import { useEffect, useState } from "react";
import { Layout } from "./components/Layout";
import { LiveCallConsole } from "./pages/LiveCallConsole";
import { LeadsPage } from "./pages/LeadsPage";
import { CallsPage } from "./pages/CallsPage";
import { AppointmentsPage } from "./pages/AppointmentsPage";
import { InsightsPage } from "./pages/InsightsPage";
import { KnowledgeBasePage } from "./pages/KnowledgeBasePage";
import { SettingsPage } from "./pages/SettingsPage";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export default function App() {
  const [darkMode, setDarkMode] = useState(true);
  const [activeTab, setActiveTab] = useState("live");
  const [tenants, setTenants] = useState([
    { id: 1, name: "ApexCRM", agent_config: {} },
    { id: 2, name: "NovaCloud", agent_config: {} },
  ]);
  const [tenantId, setTenantId] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    document.documentElement.classList.toggle("dark", darkMode);
  }, [darkMode]);

  function loadTenants() {
    fetch(`${API_BASE}/tenants`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) setTenants(data);
      })
      .catch(() => {});
  }

  useEffect(() => {
    loadTenants();
  }, []);

  return (
    <Layout
      activeTab={activeTab}
      onTabChange={setActiveTab}
      darkMode={darkMode}
      onToggleTheme={() => setDarkMode((d) => !d)}
      tenants={tenants}
      tenantId={tenantId}
      onTenantChange={setTenantId}
      searchQuery={searchQuery}
      onSearchChange={setSearchQuery}
      disableTenantSwitch={false}
    >
      {activeTab === "live" && <LiveCallConsole tenantId={tenantId} darkMode={darkMode} />}
      {activeTab === "leads" && <LeadsPage tenantId={tenantId} searchQuery={searchQuery} darkMode={darkMode} />}
      {activeTab === "calls" && <CallsPage tenantId={tenantId} darkMode={darkMode} />}
      {activeTab === "appointments" && <AppointmentsPage tenantId={tenantId} darkMode={darkMode} />}
      {activeTab === "insights" && <InsightsPage tenantId={tenantId} darkMode={darkMode} />}
      {activeTab === "kb" && <KnowledgeBasePage darkMode={darkMode} />}
      {activeTab === "settings" && (
        <SettingsPage tenantId={tenantId} tenants={tenants} onUpdated={loadTenants} darkMode={darkMode} />
      )}
    </Layout>
  );
}
