#!/usr/bin/env bash
# One-command, idempotent install of Care Manager into a Databricks workspace.
#
# Sequences the inherent two-phase dependency:
#   1. provision  — Lakebase instance + logical DB must exist BEFORE the app's
#                   `database` resource can bind.
#   2. bundle deploy — create the app (+ seed job) resources.
#   3. seed        — generate the synthetic dataset and load Lakebase.
#   4. grant       — the app SP (minted in step 2) gets DB privileges.
#   5. run app     — (re)deploy so the app connects with its grants.
#
# Safe to re-run: every step is idempotent.
#
# Usage:
#   ./install.sh -p <profile> --catalog <cat> --warehouse <id> [--endpoint <ep>] [--target dev|prod]
set -euo pipefail

PROFILE=""; CATALOG="hls_provider"; WAREHOUSE_ID=""; ENDPOINT="databricks-claude-sonnet-4-6"
TARGET="dev"; INSTANCE="care-manager-db"; PGDATABASE="caremanager"; APP_NAME="care-manager"
SEED="local"  # local | job — where to run data generation + load

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--profile) PROFILE="$2"; shift 2 ;;
    --catalog) CATALOG="$2"; shift 2 ;;
    --warehouse) WAREHOUSE_ID="$2"; shift 2 ;;
    --endpoint) ENDPOINT="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    --instance) INSTANCE="$2"; shift 2 ;;
    --database) PGDATABASE="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[[ -z "$PROFILE" ]] && { echo "ERROR: --profile is required" >&2; exit 2; }
[[ -z "$WAREHOUSE_ID" ]] && { echo "ERROR: --warehouse is required" >&2; exit 2; }

cd "$(dirname "$0")"
# DATABRICKS_PROFILE is read by our SDK helpers; DATABRICKS_CONFIG_PROFILE is the
# standard var Databricks Connect (DatabricksSession.serverless) resolves auth
# from. Export both so every step authenticates the same way.
export DATABRICKS_PROFILE="$PROFILE"
export DATABRICKS_CONFIG_PROFILE="$PROFILE"
export LAKEBASE_INSTANCE="$INSTANCE" PGDATABASE="$PGDATABASE"
export CATALOG WAREHOUSE_ID APP_NAME
PY=(uv run --python 3.12 --with "psycopg[binary]" --with databricks-sdk)

echo "== [1/6] Provision Lakebase instance + database =="
"${PY[@]}" python scripts/provision.py

echo "== [2/6] Deploy bundle (app + seed job) =="
databricks bundle deploy -t "$TARGET" -p "$PROFILE" \
  --var "catalog=$CATALOG" --var "warehouse_id=$WAREHOUSE_ID" \
  --var "serving_endpoint=$ENDPOINT" --var "lakebase_instance=$INSTANCE" \
  --var "pg_database=$PGDATABASE"

# Portable timeout (macOS has no coreutils `timeout`): run "$@" but kill it after
# $1 seconds. Returns the child's status, or 124 on timeout.
run_with_timeout() {
  local secs="$1"; shift
  ( "$@" ) & local pid=$!
  ( sleep "$secs"; kill "$pid" 2>/dev/null ) & local watcher=$!
  wait "$pid" 2>/dev/null; local rc=$?
  kill "$watcher" 2>/dev/null; wait "$watcher" 2>/dev/null || true
  return $rc
}
NOTES_TIMEOUT="${NOTES_TIMEOUT:-480}"  # optional clinical-notes step; don't let it stall the install

echo "== [3/6] Seed dataset + load Lakebase ($SEED) =="
if [[ "$SEED" == "job" ]]; then
  databricks bundle run seed -t "$TARGET" -p "$PROFILE"
else
  "${PY[@]}" --with polars --with numpy --with mimesis --with pandas --with pyarrow \
    --with "databricks-connect>=16.4,<17.0" python scripts/generate_hls_provider.py --catalog "$CATALOG"
  # Optional & time-bounded: the app only needs some notes to demo, and this
  # serverless step can be slow to warm up. If it times out or fails, the loader
  # just creates an empty clinical_notes table.
  run_with_timeout "$NOTES_TIMEOUT" "${PY[@]}" --with "databricks-connect>=16.4,<17.0" \
    python scripts/generate_clinical_notes.py --catalog "$CATALOG" --limit 60 || \
    echo "WARN: clinical notes generation skipped (timeout/failure); continuing"
  "${PY[@]}" python scripts/load_lakebase.py \
    --catalog "$CATALOG" --warehouse "$WAREHOUSE_ID" --instance "$INSTANCE" --database "$PGDATABASE"
fi

echo "== [4/6] Grant app service principal on the database =="
"${PY[@]}" python scripts/grant_app_sp.py --app "$APP_NAME" --database "$PGDATABASE" \
  --instance "$INSTANCE"

echo "== [5/6] Deploy Genie space + AI/BI dashboard over the catalog =="
# Optional analytics layer (pairs the app with a Population Health Genie space
# and Lakeview dashboard over the same data). Non-fatal if it fails.
"${PY[@]}" python scripts/deploy_analytics.py --catalog "$CATALOG" --warehouse "$WAREHOUSE_ID" || \
  echo "WARN: analytics (Genie/dashboard) deploy skipped; app is unaffected"

echo "== [6/6] (Re)deploy app so it connects with grants =="
databricks bundle run care_manager -t "$TARGET" -p "$PROFILE"

echo "== Done. App URL: =="
databricks apps get "$APP_NAME" -p "$PROFILE" -o json | \
  python3 -c "import json,sys;print(json.load(sys.stdin).get('url',''))"
