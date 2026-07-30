import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertCircle, Users, ShieldAlert, TrendingUp, ClipboardList, PhoneCall, CheckCircle2, Target } from "lucide-react";
import { api, type Panel } from "../api";

export default function PanelScreen() {
  const nav = useNavigate();
  const [panel, setPanel] = useState<Panel | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .panel()
      .then(setPanel)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <header className="sticky top-0 z-10 border-b border-clinical-line bg-clinical-card px-4 pb-3 pt-5">
        <h1 className="text-xl font-bold text-clinical-ink">My Caseload</h1>
        <p className="text-xs text-clinical-muted">Unity Health · Outpatient Care Management</p>
      </header>

      <div className="p-3">
        {loading && <Skeleton />}

        {error && (
          <div className="flex items-center gap-2 rounded-xl bg-risk-highbg p-4 text-sm text-risk-high">
            <AlertCircle size={18} /> Failed to load panel: {error}
          </div>
        )}

        {!loading && !error && panel && (
          <>
            <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-clinical-muted">
              My caseload
            </h2>
            <div className="grid grid-cols-2 gap-2.5">
              <Kpi
                icon={<Users size={18} />}
                label="Caseload size"
                value={panel.panel_size}
                hint="High + Rising · ≥1 open gap"
                accent
                onClick={() => nav("/")}
              />
              <Kpi
                icon={<ClipboardList size={18} />}
                label="Open care gaps"
                value={panel.open_gaps}
              />
              <Kpi
                icon={<ShieldAlert size={18} />}
                label="High risk"
                value={panel.high}
                tone="high"
                onClick={() => nav("/?risk=High")}
              />
              <Kpi
                icon={<TrendingUp size={18} />}
                label="Rising risk"
                value={panel.rising}
                tone="rising"
                onClick={() => nav("/?risk=Rising")}
              />
            </div>

            <RiskComposition high={panel.high} rising={panel.rising} onSelect={(tier) => nav(`/?risk=${tier}`)} />

            <div className="mt-2.5 flex items-start gap-2 rounded-xl border border-clinical-line bg-clinical-bg p-3 text-[11px] text-clinical-muted">
              <Users size={14} className="mt-0.5 shrink-0 text-clinical-muted" />
              <span>
                Program:{" "}
                <span className="font-semibold text-clinical-ink tabular-nums">
                  {panel.program_high_risk.toLocaleString()}
                </span>{" "}
                high-risk patients across the care-management team (~
                {panel.n_caseloads} care managers).
              </span>
            </div>

            <h2 className="mb-2 mt-5 px-1 text-xs font-semibold uppercase tracking-wide text-clinical-muted">
              This session
            </h2>
            <div className="grid grid-cols-2 gap-2.5">
              <Kpi
                icon={<PhoneCall size={18} />}
                label="Outreach logged"
                value={panel.outreach_logged}
                hint={`${panel.patients_touched} patient${panel.patients_touched !== 1 ? "s" : ""} touched`}
              />
              <Kpi
                icon={<CheckCircle2 size={18} />}
                label="Gaps closed"
                value={panel.gaps_closed}
                tone="good"
              />
              <div className="col-span-2 rounded-xl border border-clinical-line bg-clinical-card p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-medium text-clinical-ink">
                    <Target size={18} className="text-clinical-accent" /> Gap-closure rate
                  </div>
                  <span className="text-2xl font-bold tabular-nums text-clinical-accent">
                    {panel.closure_rate}%
                  </span>
                </div>
                <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-clinical-line">
                  <div
                    className="h-full rounded-full bg-clinical-accent transition-all"
                    style={{ width: `${Math.min(100, panel.closure_rate)}%` }}
                  />
                </div>
                <p className="mt-2 text-[11px] text-clinical-muted">
                  Gaps you closed this session vs. gaps closed + still open in your caseload.
                </p>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Stacked bar of High vs Rising risk in the caseload — a quick visual read of
// composition from the same counts shown in the KPIs above.
function RiskComposition({
  high,
  rising,
  onSelect,
}: {
  high: number;
  rising: number;
  onSelect?: (tier: "High" | "Rising") => void;
}) {
  const total = high + rising;
  if (total === 0) return null;
  const hPct = (high / total) * 100;
  const rPct = (rising / total) * 100;
  return (
    <div className="mt-2.5 rounded-xl border border-clinical-line bg-clinical-card p-3.5">
      <div className="mb-2 flex items-center justify-between text-[11px] font-medium uppercase tracking-wide text-clinical-muted">
        <span>Risk composition</span>
        <span className="tabular-nums">{total} patients</span>
      </div>
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-clinical-line">
        <div className="h-full bg-risk-high transition-all" style={{ width: `${hPct}%` }} />
        <div className="h-full bg-risk-rising transition-all" style={{ width: `${rPct}%` }} />
      </div>
      <div className="mt-2 flex gap-4 text-[11px]">
        <Legend color="bg-risk-high" label="High" value={high} onClick={onSelect && (() => onSelect("High"))} />
        <Legend color="bg-risk-rising" label="Rising" value={rising} onClick={onSelect && (() => onSelect("Rising"))} />
      </div>
    </div>
  );
}

function Legend({
  color,
  label,
  value,
  onClick,
}: {
  color: string;
  label: string;
  value: number;
  onClick?: () => void;
}) {
  const inner = (
    <>
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label} <span className="font-semibold tabular-nums text-clinical-ink">{value}</span>
    </>
  );
  if (onClick) {
    return (
      <button
        onClick={onClick}
        className="inline-flex items-center gap-1.5 rounded text-clinical-muted transition hover:text-clinical-ink"
      >
        {inner}
      </button>
    );
  }
  return <span className="inline-flex items-center gap-1.5 text-clinical-muted">{inner}</span>;
}

function Kpi({
  icon,
  label,
  value,
  hint,
  accent,
  tone,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  hint?: string;
  accent?: boolean;
  tone?: "high" | "rising" | "good";
  onClick?: () => void;
}) {
  const valueColor =
    tone === "high"
      ? "text-risk-high"
      : tone === "rising"
      ? "text-risk-rising"
      : tone === "good"
      ? "text-green-600"
      : accent
      ? "text-clinical-accent"
      : "text-clinical-ink";
  const body = (
    <>
      <div className="flex items-center gap-1.5 text-clinical-muted">
        {icon}
        <span className="text-[11px] font-medium uppercase tracking-wide">{label}</span>
      </div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${valueColor}`}>{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-clinical-muted">{hint}</div>}
    </>
  );
  if (onClick) {
    return (
      <button
        onClick={onClick}
        className="rounded-xl border border-clinical-line bg-clinical-card p-3.5 text-left transition hover:border-clinical-accent hover:shadow-sm"
      >
        {body}
      </button>
    );
  }
  return <div className="rounded-xl border border-clinical-line bg-clinical-card p-3.5">{body}</div>;
}

function Skeleton() {
  return (
    <div className="grid grid-cols-2 gap-2.5">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-[88px] animate-pulse rounded-xl border border-clinical-line bg-clinical-card" />
      ))}
    </div>
  );
}
