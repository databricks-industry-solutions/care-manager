import { useEffect, useState } from "react";
import { Routes, Route, Outlet, useNavigate, useLocation } from "react-router-dom";
import { ListChecks, Activity, LayoutGrid, Users, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { ThemeToggle } from "./theme";
import Worklist from "./screens/Worklist";
import PatientDetailScreen from "./screens/PatientDetail";
import LogOutreach from "./screens/LogOutreach";
import ActivityScreen from "./screens/Activity";
import PanelScreen from "./screens/Panel";

const TABS: { to: string; label: string; icon: LucideIcon }[] = [
  { to: "/", label: "Today", icon: ListChecks },
  { to: "/panel", label: "Caseload", icon: LayoutGrid },
  { to: "/activity", label: "Activity", icon: Activity },
];

// The mobile and desktop shells are structurally different (single-screen +
// bottom nav vs. sidebar + master/detail two-pane), so we branch in JS on the
// viewport rather than forcing one DOM tree to morph via CSS alone. Breakpoint
// matches Tailwind's `md` (768px), which the per-component `md:` utilities also
// key off, so the two never disagree.
function useIsDesktop() {
  const query = "(min-width: 768px)";
  const [isDesktop, setIsDesktop] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(query).matches : false
  );
  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setIsDesktop(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return isDesktop;
}

export default function App() {
  return useIsDesktop() ? <DesktopShell /> : <MobileShell />;
}

/* ------------------------------- mobile ---------------------------------- */
// Phone layout: one screen at a time in a centered column with a fixed bottom
// tab bar. This is the hero experience of the Provider Genie mobile demo and is
// left exactly as it was.
function MobileShell() {
  return (
    <div className="mx-auto flex h-full max-w-md flex-col bg-clinical-bg">
      {/* Pad the scroll area past the fixed bottom nav (incl. the home-indicator
          safe area) so the last row is never hidden behind it. */}
      <div className="flex-1 overflow-y-auto" style={{ paddingBottom: "calc(var(--nav-h) + 8px)" }}>
        <Routes>
          <Route path="/" element={<Worklist />} />
          <Route path="/panel" element={<PanelScreen />} />
          <Route path="/activity" element={<ActivityScreen />} />
          <Route path="/patient/:id" element={<PatientDetailScreen />} />
          <Route path="/patient/:id/outreach" element={<LogOutreach />} />
        </Routes>
      </div>
      <BottomNav />
    </div>
  );
}

function BottomNav() {
  const nav = useNavigate();
  const loc = useLocation();
  return (
    <nav
      className="fixed bottom-0 left-1/2 z-20 flex w-full max-w-md -translate-x-1/2 border-t border-clinical-line bg-clinical-card"
      // Extend the bottom padding past the iPhone home indicator.
      style={{ paddingBottom: "var(--safe-bottom)" }}
    >
      {TABS.map(({ to, label, icon: Icon }) => {
        const active = loc.pathname === to;
        return (
          <button
            key={to}
            onClick={() => nav(to)}
            aria-current={active ? "page" : undefined}
            className={`relative flex flex-1 flex-col items-center gap-0.5 py-3 text-xs font-medium transition active:scale-95 ${
              active ? "text-clinical-accent" : "text-clinical-muted"
            }`}
          >
            {active && (
              <span className="absolute inset-x-5 top-0 h-0.5 rounded-full bg-clinical-accent" />
            )}
            <Icon size={22} />
            {label}
          </button>
        );
      })}
    </nav>
  );
}

/* ------------------------------- desktop --------------------------------- */
// Desktop layout: a persistent left sidebar for section nav, plus a two-pane
// master/detail for the worklist flow (the list stays on the left while a
// patient's detail fills the right). Caseload and Activity render as a single
// wide pane. Every screen component is reused verbatim; only the shell changes.
function DesktopShell() {
  return (
    <div className="flex h-full bg-clinical-bg">
      <Sidebar />
      <div className="flex h-full min-w-0 flex-1 flex-col">
        <Routes>
          {/* Master/detail: Worklist on the left, route-driven detail on the right. */}
          <Route element={<WorklistFrame />}>
            <Route path="/" element={<DetailEmpty />} />
            <Route path="/patient/:id" element={<PatientDetailScreen />} />
            <Route path="/patient/:id/outreach" element={<LogOutreach />} />
          </Route>
          <Route
            path="/panel"
            element={
              <SinglePane>
                <PanelScreen />
              </SinglePane>
            }
          />
          <Route
            path="/activity"
            element={
              <SinglePane>
                <ActivityScreen />
              </SinglePane>
            }
          />
        </Routes>
      </div>
    </div>
  );
}

const SIDEBAR_KEY = "cm-sidebar-collapsed";

function Sidebar() {
  const nav = useNavigate();
  const loc = useLocation();
  // Collapse to an icon rail to reclaim width on smaller laptops; the choice
  // persists across sessions.
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_KEY) === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
    } catch {
      /* ignore private-mode storage errors */
    }
  }, [collapsed]);

  // A patient's detail belongs to the "Today" section, so keep Today lit while
  // drilled into /patient/*.
  const isActive = (to: string) =>
    to === "/" ? loc.pathname === "/" || loc.pathname.startsWith("/patient") : loc.pathname === to;

  return (
    <nav
      className={`flex h-full shrink-0 flex-col border-r border-clinical-line bg-clinical-card transition-[width] duration-200 ${
        collapsed ? "w-14" : "w-60"
      }`}
    >
      <div className={`flex items-center pb-5 pt-6 ${collapsed ? "justify-center px-2" : "justify-between px-5"}`}>
        {!collapsed && (
          <div className="min-w-0">
            <h1 className="truncate text-lg font-bold text-clinical-ink">Care Manager</h1>
            <p className="truncate text-xs text-clinical-muted">Unity Health · Outpatient</p>
          </div>
        )}
        <button
          onClick={() => setCollapsed((v) => !v)}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-clinical-muted transition hover:bg-clinical-bg hover:text-clinical-ink"
        >
          {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </button>
      </div>
      <div className={`flex flex-col gap-1 ${collapsed ? "px-2" : "px-3"}`}>
        {TABS.map(({ to, label, icon: Icon }) => {
          const active = isActive(to);
          return (
            <button
              key={to}
              onClick={() => nav(to)}
              aria-current={active ? "page" : undefined}
              // Native tooltip surfaces the label when collapsed to an icon.
              title={collapsed ? label : undefined}
              className={`flex items-center rounded-lg text-sm font-medium transition ${
                collapsed ? "justify-center px-0 py-2.5" : "gap-3 px-3 py-2.5"
              } ${
                active
                  ? "bg-clinical-accent/10 text-clinical-accent"
                  : "text-clinical-muted hover:bg-clinical-bg hover:text-clinical-ink"
              }`}
            >
              <Icon size={20} className="shrink-0" />
              {!collapsed && label}
            </button>
          );
        })}
      </div>
      <div className={`mt-auto border-t border-clinical-line p-2 ${collapsed ? "flex justify-center" : ""}`}>
        <ThemeToggle variant={collapsed ? "icon" : "full"} />
      </div>
    </nav>
  );
}

// Two-pane frame: fixed-width Worklist rail + a scrolling detail pane fed by the
// nested route via <Outlet/>.
function WorklistFrame() {
  return (
    <div className="flex h-full min-h-0">
      <aside className="h-full w-[420px] shrink-0 overflow-y-auto border-r border-clinical-line">
        <Worklist />
      </aside>
      {/* Each detail screen owns its own max-width (the patient detail goes wide
          for two columns; the outreach form stays narrow), so the pane itself is
          full-width. */}
      <main className="h-full min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}

// Shown in the detail pane before a patient is chosen.
function DetailEmpty() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-10 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-clinical-accent/10 text-clinical-accent">
        <Users size={26} />
      </div>
      <p className="text-sm font-medium text-clinical-ink">Select a patient</p>
      <p className="max-w-xs text-xs text-clinical-muted">
        Choose someone from today&rsquo;s worklist to see their brief, history, and outreach tools.
      </p>
    </div>
  );
}

// Single scrolling pane for the full-width screens (Caseload, Activity).
function SinglePane({ children }: { children: React.ReactNode }) {
  return (
    <main className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl">{children}</div>
    </main>
  );
}
