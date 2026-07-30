import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity as ActivityIcon,
  AlertCircle,
  CheckCircle2,
  CalendarClock,
  Trash2,
  RotateCcw,
} from "lucide-react";
import { api, type ActivityItem } from "../api";
import { RiskBadge, relativeTime } from "../components/ui";

// Bucket a logged-outreach timestamp into Today / Yesterday / Earlier for the
// section headers. Backend timestamps are naive UTC, so append "Z" when absent.
function dayBucket(iso: string): string {
  const hasTz = /[zZ]|[+-]\d{2}:\d{2}$/.test(iso);
  const d = new Date(hasTz ? iso : `${iso}Z`);
  if (Number.isNaN(d.getTime())) return "Earlier";
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = Math.round((startToday.getTime() - dDay.getTime()) / 86400000);
  if (diff <= 0) return "Today";
  if (diff === 1) return "Yesterday";
  return "Earlier";
}

export default function Activity() {
  const nav = useNavigate();
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .activity()
      .then((d) => setItems(d.items))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Delete one patient's outreach — removes every activity row for that patient
  // and brings them back to the worklist as a fresh candidate.
  const deleteForPatient = async (patientId: string) => {
    setBusy(true);
    try {
      await api.deletePatientActivity(patientId);
      setItems((prev) => prev.filter((it) => it.patient_id !== patientId));
    } catch {
      /* leave the list as-is on failure */
    } finally {
      setBusy(false);
    }
  };

  // Full demo reset — wipe all logged outreach for this user.
  const clearAll = async () => {
    setBusy(true);
    try {
      await api.clearActivity();
      setItems([]);
    } catch {
      /* ignore */
    } finally {
      setBusy(false);
      setConfirmClear(false);
    }
  };

  return (
    <div>
      <header className="sticky top-0 z-10 border-b border-clinical-line bg-clinical-card px-4 pb-3 pt-5">
        <div className="flex items-baseline justify-between">
          <div>
            <h1 className="text-xl font-bold text-clinical-ink">Activity</h1>
            <p className="text-xs text-clinical-muted">Unity Health · Outreach logged this session</p>
          </div>
          {!loading && !error && items.length > 0 && (
            <span className="rounded-full bg-clinical-accent/10 px-2.5 py-1 text-sm font-semibold text-clinical-accent">
              {items.length}
            </span>
          )}
        </div>

        {!loading && !error && items.length > 0 && (
          <div className="mt-2.5 flex justify-end">
            {confirmClear ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-clinical-muted">Reset all activity?</span>
                <button
                  onClick={clearAll}
                  disabled={busy}
                  className="rounded-full bg-risk-high px-3 py-1 text-xs font-semibold text-white active:scale-95 disabled:opacity-50"
                >
                  Clear all
                </button>
                <button
                  onClick={() => setConfirmClear(false)}
                  disabled={busy}
                  className="rounded-full border border-clinical-line bg-clinical-card px-3 py-1 text-xs font-medium text-clinical-ink active:bg-clinical-bg"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmClear(true)}
                className="inline-flex items-center gap-1.5 rounded-full border border-clinical-line bg-clinical-card px-3 py-1 text-xs font-medium text-clinical-muted active:bg-clinical-bg"
              >
                <RotateCcw size={13} /> Reset demo
              </button>
            )}
          </div>
        )}
      </header>

      <div className="space-y-2.5 p-3">
        {loading && <SkeletonList />}

        {error && (
          <div className="flex items-center gap-2 rounded-xl bg-risk-highbg p-4 text-sm text-risk-high">
            <AlertCircle size={18} /> Failed to load activity: {error}
          </div>
        )}

        {!loading && !error && items.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-3 px-8 py-20 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-clinical-accent/10 text-clinical-accent">
              <ActivityIcon size={26} />
            </div>
            <p className="text-sm font-medium text-clinical-ink">No outreach logged yet</p>
            <p className="text-sm text-clinical-muted">
              Log one from a patient to see it here.
            </p>
          </div>
        )}

        {!loading &&
          !error &&
          items.map((it, i) => {
            const bucket = dayBucket(it.at);
            const showHeader = i === 0 || dayBucket(items[i - 1].at) !== bucket;
            return (
            <div key={`${it.patient_id}-${it.at}-${i}`}>
              {showHeader && (
                <h2 className="mb-1.5 mt-3 px-1 text-xs font-semibold uppercase tracking-wide text-clinical-muted first:mt-0">
                  {bucket}
                </h2>
              )}
            <div
              onClick={() => nav(`/patient/${it.patient_id}`)}
              className="relative block w-full rounded-xl border border-clinical-line bg-clinical-card p-3.5 text-left shadow-sm transition active:scale-[0.99] active:bg-clinical-bg"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-[15px] font-semibold text-clinical-ink">
                    {it.patient_name || "Patient"}
                  </span>
                  {it.risk_tier && <RiskBadge tier={it.risk_tier} />}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="text-[11px] text-clinical-muted">{relativeTime(it.at)}</span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteForPatient(it.patient_id);
                    }}
                    disabled={busy}
                    aria-label="Delete activity for this patient"
                    title="Delete — brings this patient back to the worklist"
                    className="-mr-1 rounded-full p-1.5 text-clinical-muted active:bg-clinical-line active:text-risk-high disabled:opacity-50"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>

              <div className="mt-1.5 text-sm font-medium text-clinical-accent">{it.action}</div>

              {it.addressed_gap_measures.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {it.addressed_gap_measures.map((m) => (
                    <span
                      key={m}
                      className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2.5 py-0.5 text-xs font-medium text-green-700"
                    >
                      <CheckCircle2 size={12} /> {m}
                    </span>
                  ))}
                </div>
              )}

              {it.note && (
                <p className="mt-2 text-sm leading-relaxed text-clinical-ink">{it.note}</p>
              )}

              {it.follow_up && (
                <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700">
                  <CalendarClock size={12} /> Follow-up {it.follow_up}
                </div>
              )}
            </div>
            </div>
            );
          })}
      </div>
    </div>
  );
}

function SkeletonList() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-[88px] animate-pulse rounded-xl border border-clinical-line bg-clinical-card" />
      ))}
    </>
  );
}
