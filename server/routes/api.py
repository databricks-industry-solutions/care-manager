import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from .. import data, store
from ..config import SESSION_COOKIE, current_user
from ..llm import answer_question, generate_brief, generate_message, parse_outreach, summarize_notes

router = APIRouter()


def _user(request: Request, response: Response) -> str:
    """Resolve the per-request end-user key.

    Prefers the Databricks-forwarded identity headers (X-Forwarded-Email etc.).
    If none are present (e.g. local dev, or a header-stripping proxy), fall back
    to a stable per-session cookie we set ourselves so two browser sessions on
    the same host still get isolated state. Last resort is "anon".
    """
    u = current_user(request)
    if u:
        return u
    # No forwarded identity — establish/keep a per-session cookie.
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        cookie = f"sess-{uuid.uuid4().hex[:16]}"
        response.set_cookie(
            SESSION_COOKIE, cookie, max_age=60 * 60 * 24, httponly=True, samesite="lax"
        )
    return cookie


@router.get("/worklist")
def worklist(request: Request, response: Response):
    return {"patients": data.get_worklist(_user(request, response))}


@router.get("/patients/{patient_id}")
def patient_detail(patient_id: str, request: Request, response: Response):
    p = data.get_patient_detail(patient_id, _user(request, response))
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    return p


@router.get("/patients/{patient_id}/brief")
def patient_brief(patient_id: str, request: Request, response: Response):
    user = _user(request, response)
    p = data.get_patient_detail(patient_id, user)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    return generate_brief(p, user)


@router.get("/patients/{patient_id}/history")
def patient_history(patient_id: str, request: Request, response: Response):
    """Recent encounters + 90-day ED/admission utilization callout."""
    _user(request, response)  # establish session cookie if needed
    return data.get_patient_history(patient_id)


def _drafted_message(
    patient_id: str, request: Request, response: Response, lang: str = "English"
):
    user = _user(request, response)
    p = data.get_patient_detail(patient_id, user)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    return generate_message(p, user, language=lang)


@router.get("/patients/{patient_id}/message")
def patient_message_get(
    patient_id: str, request: Request, response: Response, lang: str = "English"
):
    """Generate (or return cached) AI-drafted patient-facing outreach message.

    Defaults to English; pass `?lang=<language>` to draft/translate into a secondary
    language on request.
    """
    return _drafted_message(patient_id, request, response, lang)


@router.post("/patients/{patient_id}/message")
def patient_message_post(
    patient_id: str, request: Request, response: Response, lang: str = "English"
):
    """Same as GET — POST kept for clients that prefer a non-cached re-draft semantics."""
    return _drafted_message(patient_id, request, response, lang)


class AskTurn(BaseModel):
    role: str
    content: str


class AskIn(BaseModel):
    question: str
    history: list[AskTurn] = []


@router.post("/patients/{patient_id}/ask")
def patient_ask(patient_id: str, body: AskIn, request: Request, response: Response):
    """Grounded, conversational Q&A about THIS patient.

    Pulls the same Lakebase-backed patient context the brief uses, enriches it
    with recent encounters / 90-day utilization for grounding, then answers the
    user's question (with short multi-turn history) via the AI Gateway.
    """
    user = _user(request, response)
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")
    p = data.get_patient_detail(patient_id, user)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    # Enrich grounding context with recent encounter history + clinical notes.
    try:
        hist = data.get_patient_history(patient_id)
        p = {
            **p,
            "recent_encounters": hist.get("encounters", []),
            "utilization_90d": hist.get("utilization_90d"),
        }
    except Exception:
        pass
    try:
        p = {**p, "recent_notes": data.get_patient_notes(patient_id)}
    except Exception:
        pass
    turns = [{"role": t.role, "content": t.content} for t in body.history]
    return answer_question(p, question, turns)


@router.get("/patients/{patient_id}/notes")
def patient_notes(patient_id: str, request: Request, response: Response):
    """Recent free-text clinical notes for this patient."""
    user = _user(request, response)
    p = data.get_patient_detail(patient_id, user)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    return {"notes": data.get_patient_notes(patient_id)}


@router.get("/patients/{patient_id}/notes/summary")
def patient_notes_summary(patient_id: str, request: Request, response: Response):
    """AI cross-note synthesis of the patient's recent notes (call prep)."""
    user = _user(request, response)
    p = data.get_patient_detail(patient_id, user)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    return summarize_notes(p, data.get_patient_notes(patient_id))


class ParseOutreachIn(BaseModel):
    text: str


@router.post("/patients/{patient_id}/parse-outreach")
def parse_outreach_route(
    patient_id: str, body: ParseOutreachIn, request: Request, response: Response
):
    """AI-assisted logging: parse a free-text/dictated recap into a structured
    outreach the Log Outreach form can pre-fill.

    Grounded ONLY in the recap text + this patient's OPEN care gaps (so returned
    gap_ids are always real) + the allowed action/follow-up enums. Human-in-the-
    loop: the care manager reviews/adjusts the pre-filled form before saving.
    """
    user = _user(request, response)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Recap text is required")
    p = data.get_patient_detail(patient_id, user)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    return parse_outreach(p, text)


class OutreachIn(BaseModel):
    action: str
    addressed_gap_ids: list[str] = []
    note: Optional[str] = None
    follow_up: Optional[str] = None
    # Denormalized display context captured at log time so the Activity feed
    # can render without re-querying the warehouse.
    patient_name: Optional[str] = None
    risk_tier: Optional[str] = None
    addressed_gap_measures: list[str] = []


@router.post("/patients/{patient_id}/outreach")
def log_outreach(patient_id: str, body: OutreachIn, request: Request, response: Response):
    store.record_outreach(
        user=_user(request, response),
        patient_id=patient_id,
        action=body.action,
        addressed_gap_ids=body.addressed_gap_ids,
        note=body.note,
        follow_up=body.follow_up,
        patient_name=body.patient_name,
        risk_tier=body.risk_tier,
        addressed_gap_measures=body.addressed_gap_measures,
    )
    return {"ok": True, "message": "Outreach logged"}


@router.get("/activity")
def activity(request: Request, response: Response):
    """Session activity feed — THIS user's outreaches, newest first."""
    return {"items": store.list_activity(_user(request, response))}


@router.delete("/activity")
def clear_activity(request: Request, response: Response):
    """Demo reset — delete ALL of this user's logged outreach so every patient
    returns to the worklist as a fresh candidate."""
    n = store.clear_activity(_user(request, response))
    return {"ok": True, "deleted": n}


@router.delete("/patients/{patient_id}/outreach")
def delete_patient_outreach(patient_id: str, request: Request, response: Response):
    """Delete this user's outreach for ONE patient so that exact patient reappears
    as a candidate (restores their open gaps and priority)."""
    n = store.delete_patient_activity(_user(request, response), patient_id)
    return {"ok": True, "deleted": n}


@router.get("/panel")
def panel(request: Request, response: Response):
    """My Panel summary — population KPIs + this user's session productivity."""
    return data.get_panel(_user(request, response))


@router.get("/health")
def health():
    return {"status": "healthy"}
