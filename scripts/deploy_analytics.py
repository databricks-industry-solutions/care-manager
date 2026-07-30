"""Deploy the Population Health Genie space + AI/BI dashboard over the seeded
Unity Catalog data. Idempotent (skips creation if an asset with the same
name/title already exists).

Both payloads are authored against the `hls_provider` catalog; this script
rewrites that to the target CATALOG and injects the target warehouse before
creating:
  - Genie space   via POST /api/2.0/genie/spaces
  - AI/BI dashboard via POST /api/2.0/lakeview/dashboards

    DATABRICKS_PROFILE=<p> CATALOG=<cat> WAREHOUSE_ID=<id> \
        uv run python scripts/deploy_analytics.py
"""
import argparse
import json
import os
import sys

# Reuse the shared workspace-client/auth helper (also fixes sys.path in-job).
try:
    _d = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _d = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else os.getcwd()
if _d not in sys.path:
    sys.path.insert(0, _d)

import _lakebase

# Payloads live alongside the repo root's analytics/ dir.
_REPO = os.path.dirname(_d)
ANALYTICS_DIR = os.path.join(_REPO, "analytics")
SOURCE_CATALOG = "hls_provider"  # the catalog the payloads were authored against


def _api(w, method: str, path: str, body: dict):
    return w.api_client.do(method, path, body=body)


def _rewrite_catalog(obj, target_catalog: str):
    """Recursively replace the source catalog with the target in every string."""
    if isinstance(obj, str):
        return obj.replace(SOURCE_CATALOG, target_catalog)
    if isinstance(obj, list):
        return [_rewrite_catalog(x, target_catalog) for x in obj]
    if isinstance(obj, dict):
        return {k: _rewrite_catalog(v, target_catalog) for k, v in obj.items()}
    return obj


def deploy_genie(w, catalog: str, warehouse_id: str) -> None:
    with open(os.path.join(ANALYTICS_DIR, "genie_population_health.json")) as f:
        payload = json.load(f)
    title = payload["title"]

    # serialized_space is a JSON string authored against hls_provider.
    space = json.loads(payload["serialized_space"])
    space = _rewrite_catalog(space, catalog)

    existing = _api(w, "GET", "/api/2.0/genie/spaces", {}) or {}
    for s in existing.get("spaces", []):
        if s.get("title") == title:
            print(f"Genie space '{title}' already exists ({s.get('space_id')}); skipping.", flush=True)
            return

    # Create under the installing user's home, resolved at runtime (the payload
    # ships no workspace-specific path).
    me = w.current_user.me().user_name
    body = {
        "title": title,
        "description": payload.get("description", ""),
        "parent_path": f"/Users/{me}",
        "warehouse_id": warehouse_id,
        "serialized_space": json.dumps(space),
    }
    resp = _api(w, "POST", "/api/2.0/genie/spaces", body) or {}
    print(f"Created Genie space '{title}' -> {resp.get('space_id', '?')}", flush=True)


def deploy_dashboard(w, catalog: str, warehouse_id: str) -> None:
    with open(os.path.join(ANALYTICS_DIR, "dashboard_population_health.json")) as f:
        payload = json.load(f)
    name = payload["display_name"]

    serialized = _rewrite_catalog(payload["serialized"], catalog)

    existing = _api(w, "GET", "/api/2.0/lakeview/dashboards", {}) or {}
    for d in existing.get("dashboards", []):
        if d.get("display_name") == name and d.get("lifecycle_state") == "ACTIVE":
            print(f"Dashboard '{name}' already exists ({d.get('dashboard_id')}); skipping.", flush=True)
            return

    body = {
        "display_name": name,
        "warehouse_id": warehouse_id,
        "serialized_dashboard": json.dumps(serialized),
    }
    resp = _api(w, "POST", "/api/2.0/lakeview/dashboards", body) or {}
    print(f"Created dashboard '{name}' -> {resp.get('dashboard_id', '?')}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Deploy the Genie space + AI/BI dashboard.")
    ap.add_argument("--catalog")
    ap.add_argument("--warehouse_id", "--warehouse", dest="warehouse_id")
    args = ap.parse_args()
    catalog = args.catalog or os.environ.get("CATALOG", "hls_provider")
    warehouse_id = args.warehouse_id or os.environ.get("WAREHOUSE_ID")
    if not warehouse_id:
        print("ERROR: warehouse id required (--warehouse or WAREHOUSE_ID)", file=sys.stderr)
        sys.exit(2)

    w = _lakebase.workspace_client()
    print(f"Deploying analytics over catalog '{catalog}' (warehouse {warehouse_id}) ...", flush=True)
    deploy_genie(w, catalog, warehouse_id)
    deploy_dashboard(w, catalog, warehouse_id)
    print("Analytics deploy complete.", flush=True)


if __name__ == "__main__":
    # Not sys.exit(main()): keep parity with the other scripts (spark_python_task
    # notebook runner treats SystemExit(None) as failure).
    main()
