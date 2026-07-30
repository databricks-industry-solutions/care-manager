"""Per-user write-back store, now backed by Lakebase Postgres (`caremanager`).

Every outreach a care manager logs is persisted to the `outreach_log` table,
keyed by user_email (resolved from X-Forwarded-Email; local fallback to a
session cookie). This replaces the previous in-memory store, so outreach now
survives app restarts and stays correctly isolated per user.

State derived from outreach_log (all scoped to user_email):
  - last_outreach_at(user, pid): newest created_at for that patient
  - addressed_gap_ids(user, pid): union of addressed gap ids
  - has_recent_outreach(user, pid): any logged outreach exists
  - list_activity(user): full feed, newest first
  - get_outreach(user, pid): per-patient outreach detail
  - session_stats(user): outreach_logged / gaps_closed / patients_touched

The AI brief & message caches stay in-memory (regenerable, non-critical).
"""
from datetime import datetime
from typing import Any, Optional

from . import db

# ---- AI caches: in-memory, per user (regenerable, non-critical) -----------
# user_key -> { patient_id -> brief/message dict }
_briefs: dict[str, dict[str, dict[str, Any]]] = {}
_messages: dict[str, dict[str, dict[str, Any]]] = {}


def _u(user: Optional[str]) -> str:
    return user or "anon"


_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS outreach_log (
    id SERIAL PRIMARY KEY,
    user_email TEXT NOT NULL,
    patient_id TEXT NOT NULL,
    action TEXT NOT NULL,
    addressed_gap_ids TEXT[] DEFAULT '{}',
    addressed_gap_measures TEXT[] DEFAULT '{}',
    note TEXT,
    follow_up TEXT,
    patient_name TEXT,
    risk_tier TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_outreach_user ON outreach_log (user_email, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_outreach_user_patient ON outreach_log (user_email, patient_id)",
]


def init_store() -> None:
    """Ensure the outreach_log table exists. Called at startup.

    The table is pre-created at load time by the deploying user (the table
    owner), and the app service principal must be granted
    SELECT/INSERT/UPDATE/DELETE on it (not CREATE on the schema). DELETE is
    required by the Activity "Reset demo" / per-patient delete feature; without
    it those endpoints 500 with "permission denied for table outreach_log".

    The SP cannot self-grant (it doesn't own the table), so if the table is ever
    dropped and recreated, the OWNER must re-run (psql/psycopg as the owner):
        GRANT SELECT, INSERT, UPDATE, DELETE ON outreach_log
            TO "<app-service-principal-client-id>";
    (discover the app SP client id at runtime; do not hardcode it)

    If the table already exists we skip DDL entirely; we only attempt CREATE when
    it's genuinely missing (e.g. local dev as the owner).
    """
    exists = db.fetchone("SELECT to_regclass('public.outreach_log')")
    if exists and exists[0] is not None:
        return
    db.execute(_CREATE_SQL)
    for ix in _INDEX_SQL:
        db.execute(ix)


# ---- Writes ---------------------------------------------------------------

def record_outreach(
    user: Optional[str],
    patient_id: str,
    action: str,
    addressed_gap_ids: list[str],
    note: Optional[str],
    follow_up: Optional[str],
    patient_name: Optional[str] = None,
    risk_tier: Optional[str] = None,
    addressed_gap_measures: Optional[list[str]] = None,
) -> None:
    uk = _u(user)
    db.execute(
        """
        INSERT INTO outreach_log
            (user_email, patient_id, action, addressed_gap_ids,
             addressed_gap_measures, note, follow_up, patient_name, risk_tier)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            uk, patient_id, action, addressed_gap_ids or [],
            addressed_gap_measures or [], note, follow_up, patient_name, risk_tier,
        ),
    )
    # An outreach may change brief context; invalidate this user's cached brief.
    _briefs.get(uk, {}).pop(patient_id, None)


def delete_patient_activity(user: Optional[str], patient_id: str) -> int:
    """Delete all of this user's outreach for one patient (demo reset).

    Removing the rows restores the patient's open gaps and worklist priority,
    so they reappear as a fresh candidate. Returns rows deleted.
    """
    uk = _u(user)
    n = db.execute(
        "DELETE FROM outreach_log WHERE user_email = %s AND patient_id = %s",
        (uk, patient_id),
    )
    _briefs.get(uk, {}).pop(patient_id, None)
    # Message cache is keyed "{patient_id}::{lang}" — drop every language variant.
    msgs = _messages.get(uk)
    if msgs:
        for k in [k for k in msgs if k == patient_id or k.startswith(f"{patient_id}::")]:
            msgs.pop(k, None)
    return n or 0


def clear_activity(user: Optional[str]) -> int:
    """Delete ALL of this user's outreach (full demo reset). Returns rows deleted."""
    uk = _u(user)
    n = db.execute("DELETE FROM outreach_log WHERE user_email = %s", (uk,))
    _briefs.get(uk, {}).clear()
    _messages.get(uk, {}).clear()
    return n or 0


# ---- Batched per-user state (one query) -----------------------------------
#
# The worklist re-ranks up to ~3k candidate patients and, for each, needs this
# user's "addressed gaps", "recently contacted?", and "last contact time". Doing
# those as per-row queries is an N+1 stampede over the pool. Instead, load the
# whole user's outreach in ONE query and answer all three from memory.

class UserState:
    """In-memory snapshot of one user's outreach_log, for hot-loop lookups."""

    def __init__(self) -> None:
        self.last_at: dict[str, str] = {}        # patient_id -> max created_at iso
        self.addressed: dict[str, set[str]] = {}  # patient_id -> set(gap_ids)

    def last_outreach_at(self, pid: str) -> Optional[str]:
        return self.last_at.get(pid)

    def addressed_gap_ids(self, pid: str) -> set[str]:
        return self.addressed.get(pid, set())

    def has_recent_outreach(self, pid: str) -> bool:
        return pid in self.last_at


def load_user_state(user: Optional[str]) -> UserState:
    rows = db.query(
        """
        SELECT patient_id, max(created_at) AS last_at,
               array_agg(g) FILTER (WHERE g IS NOT NULL) AS gap_ids
        FROM outreach_log
        LEFT JOIN LATERAL unnest(addressed_gap_ids) AS g ON true
        WHERE user_email = %s
        GROUP BY patient_id
        """,
        (_u(user),),
    )
    st = UserState()
    for pid, last_at, gap_ids in rows:
        if last_at is not None:
            st.last_at[pid] = last_at.isoformat()
        st.addressed[pid] = set(gap_ids or [])
    return st


# ---- Reads derived from outreach_log --------------------------------------

def list_activity(user: Optional[str]) -> list[dict[str, Any]]:
    """This user's logged outreaches, newest first."""
    rows = db.query(
        """
        SELECT patient_id, patient_name, risk_tier, action,
               addressed_gap_measures, note, follow_up, created_at
        FROM outreach_log
        WHERE user_email = %s
        ORDER BY created_at DESC, id DESC
        """,
        (_u(user),),
    )
    return [
        {
            "patient_id": r[0],
            "patient_name": r[1],
            "risk_tier": r[2],
            "action": r[3],
            "addressed_gap_measures": list(r[4] or []),
            "note": r[5],
            "follow_up": r[6],
            "at": r[7].isoformat() if r[7] is not None else None,
        }
        for r in rows
    ]


def get_outreach(user: Optional[str], patient_id: str) -> Optional[dict[str, Any]]:
    """Per-patient outreach detail for this user (matches the old shape:
    last_outreach_at, outreaches list, addressed_gap_ids set, follow_up)."""
    rows = db.query(
        """
        SELECT action, note, follow_up, addressed_gap_ids, created_at
        FROM outreach_log
        WHERE user_email = %s AND patient_id = %s
        ORDER BY created_at ASC, id ASC
        """,
        (_u(user), patient_id),
    )
    if not rows:
        return None
    outreaches = []
    addressed: set[str] = set()
    last_at = None
    last_follow = None
    for action, note, follow_up, gap_ids, created_at in rows:
        at = created_at.isoformat() if created_at is not None else None
        outreaches.append(
            {
                "action": action,
                "note": note,
                "follow_up": follow_up,
                "addressed_gap_ids": list(gap_ids or []),
                "at": at,
            }
        )
        addressed.update(gap_ids or [])
        last_at = at
        last_follow = follow_up
    return {
        "last_outreach_at": last_at,
        "outreaches": outreaches,
        "addressed_gap_ids": addressed,
        "follow_up": last_follow,
    }


def last_outreach_at(user: Optional[str], patient_id: str) -> Optional[str]:
    row = db.fetchone(
        "SELECT max(created_at) FROM outreach_log WHERE user_email = %s AND patient_id = %s",
        (_u(user), patient_id),
    )
    if row and row[0] is not None:
        return row[0].isoformat()
    return None


def addressed_gap_ids(user: Optional[str], patient_id: str) -> set[str]:
    rows = db.query(
        "SELECT addressed_gap_ids FROM outreach_log WHERE user_email = %s AND patient_id = %s",
        (_u(user), patient_id),
    )
    out: set[str] = set()
    for (gap_ids,) in rows:
        out.update(gap_ids or [])
    return out


def has_recent_outreach(user: Optional[str], patient_id: str) -> bool:
    row = db.fetchone(
        "SELECT 1 FROM outreach_log WHERE user_email = %s AND patient_id = %s LIMIT 1",
        (_u(user), patient_id),
    )
    return row is not None


def session_stats(user: Optional[str]) -> dict[str, Any]:
    """Per-user productivity rollup for the Panel summary.

    - outreach_logged: total outreach rows for this user
    - gaps_closed: distinct addressed gap ids across all this user's outreaches
    - patients_touched: distinct patients contacted

    (Named "session" historically; now reflects all persisted outreach for the
    user since writes survive restarts.)
    """
    uk = _u(user)
    logged = db.fetchone(
        "SELECT count(*) FROM outreach_log WHERE user_email = %s", (uk,)
    )
    touched = db.fetchone(
        "SELECT count(DISTINCT patient_id) FROM outreach_log WHERE user_email = %s", (uk,)
    )
    # Distinct gap ids closed across all outreaches (unnest the arrays).
    gaps = db.fetchone(
        """
        SELECT count(DISTINCT g)
        FROM outreach_log, unnest(addressed_gap_ids) AS g
        WHERE user_email = %s
        """,
        (uk,),
    )
    return {
        "outreach_logged": int(logged[0]) if logged and logged[0] is not None else 0,
        "gaps_closed": int(gaps[0]) if gaps and gaps[0] is not None else 0,
        "patients_touched": int(touched[0]) if touched and touched[0] is not None else 0,
    }


# ---- AI brief / message caches (in-memory) --------------------------------

def get_brief(user: Optional[str], patient_id: str) -> Optional[dict[str, Any]]:
    return _briefs.get(_u(user), {}).get(patient_id)


def set_brief(user: Optional[str], patient_id: str, brief: dict[str, Any]) -> None:
    _briefs.setdefault(_u(user), {})[patient_id] = brief


def get_message(user: Optional[str], patient_id: str) -> Optional[dict[str, Any]]:
    return _messages.get(_u(user), {}).get(patient_id)


def set_message(user: Optional[str], patient_id: str, message: dict[str, Any]) -> None:
    _messages.setdefault(_u(user), {})[patient_id] = message
