import { useEffect, useRef, useState } from "react";
import { Sparkles, Send, ChevronDown, MessageCircleQuestion } from "lucide-react";
import { api, type AskTurn } from "../api";

const SUGGESTIONS = [
  "What's driving this patient's risk?",
  "Draft a call script for the outreach",
  "What should I prioritize on the call?",
];

/**
 * "Ask AI about this patient" — a scoped, grounded mini-chat on the Patient
 * Detail screen. Mirrors the Genie "ask your data" experience for ONE patient.
 * Collapsible panel, scrollable Q&A thread, suggested-question chips, and short
 * multi-turn context (the running thread is sent back as `history`). Session
 * only — not persisted across reloads.
 */
export default function AskAI({ patientId }: { patientId: string }) {
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const threadRef = useRef<HTMLDivElement>(null);

  // Keep the thread scrolled to the latest message.
  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
  }, [turns, loading]);

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || loading) return;
    setInput("");
    // History = the thread BEFORE this question (capped server-side to ~6 turns).
    const history = turns;
    setTurns((t) => [...t, { role: "user", content: q }]);
    setLoading(true);
    try {
      const res = await api.ask(patientId, q, history);
      setTurns((t) => [...t, { role: "assistant", content: res.answer }]);
    } catch {
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          content:
            "Sorry — I couldn't reach the AI copilot just now. Please try again in a moment.",
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="overflow-hidden rounded-xl border border-clinical-accent/20 bg-clinical-card">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-semibold text-clinical-accent active:bg-blue-50"
      >
        <Sparkles size={16} />
        Ask AI about this patient
        <ChevronDown
          size={18}
          className={`ml-auto text-clinical-muted transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="border-t border-clinical-accent/20 px-3 pb-3 pt-2">
          {/* Q&A thread */}
          <div ref={threadRef} className="max-h-72 space-y-2 overflow-y-auto py-1">
            {turns.length === 0 && !loading && (
              <div className="flex flex-col items-center gap-1 py-4 text-center text-clinical-muted">
                <MessageCircleQuestion size={22} className="text-blue-300" />
                <p className="text-xs">
                  Ask anything about this patient — answers are grounded in their record.
                </p>
              </div>
            )}
            {turns.map((t, i) =>
              t.role === "user" ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-clinical-accent px-3 py-2 text-sm text-white">
                    {t.content}
                  </div>
                </div>
              ) : (
                <div key={i} className="flex justify-start">
                  <div className="max-w-[88%] whitespace-pre-wrap rounded-2xl rounded-bl-sm bg-blue-50 px-3 py-2 text-sm leading-relaxed text-clinical-ink">
                    {t.content}
                  </div>
                </div>
              )
            )}
            {loading && (
              <div className="flex justify-start">
                <div className="flex items-center gap-1.5 rounded-2xl rounded-bl-sm bg-blue-50 px-3 py-2.5">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-400 [animation-delay:-0.2s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-400 [animation-delay:-0.1s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-400" />
                </div>
              </div>
            )}
          </div>

          {/* Suggested-question chips (prefill + send) */}
          {turns.length === 0 && (
            <div className="mt-1 flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => ask(s)}
                  disabled={loading}
                  className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-clinical-accent active:bg-blue-100 disabled:opacity-50"
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          {/* Input + send */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              ask(input);
            }}
            className="mt-2 flex items-center gap-2"
          >
            <input
              name="askai-question"
              aria-label="Ask about this patient"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about this patient…"
              className="min-w-0 flex-1 rounded-xl border border-clinical-line bg-clinical-bg px-3 py-2.5 text-sm text-clinical-ink outline-none focus:border-clinical-accent"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-clinical-accent text-white active:bg-blue-700 disabled:opacity-40"
              aria-label="Send"
            >
              <Send size={18} />
            </button>
          </form>
        </div>
      )}
    </section>
  );
}
