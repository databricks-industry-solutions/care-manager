"""Dual-mode auth + environment config.

Local: uses the Databricks CLI profile (set DATABRICKS_PROFILE=<your-cli-profile>).
Remote (Databricks App): uses the auto-injected service principal credentials.
"""
import os
from functools import lru_cache
from typing import Optional

from databricks.sdk import WorkspaceClient

IS_DATABRICKS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))

# Databricks Apps forward the signed-in end user on every request via these
# headers. We key all per-user state off the email (most stable + readable),
# falling back to preferred-username / user id, then a per-session cookie, then
# "anon" as a last resort. The cookie name we set ourselves for the fallback.
_USER_HEADERS = (
    "x-forwarded-email",
    "x-forwarded-preferred-username",
    "x-forwarded-user",
)
SESSION_COOKIE = "cm_session"


def current_user(request) -> Optional[str]:
    """Resolve the end-user key for per-user state from a FastAPI Request.

    Order: X-Forwarded-Email -> X-Forwarded-Preferred-Username ->
    X-Forwarded-User -> our own session cookie -> None (caller uses "anon").
    """
    headers = request.headers
    for h in _USER_HEADERS:
        v = headers.get(h)
        if v and v.strip():
            return v.strip().lower()
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return cookie
    return None

CATALOG = os.environ.get("CATALOG", "hls_provider")
# Legacy: the app reads from Lakebase at runtime, not a warehouse. Left
# unset by default; supplied only by the seed scripts that query the catalog.
WAREHOUSE_ID = os.environ.get("WAREHOUSE_ID", "")
SERVING_ENDPOINT = os.environ.get("SERVING_ENDPOINT", "databricks-claude-sonnet-4-6")
# Optional explicit override. When unset, the LLM client derives the OpenAI-
# compatible base URL from THIS workspace's host (see llm.py), so the app is
# portable across workspaces/clouds instead of pinned to one gateway.
AI_GATEWAY_URL = os.environ.get("AI_GATEWAY_URL")


@lru_cache(maxsize=1)
def get_workspace_client() -> WorkspaceClient:
    if IS_DATABRICKS_APP:
        return WorkspaceClient()
    profile = os.environ.get("DATABRICKS_PROFILE", "DEFAULT")
    return WorkspaceClient(profile=profile)


def get_oauth_token() -> str:
    """Get a bearer token that works for both PAT and OAuth/U2M auth."""
    w = get_workspace_client()
    if w.config.token:
        return w.config.token
    auth_headers = w.config.authenticate()
    if auth_headers and "Authorization" in auth_headers:
        return auth_headers["Authorization"].replace("Bearer ", "")
    raise RuntimeError("Could not obtain an OAuth token")


def get_workspace_host() -> str:
    if IS_DATABRICKS_APP:
        host = os.environ.get("DATABRICKS_HOST", "")
        if host and not host.startswith("http"):
            host = f"https://{host}"
        return host
    return get_workspace_client().config.host
