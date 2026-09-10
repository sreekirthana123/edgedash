"""Read-only health checks for the deployed EdgeDash system.

Usage:
    python -m edgedash.health

Reads storage only, never writes, makes no LLM calls. Exits 0 when healthy
and 1 when any check fails, so CI (the GitHub Actions workflow) gets a visible
failure notification for an unhealthy system.

Checks:
  - database is reachable
  - the newest listing is no older than 3 days
  - at least one successful cycle happened within 48 hours
  - the last 3 cycle verifications are not all failures

Per rule 48, error text is redacted before it is printed; a connection error
must never leak DATABASE_URL.
"""

import sys
from datetime import datetime, timezone
from typing import Callable, Optional

from edgedash import storage
from edgedash.runtime import get_runtime_value, redact_error

DB_PATH = get_runtime_value("EDGEDASH_DB_PATH", "edgedash.db") or "edgedash.db"

# Thresholds (kept here so they are visible when reading the health report).
NEWEST_LISTING_MAX_AGE_DAYS = 3
SUCCESSFUL_CYCLE_MAX_AGE_HOURS = 48
VERIFIER_FAILURES_TO_ALERT = 3

# A check is (name, passed, one-line observed value / message).
Check = tuple[str, bool, str]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _age_hours(iso_timestamp: Optional[str]) -> Optional[float]:
    """Return age in hours of an ISO timestamp, or None if missing/unparseable."""
    if not iso_timestamp:
        return None
    try:
        timestamp = datetime.fromisoformat(iso_timestamp)
    except (ValueError, TypeError):
        return None
    if timestamp.tzinfo is None:
        # Storage writes naive UTC timestamps.
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return (_utcnow() - timestamp).total_seconds() / 3600.0


def _backend_label() -> str:
    return "postgres" if storage._using_postgres() else "sqlite"


def check_database(db_path: str) -> Check:
    """Return the database reachability check."""
    try:
        with storage.get_conn(db_path) as conn:
            conn.execute("SELECT 1").fetchone()
        return "database", True, f"reachable ({_backend_label()})"
    except Exception as error:
        return "database", False, f"unreachable: {redact_error(error)}"


def check_newest_listing(db_path: str) -> Check:
    """Fail when the newest listing is older than NEWEST_LISTING_MAX_AGE_DAYS."""
    try:
        newest = storage.last_fetch_time(db_path)
        hours = _age_hours(newest)
        if newest is None:
            return "newest listing", False, "no listings on record"
        if hours is None:
            return "newest listing", False, f"unparseable newest timestamp {newest!r}"
        days = hours / 24.0
        limit = NEWEST_LISTING_MAX_AGE_DAYS
        message = f"newest fetched {days:.1f} days ago (limit {limit})"
        return "newest listing", days <= limit, message
    except Exception as error:
        return "newest listing", False, f"cannot determine: {redact_error(error)}"


def check_successful_cycle(db_path: str) -> Check:
    """Fail when no successful cycle has finished within 48 hours."""
    try:
        last_pass = storage.get_last_passing_cycle(db_path)
        if not last_pass:
            return "successful cycle", False, "no successful cycle on record"
        hours = _age_hours(last_pass.get("timestamp"))
        limit = SUCCESSFUL_CYCLE_MAX_AGE_HOURS
        if hours is None:
            return "successful cycle", False, "last success timestamp unparseable"
        message = f"last success {hours:.1f}h ago (limit {limit}h)"
        return "successful cycle", hours <= limit, message
    except Exception as error:
        return "successful cycle", False, f"cannot determine: {redact_error(error)}"


def _recent_verifier_rows(db_path: str, limit: int) -> list[str]:
    """Return the most recent Verifier statuses, newest first."""
    rows = storage.get_cycle_activity(db_path, limit=50)
    verifier_rows = [
        row for row in rows if (row.get("agent") or "").strip() == "Verifier"
    ]
    return [
        str(row.get("status", "")).lower() or "unknown"
        for row in verifier_rows[:limit]
    ]


def check_last_three_verifications(db_path: str) -> Check:
    """Fail when the last three cycle verifications all failed."""
    try:
        statuses = _recent_verifier_rows(db_path, VERIFIER_FAILURES_TO_ALERT)
        if not statuses:
            return (
                "last 3 verifications",
                True,
                "no Verifier history yet — not alarming",
            )
        if (
            len(statuses) == VERIFIER_FAILURES_TO_ALERT
            and all(status == "failed" for status in statuses)
        ):
            return (
                "last 3 verifications",
                False,
                f"last 3 all failed ({', '.join(statuses)})",
            )
        return (
            "last 3 verifications",
            True,
            f"last {len(statuses)}: {', '.join(statuses)}",
        )
    except Exception as error:
        return "last 3 verifications", False, f"cannot determine: {redact_error(error)}"


def _runnable_checks(db_path: str) -> list[Check]:
    return [
        check_database(db_path),
        check_newest_listing(db_path),
        check_successful_cycle(db_path),
        check_last_three_verifications(db_path),
    ]


def run(db_path: Optional[str] = None, printer: Callable[[str], None] = print) -> int:
    """Run every check, print one line each, and return the process exit code."""
    checks = _runnable_checks(db_path or DB_PATH)
    failures = 0
    for name, passed, message in checks:
        flag = "OK  " if passed else "FAIL"
        printer(f"{flag} {name:<26} {message}")
        failures += int(not passed)
    total = len(checks)
    if failures:
        printer(
            f"\nEdgeDash health: {total - failures}/{total} checks passed — UNHEALTHY"
        )
        return 1
    printer(f"\nEdgeDash health: {total}/{total} checks passed — HEALTHY")
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()