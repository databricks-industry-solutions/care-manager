import type { WorklistPatient } from "./api";

// Shared worklist filter/sort logic. Lives in one place so the Worklist screen
// and the patient detail's prev/next stepping compute the exact same ordered
// list from the same URL-driven filter state.

export type Sort = "priority" | "overdue" | "name";
const SORTS: Sort[] = ["priority", "overdue", "name"];

export interface WorklistFilters {
  risk: string; // "All" | "High" | "Rising"
  cond: string; // "All" | condition
  facility: string; // "All" | facility
  due: boolean;
  sort: Sort;
  q: string; // free-text name search
}

export const DEFAULT_FILTERS: WorklistFilters = {
  risk: "All",
  cond: "All",
  facility: "All",
  due: false,
  sort: "priority",
  q: "",
};

export function parseFilters(sp: URLSearchParams): WorklistFilters {
  const sort = sp.get("sort");
  return {
    risk: sp.get("risk") || "All",
    cond: sp.get("cond") || "All",
    facility: sp.get("facility") || "All",
    due: sp.get("due") === "1",
    sort: sort && SORTS.includes(sort as Sort) ? (sort as Sort) : "priority",
    q: sp.get("q") || "",
  };
}

// Only non-default values become query params, so a pristine worklist stays a
// clean "/" URL.
export function filtersToParams(f: WorklistFilters): Record<string, string> {
  const p: Record<string, string> = {};
  if (f.risk !== "All") p.risk = f.risk;
  if (f.cond !== "All") p.cond = f.cond;
  if (f.facility !== "All") p.facility = f.facility;
  if (f.due) p.due = "1";
  if (f.sort !== "priority") p.sort = f.sort;
  if (f.q.trim()) p.q = f.q.trim();
  return p;
}

export function isDirty(f: WorklistFilters): boolean {
  return (
    f.risk !== "All" ||
    f.cond !== "All" ||
    f.facility !== "All" ||
    f.due ||
    f.sort !== "priority" ||
    !!f.q.trim()
  );
}

export function applyFilters(patients: WorklistPatient[], f: WorklistFilters): WorklistPatient[] {
  const q = f.q.trim().toLowerCase();
  const rows = patients.filter((p) => {
    if (f.risk !== "All" && p.risk_tier !== f.risk) return false;
    if (f.cond !== "All" && !p.conditions.includes(f.cond)) return false;
    if (f.facility !== "All" && p.facility !== f.facility) return false;
    if (f.due && (p.days_since_visit ?? 0) < 90) return false;
    if (q && !p.name.toLowerCase().includes(q)) return false;
    return true;
  });
  const sorted = [...rows];
  if (f.sort === "overdue") {
    sorted.sort((a, b) => (b.days_since_visit ?? -1) - (a.days_since_visit ?? -1));
  } else if (f.sort === "name") {
    sorted.sort((a, b) => a.name.localeCompare(b.name));
  } else {
    sorted.sort((a, b) => b.care_priority_score - a.care_priority_score);
  }
  return sorted;
}
