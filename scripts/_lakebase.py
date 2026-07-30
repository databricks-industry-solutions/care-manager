"""Shared Lakebase helpers used by the install scripts (provision / load / grant).

SDK-based (no CLI subprocess), so the same code runs locally (via a
DATABRICKS_PROFILE) and inside a Databricks job (auto-auth, no profile). All
target names are env-overridable so the bundle can point them at any workspace.
"""
import os
from typing import Optional

import psycopg
from databricks.sdk import WorkspaceClient

INSTANCE = os.environ.get("LAKEBASE_INSTANCE", "care-manager-db")
PGDATABASE = os.environ.get("PGDATABASE", "caremanager")
PGPORT = os.environ.get("PGPORT", "5432")


def workspace_client() -> WorkspaceClient:
    """Auth both ways: a CLI profile locally, or the ambient job/app identity."""
    profile = os.environ.get("DATABRICKS_PROFILE")
    return WorkspaceClient(profile=profile) if profile else WorkspaceClient()


def instance_host(w: WorkspaceClient, instance: str = INSTANCE) -> str:
    return w.database.get_database_instance(name=instance).read_write_dns


def db_credential(w: WorkspaceClient, instance: str = INSTANCE) -> str:
    cred = w.database.generate_database_credential(
        request_id=os.urandom(8).hex(), instance_names=[instance]
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
) -> psycopg.Connection:
    """Open a psycopg connection to the instance using a freshly minted OAuth
    database credential as the password."""
    return psycopg.connect(
        host=instance_host(w),
        port=PGPORT,
        dbname=dbname or PGDATABASE,
        user=user or current_identity(w),
        password=db_credential(w),
        sslmode="require",
        autocommit=autocommit,
    )
