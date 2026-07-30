import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ChevronLeft,
  ChevronRight,
  Sparkles,
  ArrowRight,
  Languages,
  Car,
  Utensils,
  Home,
  Phone,
  CalendarPlus,
  MessageSquare,
  CheckCircle2,
  Activity as ActivityIcon,
  Ambulance,
  BedDouble,
  Copy,
  Send,
  X,
  FileText,
  Loader2,
} from "lucide-react";
import {
  api,
  type PatientDetail,
  type Brief,
  type PatientHistory,
  type PatientMessage,
  type ClinicalNote,
  type WorklistPatient,
} from "../api";
import { RiskBadge, Chip, pct, Card } from "../components/ui";
import { applyFilters, parseFilters } from "../worklistFilters";
import AskAI from "../components/AskAI";

export default function PatientDetailScreen() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [p, setP] = useState<PatientDetail | null>(null);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [briefLoading, setBriefLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [history, setHistory] = useState<PatientHistory | null>(null);
  const [notes, setNotes] = useState<ClinicalNote[] | null>(null);

  // Prev/next stepping through the same filtered worklist the user came from.
  // Filters live in the URL, so we reconstruct the exact ordering here.
  const loc = useLocation();
  const [searchParams] = useSearchParams();
  const [worklist, setWorklist] = useState<WorklistPatient[]>([]);
  useEffect(() => {
    api
      .worklist()
      .then((d) => setWorklist(d.patients))
      .catch(() => {});
  }, []);
  const ordered = useMemo(
    () => applyFilters(worklist, parseFilters(searchParams)),
    [worklist, searchParams]
  );
  const curIdx = ordered.findIndex((x) => x.patient_id === id);
  const prevPatient = curIdx > 0 ? ordered[curIdx - 1] : null;
  const nextPatient = curIdx >= 0 && curIdx < ordered.length - 1 ? ordered[curIdx + 1] : null;
  const goToPatient = (pid: string) => nav(`/patient/${pid}${loc.search}`);

  // AI-drafted patient message modal state. Drafts default to English; the care
  // manager can translate into a secondary language on demand. Each language
  // variant is fetched once and cached client-side so toggling is instant.
  const [msgOpen, setMsgOpen] = useState(false);
  const [lang, setLang] = useState("English");
  const [msgByLang, setMsgByLang] = useState<Record<string, PatientMessage>>({});
  const [msgLoading, setMsgLoading] = useState(false);
  const [msgSent, setMsgSent] = useState(false);
  const [copied, setCopied] = useState(false);

  // Modal accessibility: focus the sheet on open, close on Esc, and trap Tab
  // within it.
  const sheetRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!msgOpen) return;
    sheetRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMsgOpen(false);
        return;
      }
      if (e.key !== "Tab") return;
      const nodes = sheetRef.current?.querySelectorAll<HTMLElement>(
        'button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])'
      );
      const list = nodes ? Array.from(nodes).filter((el) => !el.hasAttribute("disabled")) : [];
      if (list.length === 0) return;
      const first = list[0];
      const last = list[list.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [msgOpen]);

  const msg = msgByLang[lang] ?? null;

  // Language chips: English first, then the patient's preferred language (if not
  // English), then a couple of common community languages — deduped, capped at 4.
  const langOptions = (() => {
    const opts = ["English"];
    const pref = p?.sdoh?.preferred_language;
    if (pref && pref !== "English") opts.push(pref);
    for (const l of ["Spanish", "Vietnamese", "Chinese"]) {
      if (!opts.includes(l)) opts.push(l);
    }
    return opts.slice(0, 4);
  })();

  const loadMessage = (targetLang: string) => {
    if (!p) return;
    setLang(targetLang);
    setCopied(false);
    if (msgByLang[targetLang]) return; // already drafted this language
    setMsgLoading(true);
    api
      .message(p.patient_id, targetLang)
      .then((m) => setMsgByLang((prev) => ({ ...prev, [targetLang]: m })))
      .catch(() =>
        setMsgByLang((prev) => ({
          ...prev,
          [targetLang]: { message: "Message draft unavailable. Please try again.", language: targetLang },
        }))
      )
      .finally(() => setMsgLoading(false));
  };

  const openMessage = () => {
    if (!p) return;
    setMsgOpen(true);
    setMsgSent(false);
    setCopied(false);
    setLang("English");
    if (!msgByLang["English"]) loadMessage("English");
  };

  const copyMessage = async () => {
    if (!msg) return;
    try {
      await navigator.clipboard.writeText(msg.message);
    } catch {
      /* clipboard may be unavailable; ignore */
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const sendMessage = async () => {
    if (!p) return;
    try {
      await api.logOutreach(p.patient_id, {
        action: "Message sent",
        addressed_gap_ids: [],
        note: msg ? `Sent patient message (${msg.language})` : "Sent patient message",
        patient_name: p.name,
        risk_tier: p.risk_tier,
      });
    } catch {
      /* keep UX moving even if logging fails */
    }
    setMsgSent(true);
  };

  // One tap: log a "Called" outreach to the per-user store (so it flows into
  // Activity and re-ranks the worklist) AND initiate the call (tel: dialer).
  // The log request uses keepalive:true so the browser guarantees delivery even
  // though we immediately navigate to a tel: URL (which would otherwise abort an
  // in-flight fetch). We also defer the dialer handoff briefly so the user sees
  // the confirmation toast.
  const callPatient = async () => {
    if (!p) return;
    const tel = p.phone.replace(/[^0-9]/g, "");
    try {
      await fetch(`/api/patients/${p.patient_id}/outreach`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        keepalive: true,
        body: JSON.stringify({
          action: "Called",
          addressed_gap_ids: [],
          note: `Initiated call to ${p.phone}`,
          patient_name: p.name,
          risk_tier: p.risk_tier,
        }),
      });
      setToast(`Logged — call to ${p.name}`);
    } catch {
      setToast("Call started (logging failed)");
    }
    setTimeout(() => setToast(null), 2600);
    // Hand off to the device dialer after the log has been recorded.
    setTimeout(() => {
      window.location.href = `tel:${tel}`;
    }, 400);
  };

  useEffect(() => {
    if (!id) return;
    api.patient(id).then(setP).catch((e) => setError(e.message));
    setBriefLoading(true);
    api
      .brief(id)
      .then(setBrief)
      .catch(() => setBrief({ summary: "Brief unavailable.", next_best_action: "" }))
      .finally(() => setBriefLoading(false));
    api
      .history(id)
      .then(setHistory)
      .catch(() => setHistory({ encounters: [], utilization_90d: { ed_visits: 0, admissions: 0 } }));
    api
      .notes(id)
      .then((d) => setNotes(d.notes))
      .catch(() => setNotes([]));
  }, [id]);

  if (error) return <div className="p-6 text-sm text-risk-high">Error: {error}</div>;
  if (!p) return <div className="p-6 text-sm text-clinical-muted">Loading patient…</div>;

  const fmtCost = p.predicted_annual_cost
    ? `$${Math.round(p.predicted_annual_cost).toLocaleString()}`
    : "—";

  return (
    <div className="mx-auto max-w-5xl">
      <header className="sticky top-0 z-10 border-b border-clinical-line bg-clinical-card px-3 pb-3 pt-4 shadow-sm">
        {/* On desktop the worklist is always visible in the left pane, so this
            back link is redundant; hide it at the md breakpoint. */}
        <button
          onClick={() => nav(`/${loc.search}`)}
          className="mb-2 flex items-center gap-1 text-sm text-clinical-accent md:hidden"
        >
          <ChevronLeft size={18} /> Worklist
        </button>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-clinical-ink">{p.name}</h1>
            <RiskBadge tier={p.risk_tier} />
          </div>
          {/* Desktop: step through the current filtered worklist, plus the
              record-level Log Outreach action (the mobile fixed bottom bar below
              is hidden at md+). */}
          <div className="hidden shrink-0 items-center gap-2 md:flex">
            <div className="flex items-center gap-1">
              <button
                onClick={() => prevPatient && goToPatient(prevPatient.patient_id)}
                disabled={!prevPatient}
                title="Previous patient (↑)"
                aria-label="Previous patient"
                className="flex h-9 w-9 items-center justify-center rounded-lg border border-clinical-line text-clinical-muted transition hover:bg-clinical-bg hover:text-clinical-ink disabled:opacity-40 disabled:hover:bg-transparent"
              >
                <ChevronLeft size={18} />
              </button>
              <button
                onClick={() => nextPatient && goToPatient(nextPatient.patient_id)}
                disabled={!nextPatient}
                title="Next patient (↓)"
                aria-label="Next patient"
                className="flex h-9 w-9 items-center justify-center rounded-lg border border-clinical-line text-clinical-muted transition hover:bg-clinical-bg hover:text-clinical-ink disabled:opacity-40 disabled:hover:bg-transparent"
              >
                <ChevronRight size={18} />
              </button>
            </div>
            <button
              onClick={() => nav(`/patient/${p.patient_id}/outreach${loc.search}`)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-clinical-accent px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 active:scale-[0.99]"
            >
              <FileText size={16} /> Log Outreach
            </button>
          </div>
        </div>
        <p className="text-xs text-clinical-muted">
          {p.age}y · {p.sex} · {p.payer_type}
        </p>
      </header>

      <div className="p-3 pb-[calc(var(--nav-h)_+_84px)] md:grid md:grid-cols-2 md:items-start md:gap-4 md:p-4 md:pb-6">
        {/* Left column: at-a-glance metrics, the AI brief + primary actions, and
            the scoped Ask-AI chat. On mobile the two columns simply stack, which
            preserves the original top-to-bottom order. */}
        <div className="space-y-3">
        {/* Key metrics */}
        <div className="grid grid-cols-2 gap-2">
          <Metric label="Care Priority Score" value={String(p.care_priority_score)} accent />
          <Metric label="Avoidable hospitalization risk (12 mo)" value={pct(p.predicted_admit_prob)} />
          <Metric label="Predicted annual cost" value={fmtCost} />
          <Metric label="PCP" value={p.pcp_name || p.pcp_id} small />
          <Metric label="Facility" value={p.facility} small />
        </div>

        {/* AI Brief */}
        <section className="rounded-xl border border-clinical-accent/20 bg-gradient-to-br from-clinical-accent/10 to-clinical-card p-4">
          <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-clinical-accent">
            <Sparkles size={16} /> AI Outreach Brief
          </div>
          {briefLoading ? (
            <div className="space-y-2">
              <div className="h-3 w-full animate-pulse rounded bg-blue-100" />
              <div className="h-3 w-5/6 animate-pulse rounded bg-blue-100" />
              <div className="h-3 w-2/3 animate-pulse rounded bg-blue-100" />
            </div>
          ) : (
            <>
              <p className="text-sm leading-relaxed text-clinical-ink">{brief?.summary}</p>
              {brief?.next_best_action && (
                <div className="mt-3 flex items-start gap-2 rounded-lg bg-clinical-card/70 p-2.5 text-sm">
                  <ArrowRight size={16} className="mt-0.5 shrink-0 text-clinical-accent" />
                  <span>
                    <span className="font-semibold text-clinical-accent">Next best action: </span>
                    {brief.next_best_action}
                  </span>
                </div>
              )}
            </>
          )}

          {/* Initiate the next best action — one tap calls + logs */}
          <div className="mt-3">
            <button
              onClick={callPatient}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-clinical-accent py-3.5 text-base font-semibold text-white shadow-sm transition hover:bg-blue-700 active:scale-[0.99] active:bg-blue-700"
            >
              <Phone size={20} /> Call patient
              <span className="text-sm font-normal text-blue-100">· {p.phone}</span>
            </button>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <button
                onClick={() => nav(`/patient/${p.patient_id}/outreach`)}
                className="flex items-center justify-center gap-1.5 rounded-xl border border-clinical-line bg-clinical-card py-2.5 text-sm font-medium text-clinical-ink transition hover:bg-clinical-bg active:bg-clinical-bg"
              >
                <CalendarPlus size={16} /> Schedule
              </button>
              <button
                onClick={openMessage}
                className="flex items-center justify-center gap-1.5 rounded-xl border border-clinical-line bg-clinical-card py-2.5 text-sm font-medium text-clinical-ink transition hover:bg-clinical-bg active:bg-clinical-bg"
              >
                <MessageSquare size={16} /> Message
              </button>
            </div>
          </div>
        </section>

        {/* Ask AI about this patient — scoped, grounded mini-chat */}
        <AskAI patientId={p.patient_id} />
        </div>

        {/* Right column: the clinical record — history, notes, conditions,
            SDOH, and open care gaps. */}
        <div className="mt-3 space-y-3 md:mt-0">
        {/* Recent history */}
        <RecentHistory history={history} />

        {/* Clinical notes (unstructured + GenAI) */}
        <ClinicalNotes patientId={p.patient_id} notes={notes} />

        {/* Conditions */}
        {p.conditions.length > 0 && (
          <Card title="Chronic conditions">
            <div className="flex flex-wrap gap-2">
              {p.conditions.map((c) => (
                <Chip key={c} tone="blue">
                  {c}
                </Chip>
              ))}
            </div>
          </Card>
        )}

        {/* SDOH */}
        <Card title="Social determinants of health">
          <div className="flex flex-wrap gap-2">
            {p.sdoh.transportation_barrier && (
              <SdohItem icon={<Car size={14} />} label="Transportation barrier" />
            )}
            {p.sdoh.food_insecurity && <SdohItem icon={<Utensils size={14} />} label="Food insecurity" />}
            {p.sdoh.housing_instability && <SdohItem icon={<Home size={14} />} label="Housing instability" />}
            {p.sdoh.preferred_language && (
              <SdohItem
                icon={<Languages size={14} />}
                label={`${p.sdoh.preferred_language}${p.sdoh.interpreter_needed ? " · interpreter needed" : ""}`}
                neutral
              />
            )}
            {!p.sdoh.transportation_barrier &&
              !p.sdoh.food_insecurity &&
              !p.sdoh.housing_instability && (
                <span className="text-xs text-clinical-muted">No barriers reported</span>
              )}
          </div>
        </Card>

        {/* Care gaps */}
        <Card title={`Open care gaps (${p.open_gaps.length})`}>
          {p.open_gaps.length === 0 ? (
            <p className="text-sm text-clinical-muted">No open care gaps.</p>
          ) : (
            <ul className="divide-y divide-clinical-line">
              {p.open_gaps.map((g) => (
                <li key={g.gap_id} className="flex items-center justify-between py-2.5">
                  <div>
                    <div className="text-sm font-medium text-clinical-ink">{g.measure}</div>
                    <div className="text-xs text-clinical-muted">
                      Open {g.days_open}d · due {g.due_date}
                    </div>
                  </div>
                  <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
                    {g.gap_status}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        </div>
      </div>

      {/* Confirmation toast after Call action */}
      {toast && (
        <div
          role="status"
          aria-live="polite"
          className="animate-toast-in fixed left-1/2 z-30 flex w-[calc(100%-2rem)] max-w-md -translate-x-1/2 items-center gap-2 rounded-xl bg-slate-900/95 px-4 py-3 text-sm font-medium text-white shadow-lg dark:bg-slate-700/95"
          style={{ bottom: "calc(var(--nav-h) + 64px)" }}
        >
          <CheckCircle2 size={18} className="shrink-0 text-green-400" />
          {toast}
        </div>
      )}

      {/* AI-drafted patient message modal */}
      {msgOpen && (
        <div
          className="fixed inset-0 z-40 flex items-end justify-center bg-black/40 md:items-center"
          onClick={() => setMsgOpen(false)}
        >
          <div
          ref={sheetRef}
          role="dialog"
          aria-modal="true"
          aria-label={`AI-drafted message for ${p.name}`}
          tabIndex={-1}
          onClick={(e) => e.stopPropagation()}
          className="animate-sheet-in max-h-[85vh] w-full max-w-md overflow-y-auto rounded-t-2xl bg-clinical-card p-4 shadow-xl focus:outline-none md:rounded-2xl"
          style={{ paddingBottom: "calc(1.5rem + var(--safe-bottom))" }}
        >
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-sm font-semibold text-clinical-accent">
                <Sparkles size={16} /> AI-drafted message
              </div>
              <button onClick={() => setMsgOpen(false)} className="text-clinical-muted active:text-clinical-ink">
                <X size={20} />
              </button>
            </div>

            {msgSent ? (
              <div role="status" aria-live="polite" className="flex flex-col items-center gap-3 py-8 text-center">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-green-50 text-green-600">
                  <CheckCircle2 size={28} />
                </div>
                <p className="text-sm font-medium text-clinical-ink">Message sent to {p.name}</p>
                <p className="text-xs text-clinical-muted">Logged to your Activity feed.</p>
                <button
                  onClick={() => setMsgOpen(false)}
                  className="mt-2 rounded-xl bg-clinical-accent px-6 py-2.5 text-sm font-semibold text-white active:bg-blue-700"
                >
                  Done
                </button>
              </div>
            ) : (
              <>
                <p className="mb-1 text-xs text-clinical-muted">
                  To patient · written in{" "}
                  <span className="font-medium text-clinical-ink">{msg?.language || lang}</span>
                </p>
                <div className="mb-2.5 flex items-center gap-1.5 overflow-x-auto pb-0.5">
                  <Languages size={13} className="shrink-0 text-clinical-muted" />
                  {langOptions.map((l) => (
                    <button
                      key={l}
                      onClick={() => loadMessage(l)}
                      disabled={msgLoading}
                      className={`shrink-0 rounded-full border px-2.5 py-1 text-xs font-medium transition active:scale-95 disabled:opacity-50 ${
                        lang === l
                          ? "border-clinical-accent bg-clinical-accent text-white"
                          : "border-clinical-line bg-clinical-card text-clinical-ink"
                      }`}
                    >
                      {l}
                    </button>
                  ))}
                </div>
                {msgLoading ? (
                  <div className="space-y-2 py-2">
                    <div className="h-3 w-full animate-pulse rounded bg-clinical-line" />
                    <div className="h-3 w-11/12 animate-pulse rounded bg-clinical-line" />
                    <div className="h-3 w-3/4 animate-pulse rounded bg-clinical-line" />
                  </div>
                ) : (
                  <div className="rounded-xl border border-clinical-line bg-clinical-bg p-3 text-sm leading-relaxed text-clinical-ink">
                    {msg?.message}
                  </div>
                )}
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <button
                    onClick={copyMessage}
                    disabled={msgLoading}
                    className="flex items-center justify-center gap-1.5 rounded-xl border border-clinical-line bg-clinical-card py-2.5 text-sm font-medium text-clinical-ink active:bg-clinical-bg disabled:opacity-50"
                  >
                    <Copy size={16} /> {copied ? "Copied" : "Copy"}
                  </button>
                  <button
                    onClick={sendMessage}
                    disabled={msgLoading}
                    className="flex items-center justify-center gap-1.5 rounded-xl bg-clinical-accent py-2.5 text-sm font-semibold text-white active:bg-blue-700 disabled:opacity-50"
                  >
                    <Send size={16} /> Send
                  </button>
                </div>
                <p className="mt-2 text-center text-[11px] text-clinical-muted">
                  Send is simulated for this demo and logs an outreach.
                </p>
              </>
            )}
          </div>
        </div>
      )}

      {/* Log Outreach CTA — mobile only: pinned just above the bottom nav (which
          itself clears the home-indicator safe area). On desktop this action
          moves into the detail header, so hide the floating bar at md+. */}
      <div
        className="fixed left-1/2 z-20 w-full max-w-md -translate-x-1/2 border-t border-clinical-line bg-clinical-card p-3 md:hidden"
        style={{ bottom: "var(--nav-h)" }}
      >
        <button
          onClick={() => nav(`/patient/${p.patient_id}/outreach${loc.search}`)}
          className="w-full rounded-xl bg-clinical-accent py-3.5 text-center text-base font-semibold text-white transition active:scale-[0.99] active:bg-blue-700"
        >
          Log Outreach
        </button>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  accent,
  small,
}: {
  label: string;
  value: string;
  accent?: boolean;
  small?: boolean;
}) {
  return (
    <div className="rounded-xl border border-clinical-line bg-clinical-card p-3">
      <div className="text-[11px] uppercase tracking-wide text-clinical-muted">{label}</div>
      <div
        className={`mt-0.5 font-bold ${small ? "text-sm" : "text-lg"} ${
          accent ? "text-risk-high" : "text-clinical-ink"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function ClinicalNotes({ patientId, notes }: { patientId: string; notes: ClinicalNote[] | null }) {
  const [summary, setSummary] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  if (notes === null) {
    return (
      <Card title="Clinical notes" icon={<FileText size={15} />}>
        <div className="h-3 w-2/3 animate-pulse rounded bg-clinical-line" />
      </Card>
    );
  }
  if (notes.length === 0) return null;

  const summarize = () => {
    setLoading(true);
    api
      .notesSummary(patientId)
      .then((s) => setSummary(s.summary))
      .catch(() => setSummary("Notes summary is temporarily unavailable."))
      .finally(() => setLoading(false));
  };

  const tone: Record<string, string> = {
    "Progress Note": "bg-blue-50 text-blue-700",
    "Discharge Summary": "bg-risk-risingbg text-risk-rising",
    "Telephone Encounter": "bg-green-50 text-green-700",
  };

  return (
    <Card
      title="Clinical notes"
      icon={<FileText size={15} />}
      action={
        <button
          onClick={summarize}
          disabled={loading}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-clinical-accent/10 px-3 py-1 text-xs font-semibold text-clinical-accent transition active:scale-95 disabled:opacity-50"
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
          {loading ? "Summarizing…" : "Summarize"}
        </button>
      }
    >
      {summary && (
        <div className="mb-3 rounded-xl border border-clinical-accent/30 bg-clinical-accent/5 p-3">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-clinical-accent">
            <Sparkles size={12} /> AI summary of recent notes
          </div>
          <p className="text-sm leading-relaxed text-clinical-ink">{summary}</p>
        </div>
      )}

      <ul className="divide-y divide-clinical-line">
        {notes.map((n, i) => (
          <li key={i} className="py-2.5">
            <button
              onClick={() => setOpenIdx(openIdx === i ? null : i)}
              className="flex w-full items-center gap-2 text-left"
            >
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${tone[n.note_type] || "bg-clinical-line text-clinical-muted"}`}>
                {n.note_type}
              </span>
              <span className="text-xs text-clinical-muted">{n.note_date}</span>
              {n.specialty && <span className="truncate text-xs text-clinical-muted">· {n.specialty}</span>}
              <ArrowRight
                size={13}
                className={`ml-auto shrink-0 text-clinical-muted transition-transform ${openIdx === i ? "rotate-90" : ""}`}
              />
            </button>
            {openIdx === i ? (
              <pre className="mt-2 whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-clinical-ink">
                {n.note_text}
              </pre>
            ) : (
              n.ai_summary && (
                <p className="mt-1 line-clamp-2 text-xs leading-snug text-clinical-muted">{n.ai_summary}</p>
              )
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function RecentHistory({ history }: { history: PatientHistory | null }) {
  if (!history) {
    return (
      <Card title="Recent history" icon={<ActivityIcon size={15} />}>
        <div className="space-y-2">
          <div className="h-3 w-2/3 animate-pulse rounded bg-clinical-line" />
          <div className="h-3 w-1/2 animate-pulse rounded bg-clinical-line" />
        </div>
      </Card>
    );
  }
  const { ed_visits, admissions } = history.utilization_90d;
  const hot = ed_visits > 0 || admissions > 0;
  const typeTone: Record<string, string> = {
    Emergency: "bg-risk-highbg text-risk-high",
    Inpatient: "bg-risk-risingbg text-risk-rising",
    Observation: "bg-amber-50 text-amber-800",
    Outpatient: "bg-blue-50 text-blue-700",
  };
  return (
    <Card title="Recent history" icon={<ActivityIcon size={15} />}>
      {/* 90-day utilization callout */}
      <div
        className={`mb-3 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium ${
          hot ? "bg-risk-highbg text-risk-high" : "bg-clinical-line text-clinical-muted"
        }`}
      >
        <span className="inline-flex items-center gap-1">
          <Ambulance size={15} /> {ed_visits} ED visit{ed_visits !== 1 ? "s" : ""}
        </span>
        <span className="opacity-40">·</span>
        <span className="inline-flex items-center gap-1">
          <BedDouble size={15} /> {admissions} admission{admissions !== 1 ? "s" : ""}
        </span>
        <span className="ml-auto text-xs font-normal opacity-70">last 90 days</span>
      </div>

      {history.encounters.length === 0 ? (
        <p className="text-sm text-clinical-muted">No recent encounters on record.</p>
      ) : (
        <ul className="divide-y divide-clinical-line">
          {history.encounters.map((e, i) => (
            <li key={`${e.admit_date}-${i}`} className="flex items-start justify-between gap-2 py-2.5">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                      typeTone[e.encounter_type] || "bg-clinical-line text-clinical-muted"
                    }`}
                  >
                    {e.encounter_type}
                  </span>
                  <span className="text-xs text-clinical-muted">{e.admit_date}</span>
                </div>
                <div className="mt-1 truncate text-sm font-medium text-clinical-ink">
                  {e.primary_diagnosis}
                </div>
                <div className="text-xs text-clinical-muted">
                  {e.service_line}
                  {e.los_days && e.los_days > 0 ? ` · LOS ${e.los_days}d` : ""}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function SdohItem({ icon, label, neutral }: { icon: React.ReactNode; label: string; neutral?: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
        neutral ? "bg-clinical-line text-clinical-ink" : "bg-amber-50 text-amber-800"
      }`}
    >
      {icon}
      {label}
    </span>
  );
}
