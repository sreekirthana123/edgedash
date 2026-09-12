"""Read-only Streamlit dashboard for EdgeDash agent activity."""

import re
import logging
from html import escape
from datetime import datetime, timedelta, timezone

import streamlit as st

from edgedash import storage
from edgedash.config import Config
from edgedash.query.ask import ask
from edgedash.runtime import get_runtime_value, redact_error


st.set_page_config(
    page_title="EdgeDash Activity",
    page_icon="ED",
    layout="wide",
    initial_sidebar_state="collapsed",
)


DB_PATH = get_runtime_value("EDGEDASH_DB_PATH", "edgedash.db") or "edgedash.db"
GITHUB_REPO_URL = get_runtime_value(
    "GITHUB_REPO_URL", "https://github.com/your-org/edgedash"
)
LOGGER = logging.getLogger("edgedash.dashboard")


st.markdown(
    """
    <style>
    :root { --ink: #17212b; --muted: #607080; --line: #d9e1e8; --teal: #087f8c; --red: #b42318; --amber: #a15c00; }
    .stApp { background: var(--background-color, #0f172a); color: var(--text-color, #f8fafc); }
    [data-testid="stHeader"] { background: transparent; }
    .block-container { max-width: 1380px; padding-top: 2.2rem; }
    .eyebrow { color: var(--teal); font-size: .72rem; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
    h1 { color: var(--text-color, #f8fafc); font-size: 2.3rem; letter-spacing: 0; margin: .15rem 0 .3rem; }
    h2 { color: var(--text-color, #f8fafc); font-size: 1.15rem; letter-spacing: 0; margin-top: 1.6rem; }
    .subtitle { color: var(--text-color, #f8fafc); opacity: .78; margin-bottom: 1.4rem; }
    .metric { background: white; border: 1px solid var(--line); border-top: 3px solid var(--teal); padding: 1rem 1.1rem; min-height: 6.2rem; }
    .metric-label { color: var(--muted); font-size: .76rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }
    .metric-value { color: var(--ink); font-size: 1.45rem; font-weight: 800; margin-top: .35rem; }
    .status-pass { color: #137333; }
    .status-fail { color: var(--red); }
    .status-degraded { color: var(--amber); }
    .activity-table-wrap { background: white; border: 1px solid var(--line); overflow-x: auto; }
    .activity-table { border-collapse: collapse; min-width: 100%; font-size: .82rem; }
    .activity-table th { background: #eaf0f3; color: var(--muted); font-size: .7rem; letter-spacing: .06em; padding: .7rem .8rem; text-align: left; text-transform: uppercase; white-space: nowrap; }
    .activity-table td { border-top: 1px solid #edf1f3; padding: .72rem .8rem; vertical-align: top; }
    .activity-table .activity-fail { background: #fff1f0; color: #7f1d1d; }
    .activity-table .activity-suspect { background: #fff8e8; color: #7a4a00; }
    .activity-table .raw-error-detail { color: var(--muted); font-size: .72rem; }
    .activity-table .raw-error-detail summary { cursor: pointer; }
    .activity-table .raw-error-detail pre { max-height: 180px; overflow: auto; white-space: pre-wrap; word-break: break-word; margin: .15rem 0 0; padding: .4rem .6rem; border: 1px solid #e0b7b7; background: #fbf0f0; }
    .stDataFrame { border: 1px solid var(--line); }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=15)
def read_activity(db_path: str) -> list[dict]:
    return storage.get_cycle_activity(db_path, limit=5)


@st.cache_data(ttl=15)
def read_last_passing(db_path: str) -> dict | None:
    return storage.get_last_passing_cycle(db_path)


@st.cache_data(ttl=15)
def read_last_verifier(db_path: str) -> dict | None:
    return storage.get_last_verifier_row(db_path)


@st.cache_data(ttl=15)
def read_counts(db_path: str, cutoff: str | None) -> dict:
    return storage.get_listing_counts_at_cutoff(db_path, cutoff)


@st.cache_data(ttl=15)
def read_listings(db_path: str, cutoff: str | None) -> list[dict]:
    return storage.get_listings_at_cutoff(db_path, cutoff)


@st.cache_data(ttl=15)
def read_gaps(db_path: str, cutoff: str | None) -> list[dict]:
    return storage.get_gaps_at_cutoff(db_path, cutoff)


# One-line system status colors — match the app palette.
_STATUS_GREEN = "#137333"
_STATUS_AMBER = "#a15c00"
_STATUS_RED = "#b42318"


def _status_line() -> tuple[str, str]:
    """Return (color, text) for the one-line status indicator.

    - red:    the last 3 cycle verifications all failed
    - green:  the last cycle passed within 24 hours
    - amber:  otherwise (stale data, or no passing cycle on record)
    """
    now = datetime.now(timezone.utc)

    def _age_hours(iso_value: str | None) -> float | None:
        if not iso_value:
            return None
        try:
            timestamp = datetime.fromisoformat(iso_value)
        except (ValueError, TypeError):
            return None
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return (now - timestamp).total_seconds() / 3600.0

    try:
        verifier_rows = [
            row
            for row in storage.get_cycle_activity(DB_PATH, limit=50)
            if (row.get("agent") or "").strip() == "Verifier"
        ]
        recent = verifier_rows[:3]
        if len(recent) == 3 and all(
            str(row.get("status", "")).lower() == "failed" for row in recent
        ):
            return _STATUS_RED, "Unhealthy — last 3 cycles failed verification"
    except Exception:
        pass  # a status-line failure must never take the page down

    last_pass = None
    try:
        last_pass = storage.get_last_passing_cycle(DB_PATH)
    except Exception:
        last_pass = None
    hours = _age_hours(last_pass.get("timestamp") if last_pass else None)
    if hours is not None and hours <= 24:
        return _STATUS_GREEN, f"Live — last cycle passed {hours:.1f}h ago"
    if hours is not None:
        return _STATUS_AMBER, f"Stale — last successful cycle {hours:.1f}h ago"
    return _STATUS_AMBER, "Stale — no successful cycle on record"


def render_status_line() -> None:
    """Render the one-line system status.

    Rule 50: health reporting must never take the page down — any failure
    here is logged and the line is simply omitted.
    """
    try:
        color, text = _status_line()
    except Exception as error:
        LOGGER.error("Status line failed: %s", redact_error(error))
        return
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:.5rem;'
        f'font-size:.82rem;font-weight:600;color:{color};'
        f'margin-bottom:.4rem;">'
        f'<span style="width:.55rem;height:.55rem;border-radius:50%;'
        f'background:{color};display:inline-block;"></span>'
        f"{escape(text)}</div>",
        unsafe_allow_html=True,
    )


def format_timestamp(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d %b %Y, %H:%M")
    except ValueError:
        return value


def duration_seconds(row: dict) -> float:
    try:
        start = datetime.fromisoformat(row["started_at"])
        end = datetime.fromisoformat(row["finished_at"])
        return max(0.0, (end - start).total_seconds())
    except (KeyError, TypeError, ValueError):
        return 0.0


# Human-readable one-line summaries for raw cycle_log failure notes.
# The full raw detail stays in the database (unchanged) and is only revealed
# behind an expandable <details> element per row, so failed/degraded runs
# remain visible for diagnosis without dumping raw exception blobs on the page.
_VERDICT_LABELS = {
    "score_spread": "Verification failed — score distribution too flat or clustered",
    "extraction_sanity": "Verification failed — too many listings extracted empty or malformed",
    "gap_sample_size": "Verification failed — top skill gap has too few supporting listings",
    "freshness": "Verification failed — data older than the allowed freshness window",
}


def _verdict_summary(check_name: str) -> str:
    return _VERDICT_LABELS.get(check_name, f"Verification failed — {check_name} check")


def summarize_error(notes: str | None) -> str:
    """Return a short, human-readable one-line summary of raw failure notes."""
    text = (notes or "").strip()
    if not text:
        return "—"
    lower = text.lower()

    if "quota" in lower or "resource_exhausted" in lower or re.search(r"\b429\b", text):
        return "Gemini API quota exceeded — retry later"
    if "timeout" in lower or "timed out" in lower:
        return "Gemini API timed out — temporarily unavailable"
    if re.search(
        r"connectionerror|connection refused|failed to resolve|remote end closed|"
        r"max retries exceeded|broken pipe|proxyerror",
        lower,
    ):
        return "Network connection failed — temporary issue"
    if "http error" in lower or "response status" in lower:
        return "Job board request failed — temporary issue"
    if lower.startswith("distribution:"):
        return "Score distribution flagged as suspect — spread too low"

    verdict_match = re.search(r"VERDICT:\s*fail\s*[—-]\s*(\w+)", text, re.I)
    if verdict_match:
        return _verdict_summary(verdict_match.group(1).strip())
    if "gemini" in lower:
        return "Gemini API temporarily unavailable"

    first_line = text.splitlines()[0].strip()
    if len(first_line) > 140:
        return first_line[:140].rstrip() + "…"
    return first_line or "Agent reported a failure"


def retry_count(notes: str | None) -> int:
    return 1 if re.search(r"retry[- ]?1|retrying", notes or "", re.I) else 0


def safe_panel_read(label: str, reader, default, errors: list[str]):
    """Read one dashboard panel without allowing its failure to stop the page."""
    try:
        return reader()
    except Exception as error:
        LOGGER.error("Dashboard panel failed (%s): %s", label, redact_error(error))
        errors.append(label)
        return default


def _failure_cell(notes: str | None) -> str:
    """Render the 'Failed check / observed' cell for a failed/degraded/suspect row.

    Shows a short human-readable summary by default; the full raw notes are
    shown only behind an expandable <details> element per row.
    """
    full = (notes or "").strip()
    summary = summarize_error(full)
    cell = escape(summary)
    if full and full != summary:
        cell += (
            ' <details class="raw-error-detail">'
            "<summary>Show raw error</summary>"
            f"<pre>{escape(full)}</pre></details>"
        )
    return cell


def render_activity(rows: list[dict]) -> None:
    if not rows:
        st.info("No cycles yet")
        return
    display_rows = []
    for row in rows:
        status = str(row.get("status", "unknown")).lower()
        if status in {"failed", "degraded", "suspect"}:
            failure_cell = _failure_cell(row.get("notes"))
        else:
            failure_cell = "—"
        display_rows.append(
            {
                "Timestamp": format_timestamp(row.get("finished_at") or row.get("started_at")),
                "Agent run": row.get("agent", "—"),
                "Skipped": "—" if row.get("records_touched", 0) else "none",
                "Verdict": status,
                "Failed check / observed": failure_cell,
                "Retries": retry_count(row.get("notes")),
                "Duration": f"{duration_seconds(row):.1f}s",
            }
        )
    headers = list(display_rows[0])
    header_html = "".join(f"<th>{escape(header)}</th>" for header in headers)
    row_html = []
    for row in display_rows:
        status = str(row["Verdict"]).lower()
        row_class = "activity-fail" if status in {"failed", "degraded"} else "activity-suspect" if status == "suspect" else ""
        cells = []
        for header in headers:
            value = row[header]
            if header == "Failed check / observed":
                cells.append(f"<td>{value}</td>")  # value is pre-escaped HTML
            else:
                cells.append(f"<td>{escape(str(value))}</td>")
        row_html.append(f'<tr class="{row_class}">{"".join(cells)}</tr>')
    st.markdown(
        f"""
        <div class="activity-table-wrap">
          <table class="activity-table"><thead><tr>{header_html}</tr></thead>
          <tbody>{''.join(row_html)}</tbody></table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def current_verdict(rows: list[dict], fallback: dict | None = None) -> str:
    """Return the most recent Verifier verdict for the "Current verdict" metric.

    The cycle_log has many rows per cycle (one per Scorer sub-task, plus
    GapAnalyzer, plus Verifier), so the newest row overall is NOT the
    verification result. We specifically look at the most recent row whose
    agent is the Verifier, and derive the verdict from its notes
    ("VERDICT: pass" / "VERDICT: fail") with a fallback to its status column.

    When the recent activity slice has no Verifier row (the latest cycle
    skipped verification because there was nothing new to verify), we fall
    back to the last real Verifier row from the full cycle_log so the metric
    keeps showing the last known verdict instead of flipping to "not_run".

    Returns:
        "pass" / "fail" when a Verifier row exists (recent or fallback),
        "not_run" only when no Verifier row has EVER existed in history,
        "no cycles" when the log is empty.
    """
    if not rows:
        return "no cycles"
    verifier_rows = [
        row for row in rows if (row.get("agent") or "").strip() == "Verifier"
    ]
    latest = verifier_rows[0] if verifier_rows else fallback
    if latest is None:
        return "not_run"
    notes = str(latest.get("notes") or "")
    lower_notes = notes.lower()
    if "verdict: pass" in lower_notes or "verdict: ok" in lower_notes:
        return "pass"
    if "verdict: fail" in lower_notes or "verdict: failed" in lower_notes:
        return "fail"
    status = str(latest.get("status", "")).lower()
    if status in {"ok", "pass", "passed"}:
        return "pass"
    if status in {"failed", "fail"}:
        return "fail"
    return "not_run"


def main() -> None:
    st.markdown('<div class="eyebrow">EdgeDash / Read-only operations</div>', unsafe_allow_html=True)
    st.title("Agent activity")
    st.markdown('<div class="subtitle">Verified intelligence, with the machinery visible.</div>', unsafe_allow_html=True)
    render_status_line()

    panel_errors = []
    activity = safe_panel_read("activity log", lambda: read_activity(DB_PATH), [], panel_errors)
    passing = safe_panel_read("last passing cycle", lambda: read_last_passing(DB_PATH), None, panel_errors)
    cutoff = passing.get("timestamp") if passing else None
    counts = safe_panel_read("listing counts", lambda: read_counts(DB_PATH, cutoff), {"total_listings": 0, "total_scored": 0}, panel_errors)
    listings = safe_panel_read("scored listings", lambda: read_listings(DB_PATH, cutoff), [], panel_errors)
    gaps = safe_panel_read("skill gaps", lambda: read_gaps(DB_PATH, cutoff), [], panel_errors)

    if panel_errors and get_runtime_value("DATABASE_URL"):
        st.error("Database not configured or unreachable. Showing available fallback panels.")
    elif not get_runtime_value("DATABASE_URL"):
        st.info("Database not configured — using the local SQLite fallback.")

    if not activity and not passing and not listings and not gaps:
        next_run = datetime.now(timezone.utc) + timedelta(hours=6)
        st.info(f"No cycles yet — first run is scheduled for {next_run.astimezone().strftime('%d %b %Y, %H:%M %Z')}.")

    newest = activity[0] if activity else None
    newest_status = str(newest.get("status", "unknown")).lower() if newest else "no cycles"
    verdict = current_verdict(activity, read_last_verifier(DB_PATH))
    passing_timestamp = passing.get("timestamp") if passing else None

    if newest and newest_status in {"failed", "degraded", "suspect"}:
        st.warning(
            "Newest cycle is not verified. The data below is from the earlier verified cycle "
            f"at {format_timestamp(passing_timestamp)}."
        )

    metric_columns = st.columns(4)
    metrics = [
        ("Last successful cycle", format_timestamp(passing_timestamp)),
        ("Total listings", str(counts["total_listings"])),
        ("Total scored", str(counts["total_scored"])),
        ("Current verdict", verdict),
    ]
    for column, (label, value) in zip(metric_columns, metrics):
        status_class = "status-fail" if value in {"failed", "degraded", "suspect"} else ""
        column.markdown(
            f'<div class="metric"><div class="metric-label">{label}</div>'
            f'<div class="metric-value {status_class}">{value}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("## Ask your data")
    st.caption("Ask about the last passing cycle. Answers always include their source rows.")
    query_config = Config.load()
    questions_today = storage.count_queries_today(DB_PATH)
    daily_cap_reached = questions_today >= query_config.daily_query_cap
    if daily_cap_reached:
        st.info("The daily question limit has been reached. The rest of the dashboard is still available.")
    example_questions = [
        "Which companies are hiring this week?",
        "What are the top skill gaps?",
        "How many listings are scored?",
    ]
    example_columns = st.columns(3)
    for column, example in zip(example_columns, example_questions):
        if column.button(
            example,
            key=f"example_{example}",
            disabled=daily_cap_reached,
        ):
            # Only pre-fill the question input. The query must be triggered
            # solely by the "Ask" button: every question costs Gemini API
            # quota (2 calls each), so a suggestion click must never fire a
            # query on its own.
            st.session_state["query_question"] = example
    question = st.text_input(
        "Question",
        key="query_question",
        placeholder="Which companies are hiring this week?",
        disabled=daily_cap_reached,
    )
    question_to_ask = question
    if (
        not daily_cap_reached
        and st.button("Ask", type="primary")
        and question_to_ask.strip()
    ):
        try:
            session_timestamps = st.session_state.setdefault("query_timestamps", [])
            answer = ask(question_to_ask.strip(), session_timestamps)
            st.markdown(answer.text)
            st.markdown("**Underlying rows**")
            st.dataframe(answer.rows, use_container_width=True, hide_index=True)
        except Exception as error:
            LOGGER.error("Ask your data request failed: %s", redact_error(error))
            st.error("Could not answer that question right now. Please try again later.")

    st.markdown("## Agent activity log")
    st.caption("Most recent 5 cycle-log entries. Failed and degraded entries remain visible for diagnosis.")
    render_activity(activity)

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("## Top 10 scored listings")
        st.caption("From last passing cycle - min score 50")
        if listings:
            for listing in listings:
                score = listing.get("fit_score", "—")
                title = listing.get("title", "—")
                company = listing.get("company", "—")
                reason = listing.get("fit_reason", "—")
                st.markdown(f"**{score} - {title}** · {company}")
                st.markdown(
                    f'<span style="color: #607080;">{escape(str(reason))}</span>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("No verified scored listings yet")
    with right:
        st.markdown("## Top 10 skill gaps")
        st.caption("From last passing cycle")
        if gaps:
            for index, gap in enumerate(gaps, start=1):
                skill = gap.get("skill", "—")
                listings_blocked = gap.get("listings_blocked", 0)
                opportunity_cost = gap.get("opportunity_cost", 0)
                details = gap.get("confidence") or gap.get("note")
                detail_text = f" · {details}" if details else ""
                st.markdown(
                    f"{index}. {skill} — {listings_blocked} listings · "
                    f"cost {opportunity_cost}{detail_text}"
                )
        else:
            st.info("No verified skill gaps yet")

    st.divider()
    st.caption(
        f"Last successful cycle: {format_timestamp(passing_timestamp)} · "
        f"[GitHub repository]({GITHUB_REPO_URL})"
    )


if __name__ == "__main__":
    main()