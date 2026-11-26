import {
  PhoneCall,
  Users,
  History,
  Calendar,
  BarChart3,
  BookOpen,
  Settings,
  Search,
  Sun,
  Moon,
  User,
} from "lucide-react";

export const NAV_ITEMS = [
  { id: "live", label: "Live Call", Icon: PhoneCall },
  { id: "leads", label: "Leads", Icon: Users },
  { id: "calls", label: "Calls", Icon: History },
  { id: "appointments", label: "Appointments", Icon: Calendar },
  { id: "insights", label: "Insights", Icon: BarChart3 },
  { id: "kb", label: "Knowledge Base", Icon: BookOpen },
  { id: "settings", label: "Settings", Icon: Settings },
];

const MOBILE_NAV_LABELS = {
  live: "Live",
  leads: "Leads",
  calls: "Calls",
  appointments: "Appts",
  insights: "Insights",
  kb: "KB",
  settings: "Settings",
};

export function Layout({
  activeTab,
  onTabChange,
  darkMode,
  onToggleTheme,
  tenants,
  tenantId,
  onTenantChange,
  searchQuery,
  onSearchChange,
  disableTenantSwitch,
  children,
}) {
  const shellBg = darkMode ? "bg-[#090d16] text-slate-100" : "bg-slate-50 text-slate-900";
  const chromeBg = darkMode ? "bg-[#0d1320]/90 border-white/10" : "bg-white/90 border-slate-200";
  const inputBg = darkMode
    ? "bg-white/5 border-white/10 text-slate-100 placeholder:text-slate-500"
    : "bg-slate-100 border-slate-200 text-slate-900 placeholder:text-slate-400";

  return (
    <div className={`min-h-screen flex flex-col md:flex-row ${shellBg} transition-colors duration-200`}>
      {/* Desktop Left Icon Sidebar */}
      <aside
        aria-label="Primary navigation"
        className={`hidden md:flex md:w-20 lg:w-56 flex-col border-r shrink-0 ${chromeBg} backdrop-blur-md`}
      >
        <div className="h-16 px-4 flex items-center gap-3 border-b border-inherit">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-indigo-500 to-cyan-400 flex items-center justify-center text-white font-bold text-sm shrink-0">
            AI
          </div>
          <span className="hidden lg:block font-semibold text-sm tracking-tight truncate">
            Studio
          </span>
        </div>

        <nav className="flex-1 p-3 space-y-1">
          {NAV_ITEMS.map(({ id, label, Icon }) => {
            const active = activeTab === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => onTabChange(id)}
                aria-current={active ? "page" : undefined}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition duration-150 focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                  active
                    ? "bg-gradient-to-r from-indigo-500/20 to-cyan-500/15 text-indigo-400 border border-indigo-500/30"
                    : "text-slate-400 hover:text-slate-200 hover:bg-white/5 border border-transparent"
                }`}
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span className="hidden lg:inline truncate">{label}</span>
              </button>
            );
          })}
        </nav>
      </aside>

      {/* Main Column */}
      <div className="flex-1 flex flex-col min-w-0 pb-16 md:pb-0">
        {/* Top Bar */}
        <header
          className={`h-16 px-4 md:px-6 border-b flex items-center justify-between gap-4 sticky top-0 z-20 backdrop-blur-md ${chromeBg}`}
        >
          <div className="flex items-center gap-3 min-w-0">
            <select
              aria-label="Select tenant"
              value={tenantId}
              disabled={disableTenantSwitch}
              onChange={(e) => onTenantChange(Number(e.target.value))}
              className={`px-3 py-1.5 rounded-xl text-sm border focus:outline-none focus:ring-2 focus:ring-indigo-500 ${inputBg}`}
            >
              {tenants.map((t) => (
                <option key={t.id} value={t.id} className={darkMode ? "bg-[#111827]" : "bg-white"}>
                  {t.name}
                </option>
              ))}
            </select>

            <div className="relative hidden sm:block w-56 md:w-72">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="search"
                aria-label="Search workspace"
                value={searchQuery}
                onChange={(e) => onSearchChange(e.target.value)}
                placeholder="Search leads, calls…"
                className={`w-full pl-9 pr-3 py-1.5 rounded-xl text-sm border focus:outline-none focus:ring-2 focus:ring-indigo-500 ${inputBg}`}
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label="Toggle theme"
              onClick={onToggleTheme}
              className="p-2 rounded-xl border border-white/10 hover:bg-white/10 transition focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              {darkMode ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>

            <div className="flex items-center gap-2 pl-2 pr-3 py-1.5 rounded-xl border border-white/10 bg-white/5 text-sm">
              <User className="w-4 h-4 text-indigo-400" />
              <span className="hidden sm:inline text-xs font-medium">Sales Admin</span>
            </div>
          </div>
        </header>

        <main className="flex-1 p-4 md:p-6 max-w-7xl w-full mx-auto">{children}</main>
      </div>

      {/* Mobile Bottom Tab Bar */}
      <nav
        aria-label="Mobile navigation"
        className={`md:hidden fixed bottom-0 inset-x-0 h-16 border-t flex items-center justify-around px-1 z-30 backdrop-blur-md ${chromeBg}`}
      >
        {NAV_ITEMS.map(({ id, label, Icon }) => {
          const active = activeTab === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => onTabChange(id)}
              aria-label={label}
              className={`flex min-w-0 flex-1 flex-col items-center gap-1 px-1 py-1 rounded-lg text-[9px] ${
                active ? "text-indigo-400" : "text-slate-400"
              }`}
            >
              <Icon className="w-4 h-4" />
              <span>{MOBILE_NAV_LABELS[id] || label}</span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}
