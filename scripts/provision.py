"""Phase 1 of install: ensure the Lakebase instance and logical database exist.

Idempotent — safe to re-run. Must run BEFORE `databricks bundle deploy`, because
the app's `database` resource binding fails if the instance/DB don't exist yet.

    DATABRICKS_PROFILE=<profile> LAKEBASE_INSTANCE=<name> PGDATABASE=<db> \
        uv run python scripts/provision.py
"""
import os
import sys
import time

import psycopg
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import database as db

# Make the sibling `_lakebase` module importable when exec()'d as a job task.
try:
    _d = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _d = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else os.getcwd()
if _d not in sys.path:
    sys.path.insert(0, _d)

import _lakebase

INSTANCE = _lakebase.INSTANCE
PGDATABASE = _lakebase.PGDATABASE
CAPACITY = os.environ.get("LAKEBASE_CAPACITY", "CU_1")


def ensure_instance(w: WorkspaceClient) -> None:
    """Create the Lakebase instance if absent, then wait until AVAILABLE."""
    try:
        inst = w.database.get_database_instance(name=INSTANCE)
        print(f"Instance {INSTANCE} exists (state={inst.state})", flush=True)
    except Exception:
        print(f"Creating Lakebase instance {INSTANCE} ({CAPACITY}) ...", flush=True)
        w.database.create_database_instance(
            database_instance=db.DatabaseInstance(name=INSTANCE, capacity=CAPACITY)
        )
    # Poll to AVAILABLE regardless of who created it (create returns a Wait, but
    # a pre-existing instance may still be starting).
    for _ in range(60):
        inst = w.database.get_database_instance(name=INSTANCE)
        state = str(inst.state)
        if "AVAILABLE" in state:
            print(f"Instance {INSTANCE} AVAILABLE", flush=True)
            return
        print(f"  waiting for instance (state={state}) ...", flush=True)
        time.sleep(10)
    raise RuntimeError(f"Instance {INSTANCE} did not become AVAILABLE in time")


def ensure_database(w: WorkspaceClient) -> None:
    """Create the logical database if absent (a fresh instance only ships with
    `databricks_postgres`). Idempotent."""
    with _lakebase.connect(w, dbname="databricks_postgres", autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (PGDATABASE,))
        if cur.fetchone() is None:
            # Identifier can't be parameterized; PGDATABASE is our own constant.
            cur.execute(f'CREATE DATABASE "{PGDATABASE}"')
            print(f"Created database {PGDATABASE}", flush=True)
        else:
            print(f"Database {PGDATABASE} already exists", flush=True)


def main() -> None:
    w = _lakebase.workspace_client()
    ensure_instance(w)
    ensure_database(w)
    print("Provision complete.", flush=True)


if __name__ == "__main__":
    # Not sys.exit(main()): main() returns None -> SystemExit(None), which a
    # spark_python_task's notebook runner treats as a failure even on success.
    main()
