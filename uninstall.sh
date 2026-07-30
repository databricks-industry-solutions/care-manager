#!/usr/bin/env bash
# Tear down a Care Manager install from a Databricks workspace. Idempotent.
#
# Removes, in order:
#   1. bundle resources (the app + the seed job) via `bundle destroy`
#   2. the seeded logical database (caremanager)
#   3. (optional, with --delete-instance) the Lakebase instance itself
#
# The generated Unity Catalog data (the `--catalog` catalog) is NOT touched —
# drop it yourself if you want it gone (it may hold other assets).
#
# Usage:
#   ./uninstall.sh -p <profile> [--target dev|prod] [--delete-instance] [--yes]
set -euo pipefail

PROFILE=""; TARGET="dev"; INSTANCE="care-manager-db"; PGDATABASE="caremanager"
DELETE_INSTANCE="no"; ASSUME_YES="no"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--profile) PROFILE="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    --instance) INSTANCE="$2"; shift 2 ;;
    --database) PGDATABASE="$2"; shift 2 ;;
    --delete-instance) DELETE_INSTANCE="yes"; shift ;;
    --yes|-y) ASSUME_YES="yes"; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[[ -z "$PROFILE" ]] && { echo "ERROR: --profile is required" >&2; exit 2; }

cd "$(dirname "$0")"
export DATABRICKS_PROFILE="$PROFILE" DATABRICKS_CONFIG_PROFILE="$PROFILE"
export LAKEBASE_INSTANCE="$INSTANCE" PGDATABASE="$PGDATABASE"
PY=(uv run --python 3.12 --with "psycopg[binary]" --with databricks-sdk)

if [[ "$ASSUME_YES" != "yes" ]]; then
  echo "This will destroy the Care Manager app + seed job (target: $TARGET) and drop"
  echo "the '$PGDATABASE' database on Lakebase instance '$INSTANCE'."
  [[ "$DELETE_INSTANCE" == "yes" ]] && echo "It will ALSO delete the Lakebase instance '$INSTANCE'."
  read -r -p "Proceed? [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
fi

echo "== [1/3] Destroy bundle resources (app + seed job) =="
databricks bundle destroy -t "$TARGET" -p "$PROFILE" --auto-approve || \
  echo "WARN: bundle destroy reported an error (resources may already be gone)"

echo "== [2/3] Drop the '$PGDATABASE' database =="
"${PY[@]}" python scripts/_uninstall_db.py || \
  echo "WARN: could not drop database (instance may be gone, or DB already dropped)"

if [[ "$DELETE_INSTANCE" == "yes" ]]; then
  echo "== [3/3] Delete Lakebase instance '$INSTANCE' =="
  databricks database delete-database-instance "$INSTANCE" -p "$PROFILE" || \
    echo "WARN: could not delete instance (may already be gone)"
else
  echo "== [3/3] Keeping Lakebase instance '$INSTANCE' (pass --delete-instance to remove) =="
fi

echo "== Done. =="
