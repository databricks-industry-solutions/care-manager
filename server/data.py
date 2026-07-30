"""Data access layer — reads the care-manager tables from Lakebase Postgres
(`caremanager`) via the connection pool in `db.py`. Merges in the per-user
write-back store (now Postgres-backed) for re-ranking and gap removal.

Migrated from SQL-warehouse StatementExecution to Postgres for low-latency
mobile reads. Response shapes and care-priority logic are unchanged.
"""
from datetime import date, datetime
from typing import Any, Optional

from . import db, store

RISK_WEIGHT = {"High": 3, "Rising": 2, "Low": 1}

# ---- Caseload bucketing ---------------------------------------------------
#
# A real outpatient RN care manager actively manages ~80-150 high-risk
# patients, not the full ~3,092-patient High/Rising-with-open-gaps population.
# We model a team of N_CASELOADS care managers and deterministically assign
# each patient to one bucket. Each logged-in user is mapped to a bucket too,
# so they see only their own slice (~120 patients).
#
# Bucketing uses Postgres `hashtext` for BOTH the patient id and the user
# email so the two hashes come from the same implementation and the modulo
# math lines up. ~3,092 / 26 ≈ 119 patients per caseload.
N_CASELOADS = 26


def _user_bucket(user: Optional[str]) -> int:
    """The caseload bucket for this user: abs(hashtext(lower(email))) % N.

    Computed in Postgres so it uses the same hashtext implementation as the
    patient-side bucketing in the worklist/panel queries.
    """
    key = (user or "anon").strip().lower()
    row = db.fetchone("SELECT abs(hashtext(%s)) %% %s", (key, N_CASELOADS))
    return int(row[0]) if row and row[0] is not None else 0


def _days_since(d: Optional[Any]) -> Optional[int]:
    """Days since a date. Accepts a date, datetime, or ISO string (the store's
    last_outreach_at is an ISO string; Postgres date columns come back as
    datetime.date)."""
    if not d:
        return None
    try:
        if isinstance(d, datetime):
            dd = d.date()
        elif isinstance(d, date):
            dd = d
        else:
            dd = datetime.fromisoformat(str(d)[:10]).date()
        return (date.today() - dd).days
    except Exception:
        return None


def _priority_score(
    risk_tier: str, open_gaps: int, days_since_visit: Optional[int], recent: bool
) -> float:
    base = RISK_WEIGHT.get(risk_tier, 1) * max(open_gaps, 1)
    if days_since_visit is not None:
        base += min(days_since_visit, 365) / 90.0
    if recent:
        base *= 0.4
    return round(base, 3)


# Care Priority Score (0-100). See original module docstring for rationale.
_RISK_POINTS = {"High": 50, "Rising": 30, "Low": 10}


def _care_priority_score(
    risk_tier: str,
    open_gaps: int,
    days_since_contact: Optional[int],
    recent: bool,
) -> int:
    score = _RISK_POINTS.get(risk_tier, 10)
    score += min(open_gaps * 8, 30)
    if days_since_contact is not None:
        score += min(days_since_contact / 12.0, 20)
    if recent:
        score *= 0.5
    return max(0, min(100, round(score)))


def _phone_for(patient_id: str) -> str:
    digits = "".join(ch for ch in str(patient_id) if ch.isdigit()) or str(abs(hash(patient_id)))
    seed = int(digits[-7:]) if len(digits) >= 7 else int(digits.ljust(7, "0"))
    mid = (seed // 10000) % 1000
    last = seed % 10000
    return f"(555) {mid:03d}-{last:04d}"


# ---- Worklist (this user's caseload: High/Rising, >=1 open gap) -----------
#
# Scoped to the logged-in care manager's caseload bucket so they see ~120
# patients, not the whole High/Rising population. The patient-side bucket is
# `abs(hashtext(patient_id)) % N_CASELOADS`, matched against the user's bucket
# (a bound parameter). Still ranked by Care Priority Score in Python.
#
# array_agg(cg.gap_id) returns a native text[] -> psycopg gives a Python list,
# so no JSON decoding is needed (unlike the old StatementExecution path).

_WORKLIST_SQL = """
SELECT
  r.patient_id,
  p.first_name,
  p.last_name,
  r.patient_age,
  r.patient_sex,
  r.risk_tier,
  rs.predicted_admit_prob,
  r.last_visit_date,
  r.has_diabetes, r.has_chf, r.has_copd,
  s.transportation_barrier, s.food_insecurity,
  r.primary_facility_name,
  count(cg.gap_id) AS open_gaps,
  array_agg(cg.gap_id) AS open_gap_ids
FROM patient_registry r
JOIN patients p ON r.patient_id = p.patient_id
JOIN risk_scores rs ON r.patient_id = rs.patient_id
JOIN care_gaps cg
  ON r.patient_id = cg.patient_id AND cg.gap_status = 'Open'
LEFT JOIN sdoh s ON r.patient_id = s.patient_id
WHERE r.risk_tier IN ('High','Rising')
  AND abs(hashtext(r.patient_id)) %% %s = %s
GROUP BY r.patient_id, p.first_name, p.last_name, r.patient_age, r.patient_sex,
         r.risk_tier, rs.predicted_admit_prob, r.last_visit_date,
         r.has_diabetes, r.has_chf, r.has_copd,
         s.transportation_barrier, s.food_insecurity, r.primary_facility_name
"""


def get_worklist(user: Optional[str] = None) -> list[dict[str, Any]]:
    bucket = _user_bucket(user)
    rows = db.query(_WORKLIST_SQL, (N_CASELOADS, bucket))
    # Load this user's full outreach state in ONE query, then do all per-row
    # lookups in memory (avoids an N+1 stampede over ~3k candidate patients).
    st = store.load_user_state(user)
    out = []
    for r in rows:
        pid = r[0]
        gap_ids = r[15] or []  # native text[] -> list
        addressed = st.addressed_gap_ids(pid)
        effective_gaps = [g for g in gap_ids if g not in addressed]
        open_gaps = len(effective_gaps)
        if open_gaps == 0:
            continue
        risk_tier = r[5]
        last_visit = r[7]
        dsv = _days_since(last_visit)
        last_contact = st.last_outreach_at(pid)
        last_contact_days = _days_since(last_contact) if last_contact else None
        days_since_contact = last_contact_days if last_contact_days is not None else dsv
        recent = st.has_recent_outreach(pid)
        out.append(
            {
                "patient_id": pid,
                "name": f"{r[1]} {r[2]}",
                "age": int(r[3]) if r[3] is not None else None,
                "sex": r[4],
                "risk_tier": risk_tier,
                "predicted_admit_prob": float(r[6]) if r[6] is not None else None,
                "open_gaps": open_gaps,
                "transportation_barrier": bool(r[11]),
                "food_insecurity": bool(r[12]),
                "facility": r[13],
                "conditions": _conditions_short(r[8], r[9], r[10]),
                "last_contact_days": last_contact_days,
                "days_since_visit": dsv,
                "priority": _priority_score(risk_tier, open_gaps, dsv, recent),
                "care_priority_score": _care_priority_score(
                    risk_tier, open_gaps, days_since_contact, recent
                ),
            }
        )
    out.sort(key=lambda x: (x["care_priority_score"], x["priority"]), reverse=True)
    # Caseload is ~120 patients — show the full caseload (scrollable), don't
    # truncate to 50 the way the old population-wide worklist did.
    return out


def _conditions_short(diab, chf, copd) -> list[str]:
    c = []
    if diab:
        c.append("Diabetes")
    if chf:
        c.append("CHF")
    if copd:
        c.append("COPD")
    return c


# ---- Patient detail -------------------------------------------------------

_DETAIL_SQL = """
SELECT
  r.patient_id, p.first_name, p.last_name, r.patient_age, r.patient_sex,
  r.risk_tier, rs.predicted_admit_prob, rs.predicted_annual_cost,
  r.payer_type, r.attributed_pcp_id, r.primary_facility_name,
  r.has_diabetes, r.has_chf, r.has_copd, r.has_ckd, r.has_hypertension,
  r.last_visit_date,
  prov.provider_name
FROM patient_registry r
JOIN patients p ON r.patient_id = p.patient_id
JOIN risk_scores rs ON r.patient_id = rs.patient_id
LEFT JOIN providers prov ON r.attributed_pcp_id = prov.provider_id
WHERE r.patient_id = %s
LIMIT 1
"""

_SDOH_SQL = """
SELECT transportation_barrier, food_insecurity, housing_instability,
       preferred_language, interpreter_needed, svi_score
FROM sdoh WHERE patient_id = %s LIMIT 1
"""

_GAPS_SQL = """
SELECT gap_id, measure, gap_status, days_open, due_date
FROM care_gaps
WHERE patient_id = %s AND gap_status = 'Open'
ORDER BY days_open DESC
"""


def get_patient_detail(patient_id: str, user: Optional[str] = None) -> Optional[dict[str, Any]]:
    rows = db.query(_DETAIL_SQL, (patient_id,))
    if not rows:
        return None
    r = rows[0]

    conditions = []
    for label, val in [
        ("Diabetes", r[11]), ("CHF", r[12]), ("COPD", r[13]),
        ("CKD", r[14]), ("Hypertension", r[15]),
    ]:
        if val:
            conditions.append(label)

    sdoh_rows = db.query(_SDOH_SQL, (patient_id,))
    sdoh = {}
    if sdoh_rows:
        sr = sdoh_rows[0]
        sdoh = {
            "transportation_barrier": bool(sr[0]),
            "food_insecurity": bool(sr[1]),
            "housing_instability": bool(sr[2]),
            "preferred_language": sr[3],
            "interpreter_needed": bool(sr[4]),
            "svi_score": float(sr[5]) if sr[5] is not None else None,
        }

    # One store read covers addressed gaps, last-contact, and recency.
    existing_outreach = store.get_outreach(user, patient_id)
    addressed = existing_outreach["addressed_gap_ids"] if existing_outreach else set()
    gap_rows = db.query(_GAPS_SQL, (patient_id,))
    gaps = []
    for g in gap_rows:
        if g[0] in addressed:
            continue
        gaps.append(
            {
                "gap_id": g[0],
                "measure": g[1],
                "gap_status": g[2],
                "days_open": int(g[3]) if g[3] is not None else None,
                "due_date": g[4].isoformat() if g[4] is not None else None,
            }
        )

    last_contact = existing_outreach["last_outreach_at"] if existing_outreach else None
    recent = bool(existing_outreach)
    last_contact_days = _days_since(last_contact) if last_contact else None
    last_visit = r[16]
    dsv = _days_since(last_visit)
    days_since_contact = last_contact_days if last_contact_days is not None else dsv
    last_visit_iso = last_visit.isoformat() if last_visit is not None else None
    return {
        "patient_id": r[0],
        "name": f"{r[1]} {r[2]}",
        "phone": _phone_for(r[0]),
        "age": int(r[3]) if r[3] is not None else None,
        "sex": r[4],
        "risk_tier": r[5],
        "predicted_admit_prob": float(r[6]) if r[6] is not None else None,
        "care_priority_score": _care_priority_score(
            r[5], len(gaps), days_since_contact, recent
        ),
        "predicted_annual_cost": float(r[7]) if r[7] is not None else None,
        "payer_type": r[8],
        "pcp_id": r[9],
        "pcp_name": r[17],
        "facility": r[10],
        "last_visit_date": last_visit_iso,
        "days_since_visit": dsv,
        "conditions": conditions,
        "sdoh": sdoh,
        "open_gaps": gaps,
        "last_contact_days": last_contact_days,
        "outreach_history": existing_outreach["outreaches"] if existing_outreach else [],
    }


# ---- Recent encounter history -------------------------------------------

_HISTORY_SQL = """
SELECT encounter_type, service_line, primary_diagnosis, admit_date, los_days
FROM encounters
WHERE patient_id = %s
ORDER BY admit_date DESC
LIMIT 6
"""

# 90-day window anchored to the latest admit_date in the data (synthetic data
# ends ~2026-05), not today, so the callout stays meaningful at any run date.
_UTILIZATION_SQL = """
WITH latest AS (SELECT max(admit_date) AS m FROM encounters)
SELECT
  sum(CASE WHEN e.encounter_type = 'Emergency' THEN 1 ELSE 0 END) AS ed_visits,
  sum(CASE WHEN e.encounter_type = 'Inpatient' THEN 1 ELSE 0 END) AS admissions
FROM encounters e, latest
WHERE e.patient_id = %s
  AND e.admit_date >= latest.m - INTERVAL '90 days'
"""


def get_patient_history(patient_id: str) -> dict[str, Any]:
    rows = db.query(_HISTORY_SQL, (patient_id,))
    encounters = []
    for r in rows:
        encounters.append(
            {
                "encounter_type": r[0],
                "service_line": r[1],
                "primary_diagnosis": r[2],
                "admit_date": r[3].isoformat() if r[3] is not None else None,
                "los_days": int(r[4]) if r[4] is not None else None,
            }
        )

    util_rows = db.query(_UTILIZATION_SQL, (patient_id,))
    ed = adm = 0
    if util_rows and util_rows[0]:
        ed = int(util_rows[0][0]) if util_rows[0][0] is not None else 0
        adm = int(util_rows[0][1]) if util_rows[0][1] is not None else 0

    return {
        "encounters": encounters,
        "utilization_90d": {"ed_visits": ed, "admissions": adm},
    }


# ---- Clinical notes (unstructured + GenAI) --------------------------------

_NOTES_SQL = """
SELECT note_type, note_date, specialty, note_text, ai_summary
FROM clinical_notes
WHERE patient_id = %s
ORDER BY note_date DESC
LIMIT 8
"""


def get_patient_notes(patient_id: str) -> list[dict[str, Any]]:
    """Recent free-text clinical notes for a patient (newest first)."""
    rows = db.query(_NOTES_SQL, (patient_id,))
    return [
        {
            "note_type": r[0],
            "note_date": r[1].isoformat() if r[1] is not None else None,
            "specialty": r[2],
            "note_text": r[3],
            "ai_summary": r[4],
        }
        for r in rows
    ]


# ---- My Caseload summary --------------------------------------------------
#
# KPIs are scoped to the logged-in care manager's caseload bucket (the same
# bucketing the worklist uses), so the size reads ~120, not the ~3,092
# population. A separate program-context count keeps the scale story visible.

_CASELOAD_SQL = """
SELECT
  r.risk_tier,
  count(DISTINCT r.patient_id) AS patients,
  count(cg.gap_id) AS gaps
FROM patient_registry r
JOIN care_gaps cg
  ON r.patient_id = cg.patient_id AND cg.gap_status = 'Open'
WHERE r.risk_tier IN ('High','Rising')
  AND abs(hashtext(r.patient_id)) %% %s = %s
GROUP BY r.risk_tier
"""

# Full High/Rising-with-open-gaps population — the whole care-management
# program across the team. Distinct patients (not gap-weighted).
_PROGRAM_SQL = """
SELECT count(DISTINCT r.patient_id)
FROM patient_registry r
JOIN care_gaps cg
  ON r.patient_id = cg.patient_id AND cg.gap_status = 'Open'
WHERE r.risk_tier IN ('High','Rising')
"""


def get_panel(user: Optional[str] = None) -> dict[str, Any]:
    bucket = _user_bucket(user)
    rows = db.query(_CASELOAD_SQL, (N_CASELOADS, bucket))
    high = rising = open_gaps = 0
    for r in rows:
        tier, patients, gaps = r[0], int(r[1]), int(r[2])
        if tier == "High":
            high = patients
        elif tier == "Rising":
            rising = patients
        open_gaps += gaps
    panel_size = high + rising

    prog = db.fetchone(_PROGRAM_SQL)
    program_high_risk = int(prog[0]) if prog and prog[0] is not None else 0

    stats = store.session_stats(user)
    gaps_closed = stats["gaps_closed"]
    open_remaining = max(0, open_gaps - gaps_closed)
    denom = gaps_closed + open_remaining
    closure_rate = round((gaps_closed / denom) * 100) if denom > 0 else 0

    return {
        "panel_size": panel_size,
        "high": high,
        "rising": rising,
        "open_gaps": open_remaining,
        "outreach_logged": stats["outreach_logged"],
        "patients_touched": stats["patients_touched"],
        "gaps_closed": gaps_closed,
        "closure_rate": closure_rate,
        # Program context: the full population this caseload is one slice of.
        "program_high_risk": program_high_risk,
        "n_caseloads": N_CASELOADS,
    }
