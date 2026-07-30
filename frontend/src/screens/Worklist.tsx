import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useLocation, useSearchParams } from "react-router-dom";
import { ChevronRight, AlertCircle, Users, Loader2, Search, X, FileText } from "lucide-react";
import { api, type WorklistPatient } from "../api";
import { PriorityPill, SdohFlags, lastContactLabel, pct, riskAccentClass } from "../components/ui";
import {
  applyFilters,
  filtersToParams,
  isDirty,
  parseFilters,
  type Sort,
  type WorklistFilters,
} from "../worklistFilters";
import { ThemeToggle } from "../theme";

const CONDITIONS = ["Diabetes", "CHF", "COPD"];

export default function Worklist() {
  const nav = useNavigate();
  const loc = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [patients, setPatients] = useState<WorklistPatient[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters live in the URL, so a filtered/searched worklist survives reload and
  // is shareable, and the detail pane can reconstruct the same ordering.
  const filters = useMemo(() => parseFilters(searchParams), [searchParams]);
  const update = (partial: Partial<WorklistFilters>) => {
    const next = filtersToParams({ ...filters, ...partial });
    setSearchParams(next, { replace: true });
  };
  const clearFilters = () => setSearchParams({}, { replace: true });

  const load = () => {
    setLoading(true);
    api
      .worklist()
      .then((d) => setPatients(d.patients))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const facilities = useMemo(
    () => ["All", ...Array.from(new Set(patients.map((p) => p.facility).filter(Boolean)))],
    [patients]
  );

  const filtered = useMemo(() => applyFilters(patients, filters), [patients, filters]);
  const dirty = isDirty(filters);

  const selectedId = loc.pathname.startsWith("/patient/") ? loc.pathname.split("/")[2] : null;

  // Desktop keyboard triage: Up/Down walk the filtered list and open the patient
  // in the detail pane, Enter opens the highlighted row. Ignored while typing in
  // a filter/search control.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Enter") return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable))
        return;
      // Don't move the list behind an open modal (e.g. the message sheet).
      if (document.querySelector('[role="dialog"]')) return;
      if (filtered.length === 0) return;
      const idx = selectedId ? filtered.findIndex((p) => p.patient_id === selectedId) : -1;
      if (e.key === "Enter") {
        if (idx >= 0) return;
        e.preventDefault();
        nav(`/patient/${filtered[0].patient_id}${loc.search}`);
        return;
      }
      e.preventDefault();
      const next =
        e.key === "ArrowDown"
          ? idx < 0
            ? 0
            : Math.min(idx + 1, filtered.length - 1)
          : idx < 0
          ? 0
          : Math.max(idx - 1, 0);
      nav(`/patient/${filtered[next].patient_id}${loc.search}`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [filtered, selectedId, nav, loc.search]);

  // Pull-to-refresh (mobile). Scrolling happens in an ancestor container (the
  // shell), so we find the nearest scrollable parent and only engage when it's
  // at the top. `pull` drives an indicator strip that grows as you drag.
  const rootRef = useRef<HTMLDivElement>(null);
  const [pull, setPull] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const pullStart = useRef<number | null>(null);
  const THRESHOLD = 56;

  const refresh = () => {
    setRefreshing(true);
    api
      .worklist()
      .then((d) => {
        setPatients(d.patients);
        setError(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => {
        setRefreshing(false);
        setPull(0);
      });
  };

  const scrollableAncestor = (): HTMLElement | null => {
    let el = rootRef.current?.parentElement ?? null;
    while (el) {
      const oy = getComputedStyle(el).overflowY;
      if ((oy === "auto" || oy === "scroll") && el.scrollHeight > el.clientHeight) return el;
      el = el.parentElement;
    }
    return null;
  };

  const onTouchStart = (e: React.TouchEvent) => {
    if (refreshing) return;
    const sc = scrollableAncestor();
    pullStart.current = sc && sc.scrollTop <= 0 ? e.touches[0].clientY : null;
  };
  const onTouchMove = (e: React.TouchEvent) => {
    if (pullStart.current === null || refreshing) return;
    const dy = e.touches[0].clientY - pullStart.current;
    if (dy > 0) setPull(Math.min(dy * 0.5, 80));
  };
  const onTouchEnd = () => {
    if (pullStart.current === null) return;
    pullStart.current = null;
    if (pull >= THRESHOLD) {
      setPull(THRESHOLD);
      refresh();
    } else {
      setPull(0);
    }
  };

  return (
    <div ref={rootRef} onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd}>
      {/* Pull-to-refresh indicator (mobile). */}
      <div
        className="flex items-center justify-center overflow-hidden text-clinical-muted"
        style={{ height: pull, transition: pullStart.current === null ? "height 0.2s ease" : undefined }}
      >
        {(pull > 6 || refreshing) && (
          <Loader2
            size={20}
            className={refreshing ? "animate-spin" : ""}
            style={refreshing ? undefined : { transform: `rotate(${pull * 3}deg)` }}
          />
        )}
      </div>

      <header className="sticky top-0 z-10 border-b border-clinical-line bg-clinical-card px-4 pb-3 pt-5">
        <div className="flex items-baseline justify-between">
          <div>
            <h1 className="text-xl font-bold text-clinical-ink">Today</h1>
            <p className="text-xs text-clinical-muted">Unity Health · Outpatient Care Management</p>
          </div>
          <div className="flex items-center gap-2">
            {/* Desktop has the theme toggle in the sidebar; surface it here for mobile. */}
            <span className="md:hidden">
              <ThemeToggle variant="icon" />
            </span>
            <span className="rounded-full bg-clinical-accent/10 px-2.5 py-1 text-sm font-semibold text-clinical-accent tabular-nums">
              {filtered.length}
            </span>
          </div>
        </div>

        {/* Free-text search by name. */}
        <div className="relative mt-3">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-clinical-muted" />
          <input
            type="search"
            inputMode="search"
            value={filters.q}
            onChange={(e) => update({ q: e.target.value })}
            placeholder="Search patients by name"
            aria-label="Search patients by name"
            className="w-full rounded-full border border-clinical-line bg-clinical-bg py-2 pl-9 pr-9 text-sm text-clinical-ink placeholder:text-clinical-muted focus:border-clinical-accent focus:bg-clinical-card focus:outline-none"
          />
          {filters.q && (
            <button
              onClick={() => update({ q: "" })}
              aria-label="Clear search"
              className="absolute right-2.5 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full text-clinical-muted hover:bg-clinical-line"
            >
              <X size={15} />
            </button>
          )}
        </div>

        {/* Primary filter: risk as a segmented control + sort on the right */}
        <div className="mt-3 flex items-center justify-between gap-2">
          <Segmented value={filters.risk} onChange={(v) => update({ risk: v })} options={["All", "High", "Rising"]} />
          <Select
            value={filters.sort}
            onChange={(v) => update({ sort: v as Sort })}
            options={[
              { value: "priority", label: "Sort: Priority" },
              { value: "overdue", label: "Sort: Overdue" },
              { value: "name", label: "Sort: Name" },
            ]}
            ariaLabel="Sort"
          />
        </div>

        {/* Secondary filters */}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Select
            value={filters.cond}
            onChange={(v) => update({ cond: v })}
            options={["All", ...CONDITIONS].map((o) => ({ value: o, label: o === "All" ? "Condition: All" : o }))}
            ariaLabel="Condition"
          />
          <Select
            value={filters.facility}
            onChange={(v) => update({ facility: v })}
            options={facilities.map((o) => ({ value: o, label: o === "All" ? "Facility: All" : o }))}
            ariaLabel="Facility"
          />
          <button
            onClick={() => update({ due: !filters.due })}
            className={`rounded-full border px-3 py-1.5 text-xs font-medium transition active:scale-95 ${
              filters.due
                ? "border-clinical-accent bg-clinical-accent text-white"
                : "border-clinical-line bg-clinical-card text-clinical-muted"
            }`}
          >
            Due / overdue
          </button>
          {dirty && (
            <button onClick={clearFilters} className="ml-auto text-xs font-medium text-clinical-accent active:opacity-60">
              Clear
            </button>
          )}
        </div>

        {/* Desktop-only discoverability hint for keyboard triage. */}
        <p className="mt-2 hidden text-[11px] text-clinical-muted md:block">
          Tip: use{" "}
          <kbd className="rounded border border-clinical-line bg-clinical-bg px-1 font-sans">↑</kbd>{" "}
          <kbd className="rounded border border-clinical-line bg-clinical-bg px-1 font-sans">↓</kbd> to move
          through patients.
        </p>
      </header>

      <div className="space-y-2.5 p-3">
        {loading && <SkeletonList />}
        {error && (
          <div className="flex items-center gap-2 rounded-xl bg-risk-highbg p-4 text-sm text-risk-high">
            <AlertCircle size={18} /> Failed to load worklist: {error}
          </div>
        )}
        {!loading && !error && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-3 px-8 py-20 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-clinical-accent/10 text-clinical-accent">
              <Users size={26} />
            </div>
            <p className="text-sm font-medium text-clinical-ink">
              {filters.q ? `No patients matching “${filters.q}”` : "No patients match these filters"}
            </p>
            {dirty && (
              <button
                onClick={clearFilters}
                className="rounded-full border border-clinical-line bg-clinical-card px-4 py-1.5 text-sm font-medium text-clinical-accent hover:bg-clinical-bg"
              >
                Clear filters
              </button>
            )}
          </div>
        )}
        {filtered.map((p) => (
          <PatientRow
            key={p.patient_id}
            p={p}
            selected={selectedId === p.patient_id}
            onOpen={() => nav(`/patient/${p.patient_id}${loc.search}`)}
            onLog={() => nav(`/patient/${p.patient_id}/outreach${loc.search}`)}
          />
        ))}
      </div>
    </div>
  );
}

// A single worklist row. On touch, swipe left to reveal a quick "Log outreach"
// action; a plain tap (or click / Enter on desktop) opens the patient.
function PatientRow({
  p,
  selected,
  onOpen,
  onLog,
}: {
  p: WorklistPatient;
  selected: boolean;
  onOpen: () => void;
  onLog: () => void;
}) {
  const ACTION_W = 96;
  const [dx, setDx] = useState(0);
  const [open, setOpen] = useState(false);
  const startX = useRef<number | null>(null);
  const startY = useRef(0);
  const swiped = useRef(false);

  const onTouchStart = (e: React.TouchEvent) => {
    startX.current = e.touches[0].clientX;
    startY.current = e.touches[0].clientY;
    swiped.current = false;
  };
  const onTouchMove = (e: React.TouchEvent) => {
    if (startX.current === null) return;
    const dX = e.touches[0].clientX - startX.current;
    const dY = e.touches[0].clientY - startY.current;
    // Vertical intent -> let the list scroll, abandon the swipe.
    if (!swiped.current && Math.abs(dX) < Math.abs(dY)) {
      startX.current = null;
      return;
    }
    swiped.current = true;
    const next = Math.min(0, Math.max(-ACTION_W, (open ? -ACTION_W : 0) + dX));
    setDx(next);
  };
  const onTouchEnd = () => {
    if (startX.current === null && !swiped.current) return;
    startX.current = null;
    const shouldOpen = dx < -ACTION_W / 2;
    setOpen(shouldOpen);
    setDx(shouldOpen ? -ACTION_W : 0);
  };

  const activate = () => {
    if (swiped.current) {
      swiped.current = false;
      return; // a swipe, not a tap
    }
    if (open) {
      setOpen(false);
      setDx(0);
      return; // first tap closes the revealed action
    }
    onOpen();
  };

  return (
    <div className="relative overflow-hidden rounded-xl">
      {/* Swipe-revealed action (mobile). */}
      <div className="absolute inset-y-0 right-0 flex">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onLog();
          }}
          tabIndex={-1}
          aria-label={`Log outreach for ${p.name}`}
          style={{ width: ACTION_W }}
          className="flex flex-col items-center justify-center gap-1 bg-clinical-accent text-xs font-semibold text-white"
        >
          <FileText size={18} /> Log
        </button>
      </div>
      <div
        role="button"
        tabIndex={0}
        aria-current={selected ? "true" : undefined}
        ref={selected ? (el) => el?.scrollIntoView({ block: "nearest" }) : undefined}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onClick={activate}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onOpen();
          }
        }}
        style={{ transform: `translateX(${dx}px)`, transition: startX.current === null ? "transform 0.2s ease" : undefined }}
        className={`relative flex w-full items-center gap-3 border bg-clinical-card p-3.5 text-left shadow-sm transition-colors active:bg-clinical-bg md:hover:bg-clinical-bg ${
          selected ? "border-clinical-accent ring-1 ring-clinical-accent" : "border-clinical-line"
        } ${riskAccentClass(p.risk_tier)} rounded-xl`}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-[15px] font-semibold text-clinical-ink">{p.name}</span>
            <PriorityPill score={p.care_priority_score} tier={p.risk_tier} />
          </div>
          <div className="mt-0.5 text-xs text-clinical-muted">
            {p.age}y · {p.sex} · {p.facility}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <span className="font-medium text-clinical-ink">
              {p.open_gaps} open gap{p.open_gaps !== 1 ? "s" : ""}
            </span>
            <span className="text-clinical-muted">Hosp. risk {pct(p.predicted_admit_prob)}</span>
            <SdohFlags transportation={p.transportation_barrier} food={p.food_insecurity} />
          </div>
          <div className="mt-1 text-[11px] text-clinical-muted">{lastContactLabel(p.last_contact_days)}</div>
        </div>
        <ChevronRight size={20} className="shrink-0 text-slate-300" />
      </div>
    </div>
  );
}

// Segmented pill control for a small, mutually-exclusive option set (e.g. risk).
function Segmented({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <div className="inline-flex rounded-full border border-clinical-line bg-clinical-card p-0.5">
      {options.map((o) => (
        <button
          key={o}
          onClick={() => onChange(o)}
          className={`rounded-full px-3 py-1 text-xs font-semibold transition active:scale-95 ${
            value === o ? "bg-clinical-accent text-white" : "text-clinical-muted"
          }`}
        >
          {o}
        </button>
      ))}
    </div>
  );
}

// Styled native select — keeps the iOS wheel picker (good for long lists like
// facilities) while matching the pill aesthetic.
function Select({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  ariaLabel: string;
}) {
  return (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-full border border-clinical-line bg-clinical-card px-3 py-1.5 text-xs font-medium text-clinical-ink"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function SkeletonList() {
  return (
    <>
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="h-[92px] animate-pulse rounded-xl border border-clinical-line bg-clinical-card" />
      ))}
    </>
  );
}
