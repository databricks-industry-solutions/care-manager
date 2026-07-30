"""Table and column comments for the HLS Provider demo catalog.

Genie and Unified Chat lean heavily on these comments for query accuracy,
so every table has a description and the demo-relevant columns are documented.
"""

TABLE_COMMENTS = {
    # reference
    "reference.patients": "Master patient index for Unity Health. One row per patient with demographics, primary care provider, insurance/payer, and chronic condition burden. Join key: patient_id.",
    "reference.providers": "Provider (physician / NP / PA) directory. One row per provider with specialty, service line, and home facility. Join key: provider_id.",
    "reference.facilities": "The 5 hospitals in the Unity Health system, with type (Academic / Community / Critical Access / Specialty), staffed bed count, and region. Join key: facility_id.",
    "reference.units": "Nursing / care units within each facility (ICU, Med/Surg, ED, OR, etc.) with licensed bed counts. Join keys: unit_id, facility_id.",
    "reference.payers": "Insurance payers and payer types (Medicare, Medicaid, Commercial, Self-Pay). Join key: payer_id.",
    # operations
    "operations.encounters": "Central fact table: one row per patient encounter (Inpatient, Outpatient, Emergency, Observation) across all facilities. Includes length of stay, acuity/severity, sepsis and ICU flags, mortality, diagnosis, and payer. Links patients, providers, facilities, and payers. This is the primary table for volume, LOS, acuity, and mortality questions.",
    "operations.patient_census": "Daily midnight census by nursing unit: occupancy, admissions, and discharges. One row per unit per day. Use for bed occupancy, capacity, and census trend questions.",
    "operations.ed_visits": "Emergency Department visits with arrival time, ESI acuity, throughput metrics (door-to-provider, ED length of stay, boarding minutes), and disposition. One row per ED visit; links to encounters. Use for ED throughput and wait-time questions.",
    "operations.or_cases": "Operating room surgical cases with scheduled vs actual minutes, turnover time, on-time starts, and cancellations. Use for OR utilization and surgical efficiency questions.",
    "operations.appointments": "Ambulatory / outpatient clinic appointments with appointment type, telehealth flag, scheduled lead time (booking to visit, an access proxy), status (Completed / No-Show / Cancelled / Rescheduled), arrival, and wait time. No-show rates are higher for Medicaid/Self-Pay, younger patients, and behavioral health. Use for access, no-show, and clinic utilization questions.",
    # quality
    "quality.readmissions": "One row per inpatient discharge (patients discharged alive), flagging whether the patient was readmitted within 30 days. Use for 30-day readmission rate by facility, service line, or risk tier.",
    "quality.quality_measures": "Monthly quality and safety measure results by facility (readmission rate, mortality, sepsis bundle compliance, CLABSI/CAUTI, hand hygiene, falls, CMS Star Rating, HCAHPS top-box). Includes the benchmark and performance vs benchmark. Use for quality scorecard and benchmark questions.",
    "quality.safety_events": "Patient safety events (falls, medication errors, pressure injuries, CLABSI, CAUTI) with harm level and reporting unit. Use for safety event volume and harm-level questions.",
    "quality.hcahps_surveys": "HCAHPS patient experience survey responses for inpatient discharges, with overall rating, would-recommend, and domain scores (nurse/doctor communication, responsiveness, cleanliness, quietness). Use for patient experience questions.",
    # revenue cycle
    "revenue_cycle.claims": "One row per claim (one per encounter) with billed, allowed, paid, and patient-responsibility amounts, payer, service line, and claim status (Paid / Denied / Partially Paid / Pending). The primary table for revenue, reimbursement, and denial-rate questions.",
    "revenue_cycle.denials": "Denied or partially-paid claims with denial category (Prior Authorization, Eligibility, Coding, Medical Necessity, etc.), denied amount, appeal status, recovered amount, and a preventable flag. Use for denial management questions.",
    "revenue_cycle.ar_aging": "Accounts receivable aging snapshots by month, facility, payer, and aging bucket (0-30, 31-60, 61-90, 91-120, 120+ days). Use for AR and cash questions.",
    "revenue_cycle.payer_performance": "Monthly payer performance by facility: total billed, total paid, denial rate, average days to pay, and net collection rate. Use for payer scorecard questions.",
    "revenue_cycle.service_line_pnl": "Monthly service-line profit & loss by facility, derived from claims: encounter volume, gross charges, net revenue, direct cost, contribution margin, and margin percent. Margins vary by service line (e.g. Orthopedics/Cardiology high; Behavioral Health/Emergency Medicine low). Use for service-line profitability and contribution-margin questions.",
    # population health
    "population_health.patient_registry": "Population health registry: one row per patient with risk tier (Low / Rising / High), chronic condition flags (diabetes, CHF, COPD, CKD, hypertension), ACO attribution, and last visit date. Use for panel, risk stratification, and chronic disease questions.",
    "population_health.care_gaps": "Open and closed care gaps per patient (A1c testing, BP control, cancer screenings, diabetic eye exam, medication adherence, wellness visits, statin therapy) with due date and days open. Use for care gap closure questions.",
    "population_health.risk_scores": "Per-patient predictive risk scores (HCC + LACE composite) with predicted admission probability and predicted annual cost. Use for risk score and predicted-cost questions.",
    "population_health.sdoh": "Social determinants of health per patient: social vulnerability index, food insecurity, transportation barriers, housing instability, preferred language, and interpreter need. Use for SDOH and health equity questions.",
    # workforce
    "workforce.staffing_daily": "Daily nurse staffing by unit: census, scheduled vs actual nurses, agency nurses, nurse-to-patient ratio, overtime hours, sick calls, and open shifts. Agency use and overtime rise during winter census surges. Use for staffing and labor-coverage questions.",
    "workforce.productivity": "Monthly labor productivity by facility and department: worked vs paid hours, productive percentage, FTE count, vacancy rate, and turnover rate. Use for workforce productivity questions.",
    "workforce.labor_cost": "Monthly labor cost by facility and department: salary, overtime, agency, and benefits cost, plus total labor cost. Use for labor spend questions.",
}

COLUMN_COMMENTS = {
    "reference.patients": {
        "patient_id": "Unique patient identifier (join key across all domains).",
        "age": "Patient age in years.",
        "chronic_conditions": "Count of active chronic conditions; drives risk tier and utilization.",
        "payer_type": "Insurance category: Medicare, Medicaid, Commercial, Medicare Advantage, Self-Pay, Other.",
    },
    "operations.encounters": {
        "encounter_id": "Unique encounter identifier (join key to claims, ed_visits, or_cases, readmissions).",
        "encounter_type": "Inpatient, Outpatient, Emergency, or Observation.",
        "los_days": "Length of stay in days (0 for ED/outpatient).",
        "severity_level": "Acuity/severity 1 (low) to 4 (high).",
        "is_sepsis": "True if the encounter involved sepsis.",
        "is_icu": "True if the patient spent time in the ICU.",
        "expired_flag": "True if the patient died during the encounter (in-hospital mortality).",
        "discharge_disposition": "Where the patient went after discharge (Home, Home Health, SNF, Rehab, Expired, etc.).",
    },
    "operations.patient_census": {
        "midnight_census": "Number of patients in the unit at midnight.",
        "occupancy_rate": "midnight_census divided by licensed_beds.",
    },
    "operations.ed_visits": {
        "esi_acuity": "Emergency Severity Index 1 (most acute) to 5 (least acute).",
        "door_to_provider_min": "Minutes from arrival to first provider contact.",
        "ed_los_minutes": "Total ED length of stay in minutes.",
        "boarding_minutes": "Minutes a admitted patient waited in the ED for an inpatient bed.",
        "left_without_being_seen": "True if the patient left before being seen (LWBS).",
    },
    "operations.or_cases": {
        "scheduled_minutes": "Scheduled case duration in minutes.",
        "actual_minutes": "Actual case duration in minutes.",
        "first_case_on_time": "True if the first case of the day started on time.",
    },
    "operations.appointments": {
        "appointment_type": "Follow-up, New Patient, Annual Wellness, Procedure, or Telehealth.",
        "scheduled_lead_days": "Days from booking to the appointment (proxy for access / third-next-available).",
        "status": "Completed, No-Show, Cancelled, or Rescheduled.",
        "no_show_flag": "True if the patient did not show for the appointment.",
        "wait_time_minutes": "Minutes the patient waited at the clinic (0 if not arrived).",
    },
    "quality.readmissions": {
        "readmitted_30d": "True if the patient was readmitted within 30 days of discharge.",
        "days_to_readmission": "Days from discharge to readmission (0 if not readmitted).",
    },
    "quality.quality_measures": {
        "rate": "Measured value for the period.",
        "benchmark": "Target / benchmark value for the measure.",
        "better_direction": "'higher' or 'lower' — which direction is better for this measure.",
        "vs_benchmark": "Performance versus benchmark (positive = better than benchmark).",
    },
    "revenue_cycle.claims": {
        "billed_amount": "Gross charges billed.",
        "allowed_amount": "Contractually allowed amount.",
        "paid_amount": "Amount actually paid by the payer.",
        "claim_status": "Paid, Denied, Partially Paid, or Pending.",
    },
    "revenue_cycle.denials": {
        "denial_category": "Reason for denial (Prior Authorization, Eligibility, Coding, Medical Necessity, Timely Filing, Duplicate, Bundling).",
        "is_preventable": "True if the denial was potentially preventable.",
        "appeal_status": "Not Appealed, Pending, Won, or Lost.",
    },
    "revenue_cycle.ar_aging": {
        "ar_bucket": "Aging bucket in days: 0-30, 31-60, 61-90, 91-120, 120+.",
        "ar_amount": "Outstanding accounts receivable dollars in the bucket.",
    },
    "revenue_cycle.payer_performance": {
        "denial_rate": "Share of billed claims denied for this payer/facility/month.",
        "avg_days_to_pay": "Average days from claim submission to payment.",
        "net_collection_rate": "Net collection rate (paid / allowed).",
    },
    "revenue_cycle.service_line_pnl": {
        "net_revenue": "Net revenue recognized (paid + patient responsibility).",
        "direct_cost": "Estimated direct cost of delivering care for the service line.",
        "contribution_margin": "net_revenue minus direct_cost.",
        "margin_pct": "contribution_margin divided by net_revenue (negative = loss).",
    },
    "population_health.patient_registry": {
        "risk_tier": "Low, Rising, or High clinical risk.",
        "is_aco_attributed": "True if the patient is attributed to an ACO / value-based contract.",
    },
    "population_health.care_gaps": {
        "gap_status": "Open or Closed.",
        "days_open": "Days the care gap has been open.",
    },
    "population_health.risk_scores": {
        "risk_score": "Composite predictive risk score (higher = higher risk).",
        "predicted_admit_prob": "Predicted probability of admission in the next 12 months.",
        "predicted_annual_cost": "Predicted total cost of care over the next 12 months.",
    },
    "workforce.staffing_daily": {
        "nurse_to_patient_ratio": "Patients per actual nurse on the unit that day.",
        "agency_nurses": "Number of contract/agency nurses used (rises during census surges).",
        "open_shifts": "Number of unfilled nursing shifts.",
    },
    "workforce.labor_cost": {
        "agency_cost": "Contract/agency labor cost (premium labor).",
        "total_labor_cost": "Salary + overtime + agency + benefits.",
    },
}
