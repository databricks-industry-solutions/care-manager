"""Shared Lakebase helpers used by the install scripts (provision / load / grant).

SDK-based (no CLI subprocess), so the same code runs locally (via a
DATABRICKS_PROFILE) and inside a Databricks job (auto-auth, no profile). All
target names are env-overridable so the bundle can point them at any workspace.
"""
import os
from typing import Optional

import psycopg
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound

INSTANCE = os.environ.get("LAKEBASE_INSTANCE", "care-manager-db")
PGDATABASE = os.environ.get("PGDATABASE", "caremanager")
PGPORT = os.environ.get("PGPORT", "5432")


def workspace_client() -> WorkspaceClient:
    """Auth both ways: a CLI profile locally, or the ambient job/app identity."""
    profile = os.environ.get("DATABRICKS_PROFILE")
    return WorkspaceClient(profile=profile) if profile else WorkspaceClient()


def instance_host(w: WorkspaceClient, instance: Optional[str] = None) -> str:
    name = instance or INSTANCE
    try:
        return w.database.get_database_instance(name=name).read_write_dns
    except NotFound:
        # A bare "Resource not found" here is very hard to act on, so name what
        # was looked for and what the workspace actually has.
        try:
            available = [i.name for i in w.database.list_database_instances()]
        except Exception:  # listing is best-effort; never mask the original error
            available = []
        listing = ", ".join(available) if available else "(none)"
        raise NotFound(
            f"Lakebase instance '{name}' not found in this workspace. "
            f"Available: {listing}. "
            f"Pass --instance <name>, or let install.sh create the default."
        ) from None


def db_credential(w: WorkspaceClient, instance: Optional[str] = None) -> str:
    cred = w.database.generate_database_credential(
        request_id=os.urandom(8).hex(), instance_names=[instance or INSTANCE]
    )
    return cred.token


def current_identity(w: WorkspaceClient) -> str:
    """The Postgres role for the connecting identity: a user's email locally,
    or the service principal's application id when running as an SP (job/app)."""
    me = w.current_user.me()
    return me.user_name


def connect(
    w: WorkspaceClient,
    dbname: Optional[str] = None,
    autocommit: bool = False,
    user: Optional[str] = None,
    instance: Optional[str] = None,
) -> psycopg.Connection:
    """Open a psycopg connection to the instance using a freshly minted OAuth
    database credential as the password.

    `instance` must be threaded through by callers that resolve it from CLI args:
    job tasks forward no env vars, so the module-level INSTANCE default is only
    correct when the caller is using the default name.
    """
    return psycopg.connect(
        host=instance_host(w, instance),
        port=PGPORT,
        dbname=dbname or PGDATABASE,
        user=user or current_identity(w),
        password=db_credential(w, instance),
        sslmode="require",
        autocommit=autocommit,
    )
