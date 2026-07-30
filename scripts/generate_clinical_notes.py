#!/usr/bin/env python
"""
Unity Health — synthetic CLINICAL NOTES generator (unstructured + GenAI slice)
==============================================================================

Generates realistic, fictional free-text clinical notes for the High-risk
patient cohort, written BY a Foundation Model (`ai_query`) and GROUNDED in each
patient's structured record (conditions, encounters, open care gaps, SDOH).

Design intent for the Genie Mobile demo:
  - Notes read like real chart narrative (SOAP progress notes, discharge
    summaries, care-management telephone notes).
  - A subset deliberately PLANT narrative signal that the structured data does
    NOT capture (the *why* behind a gap, an un-coded barrier, a new symptom) —
    e.g. "ran out of lisinopril, can't get to the pharmacy since he stopped
    driving". That's what makes "have Genie read the notes" land: AI surfaces
    what the codes miss.

Writes:  hls_provider.population_health.clinical_notes
Engine:  Databricks Connect (serverless) + SQL `ai_query` for generation.

Validate small first, then scale:
    DATABRICKS_CONFIG_PROFILE=<your-cli-profile> \
      uv run --with "databricks-connect>=16.4,<17.0" --with pandas \
      scripts/generate_clinical_notes.py --catalog hls_provider --limit 8

Full cohort (all High-risk ~1,600):
    ... scripts/generate_clinical_notes.py --catalog hls_provider --all
"""
from __future__ import annotations
import argparse
import hashlib

MODEL = "databricks-claude-sonnet-4-6"

# Per-note "hidden signal" the model should weave into the narrative (not coded
# anywhere in the structured tables). Bucketed deterministically by patient so a
# known fraction carry each — this powers the demo's "read the notes" questions.
SIGNALS = {
    "transport": "Naturally work in that the patient has had trouble getting to the pharmacy or appointments since they stopped driving / lost reliable transportation.",
    "med_cost": "Mention that the patient has been rationing, skipping, or not filling a medication because of cost.",
    "worsening": "Note a new or worsening symptom (e.g. increasing lower-extremity edema, more exertional dyspnea, or dizziness) that warrants closer follow-up.",
    "caregiver": "Mention the patient relies on a family caregiver who is increasingly strained / overwhelmed.",
    "food": "Mention food insecurity affecting the patient's diet and ability to manage their condition.",
    "none": "",
    "none2": "",
}
SIGNAL_KEYS = list(SIGNALS.keys())


def _signal_for(patient_id: str) -> str:
    h = int(hashlib.md5(patient_id.encode()).hexdigest(), 16)
    return SIGNAL_KEYS[h % len(SIGNAL_KEYS)]


def _conditions(row) -> str:
    c = []
    if row.get("has_diabetes"): c.append("Type 2 diabetes")
    if row.get("has_chf"): c.append("CHF")
    if row.get("has_copd"): c.append("COPD")
    if row.get("has_ckd"): c.append("CKD")
    if row.get("has_hypertension"): c.append("hypertension")
    return ", ".join(c) if c else "no major chronic conditions on file"


def _sdoh(row) -> str:
    s = []
    if row.get("transportation_barrier"): s.append("transportation barrier")
    if row.get("food_insecurity"): s.append("food insecurity")
    if row.get("housing_instability"): s.append("housing instability")
    lang = row.get("preferred_language")
    if lang and lang != "English": s.append(f"preferred language {lang}")
    return ", ".join(s) if s else "none documented"


def _fmt(note_type: str) -> str:
    if note_type == "Discharge Summary":
        return ("Sections: Reason for admission, Hospital course, Discharge diagnoses, "
                "Discharge medications, Follow-up plan. 7-11 lines.")
    if note_type == "Telephone Encounter":
        return ("Brief care-management call note: who was reached, what was discussed "
                "(adherence, barriers, symptoms), and next steps. 4-7 lines.")
    return ("SOAP format (Subjective / Objective / Assessment / Plan), realistic vitals. 7-11 lines.")


def build_prompt(p, note_type, note_date, enc) -> str:
    conditions = _conditions(p)
    sdoh = _sdoh(p)
    gaps = p.get("open_gaps") or "none currently open"
    sig = SIGNALS[_signal_for(p["patient_id"])]
    enc_line = ""
    if enc:
        los = f", LOS {int(enc['los_days'])}d" if enc.get("los_days") else ""
        enc_line = (f"Relevant encounter: {enc.get('service_line','')} — "
                    f"{enc.get('primary_diagnosis','')} ({enc.get('encounter_type','')}{los}). ")
    return (
        "You are a clinician writing a concise, realistic SYNTHETIC clinical note for a "
        "FICTIONAL patient. This is fake demo data — invent plausible specifics (vitals, meds, "
        "dosages) but include NO real PHI. "
        f"Write a {note_type} dated {note_date} for a {int(p['patient_age'])}-year-old "
        f"{('male' if str(p['patient_sex']).upper().startswith('M') else 'female')}. "
        f"Known conditions: {conditions}. {enc_line}"
        f"Open care gaps to be aware of: {gaps}. "
        f"Documented social barriers: {sdoh}. "
        + (sig + " " if sig else "")
        + _fmt(note_type)
        + " Use realistic clinical shorthand. Do NOT print a name, MRN, or header — output ONLY "
        "the note body text, nothing else."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=None, help="UC catalog (omit for dry run / prompt preview)")
    ap.add_argument("--limit", type=int, default=8, help="number of patients (sample). Ignored with --all")
    ap.add_argument("--all", action="store_true", help="generate for ALL High-risk patients")
    ap.add_argument("--append", action="store_true", help="append instead of overwrite")
    ap.add_argument("--model", default=MODEL)
    args = ap.parse_args()

    from databricks.connect import DatabricksSession
    spark = DatabricksSession.builder.serverless().getOrCreate()
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    cat = args.catalog or "hls_provider"

    limit_clause = "" if args.all else f"LIMIT {args.limit}"

    # ---- pull grounded facts for the High-risk cohort -------------------------
    facts = spark.sql(f"""
        WITH hi AS (
          SELECT patient_id FROM {cat}.population_health.risk_scores
          WHERE risk_tier = 'High'
        ),
        gaps AS (
          SELECT patient_id, concat_ws(', ', collect_set(measure)) AS open_gaps
          FROM {cat}.population_health.care_gaps
          WHERE gap_status = 'Open' GROUP BY patient_id
        )
        SELECT r.patient_id, r.patient_age, r.patient_sex,
               r.has_diabetes, r.has_chf, r.has_copd, r.has_ckd, r.has_hypertension,
               r.primary_facility_name,
               s.transportation_barrier, s.food_insecurity, s.housing_instability,
               s.preferred_language,
               g.open_gaps
        FROM hi
        JOIN {cat}.population_health.patient_registry r USING (patient_id)
        LEFT JOIN {cat}.population_health.sdoh s USING (patient_id)
        LEFT JOIN gaps g USING (patient_id)
        {limit_clause}
    """).toPandas()

    pids = facts["patient_id"].tolist()
    # recent encounters for those patients (up to 3 most recent each)
    enc = spark.sql(f"""
        SELECT * FROM (
          SELECT patient_id, encounter_id, service_line, encounter_type,
                 admit_date, discharge_date, los_days, primary_diagnosis,
                 row_number() OVER (PARTITION BY patient_id ORDER BY admit_date DESC) AS rn
          FROM {cat}.operations.encounters
          WHERE patient_id IN ({','.join("'" + p + "'" for p in pids)})
        ) WHERE rn <= 3
    """).toPandas()
    enc_by_pt = {}
    for _, e in enc.iterrows():
        enc_by_pt.setdefault(e["patient_id"], []).append(e.to_dict())

    # ---- build note skeletons + prompts ---------------------------------------
    import datetime as dt
    rows = []
    for _, p in facts.iterrows():
        p = p.to_dict()
        encs = enc_by_pt.get(p["patient_id"], [])
        made = 0
        for e in encs:
            ntype = "Discharge Summary" if e.get("encounter_type") in ("Inpatient", "Observation") else "Progress Note"
            ndate = str(e.get("discharge_date") or e.get("admit_date"))[:10]
            rows.append(dict(patient_id=p["patient_id"], encounter_id=e["encounter_id"],
                             note_type=ntype, note_date=ndate, specialty=e.get("service_line"),
                             prompt=build_prompt(p, ntype, ndate, e)))
            made += 1
        # one care-management telephone note dated a few days after the latest encounter
        base = encs[0]["admit_date"] if encs else dt.date(2026, 5, 1)
        try:
            base_d = base if isinstance(base, dt.date) else dt.date.fromisoformat(str(base)[:10])
        except Exception:
            base_d = dt.date(2026, 5, 1)
        tdate = (base_d + dt.timedelta(days=6)).isoformat()
        rows.append(dict(patient_id=p["patient_id"], encounter_id=None,
                         note_type="Telephone Encounter", note_date=tdate, specialty="Care Management",
                         prompt=build_prompt(p, "Telephone Encounter", tdate, None)))

    print(f"Patients: {len(facts)}  |  notes to generate: {len(rows)}")

    if not args.catalog:
        print("\nDry run (no --catalog). Sample prompt:\n")
        print(rows[0]["prompt"])
        spark.stop(); return

    # ---- push skeletons, generate note_text with ai_query ---------------------
    import pandas as pd
    pdf = pd.DataFrame(rows)
    pdf["note_id"] = ["NOTE" + hashlib.md5((str(r.patient_id)+str(r.note_type)+str(r.note_date)+str(i)).encode()).hexdigest()[:12]
                      for i, r in pdf.reset_index().iterrows()]
    sdf = spark.createDataFrame(pdf)
    sdf.createOrReplaceTempView("note_prompts")

    fqn = f"{cat}.population_health.clinical_notes"
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {cat}.population_health")
    gen = spark.sql(f"""
        SELECT note_id, patient_id, encounter_id, note_date, note_type, specialty,
               ai_query('{args.model}', prompt) AS note_text
        FROM note_prompts
    """)
    mode = "append" if args.append else "overwrite"
    (gen.write.format("delta").mode(mode)
        .option("overwriteSchema", "true").saveAsTable(fqn))
    spark.sql(f"COMMENT ON TABLE {fqn} IS "
              "'Synthetic free-text clinical notes (progress, discharge, care-management) for the "
              "High-risk cohort, generated by a Foundation Model grounded in each patient''s "
              "structured record. Fictional demo data, no PHI. Some notes contain narrative signal "
              "(barriers, non-adherence reasons, new symptoms) not captured in the structured tables.'")

    # show a couple of generated notes
    print("\n=== sample generated notes ===")
    for r in spark.sql(f"SELECT note_type, note_date, note_text FROM {fqn} LIMIT 3").collect():
        print(f"\n--- {r['note_type']} ({r['note_date']}) ---\n{r['note_text']}")
    print(f"\nWrote {gen.count()} notes to {fqn}")
    spark.stop()


if __name__ == "__main__":
    main()
