import sqlite3
import hashlib
import os
import sys
from datetime import datetime
from contextlib import contextmanager
from typing import Optional
from edgedash.runtime import get_runtime_value

# Key used to mark extraction_cache rows that record a failed extraction
# attempt (write-only sentinel) rather than real extracted facts.
_EXTRACTION_FAILURE_KEY = "__failed_extraction__"


def _using_postgres() -> bool:
    return bool(get_runtime_value("DATABASE_URL"))


def _backend_name() -> str:
    return "postgres" if _using_postgres() else "sqlite"


def _log_backend() -> None:
    if _using_postgres():
        print("[storage] backend: postgres")
    else:
        print("[storage] backend: sqlite (set DATABASE_URL to use Postgres)")


class _PostgresCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    @staticmethod
    def _sql(statement: str) -> str:
        return statement.replace("?", "%s")

    def execute(self, statement: str, parameters=()):
        self._cursor.execute(self._sql(statement), parameters)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        return self._wrap_row(row)

    def fetchall(self):
        return [self._wrap_row(row) for row in self._cursor.fetchall()]

    def _wrap_row(self, row):
        if row is None:
            return None
        columns = [column.name for column in self._cursor.description]
        return _PostgresRow(row, columns)

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return None


class _PostgresRow(tuple):
    """SQLite-Row-compatible tuple with optional column-name access."""

    def __new__(cls, values, columns):
        instance = super().__new__(cls, values)
        instance._columns = tuple(columns)
        return instance

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                key = self._columns.index(key)
            except ValueError as error:
                raise IndexError(key) from error
        return super().__getitem__(key)

    def keys(self):
        return self._columns

    def items(self):
        return zip(self._columns, self)


class _PostgresConnection:
    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        return _PostgresCursor(self._connection.cursor())

    def execute(self, statement: str, parameters=()):
        return _PostgresCursor(self._connection.cursor()).execute(statement, parameters)

    def commit(self):
        self._connection.commit()

    def close(self):
        self._connection.close()


@contextmanager
def get_conn(db_path: str):
    if _using_postgres():
        try:
            import psycopg
        except ImportError as error:
            raise RuntimeError(
                "DATABASE_URL is set but psycopg is not installed. "
                "Install psycopg before using hosted Postgres."
            ) from error
        conn = _PostgresConnection(
            psycopg.connect(get_runtime_value("DATABASE_URL"))
        )
    else:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    if _using_postgres():
        _init_postgres(db_path)
        return
    with get_conn(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS listings (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL,
                url TEXT NOT NULL,
                description TEXT,
                source TEXT NOT NULL,
                posted_at TEXT,
                fetched_at TEXT NOT NULL,
                fit_score INTEGER,
                fit_reason TEXT,
                seniority TEXT,
                verified_at TEXT
            )
            """
        )
        listing_columns = {
            row[1] for row in cursor.execute("PRAGMA table_info(listings)").fetchall()
        }
        if "seniority" not in listing_columns:
            cursor.execute("ALTER TABLE listings ADD COLUMN seniority TEXT")
        if "verified_at" not in listing_columns:
            cursor.execute("ALTER TABLE listings ADD COLUMN verified_at TEXT")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_gaps (
                skill TEXT PRIMARY KEY,
                frequency INTEGER NOT NULL,
                last_seen TEXT NOT NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS cycle_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                records_touched INTEGER NOT NULL,
                status TEXT NOT NULL,
                notes TEXT
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS extraction_cache (
                description_hash TEXT PRIMARY KEY,
                extracted_json TEXT NOT NULL,
                cached_at TEXT NOT NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gap_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                skill TEXT NOT NULL,
                listings_blocked INTEGER NOT NULL,
                opportunity_cost REAL NOT NULL,
                mean_score REAL NOT NULL,
                top_score INTEGER NOT NULL,
                example_ids TEXT NOT NULL,
                nice_to_have_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS query_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                tool TEXT,
                params TEXT NOT NULL,
                answerable INTEGER NOT NULL,
                duration_seconds REAL NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        query_columns = {
            row[1] for row in cursor.execute("PRAGMA table_info(query_log)").fetchall()
        }
        if "reason" not in query_columns:
            cursor.execute("ALTER TABLE query_log ADD COLUMN reason TEXT")

        conn.commit()


def _init_postgres(db_path: str) -> None:
    """Create or migrate all hosted Postgres tables idempotently."""
    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        statements = [
            """
            CREATE TABLE IF NOT EXISTS listings (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, company TEXT NOT NULL,
                location TEXT NOT NULL, url TEXT NOT NULL, description TEXT,
                source TEXT NOT NULL, posted_at TEXT, fetched_at TEXT NOT NULL,
                fit_score INTEGER, fit_reason TEXT, seniority TEXT, verified_at TEXT
            )
            """,
            """CREATE TABLE IF NOT EXISTS skill_gaps (
                skill TEXT PRIMARY KEY, frequency INTEGER NOT NULL, last_seen TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS cycle_log (
                id BIGSERIAL PRIMARY KEY, agent TEXT NOT NULL, started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL, records_touched INTEGER NOT NULL,
                status TEXT NOT NULL, notes TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS extraction_cache (
                description_hash TEXT PRIMARY KEY, extracted_json TEXT NOT NULL, cached_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS gap_snapshots (
                id BIGSERIAL PRIMARY KEY, run_id TEXT NOT NULL, computed_at TEXT NOT NULL,
                skill TEXT NOT NULL, listings_blocked INTEGER NOT NULL,
                opportunity_cost DOUBLE PRECISION NOT NULL, mean_score DOUBLE PRECISION NOT NULL,
                top_score INTEGER NOT NULL, example_ids TEXT NOT NULL,
                nice_to_have_count INTEGER NOT NULL DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS query_log (
                id BIGSERIAL PRIMARY KEY, question TEXT NOT NULL, tool TEXT,
                params TEXT NOT NULL, answerable BOOLEAN NOT NULL,
                duration_seconds DOUBLE PRECISION NOT NULL, reason TEXT, created_at TEXT NOT NULL
            )""",
        ]
        for statement in statements:
            cursor.execute(statement)
        cursor.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS seniority TEXT")
        cursor.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS verified_at TEXT")
        cursor.execute("ALTER TABLE query_log ADD COLUMN IF NOT EXISTS reason TEXT")
        conn.commit()


def _make_listing_id(source: str, url: str) -> str:
    """Generate stable hash ID from source and URL."""
    combined = f"{source}:{url}".encode()
    return hashlib.sha256(combined).hexdigest()[:16]


def upsert_listings(db_path: str, rows: list[dict]) -> int:
    """Insert listings, deduped by (source, url). Returns count of new rows."""
    if not rows:
        return 0

    new_count = 0
    with get_conn(db_path) as conn:
        cursor = conn.cursor()

        for row in rows:
            listing_id = _make_listing_id(row["source"], row["url"])
            now = datetime.utcnow().isoformat()

            values = (
                listing_id,
                row["title"],
                row["company"],
                row["location"],
                row["url"],
                row.get("description", ""),
                row["source"],
                row.get("posted_at", now),
                now,
            )
            if _using_postgres():
                cursor.execute(
                    """
                    INSERT INTO listings
                    (id, title, company, location, url, description, source, posted_at, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    values,
                )
            else:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO listings
                    (id, title, company, location, url, description, source, posted_at, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )

            if cursor.rowcount > 0:
                new_count += 1

        conn.commit()

    return new_count


def count_unscored(db_path: str) -> int:
    """Return count of listings with no fit_score yet."""
    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM listings WHERE fit_score IS NULL")
        return cursor.fetchone()["count"]


def count_unverified(db_path: str) -> int:
    """Return count of scored listings not yet part of a passing verification.

    A listing is "unverified" once it has a fit_score but no verified_at
    timestamp (its output has not yet been accepted by a passing Verifier
    run). Rule 38: only a passing verification may promote output into the
    verified pool, so fresh unverified data never displaces verified data.
    """
    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM listings "
            "WHERE fit_score IS NOT NULL AND verified_at IS NULL"
        )
        return cursor.fetchone()["count"]


def mark_verified(
    db_path: str,
    before: Optional[str] = None,
) -> int:
    """Mark produced (scored) listings as verified. Returns rows updated.

    Rule 38: the orchestrator calls this ONLY after a PASSING Verifier run.
    A failing verification never calls mark_verified, so the last known-good
    verified state is left untouched.

    Args:
        before: Optional ISO timestamp bound. When provided, only listings
            fetched at or before this time are marked, so output produced
            after the verification moment can never be promoted by it.
    """
    timestamp = datetime.utcnow().isoformat()
    parameters = [timestamp]
    query = (
        "UPDATE listings SET verified_at = ? "
        "WHERE fit_score IS NOT NULL AND verified_at IS NULL"
    )
    if before:
        query += " AND (fetched_at IS NULL OR fetched_at <= ?)"
        parameters.append(before)
    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, parameters)
        conn.commit()
        return cursor.rowcount


def last_fetch_time(db_path: str) -> Optional[str]:
    """Return ISO timestamp of most recent fetch, or None if empty."""
    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(fetched_at) as last_time FROM listings")
        result = cursor.fetchone()["last_time"]
        return result


def log_cycle(
    db_path: str,
    agent: str,
    started_at: str,
    finished_at: str,
    records_touched: int,
    status: str,
    notes: Optional[str] = None,
) -> int:
    """Log a completed agent cycle. Returns cycle_log id."""
    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO cycle_log
            (agent, started_at, finished_at, records_touched, status, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (agent, started_at, finished_at, records_touched, status, notes),
        )
        conn.commit()
        return cursor.lastrowid


def log_query(
    db_path: str,
    question: str,
    tool: Optional[str],
    params: str,
    answerable: bool,
    duration_seconds: float,
    reason: Optional[str] = None,
) -> int:
    """Write one query audit row."""
    with get_conn(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO query_log
            (question, tool, params, answerable, duration_seconds, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question,
                tool,
                params,
                answerable,
                duration_seconds,
                reason,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def count_queries_today(db_path: str) -> int:
    """Count all query attempts logged since the current UTC day began."""
    today_prefix = datetime.utcnow().date().isoformat()
    try:
        with get_conn(db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM query_log WHERE created_at LIKE ?",
                (f"{today_prefix}%",),
            ).fetchone()
            return row["count"]
    except sqlite3.OperationalError as error:
        if "no such table: query_log" in str(error):
            return 0
        raise


def get_listings(
    db_path: str,
    limit: int = 50,
    min_score: Optional[int] = None,
) -> list[dict]:
    """Fetch listings, optionally filtered by min_score. Returns dicts."""
    with get_conn(db_path) as conn:
        cursor = conn.cursor()

        if min_score is not None:
            cursor.execute(
                """
                SELECT * FROM listings
                WHERE fit_score IS NOT NULL AND fit_score >= ?
                ORDER BY fit_score DESC, fetched_at DESC
                LIMIT ?
                """,
                (min_score, limit),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM listings
                ORDER BY fetched_at DESC
                LIMIT ?
                """,
                (limit,),
            )

        return [dict(row) for row in cursor.fetchall()]


def get_extraction_cache(db_path: str, description_hash: str) -> Optional[dict]:
    """Get cached extraction by description hash. Returns dict or None.

    Failure sentinel rows (recorded failed attempts) are hidden here so that
    fact consumers (Verifier, GapAnalyzer, query tools) only ever see real
    extractions. Read those markers with get_extraction_failure() instead.
    """
    import json

    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT extracted_json FROM extraction_cache WHERE description_hash = ?",
            (description_hash,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return _load_cache_entry(row["extracted_json"])


def _load_cache_entry(extracted_json: str) -> Optional[dict]:
    """Parse a cache row, returning None for missing/failed entries."""
    import json

    try:
        data = json.loads(extracted_json)
    except (ValueError, TypeError):
        return None
    if isinstance(data, dict) and data.get(_EXTRACTION_FAILURE_KEY) is True:
        return None
    return data


def set_extraction_cache(db_path: str, description_hash: str, extracted: dict) -> None:
    """Store extraction result in cache."""
    import json

    timestamp = datetime.utcnow().isoformat()
    payload = json.dumps(extracted)
    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        if _using_postgres():
            # SQLite's "INSERT OR REPLACE" is not valid Postgres syntax; wrap
            # it in an upsert so the cache also works with hosted Postgres.
            cursor.execute(
                """
                INSERT INTO extraction_cache (description_hash, extracted_json, cached_at)
                VALUES (?, ?, ?)
                ON CONFLICT (description_hash) DO UPDATE SET
                    extracted_json = EXCLUDED.extracted_json,
                    cached_at = EXCLUDED.cached_at
                """,
                (description_hash, payload, timestamp),
            )
        else:
            cursor.execute(
                """
                INSERT OR REPLACE INTO extraction_cache
                (description_hash, extracted_json, cached_at)
                VALUES (?, ?, ?)
                """,
                (description_hash, payload, timestamp),
            )
        conn.commit()


def get_extraction_failure(db_path: str, description_hash: str) -> Optional[dict]:
    """Return the recorded extraction-failure marker for a description hash.

    Returns a dict like {"__failed_extraction__": True, "attempted_at": ...,
    "error_tail": ...} when the last attempt failed, or None when the hash is
    uncached or holds real facts.
    """
    import json

    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT extracted_json FROM extraction_cache WHERE description_hash = ?",
            (description_hash,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        try:
            data = json.loads(row["extracted_json"])
        except (ValueError, TypeError):
            return None
        if isinstance(data, dict) and data.get(_EXTRACTION_FAILURE_KEY) is True:
            return data
        return None


def mark_extraction_failed(
    db_path: str,
    description_hash: str,
    error: Optional[str] = None,
    attempted_at: Optional[str] = None,
) -> None:
    """Record a failed extraction attempt so it is not retried immediately.

    Reuses the existing extraction_cache table (no schema change) by storing a
    write-only failure sentinel under the same description_hash key. The marker
    is invisible to get_extraction_cache() so fact consumers are unaffected;
    extractors read it via get_extraction_failure() to enforce a cooldown
    window. A later successful extraction (set_extraction_cache) replaces it.
    """
    import json

    timestamp = attempted_at or datetime.utcnow().isoformat()
    payload = {
        _EXTRACTION_FAILURE_KEY: True,
        "attempted_at": timestamp,
        "error_tail": (error or "")[:500],
    }
    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        if _using_postgres():
            cursor.execute(
                """
                INSERT INTO extraction_cache (description_hash, extracted_json, cached_at)
                VALUES (?, ?, ?)
                ON CONFLICT (description_hash) DO UPDATE SET
                    extracted_json = EXCLUDED.extracted_json,
                    cached_at = EXCLUDED.cached_at
                """,
                (description_hash, json.dumps(payload), timestamp),
            )
        else:
            cursor.execute(
                """
                INSERT OR REPLACE INTO extraction_cache
                (description_hash, extracted_json, cached_at)
                VALUES (?, ?, ?)
                """,
                (description_hash, json.dumps(payload), timestamp),
            )
        conn.commit()


def get_unscored_listings(db_path: str, limit: int) -> list[dict]:
    """Fetch unscored listings. Returns list of dicts."""
    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM listings
            WHERE fit_score IS NULL
            ORDER BY fetched_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def save_score(
    db_path: str,
    listing_id: str,
    fit_score: int,
    fit_reason: str,
) -> None:
    """Update a listing with its fit score and reason.

    A re-scored listing is fresh output and therefore re-enters the
    unverified pool (rule 38) until the next passing Verifier run promotes it.
    """
    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE listings
            SET fit_score = ?, fit_reason = ?, verified_at = NULL
            WHERE id = ?
            """,
            (fit_score, fit_reason, listing_id),
        )
        conn.commit()


def save_gap_snapshot(
    db_path: str,
    run_id: str,
    skill: str,
    listings_blocked: int,
    opportunity_cost: float,
    mean_score: float,
    top_score: int,
    example_ids: list[str],
    nice_to_have_count: int = 0,
) -> None:
    """Save a gap snapshot row for audit trail per rule 25."""
    import json
    from datetime import datetime, timezone

    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO gap_snapshots
            (run_id, computed_at, skill, listings_blocked, opportunity_cost, mean_score, top_score, example_ids, nice_to_have_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                datetime.now(timezone.utc).isoformat(),
                skill,
                listings_blocked,
                opportunity_cost,
                mean_score,
                top_score,
                json.dumps(example_ids),
                nice_to_have_count,
            ),
        )
        conn.commit()


def get_latest_gap_snapshots(db_path: str) -> list[dict]:
    """Get the most recent gap snapshot run. Returns list of gap dicts."""
    import json

    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        # Get the most recent run_id
        cursor.execute("SELECT DISTINCT run_id FROM gap_snapshots ORDER BY run_id DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            return []

        latest_run_id = row["run_id"]

        # Get all gaps from that run
        cursor.execute(
            """
            SELECT * FROM gap_snapshots
            WHERE run_id = ?
            ORDER BY opportunity_cost DESC
            """,
            (latest_run_id,),
        )

        gaps = []
        for row in cursor.fetchall():
            gap = dict(row)
            gap["example_ids"] = json.loads(gap["example_ids"])
            gaps.append(gap)

        return gaps


def get_all_gap_snapshots_by_date(db_path: str) -> list[tuple]:
    """Get all gap snapshots grouped by run_id (snapshot date).
    
    Returns list of tuples: (run_id, computed_at, gaps_list)
    Ordered by computed_at DESC (most recent first).
    """
    import json

    with get_conn(db_path) as conn:
        cursor = conn.cursor()
        
        # Get distinct runs ordered by date
        cursor.execute("""
            SELECT DISTINCT run_id, MAX(computed_at) as computed_at
            FROM gap_snapshots
            GROUP BY run_id
            ORDER BY computed_at DESC
        """)
        
        runs = cursor.fetchall()
        if not runs:
            return []
        
        result = []
        for run in runs:
            run_id = run["run_id"]
            computed_at = run["computed_at"]
            
            # Get all gaps for this run
            cursor.execute("""
                SELECT * FROM gap_snapshots
                WHERE run_id = ?
                ORDER BY opportunity_cost DESC
            """, (run_id,))
            
            gaps = []
            for gap_row in cursor.fetchall():
                gap = dict(gap_row)
                gap["example_ids"] = json.loads(gap["example_ids"])
                gaps.append(gap)
            
            result.append((run_id, computed_at, gaps))
        
        return result


def get_cycle_activity(db_path: str, limit: int = 30) -> list[dict]:
    """Read recent cycle-log rows for the dashboard activity panel."""
    with get_conn(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT agent, started_at, finished_at, records_touched, status, notes
            FROM cycle_log
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_last_passing_cycle(db_path: str) -> Optional[dict]:
    """Read the latest successful cycle-log row as the verified data cutoff."""
    with get_conn(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT finished_at AS timestamp, status, notes
            FROM cycle_log
            WHERE status IN ('ok', 'passed')
            ORDER BY finished_at DESC, id DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_last_verifier_row(db_path: str) -> Optional[dict]:
    """Read the most recent Verifier cycle-log row, or None if never run.

    Used by the dashboard's "Current verdict" metric so it can fall back to
    the last real verification result when the most recent cycle did not
    actually run the Verifier (e.g. nothing new to verify).
    """
    with get_conn(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT agent, status, notes, started_at, finished_at
            FROM cycle_log
            WHERE agent = 'Verifier'
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_listings_at_cutoff(db_path: str, cutoff: Optional[str]) -> list[dict]:
    """Read scored listings available at the last passing cutoff."""
    with get_conn(db_path) as conn:
        query = """
            SELECT id, fit_score, title, company, fit_reason, fetched_at
            FROM listings
            WHERE fit_score IS NOT NULL
        """
        parameters = ()
        if cutoff:
            query += " AND fetched_at <= ?"
            parameters = (cutoff,)
        query += " ORDER BY fit_score DESC, fetched_at DESC LIMIT 10"
        cursor = conn.execute(query, parameters)
        return [dict(row) for row in cursor.fetchall()]


def get_best_matches_at_cutoff(
    db_path: str, cutoff: Optional[str], limit: int
) -> list[dict]:
    """Read the highest-scoring listings available at a verified cutoff."""
    with get_conn(db_path) as conn:
        query = """
            SELECT id, fit_score, title, company, fit_reason, fetched_at
            FROM listings
            WHERE fit_score IS NOT NULL
        """
        parameters: list[str | int] = []
        if cutoff:
            query += " AND fetched_at <= ?"
            parameters.append(cutoff)
        query += " ORDER BY fit_score DESC, fetched_at DESC LIMIT ?"
        parameters.append(limit)
        return [dict(row) for row in conn.execute(query, parameters).fetchall()]


def get_listing_counts_at_cutoff(db_path: str, cutoff: Optional[str]) -> dict:
    """Read listing totals available at the last passing cutoff."""
    with get_conn(db_path) as conn:
        query = """
            SELECT COUNT(*) AS total_listings,
                   SUM(CASE WHEN fit_score IS NOT NULL THEN 1 ELSE 0 END) AS total_scored
            FROM listings
        """
        parameters = ()
        if cutoff:
            query += " WHERE fetched_at <= ?"
            parameters = (cutoff,)
        row = conn.execute(query, parameters).fetchone()
        return {
            "total_listings": row["total_listings"] or 0,
            "total_scored": row["total_scored"] or 0,
        }


def get_listing_count_details(db_path: str, cutoff: Optional[str]) -> dict:
    """Read listing totals and newest listing date at a verified cutoff."""
    with get_conn(db_path) as conn:
        query = """
            SELECT COUNT(*) AS listings,
                   SUM(CASE WHEN fit_score IS NOT NULL THEN 1 ELSE 0 END) AS scored,
                   SUM(CASE WHEN fit_score IS NULL THEN 1 ELSE 0 END) AS unscored,
                   MAX(COALESCE(posted_at, fetched_at)) AS newest_listing_date
            FROM listings
        """
        parameters = ()
        if cutoff:
            query += " WHERE fetched_at <= ?"
            parameters = (cutoff,)
        row = conn.execute(query, parameters).fetchone()
        return {key: row[key] or 0 for key in row.keys()}


def get_gap_detail_at_cutoff(
    db_path: str, skill: str, cutoff: Optional[str]
) -> list[dict]:
    """Read listings represented by a gap snapshot skill."""
    import json

    with get_conn(db_path) as conn:
        query = """
            SELECT example_ids FROM gap_snapshots
            WHERE lower(skill) = lower(?)
        """
        parameters: list[str] = [skill]
        if cutoff:
            query += " AND computed_at <= ?"
            parameters.append(cutoff)
        query += " ORDER BY computed_at DESC LIMIT 1"
        row = conn.execute(query, parameters).fetchone()
        if not row:
            return []
        ids = json.loads(row["example_ids"])
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        listing_query = f"""
            SELECT id, title, company, fit_score, fit_reason
            FROM listings WHERE id IN ({placeholders})
            ORDER BY fit_score DESC
        """
        return [dict(item) for item in conn.execute(listing_query, ids).fetchall()]


def get_listings_posted_since(
    db_path: str, since: str, cutoff: Optional[str]
) -> list[dict]:
    """Read listings posted in a time window from the verified data cutoff."""
    with get_conn(db_path) as conn:
        query = """
            SELECT company, COUNT(*) AS listing_count
            FROM listings
            WHERE COALESCE(posted_at, fetched_at) >= ?
        """
        parameters: list[str] = [since]
        if cutoff:
            query += " AND fetched_at <= ?"
            parameters.append(cutoff)
        query += " GROUP BY company ORDER BY listing_count DESC, company ASC"
        cursor = conn.execute(query, parameters)
        return [dict(row) for row in cursor.fetchall()]


def get_seniority_distribution(
    db_path: str, since: str, cutoff: Optional[str]
) -> list[dict]:
    """Read seniority counts from listings in the verified time window."""
    with get_conn(db_path) as conn:
        query = """
            SELECT COALESCE(NULLIF(seniority, ''), 'unknown') AS seniority,
                   COUNT(*) AS listing_count
            FROM listings
            WHERE COALESCE(posted_at, fetched_at) >= ?
        """
        parameters: list[str] = [since]
        if cutoff:
            query += " AND fetched_at <= ?"
            parameters.append(cutoff)
        query += " GROUP BY COALESCE(NULLIF(seniority, ''), 'unknown') ORDER BY seniority ASC"
        cursor = conn.execute(query, parameters)
        return [dict(row) for row in cursor.fetchall()]


def get_gaps_at_cutoff(db_path: str, cutoff: Optional[str]) -> list[dict]:
    """Read the latest gap snapshot that existed at the passing cutoff."""
    with get_conn(db_path) as conn:
        query = """
            SELECT skill, listings_blocked, opportunity_cost, mean_score
            FROM gap_snapshots
            WHERE computed_at = (
                SELECT MAX(computed_at) FROM gap_snapshots
        """
        parameters = ()
        if cutoff:
            query += " WHERE computed_at <= ?"
            parameters = (cutoff,)
        query += " ) ORDER BY opportunity_cost DESC LIMIT 10"
        cursor = conn.execute(query, parameters)
        return [dict(row) for row in cursor.fetchall()]


def _table_counts(db_path: str) -> dict[str, int]:
    tables = [
        "listings",
        "skill_gaps",
        "cycle_log",
        "extraction_cache",
        "gap_snapshots",
        "query_log",
    ]
    with get_conn(db_path) as conn:
        counts = {}
        for table in tables:
            row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
            counts[table] = row["count"]
        return counts


def _cli_check(db_path: str) -> int:
    _log_backend()
    print(f"backend   : {_backend_name()}")
    print(f"db_path   : {db_path}")
    try:
        init_db(db_path)
        labels = {
            "listings": "listings",
            "skill_gaps": "skill_gaps",
            "cycle_log": "cycle_log",
            "extraction_cache": "extraction_cache",
            "gap_snapshots": "skill_gaps_snapshot",
            "query_log": "query_log",
        }
        for table, count in _table_counts(db_path).items():
            print(f"  {labels[table]:<20} {count} rows")
        print("connection: ok")
        return 0
    except Exception as error:
        print(f"connection: failed ({type(error).__name__}: {error})")
        return 1


if __name__ == "__main__":
    if "--migrate" in sys.argv:
        _log_backend()
        init_db(os.environ.get("SQLITE_DB_PATH", "edgedash.db"))
        print("migration complete")
        raise SystemExit(0)
    if "--check" in sys.argv:
        raise SystemExit(_cli_check(os.environ.get("SQLITE_DB_PATH", "edgedash.db")))
