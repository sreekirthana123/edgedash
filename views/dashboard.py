"""EdgeDash Dashboard — the read-only view of agent activity and scored data."""

import re
import logging
from html import escape
from datetime import datetime, timedelta, timezone

import streamlit as st

from edgedash import storage
from edgedash.config import Config
from edgedash.query.ask import ask
from edgedash.runtime import get_runtime_value, redact_error
from edgedash.ui_style import apply_style


# NOTE: st.set_page_config is owned by app.py (the entrypoint). With
# st.navigation, app.py executes on every page run, so calling it here too
# would raise "set_page_config can only be called once per page".

apply_style(home=False)


DB_PATH = get_runtime_value("EDGEDASH_DB_PATH", "edgedash.db") or "edgedash.db"
GITHUB_REPO_URL = get_runtime_value(
    "GITHUB_REPO_URL", "https://github.com/your-org/edgedash"
)
LOGGER = logging.getLogger("edgedash.dashboard")


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
def read_listings(db_path: str, cutoff: str | None) -> list[dict]:
    return storage.get_listings_at_cutoff(db_path, cutoff)


@st.cache_data(ttl=15)
def read_gaps(db_path: str, cutoff: str | None) -> list[dict]:
    return storage.get_gaps_at_cutoff(db_path, cutoff)


@st.cache_data(ttl=15)
def read_counts(db_path: str, cutoff: str | None) -> dict:
    return storage.get_listing_counts_at_cutoff(db_path, cutoff)


def safe_panel_read(label: str, reader, default, errors: list[str]):
    """Read one dashboard panel without allowing its failure to stop the page."""
    try:
        return reader()
    except Exception as error:
        LOGGER.error("Dashboard panel failed (%s): %s", label, redact_error(error))
        errors.append(label)
        return default


# One-line system status levels, mapped to the shared pill CSS.
_STATUS_STYLES = {
    "green": ("status-pill-ok", "dot-ok", "Live"),
    "amber": ("status-pill-warn", "dot-warn", "Stale"),
    "red": ("status-pill-bad", "dot-bad", "Unhealthy"),
}


def _status_line() -> tuple[str, str, str]:
    """Return (level, title, detail) for the one-line status indicator.

    - red:    the last 3 cycle verifications all failed
    - green:  the last cycle passed within 24 hours
    - amber:  otherwise (stale data, or no passing cycle on record)
    """
    now = datetime.now(timezone.utc)

    def _age_hours(iso_value):
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
            return "red", "Unhealthy", "last 3 cycles failed verification"
    except Exception:
        pass  # a status-line failure must never take the page down

    last_pass = None
    try:
        last_pass = storage.get_last_passing_cycle(DB_PATH)
    except Exception:
        last_pass = None
    hours = _age_hours(last_pass.get("timestamp") if last_pass else None)
    if hours is not None and hours <= 24:
        return "green", "Live", f"last cycle passed {hours:.1f}h ago"
    if hours is not None:
        return "amber", "Stale", f"last successful cycle {hours:.1f}h ago"
    return "amber", "Stale", "no successful cycle on record"


def format_timestamp(value) -> str:
    if not value:
        return "-"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - value
    if delta < timedelta(minutes=1):
        return "just now"
    if delta < timedelta(hours=1):
        minutes = int(delta.total_seconds() / 60)
        return f"{minutes}m ago"
    if delta < timedelta(days=1):
        hours = int(delta.total_seconds() / 3600)
        return f"{hours}h ago"
    days = delta.days
    return f"{days}d ago"


def _verdict_from_row(row: dict) -> str:
    notes = str(row.get("notes") or "").lower()
    if "verdict: pass" in notes or "verdict: ok" in notes:
        return "pass"
    if "verdict: fail" in notes or "verdict: failed" in notes:
        return "fail"
    status = str(row.get("status") or "").lower()
    if status in ("ok", "pass", "passed"):
        return "pass"
    if status in ("failed", "fail"):
        return "fail"
    return "not_run"


def current_verdict(rows: list[dict], fallback: dict | None = None) -> str:
    if not rows:
        return "no cycles"
    for row in rows:
        if row.get("agent") == "Verifier":
            return _verdict_from_row(row)
    if fallback is not None:
        return _verdict_from_row(fallback)
    return "not_run"


def _summarize_error(notes: str) -> str:
    notes = notes.strip()
    lowered = notes.lower()
    if "429" in notes and ("quota" in lowered or "resource_exhausted" in lowered):
        return "Gemini API quota exceeded - retry later"
    if "timeout" in lowered:
        return "Gemini API timed out - temporarily unavailable"
    if "503" in notes or "service unavailable" in lowered:
        return "Gemini API temporarily unavailable"
    if "verdict: fail" in lowered or "verdict: failed" in lowered:
        return "Verification failed - check details"
    if "score_spread" in lowered or "extraction" in lowered:
        return "Verification failed - data quality issue"
    if "connection" in lowered or "network" in lowered:
        return "Network error - temporarily unavailable"
    if len(notes) > 120:
        return notes[:117] + "..."
    return notes


def _summarize_suspect(notes: str) -> str:
    """Plain-English one-liner for a 'suspect' cycle row.

    Suspect rows carry verifier statistics (e.g. "Distribution: count=8
    min=35 max=42 mean=37 spread=7") rather than an error message, so the
    error summariser would just echo the raw numbers. Translate the common
    stat lines into something a visitor can read at a glance; the raw stats
    stay available in the row's expandable detail.
    """
    lowered = notes.lower()
    if "distribution" in lowered or "spread" in lowered:
        count_match = re.search(r"count=(\d+)", lowered)
        spread_match = re.search(r"spread=([\d.]+)", lowered)
        parts = []
        if count_match:
            parts.append(f"{count_match.group(1)} listings scored")
        if spread_match:
            parts.append(f"scores within a {spread_match.group(1)}-point range")
        observed = f" ({', '.join(parts)})" if parts else ""
        return f"Scores look unusually similar{observed} - worth a second look"
    if "extraction" in lowered:
        return "Some extracted listing data looks unusual - worth a second look"
    return "Unusual data pattern detected - worth a second look"


def render_activity(activity: list[dict]) -> None:
    if not activity:
        st.info("No activity recorded yet.")
        return
    html = [
        '<div class="activity-table-wrap"><table class="activity-table"><thead><tr>'
    ]
    for header in ("Agent", "Started", "Records", "Status", "Detail"):
        html.append(f"<th>{header}</th>")
    html.append("</tr></thead><tbody>")
    for row in activity:
        agent = escape(str(row.get("agent", "")))
        started = format_timestamp(row.get("started_at"))
        records = row.get("records_touched", "-")
        status = str(row.get("status", "-")).lower()
        notes = str(row.get("notes") or "").strip()
        css_class = ""
        if status in ("failed", "fail"):
            css_class = "activity-fail"
        elif status == "suspect":
            css_class = "activity-suspect"
        if status in ("failed", "fail", "suspect") and notes:
            summary = (
                _summarize_suspect(notes) if status == "suspect"
                else _summarize_error(notes)
            )
            detail = escape(notes)
            cell = (
                f'<span class="status-{status}">{escape(status)}</span><br>'
                f'<span class="raw-error-detail">'
                f"<details><summary>{escape(summary)}</summary>"
                f"<pre>{detail}</pre></details></span>"
            )
        else:
            cell = f'<span class="status-{status}">{escape(status)}</span>'
        # Detail column: suspect rows show the human-readable line (their raw
        # stats remain in the expandable detail above); other rows keep the
        # raw notes excerpt.
        shown = summary if status == "suspect" and notes else notes[:200]
        html.append(
            f'<tr class="{css_class}">'
            f"<td>{agent}</td>"
            f"<td>{started}</td>"
            f"<td>{records}</td>"
            f"<td>{cell}</td>"
            f"<td>{escape(shown)}</td>"
            f"</tr>"
        )
    html.append("</tbody></table></div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def render_status_line() -> None:
    """One-line health indicator. Any failure here must never take the page down."""
    try:
        level, title, detail = _status_line()
    except Exception as error:
        LOGGER.error("Status line failed: %s", redact_error(error))
        return
    pill, dot, _ = _STATUS_STYLES[level]
    try:
        st.markdown(
            f'<div class="status-pill {pill}">'
            f'<span class="dot {dot}">&#9679;</span> <b>{escape(title)}</b>'
            f" <span class='pill-muted'>{escape(detail)}</span></div>",
            unsafe_allow_html=True,
        )
    except Exception:
        pass  # rule 50: the indicator must never break the page


def main() -> None:
    panel_errors: list[str] = []
    activity = safe_panel_read("activity log", lambda: read_activity(DB_PATH), [], panel_errors)
    passing = safe_panel_read("last passing cycle", lambda: read_last_passing(DB_PATH), None, panel_errors)
    fallback_verifier = safe_panel_read("last verifier", lambda: read_last_verifier(DB_PATH), None, panel_errors)

    # The passing-cycle row's cutoff key is "timestamp" (not "finished_at").
    passing_timestamp = passing.get("timestamp") if passing else None
    counts = safe_panel_read("listing counts", lambda: read_counts(DB_PATH, passing_timestamp), {"total_listings": 0, "total_scored": 0}, panel_errors)
    listings = safe_panel_read("scored listings", lambda: read_listings(DB_PATH, passing_timestamp), [], panel_errors)
    gaps = safe_panel_read("skill gaps", lambda: read_gaps(DB_PATH, passing_timestamp), [], panel_errors)

    verdict = current_verdict(activity, fallback_verifier)
    newest = activity[0] if activity else None
    newest_status = str(newest.get("status", "unknown")).lower() if newest else "no cycles"

    render_status_line()

    st.markdown('<span class="eyebrow">EdgeDash</span>', unsafe_allow_html=True)
    st.markdown("# Dashboard")
    st.markdown(
        '<p class="subtitle">Real-time view of the autonomous job-market '
        "intelligence pipeline. All data is read-only - the dashboard never "
        "triggers a cycle.</p>",
        unsafe_allow_html=True,
    )

    if newest_status in {"failed", "degraded", "suspect"}:
        st.warning(
            "Newest cycle is not verified. The data below is from the earlier "
            f"verified cycle at {format_timestamp(passing_timestamp)}."
        )
    if panel_errors:
        st.caption(
            "Some panels could not be loaded: " + ", ".join(panel_errors)
        )

    col1, col2, col3, col4 = st.columns(4)
    metrics = [
        ("Current verdict", verdict, f"status-{verdict}"),
        ("Last success", format_timestamp(passing_timestamp), ""),
        ("Listings", str(counts.get("total_listings", 0)), ""),
        ("Scored", str(counts.get("total_scored", 0)), ""),
    ]
    for column, (label, value, value_class) in zip((col1, col2, col3, col4), metrics):
        column.markdown(
            '<div class="metric"><div class="metric-label">'
            f"{label}</div>"
            f'<div class="metric-value {value_class}">{value}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("## Ask your data")
    st.caption(
        "Ask questions about the scored listings and skill gaps. "
        "Each question uses 2 Gemini API calls."
    )

    config = Config.load("config.yaml")
    daily_cap = config.daily_query_cap
    daily_count = storage.count_queries_today(DB_PATH)
    daily_cap_reached = daily_count >= daily_cap

    if daily_cap_reached:
        st.warning(
            f"Daily question cap reached ({daily_count}/{daily_cap}). "
            "Try again tomorrow."
        )

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
            st.error(
                "Could not answer that question right now. Please try again later."
            )

    st.markdown("## Agent activity log")
    st.caption(
        "Most recent 5 cycle-log entries. Failed and degraded entries remain "
        "visible for diagnosis."
    )
    render_activity(activity)

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("## Best-fit jobs for you")
        st.caption("Ranked by how well each listing matches your skills - higher score means a better fit.")
        if listings:
            for listing in listings:
                score = listing.get("fit_score", "-")
                title = listing.get("title", "-")
                company = listing.get("company", "-")
                reason = listing.get("fit_reason", "-")
                st.markdown(f"**{score} - {title}** &middot; {company}")
                st.markdown(
                    f'<span class="listing-reason">{escape(str(reason))}</span>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("No verified scored listings yet")
    with right:
        st.markdown("## Skills worth learning next")
        st.caption("Skills that appear most often in listings you'd otherwise fit - ranked by how many good opportunities each gap blocks.")
        if gaps:
            for index, gap in enumerate(gaps, start=1):
                skill = gap.get("skill", "-")
                listings_blocked = gap.get("listings_blocked", 0)
                opportunity_cost = gap.get("opportunity_cost", 0)
                details = gap.get("confidence") or gap.get("note")
                detail_text = f" &middot; {details}" if details else ""
                st.markdown(
                    f"{index}. **{skill}** - {listings_blocked} listings "
                    f"&middot; cost {opportunity_cost}{detail_text}"
                )
        else:
            st.info("No verified skill gaps yet")

    st.divider()
    st.caption(
        f"Last successful cycle: {format_timestamp(passing_timestamp)} &middot; "
        f"[GitHub repository]({GITHUB_REPO_URL})"
    )


if __name__ == "__main__":
    main()
