from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, List, Optional, Sequence

from insider_platform.schema import get_schema_sql
from insider_platform.util.time import utcnow_iso


def _debug(msg: str) -> None:
    print(f"[db] {msg}")


def _qmark_to_pct(sql: str) -> str:
    """Convert qmark placeholders (?) to psycopg2 placeholders (%s).

    We avoid replacing '?' inside single/double-quoted string literals.
    This is not a full SQL parser, but it is sufficient for this codebase.
    """
    out: List[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(sql):
        ch = sql[i]

        if ch == "'" and not in_double:
            out.append(ch)
            if in_single:
                # Escaped single quote: ''
                if i + 1 < len(sql) and sql[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                in_single = False
            else:
                in_single = True
            i += 1
            continue

        if ch == '"' and not in_single:
            out.append(ch)
            if in_double:
                # Escaped double quote: ""
                if i + 1 < len(sql) and sql[i + 1] == '"':
                    out.append('"')
                    i += 2
                    continue
                in_double = False
            else:
                in_double = True
            i += 1
            continue

        if ch == "?" and not in_single and not in_double:
            out.append("%s")
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


class PGCursor:
    def __init__(self, cur: Any):
        self._cur = cur

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> "PGCursor":
        self._cur.execute(_qmark_to_pct(sql), tuple(params or ()))
        return self

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> "PGCursor":
        self._cur.executemany(_qmark_to_pct(sql), [tuple(x) for x in seq_of_params])
        return self

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchall(self) -> Any:
        return self._cur.fetchall()

    @property
    def rowcount(self) -> int:
        try:
            return int(self._cur.rowcount or 0)
        except Exception:
            return 0

    def close(self) -> None:
        try:
            self._cur.close()
        except Exception:
            pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cur, name)


class PGConnection:
    """A tiny adapter that exposes a minimal DB-API-like API on top of psycopg2."""

    dialect = "postgres"

    def __init__(self, conn: Any):
        self._conn = conn

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> PGCursor:
        cur = self._conn.cursor()
        wrapper = PGCursor(cur)
        wrapper.execute(sql, params)
        return wrapper

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> PGCursor:
        cur = self._conn.cursor()
        wrapper = PGCursor(cur)
        wrapper.executemany(sql, seq_of_params)
        return wrapper

    def cursor(self) -> PGCursor:
        return PGCursor(self._conn.cursor())

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


@contextmanager
def connect(db_dsn: str) -> Iterator[PGConnection]:
    """Connect to PostgreSQL and yield a connection wrapper."""
    dsn = (db_dsn or "").strip()
    if not dsn:
        raise RuntimeError("DB_DSN is empty; set INSIDER_DATABASE_URL (or DATABASE_URL)")

    try:
        import psycopg2
        import psycopg2.extras
    except Exception as e:
        raise RuntimeError(
            "psycopg2 is required for PostgreSQL support. Install psycopg2-binary and try again."
        ) from e

    raw = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
    conn = PGConnection(raw)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_dsn: str) -> None:
    """Create all tables and run lightweight migrations."""
    _debug(f"Initializing DB (postgres) at {db_dsn}")
    with connect(db_dsn) as conn:
        # Ensure only one process runs schema DDL at a time (session-level lock).
        conn.execute("SELECT pg_advisory_lock(2147483647);")
        try:
            _exec_schema(conn, get_schema_sql())
            _migrate(conn)
        except Exception:
            # If a DDL statement fails, PostgreSQL marks the current transaction as aborted.
            # Roll back so we can safely release the advisory lock and re-raise.
            conn.rollback()
            raise
        finally:
            try:
                conn.execute("SELECT pg_advisory_unlock(2147483647);")
            except Exception:
                # If unlock fails for any reason, we don't want to hide the real error.
                pass


def _exec_schema(conn: Any, ddl: str) -> None:
    # Execute multi-statement DDL (naive split is OK for our schema)
    statements = [s.strip() for s in (ddl or "").split(";") if s.strip()]
    for stmt in statements:
        conn.execute(stmt)


def _table_exists(conn: Any, table: str) -> bool:
    r = conn.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema='public' AND table_name=?
        LIMIT 1
        """,
        (table,),
    ).fetchone()
    return r is not None


def _has_column(conn: Any, table: str, col: str) -> bool:
    r = conn.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema='public'
          AND table_name=?
          AND column_name=?
        LIMIT 1
        """,
        (table, col),
    ).fetchone()
    return r is not None


def _table_columns(conn: Any, table: str) -> List[str]:
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=?
        ORDER BY ordinal_position
        """,
        (table,),
    ).fetchall()
    return [str(r["column_name"]) for r in rows]


def _ensure_users_role_constraint(conn: Any) -> None:
    """Allow the showcase role on existing databases."""

    if not _table_exists(conn, "users"):
        return

    rows = conn.execute(
        """
        SELECT con.conname AS name, pg_get_constraintdef(con.oid, true) AS definition
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        WHERE nsp.nspname = 'public'
          AND rel.relname = ?
          AND con.contype = 'c'
        """,
        ("users",),
    ).fetchall()

    role_constraints = []
    showcase_allowed = False
    for row in rows:
        definition = str(row.get("definition") or "").lower()
        if "role" not in definition:
            continue
        role_constraints.append(str(row.get("name") or ""))
        if "showcase" in definition:
            showcase_allowed = True

    if showcase_allowed:
        return

    for name in role_constraints:
        safe_name = name.replace('"', '""')
        conn.execute(f'ALTER TABLE users DROP CONSTRAINT IF EXISTS "{safe_name}"')

    conn.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('admin','showcase','user'))"
    )


def _migrate(conn: Any) -> None:
    """Lightweight forward-only migrations for existing DBs."""

    # --- AI outputs: ensure input_json exists (older DBs) ---
    if _table_exists(conn, "ai_outputs") and not _has_column(conn, "ai_outputs", "input_json"):
        conn.execute("ALTER TABLE ai_outputs ADD COLUMN input_json TEXT NOT NULL DEFAULT ''")

    # --- Fundamentals cache: sector + beta ---
    if _table_exists(conn, "issuer_fundamentals_cache"):
        if not _has_column(conn, "issuer_fundamentals_cache", "sector"):
            conn.execute("ALTER TABLE issuer_fundamentals_cache ADD COLUMN sector TEXT")
        if not _has_column(conn, "issuer_fundamentals_cache", "beta"):
            conn.execute("ALTER TABLE issuer_fundamentals_cache ADD COLUMN beta DOUBLE PRECISION")
        # Helpful for sorting/grouping by sector
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fundamentals_sector ON issuer_fundamentals_cache (sector)")

    # --- event_outcomes: benchmark + excess return columns (outcomes_v2) ---
    if _table_exists(conn, "event_outcomes") and _has_column(conn, "event_outcomes", "issuer_cik"):
        cols_to_add = [
            ("bench_symbol", "TEXT"),
            ("bench_return_60d", "DOUBLE PRECISION"),
            ("bench_missing_reason_60d", "TEXT"),
            ("excess_return_60d", "DOUBLE PRECISION"),
            ("bench_return_180d", "DOUBLE PRECISION"),
            ("bench_missing_reason_180d", "TEXT"),
            ("excess_return_180d", "DOUBLE PRECISION"),
        ]
        for col, ctype in cols_to_add:
            if not _has_column(conn, "event_outcomes", col):
                conn.execute(f"ALTER TABLE event_outcomes ADD COLUMN {col} {ctype}")

    # --- ticker validation cache ---
    if not _table_exists(conn, "issuer_ticker_validation"):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS issuer_ticker_validation (
                issuer_cik TEXT NOT NULL,
                ticker TEXT NOT NULL,
                eodhd_symbol TEXT,
                status TEXT NOT NULL CHECK (status IN ('valid','invalid','unknown')),
                issuer_name TEXT,
                provider_name TEXT,
                provider_code TEXT,
                provider_exchange TEXT,
                match_score DOUBLE PRECISION,
                reason TEXT,
                checked_at TEXT NOT NULL,
                PRIMARY KEY (issuer_cik, ticker)
            )
            """
        )
    if _table_exists(conn, "issuer_ticker_validation"):
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ticker_validation_status ON issuer_ticker_validation (status, checked_at)")

    # --- users: billing / subscription columns (Stripe) ---
    if _table_exists(conn, "users") and _has_column(conn, "users", "user_id"):
        user_cols_to_add = [
            ("stripe_customer_id", "TEXT"),
            ("stripe_subscription_id", "TEXT"),
            ("stripe_price_id", "TEXT"),
            ("subscription_status", "TEXT"),
            ("current_period_end", "TEXT"),
            ("cancel_at_period_end", "INTEGER"),
            ("subscription_updated_at", "TEXT"),
        ]
        for col, ctype in user_cols_to_add:
            if not _has_column(conn, "users", col):
                # Keep defaults lightweight; the application treats missing/NULL as "no subscription".
                if col == "cancel_at_period_end":
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ctype} NOT NULL DEFAULT 0")
                else:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ctype}")

    # --- users: allow showcase role on existing DBs ---
    _ensure_users_role_constraint(conn)


def upsert_app_config(conn: Any, key: str, value: str) -> None:
    """Upsert a simple key/value config entry.

    Older DBs may have an extra NOT NULL `updated_at` column. We support both schemas.
    """
    cols = _table_columns(conn, "app_config")
    now = utcnow_iso()

    if "updated_at" in cols:
        conn.execute(
            """
            INSERT INTO app_config (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, now),
        )
        return

    conn.execute(
        """
        INSERT INTO app_config (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )


def get_app_config(conn: Any, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM app_config WHERE key=?", (key,)).fetchone()
    if row is None:
        return None
    return str(row["value"])
