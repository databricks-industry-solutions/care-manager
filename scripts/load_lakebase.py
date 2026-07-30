"""One-time, idempotent bulk load of the care-manager READ tables from the
`hls_provider` gold catalog (read via the SQL warehouse) into the Lakebase
Postgres database `caremanager`.

Idempotent: each table is DROP + CREATE + COPY-loaded, so re-running fully
refreshes. Uses psycopg COPY for speed. Types are preserved (ints, doubles,
booleans, dates) so the app's numeric/boolean/date logic keeps working.

Runs both locally (via DATABRICKS_PROFILE) and inside a Databricks job (ambient
auth). All targets are env-overridable so the install bundle can point them at
any workspace.

Run locally:
    DATABRICKS_PROFILE=<profile> CATALOG=<catalog> WAREHOUSE_ID=<id> \
        uv run python scripts/load_lakebase.py
"""
import argparse
import json
import os
import sys
from typing import Any

import psycopg
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import Disposition, Format, StatementState

# Ensure the sibling `_lakebase` module is importable when this file is exec()'d
# as a spark_python_task (the script dir isn't on sys.path, and __file__ may be
# undefined). Falls back to argv[0]'s dir, then cwd.
try:
    _d = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _d = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else os.getcwd()
if _d not in sys.path:
    sys.path.insert(0, _d)

import _lakebase

# All connection/target settings are env-overridable (local runs) or passable as
# CLI args (Databricks job tasks, which don't forward arbitrary env). CLI args
# win over env, which wins over the defaults.
_args = None


def _cfg(name: str, default: str) -> str:
    if _args is not None:
        v = getattr(_args, name.lower(), None)
        if v:
            return v
    return os.environ.get(name, default)


# Resolved at import from env/defaults; main() re-resolves after parsing CLI args.
INSTANCE = _cfg("LAKEBASE_INSTANCE", _lakebase.INSTANCE)
PGDATABASE = _cfg("PGDATABASE", _lakebase.PGDATABASE)
WAREHOUSE_ID = _cfg("WAREHOUSE_ID", "")
CATALOG = _cfg("CATALOG", "hls_provider")

# (source_table, target_table, [(col, source_type, pg_type)])
# pg_type drives the CREATE TABLE DDL. Order matches the SELECT we issue.
TABLES: list[tuple[str, str, list[tuple[str, str]]]] = [
    (
        "reference.patients",
        "patients",
        [
            ("patient_id", "text"), ("first_name", "text"), ("last_name", "text"),
            ("age", "integer"), ("sex", "text"), ("race", "text"),
            ("city", "text"), ("state", "text"), ("zip_code", "text"),
            ("primary_facility_id", "text"), ("primary_facility_name", "text"),
            ("pcp_provider_id", "text"), ("payer_id", "text"),
            ("payer_name", "text"), ("payer_type", "text"),
            ("chronic_conditions", "integer"), ("registration_date", "date"),
            ("is_active", "boolean"),
        ],
    ),
    (
        "reference.providers",
        "providers",
        [
            ("provider_id", "text"), ("provider_name", "text"),
            ("provider_type", "text"), ("specialty", "text"),
            ("service_line", "text"), ("facility_id", "text"),
            ("facility_name", "text"), ("npi", "text"), ("is_active", "boolean"),
        ],
    ),
    (
        "population_health.patient_registry",
        "patient_registry",
        [
            ("patient_id", "text"), ("patient_age", "integer"),
            ("patient_sex", "text"), ("attributed_pcp_id", "text"),
            ("primary_facility_name", "text"), ("payer_type", "text"),
            ("risk_tier", "text"), ("chronic_conditions", "integer"),
            ("has_diabetes", "boolean"), ("has_chf", "boolean"),
            ("has_copd", "boolean"), ("has_ckd", "boolean"),
            ("has_hypertension", "boolean"), ("is_aco_attributed", "boolean"),
            ("last_visit_date", "date"),
        ],
    ),
    (
        "population_health.risk_scores",
        "risk_scores",
        [
            ("patient_id", "text"), ("score_date", "date"),
            ("risk_model", "text"), ("risk_score", "double precision"),
            ("risk_tier", "text"), ("hcc_count", "integer"),
            ("predicted_admit_prob", "double precision"),
            ("predicted_annual_cost", "double precision"),
        ],
    ),
    (
        "population_health.care_gaps",
        "care_gaps",
        [
            ("gap_id", "text"), ("patient_id", "text"), ("patient_age", "integer"),
            ("patient_sex", "text"), ("risk_tier", "text"),
            ("primary_facility_name", "text"), ("measure", "text"),
            ("gap_status", "text"), ("due_date", "date"), ("days_open", "integer"),
        ],
    ),
    (
        "population_health.sdoh",
        "sdoh",
        [
            ("patient_id", "text"), ("zip_code", "text"),
            ("svi_score", "double precision"), ("food_insecurity", "boolean"),
            ("transportation_barrier", "boolean"), ("housing_instability", "boolean"),
            ("preferred_language", "text"), ("interpreter_needed", "boolean"),
        ],
    ),
    (
        "operations.encounters",
        "encounters",
        [
            ("encounter_id", "text"), ("patient_id", "text"), ("patient_age", "integer"),
            ("patient_sex", "text"), ("facility_id", "text"), ("facility_name", "text"),
            ("attending_provider_id", "text"), ("service_line", "text"),
            ("encounter_type", "text"), ("admit_date", "date"),
            ("discharge_date", "date"), ("los_days", "integer"),
            ("severity_level", "integer"), ("is_icu", "boolean"),
            ("is_sepsis", "boolean"), ("primary_diagnosis", "text"),
            ("discharge_disposition", "text"), ("expired_flag", "boolean"),
            ("payer_id", "text"), ("payer_name", "text"), ("payer_type", "text"),
        ],
    ),
    (
        "population_health.clinical_notes",
        "clinical_notes",
        [
            ("note_id", "text"), ("patient_id", "text"), ("encounter_id", "text"),
            ("note_date", "date"), ("note_type", "text"), ("specialty", "text"),
            ("note_text", "text"), ("ai_summary", "text"),
            ("key_barriers", "text"), ("adherence_signal", "text"),
        ],
    ),
]

# Indexes for the app's access paths.
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_patients_pid ON patients (patient_id)",
    "CREATE INDEX IF NOT EXISTS idx_registry_pid ON patient_registry (patient_id)",
    "CREATE INDEX IF NOT EXISTS idx_registry_tier ON patient_registry (risk_tier)",
    "CREATE INDEX IF NOT EXISTS idx_risk_pid ON risk_scores (patient_id)",
    "CREATE INDEX IF NOT EXISTS idx_sdoh_pid ON sdoh (patient_id)",
    "CREATE INDEX IF NOT EXISTS idx_gaps_pid ON care_gaps (patient_id)",
    "CREATE INDEX IF NOT EXISTS idx_gaps_pid_status ON care_gaps (patient_id, gap_status)",
    "CREATE INDEX IF NOT EXISTS idx_enc_pid ON encounters (patient_id)",
    "CREATE INDEX IF NOT EXISTS idx_providers_pid ON providers (provider_id)",
    "CREATE INDEX IF NOT EXISTS idx_notes_pid ON clinical_notes (patient_id)",
]


def pg_connect(w: WorkspaceClient) -> psycopg.Connection:
    return _lakebase.connect(w, dbname=PGDATABASE, autocommit=False)


def fetch_rows(w: WorkspaceClient, source: str, cols: list[tuple[str, str]]) -> list[list[Any]]:
    """Fetch the given columns from a gold table (errors surface as RuntimeError)."""
    select = ", ".join(c[0] for c in cols)
    return fetch_rows_raw(w, f"SELECT {select} FROM {source}", label=source)


def fetch_rows_raw(w: WorkspaceClient, statement: str, label: str = "query") -> list[list[Any]]:
    """Run a SQL statement via StatementExecution, paginating through result
    chunks (data_array is capped per chunk)."""
    stmt = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, catalog=CATALOG,
        statement=statement,
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
        wait_timeout="50s",
    )
    state = stmt.status.state if stmt.status else None
    sid = stmt.statement_id
    while state in (StatementState.PENDING, StatementState.RUNNING):
        stmt = w.statement_execution.get_statement(sid)
        state = stmt.status.state
    if state != StatementState.SUCCEEDED:
        msg = stmt.status.error.message if stmt.status and stmt.status.error else "unknown"
        raise RuntimeError(f"{label} failed: {msg}")

    rows: list[list[Any]] = []
    result = stmt.result
    if result and result.data_array:
        rows.extend(result.data_array)
    # Follow chunk links if the result is split.
    next_chunk = result.next_chunk_index if result else None
    while next_chunk is not None:
        chunk = w.statement_execution.get_statement_result_chunk_n(sid, next_chunk)
        if chunk.data_array:
            rows.extend(chunk.data_array)
        next_chunk = chunk.next_chunk_index
    return rows


def to_copy_value(raw: Any, pg_type: str) -> str:
    r"""Convert a StatementExecution string cell to a COPY text-format token.
    \N denotes NULL. Booleans arrive as 'true'/'false' strings."""
    if raw is None:
        return r"\N"
    s = str(raw)
    if pg_type == "boolean":
        return "t" if s.lower() == "true" else "f"
    if pg_type in ("integer", "double precision", "date"):
        if s == "":
            return r"\N"
        return s
    # text: escape backslash, tab, newline, carriage return for COPY text format
    s = s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
    return s


def source_columns(w: WorkspaceClient, source: str) -> set[str]:
    """Actual column names present in the source UC table (lowercased)."""
    schema, table = source.split(".", 1)
    try:
        rows = fetch_rows_raw(
            w,
            f"SELECT column_name FROM {CATALOG}.information_schema.columns "
            f"WHERE table_schema='{schema}' AND table_name='{table}'",
        )
        return {r[0].lower() for r in rows if r and r[0]}
    except RuntimeError:
        return set()


def load_table(conn: psycopg.Connection, w: WorkspaceClient,
               source: str, target: str, cols: list[tuple[str, str]]) -> int:
    # Only fetch columns the source actually has; any declared column that's
    # missing upstream (e.g. ai_summary, produced by a later enrichment step) is
    # still created in Postgres but left NULL — the app tolerates NULLs and this
    # keeps the loader resilient to source-schema drift.
    present = source_columns(w, source)
    fetch_cols = [c for c in cols if not present or c[0].lower() in present]
    missing = [c[0] for c in cols if present and c[0].lower() not in present]
    if missing:
        print(f"  note: {source} missing {missing}; loading them as NULL", flush=True)
    try:
        rows = fetch_rows(w, source, fetch_cols) if fetch_cols else []
    except RuntimeError as e:
        # Source table absent (e.g. optional clinical_notes not generated yet):
        # still create the empty target so the app's queries don't hit a missing
        # relation. Re-run the loader after backfilling the source.
        print(f"  WARN {source} unavailable ({e}); creating empty {target}", flush=True)
        rows = []
        fetch_cols = []
    # Reindex fetched rows back into the full declared column order, NULL-filling
    # any columns we didn't fetch.
    if fetch_cols != cols:
        fetch_names = [c[0] for c in fetch_cols]
        idx = {name: i for i, name in enumerate(fetch_names)}
        rows = [
            [row[idx[c[0]]] if c[0] in idx else None for c in cols]
            for row in rows
        ]
    ddl_cols = ", ".join(f'"{c}" {t}' for c, t in cols)
    with conn.cursor() as cur:
        cur.execute(f'DROP TABLE IF EXISTS "{target}" CASCADE')
        cur.execute(f'CREATE TABLE "{target}" ({ddl_cols})')
        col_list = ", ".join(f'"{c}"' for c, _ in cols)
        copy_sql = f'COPY "{target}" ({col_list}) FROM STDIN'
        with cur.copy(copy_sql) as cp:
            for row in rows:
                line = "\t".join(to_copy_value(row[i], cols[i][1]) for i in range(len(cols)))
                cp.write(line + "\n")
    conn.commit()
    return len(rows)


def main() -> None:
    global _args, INSTANCE, PGDATABASE, WAREHOUSE_ID, CATALOG
    ap = argparse.ArgumentParser(description="Load Lakebase from the UC gold catalog.")
    ap.add_argument("--catalog")
    ap.add_argument("--warehouse_id", "--warehouse", dest="warehouse_id")
    ap.add_argument("--lakebase_instance", "--instance", dest="lakebase_instance")
    ap.add_argument("--pgdatabase", "--database", dest="pgdatabase")
    _args = ap.parse_args()
    INSTANCE = _cfg("LAKEBASE_INSTANCE", _lakebase.INSTANCE)
    PGDATABASE = _cfg("PGDATABASE", _lakebase.PGDATABASE)
    WAREHOUSE_ID = _cfg("WAREHOUSE_ID", WAREHOUSE_ID)
    CATALOG = _cfg("CATALOG", CATALOG)

    w = _lakebase.workspace_client()
    conn = pg_connect(w)
    print(f"Connected to Lakebase {INSTANCE}/{PGDATABASE}", flush=True)
    counts = {}
    try:
        for source, target, cols in TABLES:
            n = load_table(conn, w, source, target, cols)
            counts[target] = n
            print(f"  loaded {target:18s} {n:>7,} rows", flush=True)
        with conn.cursor() as cur:
            for ix in INDEXES:
                cur.execute(ix)
            cur.execute("ANALYZE")
        conn.commit()
        print("Indexes created + ANALYZE done", flush=True)
    finally:
        conn.close()
    print("ROW COUNTS:", json.dumps(counts))


if __name__ == "__main__":
    # Call directly (not sys.exit(main())): main() returns None, and
    # sys.exit(None) raises SystemExit, which a Databricks spark_python_task's
    # notebook runner reports as a task failure even on success.
    main()
