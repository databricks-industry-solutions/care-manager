"""Phase 3 of install: grant the app's service principal access to the seeded
Lakebase database.

The Databricks App connects to Lakebase as its own service principal (the
`database` app resource auto-registers it as a Postgres role). The seed loader
runs as the deployer, so the app SP has no privileges until we grant them here.

Discovers the app SP client id dynamically (no hardcoded ids) and grants
read/write on the target database's `public` schema. Idempotent.

    DATABRICKS_PROFILE=<profile> APP_NAME=care-manager \
    LAKEBASE_INSTANCE=<name> PGDATABASE=<db> \
        uv run python scripts/grant_app_sp.py
"""
import argparse
import os
import sys

from databricks.sdk import WorkspaceClient

# Make the sibling `_lakebase` module importable when exec()'d as a job task.
try:
    _d = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _d = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else os.getcwd()
if _d not in sys.path:
    sys.path.insert(0, _d)

import _lakebase


def app_sp_client_id(w: WorkspaceClient, app_name: str) -> str:
    """The app's service principal *application id* == its Lakebase Postgres
    role name (auto-registered by the database app resource)."""
    app = w.apps.get(name=app_name)
    cid = app.service_principal_client_id
    if not cid:
        raise RuntimeError(f"App {app_name} has no service_principal_client_id yet")
    return cid


def grant(w: WorkspaceClient, sp: str, pgdatabase: str) -> None:
    stmts = [
        f'GRANT CONNECT ON DATABASE "{pgdatabase}" TO "{sp}"',
        f'GRANT USAGE, CREATE ON SCHEMA public TO "{sp}"',
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{sp}"',
        f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{sp}"',
        # Cover tables/sequences created later (e.g. the app's own write-back store).
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{sp}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "{sp}"',
    ]
    with _lakebase.connect(w, dbname=pgdatabase, autocommit=True) as conn, conn.cursor() as cur:
        for s in stmts:
            cur.execute(s)
            print(f"OK: {s[:70]}", flush=True)
        cur.execute("SELECT has_table_privilege(%s, 'patients', 'SELECT')", (sp,))
        print(f"verify: SP can SELECT patients = {cur.fetchone()[0]}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Grant the app SP on the Lakebase DB.")
    ap.add_argument("--app_name", "--app", dest="app_name")
    ap.add_argument("--pgdatabase", "--database", dest="pgdatabase")
    args = ap.parse_args()
    app_name = args.app_name or os.environ.get("APP_NAME", "care-manager")
    pgdatabase = args.pgdatabase or _lakebase.PGDATABASE

    w = _lakebase.workspace_client()
    sp = app_sp_client_id(w, app_name)
    print(f"Granting app SP {sp} on {pgdatabase} ...", flush=True)
    grant(w, sp, pgdatabase)
    print("Grant complete.", flush=True)


if __name__ == "__main__":
    # Not sys.exit(main()): main() returns None -> SystemExit(None), which a
    # spark_python_task's notebook runner treats as a failure even on success.
    main()
