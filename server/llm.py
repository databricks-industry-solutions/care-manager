"""Foundation Model API client via AI Gateway (OpenAI-compatible)."""
import json
import re
from datetime import datetime
from typing import Any

from openai import OpenAI

from . import store
from .config import AI_GATEWAY_URL, SERVING_ENDPOINT, get_oauth_token, get_workspace_host

SYSTEM_PROMPT = (
    "You are an outpatient (ambulatory) care-management assistant supporting a "
    "community-based nurse care manager at a primary-care clinic. The patient lives "
    "in the community and is NOT post-discharge. Write a concise, actionable, "
    "non-judgmental brief for a PROACTIVE outreach call: the goal is to close open "
    "care gaps, address SDOH barriers, and prevent avoidable hospitalizations and ED "
    "visits before they happen. Do NOT use discharge, readmission, or post-acute "
    "language. Do NOT invent clinical facts beyond what is provided. "
    "Respond ONLY with a JSON object with two keys: "
    '"summary" (2-3 plain-language sentences framing why to reach out now and what '
    'to focus on) and "next_best_action" (one short imperative line, e.g. a call to '
    "schedule a visit or close a specific gap). No markdown, no extra keys."
)


def _client() -> OpenAI:
    # Prefer an explicit gateway override; otherwise use this workspace's own
    # OpenAI-compatible Foundation Model API endpoint so the app is portable.
    base = AI_GATEWAY_URL or f"{get_workspace_host().rstrip('/')}/serving-endpoints"
    return OpenAI(api_key=get_oauth_token(), base_url=base.rstrip("/"))


def _build_profile(patient: dict[str, Any]) -> str:
    sdoh = patient.get("sdoh", {})
    barriers = [
        k.replace("_", " ")
        for k in ("transportation_barrier", "food_insecurity", "housing_instability")
        if sdoh.get(k)
    ]
    gaps = [f"{g['measure']} (open {g.get('days_open')}d)" for g in patient.get("open_gaps", [])]
    admit = patient.get("predicted_admit_prob")
    profile = {
        "risk_tier": patient.get("risk_tier"),
        "care_priority_score_0_100": patient.get("care_priority_score"),
        "age": patient.get("age"),
        "sex": patient.get("sex"),
        "avoidable_hospitalization_risk_12mo_pct": (
            round(admit * 100, 1) if admit is not None else None
        ),
        "chronic_conditions": patient.get("conditions"),
        "open_care_gaps": gaps,
        "sdoh_barriers": barriers or ["none reported"],
        "preferred_language": sdoh.get("preferred_language"),
        "interpreter_needed": sdoh.get("interpreter_needed"),
        "days_since_last_visit": patient.get("days_since_visit"),
    }
    # Recent encounters + 90-day utilization, when supplied (used by the ask
    # copilot for richer grounding; the brief omits these, leaving them absent).
    encounters = patient.get("recent_encounters")
    if encounters:
        profile["recent_encounters"] = encounters
    util = patient.get("utilization_90d")
    if util:
        profile["utilization_last_90_days"] = util
    return json.dumps(profile, indent=2)


def generate_brief(patient: dict[str, Any], user: Any = None) -> dict[str, Any]:
    pid = patient["patient_id"]
    cached = store.get_brief(user, pid)
    if cached:
        return cached

    user_msg = (
        "Patient structured profile:\n" + _build_profile(patient) +
        "\n\nGenerate the proactive outpatient care-management outreach brief now."
    )
    try:
        resp = _client().chat.completions.create(
            model=SERVING_ENDPOINT,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=400,
            temperature=0.3,
        )
        content = resp.choices[0].message.content or ""
        brief = _parse(content)
    except Exception as e:
        brief = {
            "summary": "AI brief is temporarily unavailable. Review the patient's open care "
                       "gaps, risk tier, and SDOH barriers below to plan outreach.",
            "next_best_action": "Call the patient to schedule a visit and address open care gaps.",
            "error": str(e),
        }
    brief["generated_at"] = datetime.utcnow().isoformat()
    store.set_brief(user, pid, brief)
    return brief


_MESSAGE_SYSTEM_PROMPT = (
    "You are a warm, plain-language outreach assistant for a community-based nurse "
    "care manager at Unity Health, a primary-care clinic. Draft a SHORT outreach "
    "message addressed directly TO THE PATIENT (second person, e.g. 'Hi <first name>'). "
    "Requirements: 2-4 sentences; warm and respectful, never clinical or alarming; "
    "reference the patient's top open care gap(s) in everyday words (e.g. an overdue "
    "A1c check, a wellness visit, a mammogram); and include ONE clear call to action "
    "(e.g. call the clinic to schedule, or reply to confirm a time). Sign off as "
    "'Your care team at Unity Health'. CRITICAL: write the ENTIRE message in the "
    "requested TARGET LANGUAGE. If the target language is not English, write it fully "
    "in that language (do NOT include an English translation). Do not invent "
    "clinical facts beyond the care gaps provided. "
    'Respond ONLY with a JSON object: {"message": "<the full message text>", '
    '"language": "<language you wrote it in>"}. No markdown, no extra keys.'
)


def _build_message_profile(patient: dict[str, Any], target_language: str = "English") -> str:
    sdoh = patient.get("sdoh", {})
    gaps = [g["measure"] for g in patient.get("open_gaps", [])]
    name = patient.get("name") or ""
    first_name = name.split(" ")[0] if name else ""
    profile = {
        "patient_first_name": first_name,
        "target_language": target_language,
        "patient_preferred_language": sdoh.get("preferred_language") or "English",
        "interpreter_needed": sdoh.get("interpreter_needed"),
        "open_care_gaps": gaps or ["a routine wellness visit"],
        "risk_tier": patient.get("risk_tier"),
    }
    return json.dumps(profile, indent=2)


def generate_message(
    patient: dict[str, Any], user: Any = None, language: str = "English"
) -> dict[str, Any]:
    """Draft a short, warm, patient-facing outreach message.

    Defaults to English; pass `language` to draft (or translate) into a secondary
    language on request. Cached per user+patient+language so each language variant
    is generated once.
    """
    target_language = (language or "English").strip() or "English"
    pid = patient["patient_id"]
    cache_key = f"{pid}::{target_language.lower()}"
    cached = store.get_message(user, cache_key)
    if cached:
        return cached

    user_msg = (
        "Patient context:\n" + _build_message_profile(patient, target_language) +
        f"\n\nDraft the patient-facing outreach message now, written in {target_language}."
    )
    try:
        resp = _client().chat.completions.create(
            model=SERVING_ENDPOINT,
            messages=[
                {"role": "system", "content": _MESSAGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            # Generous headroom: non-Latin scripts (Chinese, Vietnamese) consume
            # tokens faster, so a 2-4 sentence message can exceed a tight budget
            # and get cut off mid-JSON. 900 leaves room for any target language.
            max_tokens=900,
            temperature=0.5,
        )
        content = resp.choices[0].message.content or ""
        msg = _parse_message(content)
    except Exception as e:
        msg = {
            "message": (
                "Hi, this is your care team at Unity Health reaching out. We'd love to "
                "help you stay on top of your health and have a few items we'd like to "
                "schedule. Please call the clinic when you have a moment so we can find a "
                "time that works for you."
            ),
            "language": target_language,
            "error": str(e),
        }
    msg["generated_at"] = datetime.utcnow().isoformat()
    store.set_message(user, cache_key, msg)
    return msg


_ASK_SYSTEM_PROMPT = (
    "You are an outpatient (ambulatory) care-management copilot supporting a "
    "community-based nurse care manager at Unity Health, a primary-care clinic. "
    "The care manager is asking free-form questions about ONE specific patient. "
    "Answer ONLY using the structured patient context provided below — risk tier, "
    "Care Priority Score, avoidable-hospitalization risk, predicted annual cost, "
    "chronic conditions, SDOH barriers and preferred language, open care gaps, and "
    "recent encounters. Do NOT invent or assume clinical facts (labs, vitals, "
    "medications, diagnoses) that are not in the context; if asked about something "
    "not provided, say it isn't in this patient's record and suggest how to find it. "
    "This patient lives in the community and is NOT post-discharge — use proactive "
    "outpatient framing and never use discharge, readmission, or post-acute language. "
    "Keep answers concise, specific to THIS patient (reference their actual "
    "conditions, gaps, and barriers), and actionable for a phone outreach. Plain "
    "text only — short paragraphs or a few bullet lines, no markdown headers."
)

_MAX_HISTORY_TURNS = 6


_NOTES_SUMMARY_PROMPT = (
    "You are a care-management assistant. Summarize this patient's recent clinical notes for "
    "a nurse about to make a proactive outreach call. In 3-4 sentences capture: the main "
    "clinical picture, any change or trend across visits, and any barriers or red flags "
    "(non-adherence, transportation, cost, worsening symptoms, caregiver strain) mentioned in "
    "the narrative. Ground ONLY in the notes provided — do not invent. Plain text, no markdown."
)


def summarize_notes(patient: dict[str, Any], notes: list[dict[str, Any]]) -> dict[str, Any]:
    """Cross-note synthesis of a patient's recent clinical notes for call prep."""
    notes = [n for n in (notes or []) if n.get("note_text")]
    if not notes:
        return {"summary": "No clinical notes on file for this patient."}
    blob = "\n\n".join(
        f"[{n.get('note_type')} · {n.get('note_date')}] {n.get('note_text')}" for n in notes[:5]
    )
    try:
        resp = _client().chat.completions.create(
            model=SERVING_ENDPOINT,
            messages=[
                {"role": "system", "content": _NOTES_SUMMARY_PROMPT},
                {"role": "user", "content": f"Patient: {patient.get('name') or ''}\n\nRecent notes:\n{blob}\n\nSummarize now."},
            ],
            max_tokens=350,
            temperature=0.3,
        )
        return {"summary": (resp.choices[0].message.content or "").strip(),
                "generated_at": datetime.utcnow().isoformat()}
    except Exception as e:
        return {"summary": "Notes summary is temporarily unavailable.", "error": str(e)}


def answer_question(
    patient: dict[str, Any],
    question: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Grounded, conversational Q&A about a single patient.

    `history` is a list of prior turns ([{role, content}, ...]); we cap it to the
    last ~6 turns to keep latency and token use reasonable. Not cached — each
    question is a fresh turn within the session.
    """
    name = patient.get("name") or "this patient"
    context = (
        f"Patient: {name}\n"
        "Structured patient context (the ONLY facts you may rely on):\n"
        + _build_profile(patient)
    )
    # Ground in recent free-text clinical notes too, when provided — lets the
    # care manager ask "did they mention transportation / meds / new symptoms?"
    notes = patient.get("recent_notes") or []
    if notes:
        blob = "\n\n".join(
            f"[{n.get('note_type')} · {n.get('note_date')}] {n.get('note_text')}"
            for n in notes[:4] if n.get("note_text")
        )
        if blob:
            context += "\n\nRecent clinical notes (you MAY quote and cite these by date):\n" + blob

    messages: list[dict[str, str]] = [
        {"role": "system", "content": _ASK_SYSTEM_PROMPT},
        {"role": "system", "content": context},
    ]
    # Append short prior context, keeping only valid user/assistant turns.
    for turn in (history or [])[-_MAX_HISTORY_TURNS:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question.strip()})

    try:
        resp = _client().chat.completions.create(
            model=SERVING_ENDPOINT,
            messages=messages,
            max_tokens=600,
            temperature=0.3,
        )
        answer = (resp.choices[0].message.content or "").strip()
        if not answer:
            answer = "I couldn't generate an answer for that. Please try rephrasing."
    except Exception as e:
        answer = (
            "The AI copilot is temporarily unavailable. Please try again in a moment, "
            "or review this patient's open care gaps, risk tier, and SDOH barriers below."
        )
        return {"answer": answer, "generated_at": datetime.utcnow().isoformat(), "error": str(e)}
    return {"answer": answer, "generated_at": datetime.utcnow().isoformat()}


_OUTREACH_ACTIONS = [
    "Called",
    "Left voicemail",
    "Scheduled appointment",
    "Unable to reach",
    "Closed gap",
]
# Follow-up values must match the LogOutreach dropdown option VALUES exactly
# ("No follow-up" is the UI's null sentinel; the model returns one of these or null).
_OUTREACH_FOLLOW_UPS = ["in 1 week", "in 2 weeks", "in 1 month"]

_PARSE_OUTREACH_SYSTEM_PROMPT = (
    "You are a documentation assistant for a community-based nurse care manager at "
    "Unity Health, a primary-care clinic. The care manager just finished a patient "
    "outreach interaction and dictated or typed a free-text recap. Convert that recap "
    "into a structured outreach log entry for the clinic's care-management app. "
    "You MUST ground every field ONLY in the recap text and the lists provided below "
    "— do NOT invent gaps, actions, or follow-ups that are not supported.\n\n"
    "Return ONLY a JSON object with exactly these keys:\n"
    '  "action": one of EXACTLY these strings (pick the single best match; if unclear '
    'default to "Called"): ["Called","Left voicemail","Scheduled appointment",'
    '"Unable to reach","Closed gap"].\n'
    '  "addressed_gap_ids": an array of gap_id strings, chosen ONLY from the '
    "OPEN_CARE_GAPS list below, for the measures the recap says were discussed, "
    "addressed, scheduled, or closed. Match by measure meaning (e.g. \"A1c\" or "
    "\"blood sugar\" -> a Hemoglobin A1c / diabetes measure; \"mammogram\" -> a breast "
    "cancer screening measure; \"blood pressure\" -> a hypertension/BP control measure). "
    "Use the EXACT gap_id values. If no gap is clearly referenced, return [].\n"
    '  "follow_up": one of EXACTLY ["in 1 week","in 2 weeks","in 1 month"], or null. '
    "Map natural phrases (\"next week\"->\"in 1 week\", \"a couple weeks\"/\"two weeks\""
    "->\"in 2 weeks\", \"next month\"/\"in a few weeks\"->\"in 1 month\"). If no "
    "follow-up is mentioned, return null.\n"
    '  "note": a cleaned, concise, professional clinical note of 1-2 sentences '
    "summarizing the recap in third person. Do NOT add facts not in the recap.\n\n"
    "No markdown, no code fences, no extra keys."
)


def parse_outreach(patient: dict[str, Any], text: str) -> dict[str, Any]:
    """Parse a care manager's free-text/dictated recap into a structured outreach
    log the Log Outreach form can pre-fill.

    Grounded ONLY in the recap text, the patient's OPEN care gaps (gap_id+measure),
    and the allowed action/follow-up enums. Never invents gaps not in the list.
    Returns: {action, addressed_gap_ids, follow_up, note}.
    """
    open_gaps = [
        {"gap_id": g["gap_id"], "measure": g["measure"]}
        for g in patient.get("open_gaps", [])
    ]
    valid_gap_ids = {g["gap_id"] for g in open_gaps}

    user_msg = (
        "OPEN_CARE_GAPS (the ONLY gaps you may reference; map mentions to these "
        "gap_ids):\n" + json.dumps(open_gaps, indent=2) +
        "\n\nCARE_MANAGER_RECAP (free text / dictation):\n" + text.strip() +
        "\n\nProduce the structured outreach JSON now."
    )

    fallback = {
        "action": "Called",
        "addressed_gap_ids": [],
        "follow_up": None,
        "note": text.strip()[:280],
    }

    try:
        resp = _client().chat.completions.create(
            model=SERVING_ENDPOINT,
            messages=[
                {"role": "system", "content": _PARSE_OUTREACH_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=500,
            temperature=0.1,
        )
        content = resp.choices[0].message.content or ""
        parsed = _parse_outreach_json(content, valid_gap_ids)
    except Exception as e:
        fallback["error"] = str(e)
        return fallback

    parsed["generated_at"] = datetime.utcnow().isoformat()
    return parsed


def _parse_outreach_json(content: str, valid_gap_ids: set[str]) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    data = json.loads(content)

    action = (data.get("action") or "").strip()
    if action not in _OUTREACH_ACTIONS:
        action = "Called"

    raw_ids = data.get("addressed_gap_ids") or []
    # Defensively keep ONLY gap_ids that are real open gaps for this patient.
    gap_ids = [g for g in raw_ids if isinstance(g, str) and g in valid_gap_ids]

    follow_up = data.get("follow_up")
    if isinstance(follow_up, str):
        follow_up = follow_up.strip()
    if follow_up not in _OUTREACH_FOLLOW_UPS:
        follow_up = None

    note = (data.get("note") or "").strip()

    return {
        "action": action,
        "addressed_gap_ids": gap_ids,
        "follow_up": follow_up,
        "note": note,
    }


def _salvage_json_string(content: str, key: str) -> str:
    """Extract the value of a JSON string field even when the surrounding JSON is
    truncated or malformed (e.g. the model hit max_tokens mid-message). Walks from
    the opening quote, honoring escapes, and stops at the closing quote OR the end
    of the (cut-off) content — so we return clean prose, never a broken JSON dump.
    """
    m = re.search(rf'"{re.escape(key)}"\s*:\s*"', content)
    if not m:
        return ""
    i = m.end()
    out: list[str] = []
    escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}
    while i < len(content):
        ch = content[i]
        if ch == "\\" and i + 1 < len(content):
            out.append(escapes.get(content[i + 1], content[i + 1]))
            i += 2
            continue
        if ch == '"':  # closing quote of the value
            break
        out.append(ch)
        i += 1
    return "".join(out).strip()


def _parse_message(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()
    try:
        data = json.loads(content)
        return {
            "message": (data.get("message") or "").strip(),
            "language": (data.get("language") or "English").strip(),
        }
    except Exception:
        # Truncated/invalid JSON — salvage the message text instead of surfacing a
        # cut-off raw JSON blob to the care manager.
        msg = _salvage_json_string(content, "message")
        lang = _salvage_json_string(content, "language") or "English"
        if not msg:
            msg = content  # no recognizable structure; return what we have, uncapped
        return {"message": msg, "language": lang}


def _parse(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    try:
        data = json.loads(content)
        return {
            "summary": data.get("summary", "").strip(),
            "next_best_action": data.get("next_best_action", "").strip(),
        }
    except Exception:
        return {"summary": content[:600], "next_best_action": ""}
