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
def read_listings(db_path: str, since: str | None, min_score: int) -> list[dict]:
    return storage.get_listings(db_path, since=since, min_score=min_score)


@st.cache_data(ttl=15)
def read_gaps(db_path: str, since: str | None) -> list[dict]:
    return storage.get_skill_gaps(db_path, since=since)


@st.cache_data(ttl=15)
def read_counts(db_path: str) -> dict:
    return storage.get_counts(db_path)


@st.cache_data(ttl=15)
def read_health(db_path: str) -> dict:
    from edgedash.health import run as run_health

    return run_health(db_path, quiet=True)


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
            summary = _summarize_error(notes)
            detail = escape(notes)
            cell = (
                f'<span class="status-{status}">{escape(status)}</span><br>'
                f'<span class="raw-error-detail">'
                f"<details><summary>{escape(summary)}</summary>"
                f"<pre>{detail}</pre></details></span>"
            )
        else:
            cell = f'<span class="status-{status}">{escape(status)}</span>'
        html.append(
            f'<tr class="{css_class}">'
            f"<td>{agent}</td>"
            f"<td>{started}</td>"
            f"<td>{records}</td>"
            f"<td>{cell}</td>"
            f"<td>{escape(notes[:200])}</td>"
            f"</tr>"
        )
    html.append("</tbody></table></div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def render_status_line(health: dict) -> None:
    """One-line health indicator. Any failure here must never take the page down."""
    if not health:
        return
    overall = health.get("overall", "unknown")
    checks = health.get("checks", {})
    try:
        if overall == "healthy":
            st.markdown(
                '<div class="status-pill status-pill-ok">'
                '<span class="dot dot-ok">&#9679;</span> <b>Live</b>'
                " <span class='pill-muted'>system healthy</span></div>",
                unsafe_allow_html=True,
            )
        elif overall == "degraded":
            failed = [k for k, v in checks.items() if v.get("status") == "fail"]
            reason = ", ".join(failed[:2]) if failed else "degraded"
            st.markdown(
                f'<div class="status-pill status-pill-warn">'
                f'<span class="dot dot-warn">&#9679;</span> <b>Degraded</b>'
                f" <span class='pill-muted'>- {escape(reason)}</span></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="status-pill status-pill-bad">'
                '<span class="dot dot-bad">&#9679;</span> <b>Unhealthy</b>'
                " <span class='pill-muted'>checks failing</span></div>",
                unsafe_allow_html=True,
            )
    except Exception:
        pass  # rule 50: the indicator must never break the page


def main() -> None:
    activity = read_activity(DB_PATH)
    passing = read_last_passing(DB_PATH)
    fallback_verifier = read_last_verifier(DB_PATH)
    counts = read_counts(DB_PATH)
    try:
        health = read_health(DB_PATH)
    except Exception:
        health = None  # rule 50: health failure must never break the page

    passing_timestamp = passing.get("finished_at") if passing else None
    listings = read_listings(
        DB_PATH,
        since=passing_timestamp,
        min_score=Config.load("config.yaml").min_fit_score,
    )
    gaps = read_gaps(DB_PATH, since=passing_timestamp)

    verdict = current_verdict(activity, fallback_verifier)

    render_status_line(health)

    st.markdown('<span class="eyebrow">EdgeDash</span>', unsafe_allow_html=True)
    st.markdown("# Dashboard")
    st.markdown(
        '<p class="subtitle">Real-time view of the autonomous job-market '
        "intelligence pipeline. All data is read-only - the dashboard never "
        "triggers a cycle.</p>",
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.markdown(
            '<div class="metric"><div class="metric-label">Current verdict</div>'
            f'<div class="metric-value status-{verdict}">{verdict}</div></div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            '<div class="metric"><div class="metric-label">Last success</div>'
            f'<div class="metric-value">{format_timestamp(passing_timestamp)}</div></div>',
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            '<div class="metric"><div class="metric-label">Listings</div>'
            f'<div class="metric-value">{counts.get("total_listings", 0)}</div></div>',
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            '<div class="metric"><div class="metric-label">Scored</div>'
            f'<div class="metric-value">{counts.get("scored_listings", 0)}</div></div>',
            unsafe_allow_html=True,
        )
    with col5:
        st.markdown(
            '<div class="metric"><div class="metric-label">Skill gaps</div>'
            f'<div class="metric-value">{counts.get("skill_gaps", 0)}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("## Ask your data")
    st.caption(
        "Ask questions about the scored listings and skill gaps. "
        "Each question uses 2 Gemini API calls."
    )

    config = Config.load("config.yaml")
    daily_cap = config.daily_query_cap
    now = datetime.now(timezone.utc)
    window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now.hour < 6:
        window_start -= timedelta(days=1)
    daily_count = storage.count_queries_since(DB_PATH, window_start)
    daily_cap_reached = daily_count >= daily_cap

    if daily_cap_reached:
        st.warning(
            f"Daily question cap reached ({daily_count}/{daily_cap}). "
            "Try again after midnight UTC."
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
        st.markdown("## Top 10 scored listings")
        st.caption("From last passing cycle - min score 50")
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
        st.markdown("## Top 10 skill gaps")
        st.caption("From last passing cycle")
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
