import { Car, Utensils } from "lucide-react";

// Left-edge accent so a card's risk reads at a glance down a list.
export function riskAccentClass(tier?: string): string {
  if (tier === "High") return "border-l-4 border-l-risk-high";
  if (tier === "Rising") return "border-l-4 border-l-risk-rising";
  return "border-l-4 border-l-clinical-line";
}

// Shared section card. One primitive for every titled block so spacing,
// borders, and the title row stay consistent across screens. `action` renders
// on the right of the title row (e.g. the notes "Summarize" button).
export function Card({
  title,
  icon,
  action,
  children,
}: {
  title?: React.ReactNode;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-clinical-line bg-clinical-card p-4">
      {(title || action) && (
        <div className="mb-2.5 flex items-center justify-between gap-2">
          {title && (
            <h2 className="flex items-center gap-1.5 text-sm font-semibold text-clinical-ink">
              {icon}
              {title}
            </h2>
          )}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function RiskBadge({ tier }: { tier: string }) {
  const map: Record<string, string> = {
    High: "bg-risk-highbg text-risk-high",
    Rising: "bg-risk-risingbg text-risk-rising",
    Low: "bg-clinical-line text-clinical-muted",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
        map[tier] || map.Low
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          tier === "High" ? "bg-risk-high" : tier === "Rising" ? "bg-risk-rising" : "bg-slate-400"
        }`}
      />
      {tier}
    </span>
  );
}

export function PriorityPill({ score, tier }: { score: number; tier?: string }) {
  // Color encodes the risk tier so urgency reads at a glance from a SINGLE pill
  // (the separate risk badge on the worklist card is now redundant and dropped):
  //   High = red · Rising = amber · Low = green/slate.
  // When no tier is supplied, fall back to scaling color by the score itself.
  const byTier: Record<string, string> = {
    High: "bg-risk-highbg text-risk-high",
    Rising: "bg-risk-risingbg text-risk-rising",
    Low: "bg-emerald-50 text-emerald-700",
  };
  const tone = tier
    ? byTier[tier] || "bg-clinical-line text-clinical-muted"
    : score >= 70
    ? "bg-risk-highbg text-risk-high"
    : score >= 45
    ? "bg-risk-risingbg text-risk-rising"
    : "bg-clinical-line text-clinical-muted";
  const dot =
    tier === "High"
      ? "bg-risk-high"
      : tier === "Rising"
      ? "bg-risk-rising"
      : tier === "Low"
      ? "bg-emerald-500"
      : "bg-current opacity-60";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-bold tabular-nums ${tone}`}
      title={`Care Priority Score (0–100) — higher means reach out sooner${
        tier ? ` · ${tier} risk` : ""
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      Priority {score}
    </span>
  );
}

export function SdohFlags({
  transportation,
  food,
}: {
  transportation?: boolean;
  food?: boolean;
}) {
  if (!transportation && !food) return null;
  return (
    <div className="flex items-center gap-1.5">
      {transportation && (
        <span title="Transportation barrier" className="rounded-md bg-amber-50 p-1 text-amber-700">
          <Car size={14} />
        </span>
      )}
      {food && (
        <span title="Food insecurity" className="rounded-md bg-amber-50 p-1 text-amber-700">
          <Utensils size={14} />
        </span>
      )}
    </div>
  );
}

export function Chip({ children, tone = "slate" }: { children: React.ReactNode; tone?: string }) {
  const tones: Record<string, string> = {
    slate: "bg-clinical-line text-clinical-ink",
    blue: "bg-blue-50 text-blue-700",
    amber: "bg-amber-50 text-amber-800",
  };
  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function lastContactLabel(days: number | null): string {
  if (days === null || days === undefined) return "Last contact: never";
  if (days === 0) return "Last contact: today";
  return `Last contact: ${days}d ago`;
}

export function pct(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v * 100)}%`;
}

export function relativeTime(iso: string): string {
  // Backend timestamps are naive UTC (datetime.utcnow().isoformat(), no offset),
  // so append "Z" when no timezone info is present to parse them as UTC.
  const hasTz = /[zZ]|[+-]\d{2}:\d{2}$/.test(iso);
  const then = new Date(hasTz ? iso : `${iso}Z`).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (secs < 45) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}
