export interface WorklistPatient {
  patient_id: string;
  name: string;
  age: number | null;
  sex: string;
  risk_tier: string;
  predicted_admit_prob: number | null;
  open_gaps: number;
  transportation_barrier: boolean;
  food_insecurity: boolean;
  facility: string;
  conditions: string[];
  last_contact_days: number | null;
  days_since_visit: number | null;
  priority: number;
  care_priority_score: number;
}

export interface CareGap {
  gap_id: string;
  measure: string;
  gap_status: string;
  days_open: number | null;
  due_date: string | null;
}

export interface Sdoh {
  transportation_barrier?: boolean;
  food_insecurity?: boolean;
  housing_instability?: boolean;
  preferred_language?: string;
  interpreter_needed?: boolean;
  svi_score?: number | null;
}

export interface PatientDetail {
  patient_id: string;
  name: string;
  phone: string;
  age: number | null;
  sex: string;
  risk_tier: string;
  predicted_admit_prob: number | null;
  care_priority_score: number;
  predicted_annual_cost: number | null;
  payer_type: string;
  pcp_id: string;
  pcp_name: string | null;
  facility: string;
  last_visit_date: string | null;
  days_since_visit: number | null;
  conditions: string[];
  sdoh: Sdoh;
  open_gaps: CareGap[];
  last_contact_days: number | null;
}

export interface Brief {
  summary: string;
  next_best_action: string;
  generated_at?: string;
}

export interface ActivityItem {
  patient_id: string;
  patient_name: string | null;
  risk_tier: string | null;
  action: string;
  addressed_gap_measures: string[];
  note: string | null;
  follow_up: string | null;
  at: string;
}

export interface Encounter {
  encounter_type: string;
  service_line: string;
  primary_diagnosis: string;
  admit_date: string;
  los_days: number | null;
}

export interface PatientHistory {
  encounters: Encounter[];
  utilization_90d: { ed_visits: number; admissions: number };
}

export interface PatientMessage {
  message: string;
  language: string;
  generated_at?: string;
}

export interface ClinicalNote {
  note_type: string;
  note_date: string | null;
  specialty: string | null;
  note_text: string;
  ai_summary: string | null;
}

export interface NotesSummary {
  summary: string;
  generated_at?: string;
  error?: string;
}

export interface AskTurn {
  role: "user" | "assistant";
  content: string;
}

export interface AskResponse {
  answer: string;
  generated_at?: string;
  error?: string;
}

export interface ParsedOutreach {
  action: string;
  addressed_gap_ids: string[];
  follow_up: string | null;
  note: string;
  generated_at?: string;
  error?: string;
}

export interface Panel {
  panel_size: number;
  high: number;
  rising: number;
  open_gaps: number;
  outreach_logged: number;
  patients_touched: number;
  gaps_closed: number;
  closure_rate: number;
  program_high_risk: number;
  n_caseloads: number;
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export const api = {
  worklist: () => fetch("/api/worklist").then((r) => j<{ patients: WorklistPatient[] }>(r)),
  patient: (id: string) => fetch(`/api/patients/${id}`).then((r) => j<PatientDetail>(r)),
  brief: (id: string) => fetch(`/api/patients/${id}/brief`).then((r) => j<Brief>(r)),
  logOutreach: (
    id: string,
    body: {
      action: string;
      addressed_gap_ids: string[];
      note?: string;
      follow_up?: string;
      patient_name?: string;
      risk_tier?: string;
      addressed_gap_measures?: string[];
    }
  ) =>
    fetch(`/api/patients/${id}/outreach`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => j<{ ok: boolean; message: string }>(r)),
  activity: () => fetch("/api/activity").then((r) => j<{ items: ActivityItem[] }>(r)),
  clearActivity: () =>
    fetch("/api/activity", { method: "DELETE" }).then((r) => j<{ ok: boolean; deleted: number }>(r)),
  deletePatientActivity: (id: string) =>
    fetch(`/api/patients/${id}/outreach`, { method: "DELETE" }).then((r) =>
      j<{ ok: boolean; deleted: number }>(r)
    ),
  history: (id: string) => fetch(`/api/patients/${id}/history`).then((r) => j<PatientHistory>(r)),
  notes: (id: string) => fetch(`/api/patients/${id}/notes`).then((r) => j<{ notes: ClinicalNote[] }>(r)),
  notesSummary: (id: string) =>
    fetch(`/api/patients/${id}/notes/summary`).then((r) => j<NotesSummary>(r)),
  message: (id: string, lang = "English") =>
    fetch(`/api/patients/${id}/message?lang=${encodeURIComponent(lang)}`).then((r) =>
      j<PatientMessage>(r)
    ),
  ask: (id: string, question: string, history: AskTurn[]) =>
    fetch(`/api/patients/${id}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history }),
    }).then((r) => j<AskResponse>(r)),
  panel: () => fetch("/api/panel").then((r) => j<Panel>(r)),
  parseOutreach: (id: string, text: string) =>
    fetch(`/api/patients/${id}/parse-outreach`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }).then((r) => j<ParsedOutreach>(r)),
};
