"""Drop the seeded logical database from the Lakebase instance. Idempotent.

Used by uninstall.sh. Terminates any active connections to the target database
first (the app's pool may still hold some), then DROP DATABASE IF EXISTS.
"""
import os
import sys

import psycopg

# Make the sibling `_lakebase` module importable when run from any cwd.
try:
    _d = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _d = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else os.getcwd()
if _d not in sys.path:
    sys.path.insert(0, _d)

import _lakebase

PGDATABASE = _lakebase.PGDATABASE


def main() -> None:
    w = _lakebase.workspace_client()
    # Connect to the admin DB (not the one we're dropping).
    with _lakebase.connect(w, dbname="databricks_postgres", autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (PGDATABASE,))
        if cur.fetchone() is None:
            print(f"Database {PGDATABASE} does not exist; nothing to drop.", flush=True)
            return
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (PGDATABASE,),
        )
        cur.execute(f'DROP DATABASE IF EXISTS "{PGDATABASE}"')
        print(f"Dropped database {PGDATABASE}.", flush=True)


if __name__ == "__main__":
    main()
