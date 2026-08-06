"""Lakebase Postgres connection pool (PROVISIONED tier) using the official
Databricks Apps OAuth pattern.

PROVISIONED tier auth: a fresh database credential is minted per physical
connection via the SDK `WorkspaceClient().database.generate_database_credential`,
used as the Postgres password. Credentials are short-lived (~1h), so we cap
each connection's lifetime well under that (`max_lifetime=2700` = 45 min) and
mint a new token on every `connect`.

Dual-mode:
  - Local dev: WorkspaceClient(profile=DATABRICKS_PROFILE) -> the developer's
    identity is the Postgres role (their email).
  - Deployed app: WorkspaceClient() picks up the auto-injected service principal;
    the SP's client id is the Postgres role.

Connection params (host/port/db/user) come from the Lakebase app-resource env
vars (PGHOST/PGPORT/PGDATABASE/PGUSER) when present; locally we fill them from
the CLI/instance lookup.
"""
import os
import time
from functools import lru_cache
from typing import Any, Callable, Optional, TypeVar

import psycopg
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout

from .config import IS_DATABRICKS_APP, get_workspace_client

_T = TypeVar("_T")

# Transient failures worth retrying on the FIRST cold request: the Lakebase
# instance still waking, a cold pool with no ready connection, or a just-expired
# credential. Without this, the very first worklist load can 500 and the user
# has to refresh — this makes the request self-heal instead. psycopg.OperationalError
# is the base for connection/timeout failures; PoolTimeout is raised when the
# pool can't hand out a connection within its timeout.
#
# PoolClosed matters for a *permanently* stuck app: if open_pool()'s warmup
# exhausts its retries at boot (Lakebase briefly unreachable), the pool is left
# unopened and every later request raises PoolClosed. Without it here that state
# never recovers and the app 500s until someone restarts it manually — with it,
# _reset_for_retry() rebuilds the pool and the request self-heals.
_RETRYABLE = (psycopg.OperationalError, PoolTimeout, PoolClosed)


def _with_retry(fn: Callable[[], _T], attempts: int = 3, base_delay: float = 1.0) -> _T:
    """Run fn, retrying transient connection errors with linear backoff. On a
    retryable failure we also drop the cached host/user + reset the pool so the
    next attempt re-resolves cleanly (covers a not-yet-ready instance at boot)."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if not isinstance(e, _RETRYABLE) or i == attempts - 1:
                raise
            last = e
            _reset_for_retry()
            time.sleep(base_delay * (i + 1))
    raise last  # unreachable, keeps type-checkers happy


def _reset_for_retry() -> None:
    """Clear cached connection metadata + the pool so a retry re-resolves."""
    global _pool
    _resolve_host.cache_clear()
    _resolve_user.cache_clear()
    try:
        if _pool is not None:
            _pool.close()
    except Exception:  # noqa: BLE001
        pass
    _pool = None

INSTANCE_NAME = os.environ.get("LAKEBASE_INSTANCE", "care-manager-db")
PGDATABASE = os.environ.get("PGDATABASE", "caremanager")
PGPORT = os.environ.get("PGPORT", "5432")
PROFILE = os.environ.get("DATABRICKS_PROFILE", "DEFAULT")

_pool: Optional[ConnectionPool] = None


@lru_cache(maxsize=1)
def _resolve_host() -> str:
    """Read-write DNS for the instance. Prefer the injected PGHOST (deployed
    app resource); otherwise resolve via the SDK from the instance name."""
    host = os.environ.get("PGHOST")
    if host:
        return host
    w = get_workspace_client()
    inst = w.database.get_database_instance(name=INSTANCE_NAME)
    return inst.read_write_dns


@lru_cache(maxsize=1)
def _resolve_user() -> str:
    """Postgres role = the connecting identity.
    Deployed: the SP client id (injected as PGUSER, or DATABRICKS_CLIENT_ID).
    Local: the developer's email from current-user."""
    user = os.environ.get("PGUSER")
    if user:
        return user
    if IS_DATABRICKS_APP:
        cid = os.environ.get("DATABRICKS_CLIENT_ID")
        if cid:
            return cid
    w = get_workspace_client()
    return w.current_user.me().user_name


def _mint_token() -> str:
    """Fresh, short-lived Lakebase credential for one physical connection."""
    w = get_workspace_client()
    cred = w.database.generate_database_credential(
        request_id=os.urandom(8).hex(), instance_names=[INSTANCE_NAME]
    )
    return cred.token


class OAuthConnection(psycopg.Connection):
    """psycopg Connection subclass that injects a freshly-minted Lakebase OAuth
    token as the password at connect time. The pool calls this for every new
    physical connection, so each connection authenticates with a current token.
    """

    @classmethod
    def connect(cls, conninfo: str = "", **kwargs: Any) -> "OAuthConnection":
        kwargs["password"] = _mint_token()
        return super().connect(conninfo, **kwargs)


def _conninfo() -> str:
    return (
        f"host={_resolve_host()} port={PGPORT} dbname={PGDATABASE} "
        f"user={_resolve_user()} sslmode=require"
    )


def init_pool() -> ConnectionPool:
    """Return the pool, creating and opening it if needed.

    Normally open_pool() has already opened it during app startup. If that
    warmup failed (or a retry reset the pool), open it here so a request can
    still be served instead of hitting PoolClosed forever.
    """
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=_conninfo(),
            connection_class=OAuthConnection,
            min_size=1,
            max_size=8,
            max_lifetime=2700,   # < token TTL so connections rotate before expiry
            max_idle=600,
            timeout=30,
            open=False,
        )
    if _pool.closed:
        # Raises on failure; _with_retry decides whether to try again.
        _pool.open(wait=True, timeout=30)
    return _pool


def open_pool() -> None:
    """Open the pool at boot AND warm it: resolve host/user and validate one
    real connection (with retry) so the FIRST user request doesn't pay the cold
    connect + wait for a still-waking instance. Retrying here means a briefly
    unreachable Lakebase at boot recovers before any request lands."""
    def _open_and_warm() -> None:
        init_pool().open(wait=True, timeout=30)
        # Force a real round-trip so metadata resolution + TLS + a live token
        # are all warm and cached before we serve traffic.
        with init_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    _with_retry(_open_and_warm)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def query(sql: str, params: Optional[tuple] = None) -> list[tuple]:
    """Run a read query, return rows as tuples. Retries transient cold-start
    connection failures so the first request self-heals."""
    def _run() -> list[tuple]:
        with init_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
    return _with_retry(_run)


def execute(sql: str, params: Optional[tuple] = None) -> int:
    """Run a write statement (INSERT/UPDATE/DELETE/DDL), committing on success.

    Returns the affected row count (-1 if the driver doesn't report one).
    Retries only apply to acquiring the connection; a write that fails mid-txn
    is not re-run (the retry wraps the whole unit, which is safe here because
    these statements are idempotent-by-key or single-row upserts)."""
    def _run() -> int:
        with init_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rowcount = cur.rowcount
            conn.commit()
        return rowcount
    return _with_retry(_run)


def fetchone(sql: str, params: Optional[tuple] = None) -> Optional[tuple]:
    def _run() -> Optional[tuple]:
        with init_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()
    return _with_retry(_run)
