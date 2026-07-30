import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ChevronLeft, Check, CheckCircle2, Sparkles, Mic, MicOff, Loader2 } from "lucide-react";
import { api, type PatientDetail } from "../api";

const ACTIONS = ["Called", "Left voicemail", "Scheduled appointment", "Unable to reach", "Closed gap"];
const FOLLOW_UPS = ["No follow-up", "in 1 week", "in 2 weeks", "in 1 month"];

// Web Speech API is vendor-prefixed in some browsers and absent in others.
const SpeechRecognitionCtor: any =
  typeof window !== "undefined"
    ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    : undefined;
const SPEECH_SUPPORTED = !!SpeechRecognitionCtor;

export default function LogOutreach() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [p, setP] = useState<PatientDetail | null>(null);
  const [action, setAction] = useState<string>("Called");
  const [gaps, setGaps] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const [followUp, setFollowUp] = useState("No follow-up");
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);

  // AI-assisted logging (Layer 1): dictate or type a recap -> AI fills the form.
  const [recap, setRecap] = useState("");
  const [parsing, setParsing] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [autoFilled, setAutoFilled] = useState(false);
  const [listening, setListening] = useState(false);
  // In-app speech recognition is unreliable inside the iOS app's WKWebView (the
  // API may exist but never captures audio). If a start attempt errors before we
  // get any transcript, we hide the mic and point the user at the keyboard mic.
  const [dictationFailed, setDictationFailed] = useState(false);
  const recognitionRef = useRef<any>(null);
  const recapBaseRef = useRef("");
  const gotResultRef = useRef(false);

  useEffect(() => {
    if (id) api.patient(id).then(setP).catch(() => {});
  }, [id]);

  // Clean up any active speech recognition on unmount.
  useEffect(() => {
    return () => {
      try {
        recognitionRef.current?.stop?.();
      } catch {
        /* no-op */
      }
    };
  }, []);

  const autoFill = async () => {
    if (!id || !recap.trim() || parsing) return;
    setParsing(true);
    setAiError(null);
    try {
      const r = await api.parseOutreach(id, recap.trim());
      // Pre-fill the existing controls (human reviews/adjusts before Save).
      setAction(ACTIONS.includes(r.action) ? r.action : "Called");
      // Only check gap_ids that are real open gaps on this patient.
      const valid = new Set((p?.open_gaps ?? []).map((g) => g.gap_id));
      setGaps(new Set((r.addressed_gap_ids ?? []).filter((g) => valid.has(g))));
      setFollowUp(r.follow_up && FOLLOW_UPS.includes(r.follow_up) ? r.follow_up : "No follow-up");
      if (r.note) setNote(r.note);
      setAutoFilled(true);
      if (r.error) setAiError("AI is temporarily unavailable — review the form below.");
    } catch {
      setAiError("Could not auto-fill. You can still log this manually below.");
    } finally {
      setParsing(false);
    }
  };

  const toggleDictation = () => {
    if (!SPEECH_SUPPORTED) return;
    if (listening) {
      try {
        recognitionRef.current?.stop?.();
      } catch {
        /* no-op */
      }
      setListening(false);
      return;
    }
    try {
      const rec = new SpeechRecognitionCtor();
      rec.lang = "en-US";
      rec.interimResults = true;
      rec.continuous = true;
      recapBaseRef.current = recap ? recap.trimEnd() + " " : "";
      gotResultRef.current = false;
      rec.onresult = (e: any) => {
        gotResultRef.current = true;
        let transcript = "";
        for (let i = 0; i < e.results.length; i++) {
          transcript += e.results[i][0].transcript;
        }
        setRecap(recapBaseRef.current + transcript);
      };
      rec.onerror = () => {
        setListening(false);
        // Errored without ever capturing audio (typical in the iOS WKWebView) —
        // retire the in-app mic and surface the keyboard-dictation hint instead.
        if (!gotResultRef.current) setDictationFailed(true);
      };
      rec.onend = () => setListening(false);
      recognitionRef.current = rec;
      rec.start();
      setListening(true);
    } catch {
      setListening(false);
      setDictationFailed(true);
    }
  };

  const toggleGap = (g: string) =>
    setGaps((prev) => {
      const n = new Set(prev);
      n.has(g) ? n.delete(g) : n.add(g);
      return n;
    });

  const save = async () => {
    if (!id) return;
    setSaving(true);
    try {
      const gapIds = Array.from(gaps);
      const gapMeasures = p
        ? p.open_gaps.filter((g) => gaps.has(g.gap_id)).map((g) => g.measure)
        : [];
      await api.logOutreach(id, {
        action,
        addressed_gap_ids: gapIds,
        note: note || undefined,
        follow_up: followUp === "No follow-up" ? undefined : followUp,
        patient_name: p?.name,
        risk_tier: p?.risk_tier,
        addressed_gap_measures: gapMeasures,
      });
      setDone(true);
      setTimeout(() => nav("/"), 1100);
    } catch {
      setSaving(false);
    }
  };

  if (done) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex h-[80vh] flex-col items-center justify-center gap-3 px-8 text-center"
      >
        <CheckCircle2 size={56} className="text-green-600" />
        <h2 className="text-lg font-semibold text-clinical-ink">Outreach logged</h2>
        <p className="text-sm text-clinical-muted">Worklist re-ranked. Returning…</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl">
      <header className="sticky top-0 z-10 border-b border-clinical-line bg-clinical-card px-3 pb-3 pt-4 shadow-sm">
        <button onClick={() => nav(-1)} className="mb-2 flex items-center gap-1 text-sm text-clinical-accent">
          <ChevronLeft size={18} /> Back
        </button>
        <div className="flex items-start justify-between gap-2">
          <div>
            <h1 className="text-xl font-bold text-clinical-ink">Log Outreach</h1>
            {p && <p className="text-xs text-clinical-muted">{p.name}</p>}
          </div>
          {/* Desktop: primary submit lives in the header (the mobile fixed Save
              bar below is hidden at md+). */}
          <button
            onClick={save}
            disabled={saving}
            className="hidden shrink-0 items-center gap-1.5 rounded-lg bg-clinical-accent px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 active:scale-[0.99] disabled:opacity-60 md:inline-flex"
          >
            <Check size={16} /> {saving ? "Saving…" : "Save Outreach"}
          </button>
        </div>
      </header>

      {/* pb-56 (224px) clears the mobile fixed Save bar, which reserves the
          bottom ~137px of the viewport (60px bottom nav + ~77px Save bar). This
          keeps the Follow-up control fully scrollable into view and never
          hidden, even when a patient has many care-gap checkboxes. On desktop
          the Save action is in the header, so drop the extra bottom padding. */}
      <div className="space-y-4 p-4 pb-56 md:pb-6">
        {/* AI-assisted logging: dictate or type a recap, then auto-fill the form. */}
        <section className="rounded-xl border border-clinical-accent/30 bg-clinical-accent/5 p-3">
          <div className="mb-2 flex items-center gap-1.5">
            <Sparkles size={15} className="text-clinical-accent" />
            <h2 className="text-sm font-semibold text-clinical-ink">Recap the call</h2>
            <span className="ml-auto text-[11px] font-medium text-clinical-accent">AI assist</span>
          </div>
          <div className="relative">
            <textarea
              value={recap}
              onChange={(e) => setRecap(e.target.value)}
              rows={3}
              placeholder={
                listening
                  ? "Listening… speak your recap"
                  : "Type or dictate, e.g. “Called her, she'll schedule her A1c and mammogram, follow up in two weeks.”"
              }
              className={`w-full rounded-lg border bg-clinical-card p-3 ${
                SPEECH_SUPPORTED && !dictationFailed ? "pr-11" : ""
              } text-sm focus:border-clinical-accent focus:outline-none ${
                listening ? "border-clinical-accent" : "border-clinical-line"
              }`}
            />
            {SPEECH_SUPPORTED && !dictationFailed && (
              <button
                type="button"
                onClick={toggleDictation}
                aria-label={listening ? "Stop dictation" : "Start dictation"}
                className={`absolute right-2 top-2 flex h-8 w-8 items-center justify-center rounded-full ${
                  listening
                    ? "animate-pulse bg-red-500 text-white"
                    : "bg-clinical-accent/10 text-clinical-accent"
                }`}
              >
                {listening ? <MicOff size={16} /> : <Mic size={16} />}
              </button>
            )}
          </div>
          {(!SPEECH_SUPPORTED || dictationFailed) && (
            <p className="mt-1.5 flex items-center gap-1 text-[11px] text-clinical-muted">
              <Mic size={11} /> To dictate, tap the microphone on your phone's keyboard, then Auto-fill.
            </p>
          )}
          <button
            type="button"
            onClick={autoFill}
            disabled={parsing || !recap.trim()}
            className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg bg-clinical-accent py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          >
            {parsing ? (
              <>
                <Loader2 size={16} className="animate-spin" /> Reading recap…
              </>
            ) : (
              <>
                <Sparkles size={16} /> Auto-fill form
              </>
            )}
          </button>
          {aiError && <p className="mt-2 text-xs text-amber-600">{aiError}</p>}
          {autoFilled && !aiError && (
            <p className="mt-2 text-xs text-clinical-muted">
              Form pre-filled from your recap — review and adjust below, then Save.
            </p>
          )}
        </section>

        <Section title="Action">
          <div className="flex flex-wrap gap-2">
            {ACTIONS.map((a) => (
              <button
                key={a}
                onClick={() => setAction(a)}
                className={`rounded-full px-3.5 py-2 text-sm font-medium transition ${
                  action === a
                    ? "bg-clinical-accent text-white"
                    : "border border-clinical-line bg-clinical-card text-clinical-ink hover:bg-clinical-bg"
                }`}
              >
                {a}
              </button>
            ))}
          </div>
        </Section>

        <Section title="Care gaps addressed">
          {p && p.open_gaps.length > 0 ? (
            <div className="space-y-2">
              {p.open_gaps.map((g) => {
                const on = gaps.has(g.gap_id);
                return (
                  <button
                    key={g.gap_id}
                    onClick={() => toggleGap(g.gap_id)}
                    className="flex w-full items-center gap-3 rounded-lg border border-clinical-line bg-clinical-card p-3 text-left transition hover:bg-clinical-bg"
                  >
                    <span
                      className={`flex h-5 w-5 items-center justify-center rounded border ${
                        on ? "border-clinical-accent bg-clinical-accent text-white" : "border-slate-300"
                      }`}
                    >
                      {on && <Check size={14} />}
                    </span>
                    <span className="text-sm text-clinical-ink">{g.measure}</span>
                  </button>
                );
              })}
            </div>
          ) : (
            <p className="text-sm text-clinical-muted">No open gaps to address.</p>
          )}
        </Section>

        <Section title="Note (optional)">
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            placeholder="Add a brief note…"
            className="w-full rounded-lg border border-clinical-line p-3 text-sm focus:border-clinical-accent focus:outline-none"
          />
        </Section>

        <Section title="Follow-up">
          <select
            value={followUp}
            onChange={(e) => setFollowUp(e.target.value)}
            className="w-full rounded-lg border border-clinical-line bg-clinical-card p-3 text-sm"
          >
            {FOLLOW_UPS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </Section>
      </div>

      {/* Mobile only: fixed Save bar above the bottom nav. On desktop the Save
          action moves into the header, so hide this floating bar at md+. */}
      <div className="fixed bottom-[60px] left-1/2 z-20 w-full max-w-md -translate-x-1/2 border-t border-clinical-line bg-clinical-card p-3 md:hidden">
        <button
          onClick={save}
          disabled={saving}
          className="w-full rounded-xl bg-clinical-accent py-3.5 text-base font-semibold text-white disabled:opacity-60"
        >
          {saving ? "Saving…" : "Save Outreach"}
        </button>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold text-clinical-ink">{title}</h2>
      {children}
    </section>
  );
}
