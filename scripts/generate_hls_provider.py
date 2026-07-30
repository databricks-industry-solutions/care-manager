#!/usr/bin/env python
"""
HLS Provider — Genie Mobile demo dataset generator
====================================================

Generates a realistic, INTERCONNECTED synthetic dataset for a fictional
health system ("Unity Health") across five domains, written to Unity
Catalog as gold tables ready for Databricks AI/BI dashboards and Genie spaces.

Connective tissue (shared keys flow across every domain):
    patient_id, provider_id, facility_id, unit_id, payer_id, encounter_id

Design principle for Genie Mobile: descriptive attributes (facility_name,
service_line, payer_name, patient_age, etc.) are DENORMALIZED into each fact
table so single-table questions need no joins, while the keys preserve
realistic lineage for joins / direct-to-table chat.

Schemas (catalog = hls_provider):
    reference         patients, providers, facilities, units, payers
    operations        encounters, patient_census, ed_visits, or_cases, appointments
    quality           readmissions, quality_measures, safety_events, hcahps_surveys
    revenue_cycle     claims, denials, ar_aging, payer_performance, service_line_pnl
    population_health patient_registry, care_gaps, risk_scores, sdoh
    workforce         staffing_daily, productivity, labor_cost

Engine: Polars + NumPy + Mimesis  ->  Unity Catalog via Databricks Connect (serverless).
Total volume ~575K rows across 26 tables. Deterministic (seed=42).

Run:
    DATABRICKS_CONFIG_PROFILE=<profile> \
    uv run --with polars --with numpy --with mimesis --with pandas --with pyarrow \
        --with "databricks-connect>=16.4,<17.0" \
        scripts/generate_hls_provider.py --catalog hls_provider
"""
from __future__ import annotations
import argparse
import numpy as np
import polars as pl
from mimesis import Generic
from mimesis.locales import Locale

SEED = 42
rng = np.random.default_rng(SEED)
g = Generic(locale=Locale.EN, seed=SEED)

# ----------------------------------------------------------------------------
# Volumes (tuned for a mid-size 5-hospital system over 24 months)
# ----------------------------------------------------------------------------
N_PATIENTS   = 20_000
N_PROVIDERS  = 500
N_FACILITIES = 5
N_UNITS      = 35
N_PAYERS     = 10
N_ENCOUNTERS = 90_000

# 24 months ending recently so "this month" / "last quarter" demo well
DATE_START = np.datetime64("2024-06-01")
DATE_END   = np.datetime64("2026-05-31")
N_DAYS     = int((DATE_END - DATE_START).astype(int)) + 1

def daterange():
    return DATE_START + np.arange(N_DAYS).astype("timedelta64[D]")

def month_of(d):
    """numpy datetime64[D] array -> first-of-month datetime64[D] array."""
    return d.astype("datetime64[M]").astype("datetime64[D]")

def seasonal_weight(months_0_11):
    """Winter respiratory surge: Dec/Jan/Feb high, summer low. Returns weights."""
    # month index 0=Jan ... 11=Dec
    base = np.array([1.25, 1.30, 1.15, 1.00, 0.92, 0.85,
                     0.82, 0.84, 0.90, 1.00, 1.10, 1.22])
    return base[months_0_11]

def pool(fn, n=1000):
    return np.array([fn() for _ in range(n)])

def pick(arr, size):
    return arr[rng.integers(0, len(arr), size=size)]

def wchoice(values, weights, size):
    w = np.array(weights, dtype=float)
    return rng.choice(values, size=size, p=w / w.sum())

TABLES: dict[str, pl.DataFrame] = {}

# ============================================================================
# REFERENCE DIMENSIONS
# ============================================================================
print("Generating reference dimensions ...")

# --- facilities ---
fac_names = ["Unity General Hospital", "Unity Memorial Medical Center",
             "Unity Riverside Hospital", "Unity Lakeshore Community Hospital",
             "Unity Children's & Women's Hospital"]
fac_types = ["Academic Medical Center", "Community", "Community",
             "Critical Access", "Specialty"]
fac_beds  = [620, 410, 280, 95, 240]
fac_city  = ["Centerport", "Riverton", "Riverside", "Lakeshore", "Centerport"]
facilities = pl.DataFrame({
    "facility_id":   [f"FAC{i+1:02d}" for i in range(N_FACILITIES)],
    "facility_name": fac_names,
    "facility_type": fac_types,
    "staffed_beds":  fac_beds,
    "city":          fac_city,
    "state":         ["NY"] * N_FACILITIES,
    "region":        ["North", "West", "West", "South", "North"],
})
TABLES["reference.facilities"] = facilities
fac_id_arr   = facilities["facility_id"].to_numpy()
fac_name_arr = facilities["facility_name"].to_numpy()
# facility share-of-volume weights (academic & memorial are larger)
fac_w = np.array([0.34, 0.26, 0.18, 0.07, 0.15])
# per-facility baseline occupancy (academic runs hot; critical access low) -> real spread by facility
fac_occ_base = np.array([0.89, 0.83, 0.74, 0.57, 0.69])

def fac_idx(size):
    return rng.choice(np.arange(N_FACILITIES), size=size, p=fac_w)

# --- units ---
unit_types = ["ICU", "Med/Surg", "Telemetry", "Emergency Dept", "Operating Room",
              "Labor & Delivery", "Behavioral Health", "Oncology", "Cardiac"]
unit_type_w = [0.12, 0.30, 0.16, 0.10, 0.10, 0.06, 0.05, 0.06, 0.05]
u_fac = fac_idx(N_UNITS)
u_type = wchoice(unit_types, unit_type_w, N_UNITS)
u_beds = np.clip((rng.normal(28, 10, N_UNITS)).astype(int), 8, 60)
units = pl.DataFrame({
    "unit_id":       [f"U{i+1:03d}" for i in range(N_UNITS)],
    "unit_name":     [f"{u_type[i]} {chr(65 + (i % 4))}" for i in range(N_UNITS)],
    "facility_id":   fac_id_arr[u_fac],
    "facility_name": fac_name_arr[u_fac],
    "unit_type":     u_type,
    "licensed_beds": u_beds,
})
TABLES["reference.units"] = units

# --- payers ---
payer_names = ["Medicare", "Medicaid", "Empire BlueCross BlueShield", "UnitedHealthcare",
               "Aetna", "Cigna", "Humana", "Oscar Health", "Self-Pay / Uninsured",
               "Workers' Compensation"]
payer_types = ["Medicare", "Medicaid", "Commercial", "Commercial", "Commercial",
               "Commercial", "Medicare Advantage", "Commercial", "Self-Pay", "Other"]
# payer mix weights
payer_w = np.array([0.30, 0.18, 0.14, 0.12, 0.07, 0.05, 0.06, 0.02, 0.04, 0.02])
payers = pl.DataFrame({
    "payer_id":   [f"PY{i+1:02d}" for i in range(N_PAYERS)],
    "payer_name": payer_names,
    "payer_type": payer_types,
})
TABLES["reference.payers"] = payers
payer_id_arr   = payers["payer_id"].to_numpy()
payer_name_arr = payers["payer_name"].to_numpy()
payer_type_arr = payers["payer_type"].to_numpy()
# per-payer denial propensity & days-to-pay (realistic spread)
payer_denial_rate = np.array([0.08, 0.16, 0.11, 0.13, 0.12, 0.10, 0.09, 0.14, 0.02, 0.18])
payer_days_to_pay = np.array([22, 41, 33, 30, 32, 29, 27, 35, 12, 55])
# per-payer net collection rate (govt/self-pay collect less than commercial)
payer_net_collect = np.array([0.97, 0.915, 0.965, 0.96, 0.955, 0.96, 0.95, 0.94, 0.32, 0.93])

# --- providers ---
service_lines = ["Cardiology", "Orthopedics", "General Surgery", "Internal Medicine",
                 "Emergency Medicine", "Neurology", "Oncology", "Obstetrics & Gynecology",
                 "Pulmonology", "Gastroenterology", "Nephrology", "Behavioral Health"]
sl_w = [0.11, 0.10, 0.09, 0.18, 0.12, 0.06, 0.07, 0.07, 0.06, 0.06, 0.04, 0.04]
# real-world base inpatient ALOS (days) by service line, at average acuity
sl_base_los = {"Obstetrics & Gynecology": 2.4, "Orthopedics": 3.0, "Emergency Medicine": 2.8,
               "Internal Medicine": 4.2, "Gastroenterology": 4.3, "General Surgery": 4.6,
               "Cardiology": 4.6, "Pulmonology": 4.8, "Nephrology": 5.0, "Neurology": 5.4,
               "Oncology": 5.8, "Behavioral Health": 7.5}
prov_first = pool(g.person.first_name)
prov_last  = pool(g.person.last_name)
p_sl  = wchoice(service_lines, sl_w, N_PROVIDERS)
p_fac = fac_idx(N_PROVIDERS)
p_type = wchoice(["MD", "DO", "NP", "PA"], [0.62, 0.10, 0.16, 0.12], N_PROVIDERS)
providers = pl.DataFrame({
    "provider_id":    [f"PR{i+1:05d}" for i in range(N_PROVIDERS)],
    "provider_name":  ["Dr. " + f + " " + l for f, l in
                       zip(pick(prov_first, N_PROVIDERS), pick(prov_last, N_PROVIDERS))],
    "provider_type":  p_type,
    "specialty":      p_sl,
    "service_line":   p_sl,
    "facility_id":    fac_id_arr[p_fac],
    "facility_name":  fac_name_arr[p_fac],
    "npi":            [f"{n}" for n in rng.integers(1_000_000_000, 1_999_999_999, N_PROVIDERS)],
    "is_active":      rng.random(N_PROVIDERS) < 0.94,
})
TABLES["reference.providers"] = providers
prov_id_arr = providers["provider_id"].to_numpy()
prov_sl_arr = providers["service_line"].to_numpy()
prov_fac_arr = p_fac  # facility index per provider

# --- patients ---
print("Generating patients ...")
# curated common US names (less "random"-looking than Mimesis); first name matched to sex
FIRST_F = np.array(["Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan",
                    "Jessica", "Sarah", "Karen", "Nancy", "Lisa", "Margaret", "Sandra", "Ashley",
                    "Kimberly", "Emily", "Donna", "Michelle", "Carol", "Amanda", "Dorothy", "Melissa",
                    "Deborah", "Stephanie", "Rebecca", "Sharon", "Laura", "Cynthia", "Kathleen",
                    "Amy", "Angela", "Anna", "Ruth", "Brenda", "Pamela", "Nicole", "Katherine", "Christine", "Maria"])
FIRST_M = np.array(["James", "Robert", "John", "Michael", "David", "William", "Richard", "Joseph",
                    "Thomas", "Charles", "Christopher", "Daniel", "Matthew", "Anthony", "Mark",
                    "Donald", "Steven", "Paul", "Andrew", "Joshua", "Kenneth", "Kevin", "Brian",
                    "George", "Timothy", "Ronald", "Edward", "Jason", "Jeffrey", "Ryan", "Jacob",
                    "Gary", "Nicholas", "Eric", "Jonathan", "Stephen", "Larry", "Frank", "Scott", "Raymond"])
LAST = np.array(["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
                 "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
                 "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
                 "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
                 "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
                 "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts"])
# age skewed older (provider panel); mixture of buckets
# includes newborns (0) and pediatrics; skews older overall (provider panel)
age_bucket = wchoice([0, 1, 12, 30, 45, 62, 75],
                     [0.05, 0.06, 0.10, 0.18, 0.20, 0.24, 0.17], N_PATIENTS)
pt_age = np.clip(age_bucket + rng.integers(0, 13, N_PATIENTS), 0, 99)
pt_sex = wchoice(["Female", "Male"], [0.52, 0.48], N_PATIENTS)
pt_first_name = np.where(pt_sex == "Female",
                         FIRST_F[rng.integers(0, len(FIRST_F), N_PATIENTS)],
                         FIRST_M[rng.integers(0, len(FIRST_M), N_PATIENTS)])
pt_last_name = LAST[rng.integers(0, len(LAST), N_PATIENTS)]
# chronic conditions increase with age
chronic_lambda = np.clip((pt_age - 30) / 22, 0.1, 3.2)
chronic_cnt = rng.poisson(chronic_lambda).clip(0, 8)
# payer correlated with age (older -> Medicare)
pt_payer_idx = np.empty(N_PATIENTS, dtype=int)
for i in range(N_PATIENTS):
    if pt_age[i] >= 65:
        pt_payer_idx[i] = rng.choice([0, 6, 1, 8], p=[0.62, 0.22, 0.10, 0.06])  # Medicare/MA/Medicaid/SelfPay
    elif pt_age[i] < 18:
        pt_payer_idx[i] = rng.choice([1, 2, 3, 4], p=[0.45, 0.22, 0.20, 0.13])
    else:
        # working-age adults: commercial-skewed, little/no Medicare
        pt_payer_idx[i] = rng.choice([1, 2, 3, 4, 5, 7, 8, 9],
                                     p=[0.20, 0.26, 0.22, 0.13, 0.09, 0.04, 0.04, 0.02])
pt_fac = fac_idx(N_PATIENTS)
pt_pcp = pick(prov_id_arr, N_PATIENTS)
reg_offset = rng.integers(0, 365 * 8, N_PATIENTS).astype("timedelta64[D]")
patients = pl.DataFrame({
    "patient_id":            [f"PT{i+1:08d}" for i in range(N_PATIENTS)],
    "first_name":            pt_first_name,
    "last_name":             pt_last_name,
    "age":                   pt_age,
    "sex":                   pt_sex,
    "race":                  wchoice(["White", "Black or African American", "Asian",
                                      "Hispanic or Latino", "Other", "Unknown"],
                                     [0.55, 0.16, 0.08, 0.15, 0.04, 0.02], N_PATIENTS),
    "city":                  pick(np.array(fac_city), N_PATIENTS),
    "state":                 ["NY"] * N_PATIENTS,
    "zip_code":              [f"1{z:04d}" for z in rng.integers(0, 9999, N_PATIENTS)],
    "primary_facility_id":   fac_id_arr[pt_fac],
    "primary_facility_name": fac_name_arr[pt_fac],
    "pcp_provider_id":       pt_pcp,
    "payer_id":              payer_id_arr[pt_payer_idx],
    "payer_name":            payer_name_arr[pt_payer_idx],
    "payer_type":            payer_type_arr[pt_payer_idx],
    "chronic_conditions":    chronic_cnt,
    "registration_date":     DATE_START - reg_offset,
    "is_active":             rng.random(N_PATIENTS) < 0.9,
})
TABLES["reference.patients"] = patients

# risk tier derived from age + chronic burden (drives utilization downstream).
# Quantile thresholds enforce a realistic population-health pyramid: ~75% Low,
# ~17% Rising, ~8% High (rather than a fixed cutoff that skews top-heavy).
risk_raw = (pt_age / 100) + chronic_cnt * 0.18 + rng.normal(0, 0.15, N_PATIENTS)
_ris_thr = np.quantile(risk_raw, 0.75)
_hi_thr = np.quantile(risk_raw, 0.92)
risk_tier = np.where(risk_raw >= _hi_thr, "High",
             np.where(risk_raw >= _ris_thr, "Rising", "Low"))
# utilization weight: high-risk patients generate more encounters
util_w = np.where(risk_tier == "High", 5.0,
          np.where(risk_tier == "Rising", 2.2, 1.0)) * rng.uniform(0.5, 1.5, N_PATIENTS)
util_w = util_w / util_w.sum()

# ============================================================================
# OPERATIONS
# ============================================================================
print("Generating encounters ...")
# assign encounters to patients weighted by utilization
enc_pt_idx = rng.choice(np.arange(N_PATIENTS), size=N_ENCOUNTERS, p=util_w)

# admit dates with seasonal weighting
day_arr = daterange()
day_months = day_arr.astype("datetime64[M]").astype(int) % 12  # 0=Jan
day_w = seasonal_weight(day_months)
day_w = day_w / day_w.sum()
enc_day_idx = rng.choice(np.arange(N_DAYS), size=N_ENCOUNTERS, p=day_w)
admit_date = day_arr[enc_day_idx]

enc_type = wchoice(["Emergency", "Outpatient", "Inpatient", "Observation"],
                   [0.38, 0.35, 0.20, 0.07], N_ENCOUNTERS)
is_ip  = enc_type == "Inpatient"
is_ed  = enc_type == "Emergency"
is_obs = enc_type == "Observation"

# service line per encounter — eligibility-aware (no OB/Delivery for men or
# outside reproductive age; that was the "Delivery for a 69-year-old" bug)
pt_age_enc = pt_age[enc_pt_idx]
pt_sex_enc = pt_sex[enc_pt_idx]
enc_sl = wchoice(service_lines, sl_w, N_ENCOUNTERS)
_OB = "Obstetrics & Gynecology"
_ob_ok = (pt_sex_enc == "Female") & (pt_age_enc >= 15) & (pt_age_enc <= 50)
_bad_ob = (enc_sl == _OB) & ~_ob_ok
if _bad_ob.any():
    _nonob = [s for s in service_lines if s != _OB]
    _nonob_w = np.array([sl_w[service_lines.index(s)] for s in _nonob])
    enc_sl[_bad_ob] = wchoice(_nonob, _nonob_w, int(_bad_ob.sum()))

# acuity/severity 1-4 (higher for inpatient + older + high chronic)
pt_chr_enc = chronic_cnt[enc_pt_idx]
sev_score = (rng.normal(1.6, 0.7, N_ENCOUNTERS)
             + is_ip * 1.1 + (pt_age_enc > 70) * 0.5 + (pt_chr_enc > 3) * 0.4)
severity = np.clip(np.round(sev_score), 1, 4).astype(int)

# sepsis flag (mostly inpatient, higher severity)
sepsis_p = np.where(is_ip, 0.04, 0.005) * (1 + (severity - 1) * 0.6)
is_sepsis = rng.random(N_ENCOUNTERS) < sepsis_p

# LOS: inpatient driven by severity + sepsis + age; others short.
# Tuned to a realistic inpatient ALOS (~4.5 days, median 3-4).
# LOS anchored on each line's real base ALOS, modulated by acuity, sepsis, and age
los_noise = rng.gamma(3.0, 1 / 3.0, N_ENCOUNTERS)  # mean 1, realistic right skew
sl_base_arr = np.array([sl_base_los[sl] for sl in enc_sl])
los_days = np.where(is_ip,
                    np.round(sl_base_arr * los_noise * (1 + 0.20 * (severity - 3)) * (1 + 0.8 * is_sepsis)
                             + (pt_age_enc > 75) * 0.7).clip(1, 60),
            np.where(is_obs, rng.integers(1, 3, N_ENCOUNTERS), 0)).astype(int)
discharge_date = admit_date + los_days.astype("timedelta64[D]")

# mortality: rare, rises with severity/sepsis/age
mort_p = (0.002 + (severity == 4) * 0.04 + is_sepsis * 0.08
          + (pt_age_enc > 80) * 0.03) * is_ip
expired = rng.random(N_ENCOUNTERS) < mort_p

# Disposition: ED encounters use ED-appropriate outcomes (home / admitted /
# transferred); inpatient & observation use post-acute dispositions.
ed_disp = wchoice(["Discharged - Home", "Admitted as Inpatient", "Transferred"],
                  [0.80, 0.17, 0.03], N_ENCOUNTERS)
ip_disp = wchoice(["Discharged - Home", "Home Health", "Skilled Nursing Facility",
                   "Rehab", "Transferred", "Against Medical Advice"],
                  [0.58, 0.16, 0.13, 0.06, 0.04, 0.03], N_ENCOUNTERS)
disposition = np.where(expired, "Expired",
               np.where(is_ed, ed_disp, ip_disp))

# provider: pick a provider matching the encounter service line where possible
sl_to_prov = {sl: prov_id_arr[prov_sl_arr == sl] for sl in service_lines}
attending = np.empty(N_ENCOUNTERS, dtype=object)
for sl in service_lines:
    mask = enc_sl == sl
    cand = sl_to_prov[sl] if len(sl_to_prov[sl]) else prov_id_arr
    attending[mask] = cand[rng.integers(0, len(cand), mask.sum())]

enc_fac_idx = fac_idx(N_ENCOUNTERS)
diagnoses = {
    "Cardiology": ["Heart failure", "Atrial fibrillation", "Acute MI", "Chest pain"],
    "Orthopedics": ["Hip fracture", "Knee osteoarthritis", "Joint replacement", "Back pain"],
    "General Surgery": ["Appendicitis", "Cholecystitis", "Hernia", "Bowel obstruction"],
    "Internal Medicine": ["Pneumonia", "Diabetes complication", "Cellulitis", "Dehydration"],
    "Emergency Medicine": ["Chest pain", "Abdominal pain", "Injury", "Shortness of breath"],
    "Neurology": ["Stroke", "Seizure", "TIA", "Headache"],
    "Oncology": ["Chemotherapy", "Neutropenic fever", "Malignancy", "Pain management"],
    "Obstetrics & Gynecology": ["Delivery", "Preeclampsia", "Pelvic pain", "Hemorrhage"],
    "Pulmonology": ["COPD exacerbation", "Pneumonia", "Respiratory failure", "Asthma"],
    "Gastroenterology": ["GI bleed", "Pancreatitis", "Liver disease", "Colitis"],
    "Nephrology": ["Acute kidney injury", "ESRD", "Electrolyte disorder", "Dialysis"],
    "Behavioral Health": ["Depression", "Psychosis", "Substance use", "Anxiety"],
}
primary_dx = np.array([rng.choice(diagnoses[sl]) for sl in enc_sl])

enc_payer_idx = pt_payer_idx[enc_pt_idx]
encounters = pl.DataFrame({
    "encounter_id":           [f"EN{i+1:08d}" for i in range(N_ENCOUNTERS)],
    "patient_id":             patients["patient_id"].to_numpy()[enc_pt_idx],
    "patient_age":            pt_age_enc,
    "patient_sex":            pt_sex[enc_pt_idx],
    "facility_id":            fac_id_arr[enc_fac_idx],
    "facility_name":          fac_name_arr[enc_fac_idx],
    "attending_provider_id":  attending.astype(str),
    "service_line":           enc_sl,
    "encounter_type":         enc_type,
    "admit_date":             admit_date,
    "discharge_date":         discharge_date,
    "los_days":               los_days,
    "severity_level":         severity,
    "is_icu":                 (is_ip & (severity >= 3) & (rng.random(N_ENCOUNTERS) < 0.6)),
    "is_sepsis":              is_sepsis,
    "primary_diagnosis":      primary_dx,
    "discharge_disposition":  disposition,
    "expired_flag":           expired,
    "payer_id":               payer_id_arr[enc_payer_idx],
    "payer_name":             payer_name_arr[enc_payer_idx],
    "payer_type":             payer_type_arr[enc_payer_idx],
})
TABLES["operations.encounters"] = encounters

# --- ed_visits (derived from Emergency encounters) ---
print("Generating ED visits ...")
ed_idx = np.where(is_ed)[0]
n_ed = len(ed_idx)
# arrival hour: bimodal, afternoon/evening peak
hour_w = np.array([2,1,1,1,1,2,3,4,5,5,6,6,7,7,8,8,9,9,8,7,6,5,4,3], dtype=float)
arr_hour = rng.choice(np.arange(24), size=n_ed, p=hour_w / hour_w.sum())
esi = wchoice([1, 2, 3, 4, 5], [0.03, 0.15, 0.42, 0.30, 0.10], n_ed)
admitted = disposition[ed_idx] != "Discharged - Home"
# boarding worse for admitted + winter (seasonal)
ed_month = admit_date[ed_idx].astype("datetime64[M]").astype(int) % 12
season = seasonal_weight(ed_month)
door_to_prov = np.round(rng.gamma(2.0, 9, n_ed) * (6 - esi) / 3 * season).clip(2, 240).astype(int)
ed_los = np.round(rng.gamma(3.0, 50, n_ed) + admitted * 120).clip(20, 1440).astype(int)
boarding = np.where(admitted, np.round(rng.gamma(2.0, 80, n_ed) * season).clip(0, 1440), 0).astype(int)
lwbs = (esi >= 4) & (rng.random(n_ed) < 0.04 * season)
ed_visits = pl.DataFrame({
    "ed_visit_id":          [f"ED{i+1:07d}" for i in range(n_ed)],
    "encounter_id":         encounters["encounter_id"].to_numpy()[ed_idx],
    "patient_id":           encounters["patient_id"].to_numpy()[ed_idx],
    "facility_id":          encounters["facility_id"].to_numpy()[ed_idx],
    "facility_name":        encounters["facility_name"].to_numpy()[ed_idx],
    "arrival_date":         admit_date[ed_idx],
    "arrival_hour":         arr_hour,
    "esi_acuity":           esi,
    "chief_complaint":      primary_dx[ed_idx],
    "disposition":          np.where(lwbs, "Left Without Being Seen",
                                     np.where(admitted, "Admitted", "Discharged")),
    "door_to_provider_min": door_to_prov,
    "ed_los_minutes":       ed_los,
    "boarding_minutes":     boarding,
    "left_without_being_seen": lwbs,
    "admitted_flag":        admitted,
})
TABLES["operations.ed_visits"] = ed_visits

# --- or_cases (derived from surgical service lines) ---
print("Generating OR cases ...")
surg_lines = ["Orthopedics", "General Surgery", "Cardiology", "Obstetrics & Gynecology", "Neurology"]
or_mask = np.isin(enc_sl, surg_lines) & (rng.random(N_ENCOUNTERS) < 0.45) & ~is_ed
or_idx = np.where(or_mask)[0]
n_or = len(or_idx)
sched_min = np.round(rng.gamma(4.0, 35, n_or) + 30).clip(20, 600).astype(int)
actual_min = np.round(sched_min * rng.normal(1.05, 0.18, n_or)).clip(15, 720).astype(int)
or_cases = pl.DataFrame({
    "or_case_id":          [f"OR{i+1:07d}" for i in range(n_or)],
    "encounter_id":        encounters["encounter_id"].to_numpy()[or_idx],
    "patient_id":          encounters["patient_id"].to_numpy()[or_idx],
    "facility_id":         encounters["facility_id"].to_numpy()[or_idx],
    "facility_name":       encounters["facility_name"].to_numpy()[or_idx],
    "service_line":        enc_sl[or_idx],
    "surgeon_provider_id": attending.astype(str)[or_idx],
    "procedure_name":      primary_dx[or_idx],
    "case_date":           admit_date[or_idx],
    "scheduled_minutes":   sched_min,
    "actual_minutes":      actual_min,
    "turnover_minutes":    np.round(rng.gamma(2.0, 12, n_or)).clip(8, 90).astype(int),
    "first_case_on_time":  rng.random(n_or) < 0.74,
    "cancelled_flag":      rng.random(n_or) < 0.06,
})
TABLES["operations.or_cases"] = or_cases

# --- appointments (ambulatory access & no-shows) ---
print("Generating ambulatory appointments ...")
N_APPTS = 120_000
ap_pt = rng.choice(np.arange(N_PATIENTS), size=N_APPTS, p=util_w)  # same utilization weighting
ap_day = rng.choice(np.arange(N_DAYS), size=N_APPTS, p=day_w)
ap_date = day_arr[ap_day]
ap_sl = wchoice(service_lines, sl_w, N_APPTS)
ap_type = wchoice(["Follow-up", "New Patient", "Annual Wellness", "Procedure", "Telehealth"],
                  [0.50, 0.18, 0.12, 0.10, 0.10], N_APPTS)
ap_tele = ap_type == "Telehealth"
ap_lead = np.round(rng.gamma(2.0, 9, N_APPTS)).clip(0, 120).astype(int)  # booking->visit (access proxy)
ap_payer = payer_type_arr[pt_payer_idx[ap_pt]]
ap_age = pt_age[ap_pt]
# no-show probability: higher for Medicaid/Self-Pay, younger, behavioral health, long lead; telehealth lower
noshow_p = np.clip(0.10 + (ap_payer == "Medicaid") * 0.10 + (ap_payer == "Self-Pay") * 0.08
                   + (ap_age < 35) * 0.05 + (ap_sl == "Behavioral Health") * 0.12
                   + (ap_lead > 30) * 0.05 - ap_tele * 0.04, 0.02, 0.6)
r = rng.random(N_APPTS)
ap_status = np.where(r < noshow_p, "No-Show",
             np.where(r < noshow_p + 0.06, "Cancelled",
              np.where(r < noshow_p + 0.10, "Rescheduled", "Completed")))
ap_arrived = ap_status == "Completed"
ap_wait = np.where(ap_arrived, np.round(rng.gamma(2.0, 9, N_APPTS)).clip(0, 120), 0).astype(int)
ap_prov = np.empty(N_APPTS, dtype=object)
for sl in service_lines:
    mask = ap_sl == sl
    cand = sl_to_prov[sl] if len(sl_to_prov[sl]) else prov_id_arr
    ap_prov[mask] = cand[rng.integers(0, len(cand), mask.sum())]
ap_fac = fac_idx(N_APPTS)
appointments = pl.DataFrame({
    "appointment_id":      [f"AP{i+1:08d}" for i in range(N_APPTS)],
    "patient_id":          patients["patient_id"].to_numpy()[ap_pt],
    "patient_age":         ap_age,
    "provider_id":         ap_prov.astype(str),
    "service_line":        ap_sl,
    "facility_id":         fac_id_arr[ap_fac],
    "facility_name":       fac_name_arr[ap_fac],
    "appointment_date":    ap_date,
    "appointment_type":    ap_type,
    "is_telehealth":       ap_tele,
    "scheduled_lead_days": ap_lead,
    "status":              ap_status,
    "arrived_flag":        ap_arrived,
    "no_show_flag":        ap_status == "No-Show",
    "wait_time_minutes":   ap_wait,
    "payer_type":          ap_payer,
})
TABLES["operations.appointments"] = appointments

# --- patient_census (daily by unit) ---
print("Generating daily census ...")
unit_ids = units["unit_id"].to_numpy()
unit_names = units["unit_name"].to_numpy()
unit_fac_id = units["facility_id"].to_numpy()
unit_fac_nm = units["facility_name"].to_numpy()
unit_typ = units["unit_type"].to_numpy()
unit_bed = units["licensed_beds"].to_numpy()
days = daterange()
rows = N_UNITS * N_DAYS
c_unit = np.repeat(np.arange(N_UNITS), N_DAYS)
c_day  = np.tile(np.arange(N_DAYS), N_UNITS)
c_month = days[c_day].astype("datetime64[M]").astype(int) % 12
c_season = seasonal_weight(c_month)
beds = unit_bed[c_unit]
# occupancy driven by per-facility baseline (+ ICU runs hotter) + seasonality
occ_base = fac_occ_base[u_fac[c_unit]] + np.where(unit_typ[c_unit] == "ICU", 0.05, 0.0)
target_occ = np.clip(rng.normal(occ_base, 0.06) * c_season, 0.25, 0.99)
census = np.round(beds * target_occ).astype(int)
admissions = np.round(census * rng.uniform(0.12, 0.30, rows)).astype(int)
census_tbl = pl.DataFrame({
    "census_date":   days[c_day],
    "facility_id":   unit_fac_id[c_unit],
    "facility_name": unit_fac_nm[c_unit],
    "unit_id":       unit_ids[c_unit],
    "unit_name":     unit_names[c_unit],
    "unit_type":     unit_typ[c_unit],
    "licensed_beds": beds,
    "midnight_census": census,
    "occupancy_rate":  np.round(census / beds, 3),
    "admissions":    admissions,
    "discharges":    np.round(admissions * rng.uniform(0.85, 1.15, rows)).astype(int),
})
TABLES["operations.patient_census"] = census_tbl

# ============================================================================
# QUALITY
# ============================================================================
print("Generating quality ...")
# --- readmissions (one row per inpatient discharge, alive) ---
ip_idx = np.where(is_ip & ~expired)[0]
n_ip = len(ip_idx)
pt_risk_ip = risk_tier[enc_pt_idx[ip_idx]]
# service-line readmission tendency (CHF/COPD/renal-heavy lines high; OB/Ortho low)
sl_readmit_adj = {"Cardiology": 0.08, "Pulmonology": 0.07, "Nephrology": 0.06,
                  "Behavioral Health": 0.05, "Oncology": 0.04, "Gastroenterology": 0.03,
                  "Internal Medicine": 0.02, "Neurology": 0.01, "General Surgery": 0.0,
                  "Emergency Medicine": -0.03, "Orthopedics": -0.05, "Obstetrics & Gynecology": -0.06}
sl_radj = np.array([sl_readmit_adj[sl] for sl in enc_sl[ip_idx]])
readmit_p = np.clip(0.07 + sl_radj + (pt_risk_ip == "High") * 0.10 + (pt_risk_ip == "Rising") * 0.05
                    + is_sepsis[ip_idx] * 0.05
                    + (disposition[ip_idx] == "Skilled Nursing Facility") * 0.04, 0.01, 0.6)
readmit = rng.random(n_ip) < readmit_p
days_to_readmit = np.where(readmit, rng.integers(2, 31, n_ip), 0)
readmissions = pl.DataFrame({
    "index_encounter_id": encounters["encounter_id"].to_numpy()[ip_idx],
    "patient_id":         encounters["patient_id"].to_numpy()[ip_idx],
    "facility_id":        encounters["facility_id"].to_numpy()[ip_idx],
    "facility_name":      encounters["facility_name"].to_numpy()[ip_idx],
    "service_line":       enc_sl[ip_idx],
    "primary_diagnosis":  primary_dx[ip_idx],
    "discharge_date":     discharge_date[ip_idx],
    "discharge_disposition": disposition[ip_idx],
    "readmitted_30d":     readmit,
    "days_to_readmission": days_to_readmit,
    "readmission_date":   np.where(readmit,
                                   discharge_date[ip_idx] + days_to_readmit.astype("timedelta64[D]"),
                                   np.datetime64("NaT")),
    "is_high_risk":       pt_risk_ip == "High",
})
TABLES["quality.readmissions"] = readmissions

# --- quality_measures (facility x month aggregates) ---
measures = [
    ("30-Day All-Cause Readmission Rate", "Readmission", 0.152, "lower"),
    ("In-Hospital Mortality Rate", "Mortality", 0.021, "lower"),
    ("Sepsis Bundle Compliance (SEP-1)", "Sepsis", 0.68, "higher"),
    ("CLABSI Rate (per 1000 line days)", "Safety", 0.9, "lower"),
    ("CAUTI Rate (per 1000 cath days)", "Safety", 1.1, "lower"),
    ("Hand Hygiene Compliance", "Safety", 0.90, "higher"),
    ("ED Median Length of Stay (min)", "Throughput", 168, "lower"),
    ("Patient Falls (per 1000 pt days)", "Safety", 3.2, "lower"),
    ("CMS Star Rating", "Overall", 3.6, "higher"),
    ("HCAHPS Overall Rating (Top Box %)", "Experience", 0.72, "higher"),
]
months = np.arange(np.datetime64(str(DATE_START)[:7]), np.datetime64(str(DATE_END)[:7]) + 1)
qm_rows = []
for fi in range(N_FACILITIES):
    for m in months:
        for nm, cat, bench, dirn in measures:
            noise = rng.normal(0, bench * 0.12)
            rate = max(bench + noise, 0)
            qm_rows.append((nm, cat, fac_id_arr[fi], fac_name_arr[fi],
                            np.datetime64(m).astype("datetime64[D]").astype(object), round(float(rate), 3),
                            round(float(bench), 3), dirn))
quality_measures = pl.DataFrame(
    qm_rows,
    schema=["measure_name", "measure_category", "facility_id", "facility_name",
            "period_month", "rate", "benchmark", "better_direction"],
    orient="row",
).with_columns(
    pl.when(pl.col("better_direction") == "lower")
      .then(pl.col("benchmark") - pl.col("rate"))
      .otherwise(pl.col("rate") - pl.col("benchmark"))
      .round(3).alias("vs_benchmark"),
)
TABLES["quality.quality_measures"] = quality_measures

# --- safety_events ---
n_safety = 3000
se_unit = rng.integers(0, N_UNITS, n_safety)
se_day = rng.choice(np.arange(N_DAYS), size=n_safety, p=day_w)
safety_events = pl.DataFrame({
    "event_id":      [f"SE{i+1:06d}" for i in range(n_safety)],
    "event_date":    days[se_day],
    "facility_id":   unit_fac_id[se_unit],
    "facility_name": unit_fac_nm[se_unit],
    "unit_id":       unit_ids[se_unit],
    "unit_name":     unit_names[se_unit],
    "event_type":    wchoice(["Patient Fall", "Medication Error", "Pressure Injury",
                              "CLABSI", "CAUTI", "Specimen Error", "Equipment Failure"],
                             [0.30, 0.22, 0.14, 0.08, 0.08, 0.10, 0.08], n_safety),
    "harm_level":    wchoice(["No Harm", "Minor", "Moderate", "Severe", "Sentinel"],
                            [0.52, 0.28, 0.13, 0.06, 0.01], n_safety),
    "reported_by_role": wchoice(["RN", "Physician", "Pharmacist", "Tech", "Other"],
                               [0.55, 0.15, 0.10, 0.12, 0.08], n_safety),
})
TABLES["quality.safety_events"] = safety_events

# --- hcahps_surveys (subset of inpatient discharges) ---
hc_idx = ip_idx[rng.random(n_ip) < 0.55]
n_hc = len(hc_idx)
fac_quality_base = np.array([7.9, 8.6, 7.5, 9.0, 8.7])  # per-facility experience baseline (wider spread)
hc_fac_local = enc_fac_idx[hc_idx]
overall = np.clip(np.round(rng.normal(fac_quality_base[hc_fac_local], 1.4)), 0, 10).astype(int)
hcahps = pl.DataFrame({
    "survey_id":           [f"HC{i+1:07d}" for i in range(n_hc)],
    "encounter_id":        encounters["encounter_id"].to_numpy()[hc_idx],
    "facility_id":         encounters["facility_id"].to_numpy()[hc_idx],
    "facility_name":       encounters["facility_name"].to_numpy()[hc_idx],
    "discharge_date":      discharge_date[hc_idx],
    "overall_rating":      overall,
    "would_recommend":     overall >= 9,
    "nurse_communication": np.clip(overall + rng.integers(-1, 2, n_hc), 0, 10),
    "doctor_communication":np.clip(overall + rng.integers(-1, 2, n_hc), 0, 10),
    "staff_responsiveness":np.clip(overall + rng.integers(-2, 2, n_hc), 0, 10),
    "cleanliness":         np.clip(overall + rng.integers(-1, 3, n_hc), 0, 10),
    "quietness":           np.clip(overall + rng.integers(-2, 2, n_hc), 0, 10),
    "discharge_info":      np.clip(overall + rng.integers(-1, 2, n_hc), 0, 10),
})
TABLES["quality.hcahps_surveys"] = hcahps

# ============================================================================
# REVENUE CYCLE
# ============================================================================
print("Generating revenue cycle ...")
# --- claims (one per encounter) ---
base_charge = np.where(is_ip, rng.gamma(4.0, 9000, N_ENCOUNTERS),
               np.where(is_obs, rng.gamma(3.0, 3500, N_ENCOUNTERS),
               np.where(is_ed, rng.gamma(2.5, 1800, N_ENCOUNTERS),
                        rng.gamma(2.0, 900, N_ENCOUNTERS))))
billed = np.round(base_charge * (1 + 0.35 * (severity - 1)) * (1 + los_days * 0.04) + 250, 2)
# allowed rate by payer type
ptype_enc = payer_type_arr[enc_payer_idx]
allowed_rate = np.select(
    [ptype_enc == "Medicare", ptype_enc == "Medicaid", ptype_enc == "Self-Pay",
     ptype_enc == "Medicare Advantage"],
    [0.42, 0.38, 0.18, 0.46], default=0.55) * rng.uniform(0.9, 1.1, N_ENCOUNTERS)
allowed = np.round(billed * allowed_rate, 2)
# denial based on payer propensity + coding/severity + a gentle improving trend over time
# (denial-reduction initiative): months-since-start 0..23 -> factor ~1.12 down to ~0.85
_month_idx = ((admit_date.astype("datetime64[M]") - DATE_START.astype("datetime64[M]")).astype(int))
denial_trend = np.clip(1.12 - 0.012 * _month_idx, 0.8, 1.2)
denial_p = payer_denial_rate[enc_payer_idx] * (1 + (severity == 4) * 0.3) * denial_trend
is_denied = rng.random(N_ENCOUNTERS) < denial_p
is_partial = ~is_denied & (rng.random(N_ENCOUNTERS) < 0.12)
claim_status = np.where(is_denied, "Denied",
                np.where(is_partial, "Partially Paid",
                np.where(rng.random(N_ENCOUNTERS) < 0.08, "Pending", "Paid")))
paid = np.where(claim_status == "Paid", allowed,
        np.where(claim_status == "Partially Paid", np.round(allowed * rng.uniform(0.4, 0.8, N_ENCOUNTERS), 2),
        0.0))
patient_resp = np.round(np.where(ptype_enc == "Self-Pay", billed * 0.6, allowed * rng.uniform(0.05, 0.2, N_ENCOUNTERS)), 2)
submit_date = discharge_date + rng.integers(1, 14, N_ENCOUNTERS).astype("timedelta64[D]")
claims = pl.DataFrame({
    "claim_id":              [f"CL{i+1:08d}" for i in range(N_ENCOUNTERS)],
    "encounter_id":          encounters["encounter_id"].to_numpy(),
    "patient_id":            encounters["patient_id"].to_numpy(),
    "facility_id":           encounters["facility_id"].to_numpy(),
    "facility_name":         encounters["facility_name"].to_numpy(),
    "payer_id":              payer_id_arr[enc_payer_idx],
    "payer_name":            payer_name_arr[enc_payer_idx],
    "payer_type":            ptype_enc,
    "service_line":          enc_sl,
    "claim_type":            np.where(is_ip, "Inpatient", np.where(is_ed, "Emergency", "Outpatient")),
    "submit_date":           submit_date,
    "billed_amount":         billed,
    "allowed_amount":        allowed,
    "paid_amount":           paid,
    "patient_responsibility":patient_resp,
    "claim_status":          claim_status,
})
TABLES["revenue_cycle.claims"] = claims

# --- denials (from denied + partially paid claims) ---
den_idx = np.where((claim_status == "Denied") | (claim_status == "Partially Paid"))[0]
n_den = len(den_idx)
den_cat = wchoice(["Eligibility / Registration", "Missing or Invalid Information",
                   "Prior Authorization", "Coding Error", "Medical Necessity",
                   "Untimely Filing", "Duplicate Claim", "Non-Covered Service"],
                  [0.24, 0.18, 0.14, 0.12, 0.10, 0.09, 0.07, 0.06], n_den)
denied_amt = np.where(claim_status[den_idx] == "Denied", allowed[den_idx],
                      np.round(allowed[den_idx] - paid[den_idx], 2))
appeal = wchoice(["Not Appealed", "Pending", "Won", "Lost"], [0.40, 0.20, 0.25, 0.15], n_den)
recovered = np.where(appeal == "Won", denied_amt, np.where(appeal == "Pending", 0.0, 0.0))
denials = pl.DataFrame({
    "denial_id":        [f"DN{i+1:07d}" for i in range(n_den)],
    "claim_id":         claims["claim_id"].to_numpy()[den_idx],
    "encounter_id":     encounters["encounter_id"].to_numpy()[den_idx],
    "facility_id":      encounters["facility_id"].to_numpy()[den_idx],
    "facility_name":    encounters["facility_name"].to_numpy()[den_idx],
    "payer_id":         payer_id_arr[enc_payer_idx][den_idx],
    "payer_name":       payer_name_arr[enc_payer_idx][den_idx],
    "denial_date":      submit_date[den_idx] + rng.integers(5, 40, n_den).astype("timedelta64[D]"),
    "denial_category":  den_cat,
    "denied_amount":    denied_amt,
    "recovered_amount": recovered,
    "appeal_status":    appeal,
    "is_preventable":   np.isin(den_cat, ["Eligibility / Registration", "Missing or Invalid Information",
                                          "Coding Error", "Untimely Filing", "Duplicate Claim"]),
})
TABLES["revenue_cycle.denials"] = denials

# --- ar_aging (month x facility x payer x bucket) ---
print("Generating AR aging & payer performance ...")
buckets = ["0-30", "31-60", "61-90", "91-120", "120+"]
# real AR aging curve: most current, declining, with an aged 120+ tail that exceeds 91-120
bucket_w = np.array([0.52, 0.19, 0.11, 0.06, 0.12])
ar_rows = []
pp_rows = []
for m in months:
    md = np.datetime64(m).astype("datetime64[D]").astype(object)
    for fi in range(N_FACILITIES):
        for pj in range(N_PAYERS):
            total_ar = rng.gamma(3.0, 220_000) * fac_w[fi] * (payer_w[pj] / payer_w.max())
            for bi, b in enumerate(buckets):
                amt = round(float(total_ar * bucket_w[bi] * rng.uniform(0.8, 1.2)), 2)
                ar_rows.append((md, fac_id_arr[fi], fac_name_arr[fi], payer_id_arr[pj],
                                payer_name_arr[pj], payer_type_arr[pj], b, amt,
                                int(amt / rng.uniform(1800, 4200))))
            billed_m = round(float(rng.gamma(4.0, 180_000) * fac_w[fi] * (payer_w[pj] / payer_w.max() + 0.2)), 2)
            dr = float(np.clip(payer_denial_rate[pj] + rng.normal(0, 0.02), 0.01, 0.4))
            pp_rows.append((md, payer_id_arr[pj], payer_name_arr[pj], payer_type_arr[pj],
                            fac_id_arr[fi], fac_name_arr[fi], billed_m,
                            round(billed_m * (1 - dr) * rng.uniform(0.5, 0.62), 2),
                            round(dr, 3), int(payer_days_to_pay[pj] + rng.integers(-4, 5)),
                            round(float(np.clip(payer_net_collect[pj] + rng.normal(0, 0.008), 0.15, 0.999)), 3)))
ar_aging = pl.DataFrame(ar_rows, schema=[
    "snapshot_month", "facility_id", "facility_name", "payer_id", "payer_name",
    "payer_type", "ar_bucket", "ar_amount", "account_count"], orient="row")
TABLES["revenue_cycle.ar_aging"] = ar_aging
payer_perf = pl.DataFrame(pp_rows, schema=[
    "period_month", "payer_id", "payer_name", "payer_type", "facility_id", "facility_name",
    "total_billed", "total_paid", "denial_rate", "avg_days_to_pay", "net_collection_rate"],
    orient="row")
TABLES["revenue_cycle.payer_performance"] = payer_perf

# --- service_line_pnl (contribution margin) — derived from claims so it reconciles ---
print("Generating service line P&L ...")
# direct cost as a share of net revenue, varying by service line (drives margin spread)
cost_ratio = {
    "Orthopedics": 0.62, "Cardiology": 0.67, "General Surgery": 0.70, "Gastroenterology": 0.72,
    "Obstetrics & Gynecology": 0.80, "Neurology": 0.78, "Oncology": 0.83, "Pulmonology": 0.82,
    "Nephrology": 0.88, "Internal Medicine": 0.92, "Emergency Medicine": 0.95,
    "Behavioral Health": 1.06,  # typically a loss leader
}
pnl = (
    claims
    .with_columns([
        pl.date(pl.col("submit_date").dt.year(), pl.col("submit_date").dt.month(), 1).alias("period_month"),
        (pl.col("paid_amount") + pl.col("patient_responsibility")).alias("_net"),
    ])
    .group_by(["period_month", "facility_id", "facility_name", "service_line"])
    .agg([
        pl.len().alias("encounter_volume"),
        pl.col("billed_amount").sum().round(2).alias("gross_charges"),
        pl.col("_net").sum().round(2).alias("net_revenue"),
    ])
    .with_columns(
        pl.col("service_line").replace_strict(cost_ratio, default=0.85).alias("_cr"))
    .with_columns(
        (pl.col("net_revenue") * pl.col("_cr")).round(2).alias("direct_cost"))
    .with_columns(
        (pl.col("net_revenue") - pl.col("direct_cost")).round(2).alias("contribution_margin"))
    .with_columns(
        pl.when(pl.col("net_revenue") > 0)
          .then((pl.col("contribution_margin") / pl.col("net_revenue")).round(3))
          .otherwise(0.0).alias("margin_pct"))
    .drop("_cr")
    .sort(["period_month", "facility_name", "service_line"])
)
TABLES["revenue_cycle.service_line_pnl"] = pnl

# ============================================================================
# POPULATION HEALTH
# ============================================================================
print("Generating population health ...")
has_dm  = (chronic_cnt >= 1) & (rng.random(N_PATIENTS) < 0.45)
has_chf = (chronic_cnt >= 2) & (rng.random(N_PATIENTS) < 0.35)
has_copd= (chronic_cnt >= 2) & (rng.random(N_PATIENTS) < 0.30)
has_ckd = (chronic_cnt >= 2) & (rng.random(N_PATIENTS) < 0.28)
has_htn = (chronic_cnt >= 1) & (rng.random(N_PATIENTS) < 0.60)
# last visit date
last_visit = DATE_END - rng.integers(0, 400, N_PATIENTS).astype("timedelta64[D]")
registry = pl.DataFrame({
    "patient_id":           patients["patient_id"].to_numpy(),
    "patient_age":          pt_age,
    "patient_sex":          pt_sex,
    "attributed_pcp_id":    pt_pcp,
    "primary_facility_name":fac_name_arr[pt_fac],
    "payer_type":           payer_type_arr[pt_payer_idx],
    "risk_tier":            risk_tier,
    "chronic_conditions":   chronic_cnt,
    "has_diabetes":         has_dm,
    "has_chf":              has_chf,
    "has_copd":             has_copd,
    "has_ckd":              has_ckd,
    "has_hypertension":     has_htn,
    "is_aco_attributed":    rng.random(N_PATIENTS) < 0.55,
    "last_visit_date":      last_visit,
})
TABLES["population_health.patient_registry"] = registry

# --- care_gaps (clinically eligible; one row per patient-measure, no repeats) ---
gap_measures = ["A1c Testing (Diabetes)", "Blood Pressure Control", "Breast Cancer Screening",
                "Colorectal Cancer Screening", "Diabetic Eye Exam", "Medication Adherence",
                "Annual Wellness Visit", "Statin Therapy"]
# per-measure closure rate (process measures close easily; screenings lag)
gap_close_p = {"A1c Testing (Diabetes)": 0.74, "Blood Pressure Control": 0.66,
               "Breast Cancer Screening": 0.61, "Colorectal Cancer Screening": 0.47,
               "Diabetic Eye Exam": 0.50, "Medication Adherence": 0.57,
               "Annual Wellness Visit": 0.71, "Statin Therapy": 0.64}
# clinical eligibility per measure (sex / age / condition appropriate)
gap_eligible = {
    "A1c Testing (Diabetes)":      has_dm,
    "Diabetic Eye Exam":           has_dm,
    "Blood Pressure Control":      has_htn,
    "Statin Therapy":              has_dm | has_htn | (pt_age >= 55),
    "Breast Cancer Screening":     (pt_sex == "Female") & (pt_age >= 40) & (pt_age <= 74),
    "Colorectal Cancer Screening": (pt_age >= 45) & (pt_age <= 75),
    "Medication Adherence":        chronic_cnt >= 1,
    "Annual Wellness Visit":       pt_age >= 18,
}
# share of eligible patients carrying a (open or closed) gap for the measure
gap_prevalence = {"A1c Testing (Diabetes)": 0.55, "Diabetic Eye Exam": 0.50,
                  "Blood Pressure Control": 0.50, "Statin Therapy": 0.40,
                  "Breast Cancer Screening": 0.45, "Colorectal Cancer Screening": 0.50,
                  "Medication Adherence": 0.35, "Annual Wellness Visit": 0.55}
gp_pt_list, gp_meas_list = [], []
for m in gap_measures:
    elig_idx = np.where(gap_eligible[m])[0]
    take = elig_idx[rng.random(len(elig_idx)) < gap_prevalence[m]]
    gp_pt_list.append(take)
    gp_meas_list.append(np.full(len(take), m, dtype=object))
gp_pt = np.concatenate(gp_pt_list)
gp_meas = np.concatenate(gp_meas_list).astype(str)
n_gap = len(gp_pt)
gap_status = np.where(rng.random(n_gap) < np.array([gap_close_p[m] for m in gp_meas]), "Closed", "Open")
due = DATE_END - rng.integers(-120, 240, n_gap).astype("timedelta64[D]")
care_gaps = pl.DataFrame({
    "gap_id":         [f"GAP{i+1:07d}" for i in range(n_gap)],
    "patient_id":     patients["patient_id"].to_numpy()[gp_pt],
    "patient_age":    pt_age[gp_pt],
    "patient_sex":    pt_sex[gp_pt],
    "risk_tier":      risk_tier[gp_pt],
    "primary_facility_name": fac_name_arr[pt_fac][gp_pt],
    "measure":        gp_meas,
    "gap_status":     gap_status,
    "due_date":       due,
    "days_open":      np.where(gap_status == "Open",
                               (DATE_END - due).astype("timedelta64[D]").astype(int).clip(0, None),
                               rng.integers(0, 120, n_gap)),
})
TABLES["population_health.care_gaps"] = care_gaps

# --- risk_scores (one per patient) ---
hcc = np.round(chronic_cnt * rng.uniform(0.6, 1.2, N_PATIENTS)).astype(int)
risk_score_val = np.round(0.5 + (pt_age / 100) + hcc * 0.25 + rng.normal(0, 0.2, N_PATIENTS), 2).clip(0.1, 6)
risk_scores = pl.DataFrame({
    "patient_id":            patients["patient_id"].to_numpy(),
    "score_date":            np.full(N_PATIENTS, DATE_END),
    "risk_model":            np.full(N_PATIENTS, "HCC + Care Gap Composite"),
    "risk_score":            risk_score_val,
    "risk_tier":             risk_tier,
    "hcc_count":             hcc,
    "predicted_admit_prob":  np.round(np.clip(risk_score_val / 8 + rng.normal(0, 0.03, N_PATIENTS), 0.01, 0.95), 3),
    "predicted_annual_cost": np.round(risk_score_val * rng.uniform(4000, 9000, N_PATIENTS), 2),
})
TABLES["population_health.risk_scores"] = risk_scores

# --- sdoh ---
svi = np.round(rng.beta(2, 3, N_PATIENTS), 3)
sdoh = pl.DataFrame({
    "patient_id":               patients["patient_id"].to_numpy(),
    "zip_code":                 patients["zip_code"].to_numpy(),
    "svi_score":                svi,
    "food_insecurity":          rng.random(N_PATIENTS) < (0.10 + svi * 0.3),
    "transportation_barrier":   rng.random(N_PATIENTS) < (0.08 + svi * 0.25),
    "housing_instability":      rng.random(N_PATIENTS) < (0.05 + svi * 0.2),
    "preferred_language":       wchoice(["English", "Spanish", "Mandarin", "Other"],
                                        [0.78, 0.14, 0.04, 0.04], N_PATIENTS),
    "interpreter_needed":       rng.random(N_PATIENTS) < 0.12,
})
TABLES["population_health.sdoh"] = sdoh

# ============================================================================
# WORKFORCE
# ============================================================================
print("Generating workforce ...")
# --- staffing_daily (unit x day; agency/OT correlate with census/season) ---
staffed_units = units.filter(pl.col("unit_type").is_in(
    ["ICU", "Med/Surg", "Telemetry", "Oncology", "Cardiac", "Behavioral Health"]))
su_id = staffed_units["unit_id"].to_numpy()
su_nm = staffed_units["unit_name"].to_numpy()
su_fid = staffed_units["facility_id"].to_numpy()
su_fnm = staffed_units["facility_name"].to_numpy()
su_typ = staffed_units["unit_type"].to_numpy()
su_bed = staffed_units["licensed_beds"].to_numpy()
nU = len(su_id)
s_unit = np.repeat(np.arange(nU), N_DAYS)
s_day = np.tile(np.arange(N_DAYS), nU)
rows_s = nU * N_DAYS
s_month = days[s_day].astype("datetime64[M]").astype(int) % 12
s_season = seasonal_weight(s_month)
s_census = np.round(su_bed[s_unit] * np.clip(rng.normal(0.78, 0.1, rows_s) * s_season, 0.2, 0.99)).astype(int)
# target ratio by unit type
ratio_map = {"ICU": 2.0, "Med/Surg": 5.0, "Telemetry": 4.0, "Oncology": 4.0,
             "Cardiac": 3.5, "Behavioral Health": 6.0}
target_ratio = np.array([ratio_map[t] for t in su_typ[s_unit]])
needed = np.ceil(s_census / target_ratio).astype(int)
sick = rng.poisson(0.4 * s_season).clip(0, 5)
actual = (needed - sick).clip(1, None)
agency = np.round((needed - actual).clip(0, None) + (s_season > 1.1) * rng.integers(0, 3, rows_s)).clip(0, None).astype(int)
overtime = np.round(rng.gamma(2.0, 4, rows_s) * s_season).clip(0, 80).astype(int)
staffing = pl.DataFrame({
    "staffing_date":   days[s_day],
    "facility_id":     su_fid[s_unit],
    "facility_name":   su_fnm[s_unit],
    "unit_id":         su_id[s_unit],
    "unit_name":       su_nm[s_unit],
    "unit_type":       su_typ[s_unit],
    "patient_census":  s_census,
    "scheduled_nurses":needed,
    "actual_nurses":   actual,
    "agency_nurses":   agency,
    "nurse_to_patient_ratio": np.round(s_census / actual.clip(1, None), 2),
    "overtime_hours":  overtime,
    "sick_calls":      sick,
    "open_shifts":     (needed - actual + agency).clip(0, None),
})
TABLES["workforce.staffing_daily"] = staffing

# --- productivity & labor_cost (facility x dept x month) ---
depts = ["Nursing", "Emergency", "Surgical Services", "Pharmacy", "Imaging", "Laboratory"]
# per-department vacancy & turnover (Nursing/ED run hot; Pharmacy/Lab stable)
dept_vacancy = {"Nursing": 0.13, "Emergency": 0.15, "Surgical Services": 0.09,
                "Pharmacy": 0.06, "Imaging": 0.07, "Laboratory": 0.08}
dept_turnover = {"Nursing": 0.21, "Emergency": 0.25, "Surgical Services": 0.15,
                 "Pharmacy": 0.10, "Imaging": 0.13, "Laboratory": 0.14}
prod_rows = []
cost_rows = []
for m in months:
    md = np.datetime64(m).astype("datetime64[D]").astype(object)
    mi = int(np.datetime64(m).astype(int) % 12)
    seas = seasonal_weight(np.array([mi]))[0]
    for fi in range(N_FACILITIES):
        for d in depts:
            fte = round(float(np.clip(rng.normal(120, 40) * fac_w[fi] / fac_w.mean(), 8, None)), 1)
            worked = round(fte * 173.3 * rng.uniform(0.9, 1.05), 1)
            paid = round(worked * rng.uniform(1.08, 1.18), 1)
            prod_rows.append((md, fac_id_arr[fi], fac_name_arr[fi], d, worked, paid,
                              round(worked / paid, 3),
                              round(float(np.clip(rng.normal(dept_vacancy[d], 0.015), 0.02, 0.3)), 3),
                              fte,
                              round(float(np.clip(rng.normal(dept_turnover[d], 0.02), 0.03, 0.4)), 3),
                              round(rng.uniform(0.10, 0.26), 3)))
            salary = round(worked * rng.uniform(48, 72), 2)
            ot_cost = round(salary * rng.uniform(0.04, 0.12) * seas, 2)
            agency_cost = round(salary * rng.uniform(0.05, 0.20) * seas, 2)
            benefits = round(salary * 0.28, 2)
            cost_rows.append((md, fac_id_arr[fi], fac_name_arr[fi], d, salary, ot_cost,
                              agency_cost, benefits, round(salary + ot_cost + agency_cost + benefits, 2)))
productivity = pl.DataFrame(prod_rows, schema=[
    "period_month", "facility_id", "facility_name", "department", "worked_hours", "paid_hours",
    "productive_pct", "vacancy_rate", "fte_count", "turnover_rate", "premium_pay_pct"], orient="row")
TABLES["workforce.productivity"] = productivity
labor_cost = pl.DataFrame(cost_rows, schema=[
    "period_month", "facility_id", "facility_name", "department", "salary_cost", "overtime_cost",
    "agency_cost", "benefits_cost", "total_labor_cost"], orient="row")
TABLES["workforce.labor_cost"] = labor_cost

# ============================================================================
# SUMMARY / WRITE
# ============================================================================
total = sum(len(df) for df in TABLES.values())
print(f"\nGenerated {len(TABLES)} tables, {total:,} total rows:")
for name, df in TABLES.items():
    print(f"  {name:40s} {len(df):>8,} rows  x {len(df.columns)} cols")


def write_to_uc(catalog: str):
    import datetime as _dt
    import pandas as pd
    from databricks.connect import DatabricksSession
    from comments import TABLE_COMMENTS, COLUMN_COMMENTS  # local module

    def to_spark_pandas(df):
        """Coerce types Spark's Arrow path can't infer: object dates -> datetime64,
        and unsigned ints (e.g. polars pl.len() -> uint32) -> signed int64."""
        pdf = df.to_pandas()
        for c in pdf.columns:
            if pdf[c].dtype == object:
                s = pdf[c].dropna()
                if len(s) and isinstance(s.iloc[0], (_dt.date, _dt.datetime)):
                    pdf[c] = pd.to_datetime(pdf[c])
            elif pd.api.types.is_unsigned_integer_dtype(pdf[c].dtype):
                pdf[c] = pdf[c].astype("int64")
        return pdf

    spark = DatabricksSession.builder.serverless().getOrCreate()
    # Keep naive midnight dates on their calendar day (no timezone shift), and
    # store true dates as DATE (not TIMESTAMP) for clean month-boundary queries.
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    schemas = sorted({n.split(".")[0] for n in TABLES})
    for s in schemas:
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{s}")
    for name, df in TABLES.items():
        fqn = f"{catalog}.{name}"
        print(f"Writing {fqn} ({len(df):,} rows) ...")
        date_cols = [c for c, dt in zip(df.columns, df.dtypes) if dt == pl.Date]
        sdf = spark.createDataFrame(to_spark_pandas(df))
        for c in date_cols:
            sdf = sdf.withColumn(c, sdf[c].cast("date"))
        (sdf.write.format("delta").mode("overwrite")
            .option("overwriteSchema", "true").saveAsTable(fqn))
        if name in TABLE_COMMENTS:
            spark.sql(f"COMMENT ON TABLE {fqn} IS '{TABLE_COMMENTS[name].replace(chr(39), chr(39)*2)}'")
        for col, cmt in COLUMN_COMMENTS.get(name, {}).items():
            spark.sql(f"ALTER TABLE {fqn} ALTER COLUMN {col} "
                      f"COMMENT '{cmt.replace(chr(39), chr(39)*2)}'")
    print("\nDone. All tables + comments written.")
    spark.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=None, help="UC catalog to write to (omit for dry run)")
    args = ap.parse_args()
    if args.catalog:
        import sys, os
        # Make the sibling `comments` module importable. `__file__` is undefined
        # when a spark_python_task exec()s this file on serverless, so fall back
        # to argv[0]'s dir, then cwd.
        try:
            _here = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            _here = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else os.getcwd()
        sys.path.insert(0, _here)
        write_to_uc(args.catalog)
    else:
        print("\nDry run (no --catalog). Sample of operations.encounters:")
        print(TABLES["operations.encounters"].head(8))
