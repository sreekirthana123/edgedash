"""EdgeDash — Home page and multipage entrypoint.

The intro/landing page. The live data dashboard lives in views/dashboard.py
and is registered below via st.navigation. Purely presentational: this page
performs no database reads, so it always renders fast and never fails.
"""

import streamlit as st

from edgedash.ui_style import apply_style


st.set_page_config(
    page_title="EdgeDash",
    page_icon="ED",
    layout="wide",
    initial_sidebar_state="collapsed",
)

apply_style(home=True)


def _render_home() -> None:
    st.markdown(
        '<div class="hero"><span class="eyebrow">EdgeDash &middot; autonomous '
        "job-market intelligence</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown("# Stop guessing which jobs are actually worth your time.")
    st.markdown(
        '<p class="hero-tagline">EdgeDash runs a daily pipeline that pulls live '
        "job listings, scores each one <b>deterministically</b> against your own "
        "skills and preferences, and surfaces the skill gaps that are actually "
        "costing you the most opportunities. Every cycle is <b>verified before "
        "it's trusted</b> &mdash; and every failure stays visible instead of "
        "being hidden.</p>",
        unsafe_allow_html=True,
    )

    cta_left, cta_right = st.columns([1, 2])
    with cta_left:
        if st.button("Open the Dashboard", type="primary", key="cta_dashboard"):
            st.switch_page(dashboard_page)
    with cta_right:
        st.markdown(
            '<p style="color: var(--muted); margin-top: 0.7rem;">'
            "or pick <b>Dashboard</b> in the sidebar &middot; "
            '<a href="https://github.com/sreekirthana123/edgedash" '
            'target="_blank">view the source on GitHub</a></p>',
            unsafe_allow_html=True,
        )

    st.markdown("## How it works")
    st.markdown(
        '<div class="pipeline">'
        '<span class="pipeline-step">Fetcher</span>'
        '<span class="pipeline-arrow">&#8594;</span>'
        '<span class="pipeline-step">Scorer</span>'
        '<span class="pipeline-arrow">&#8594;</span>'
        '<span class="pipeline-step">GapAnalyzer</span>'
        '<span class="pipeline-arrow">&#8594;</span>'
        '<span class="pipeline-step">Verifier</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "Every day, on a schedule, four agents run in sequence. The orchestrator "
        "decides what needs to run; the Verifier has the final say on whether "
        "the cycle's output can be trusted."
    )

    st.markdown('<div class="feature-grid">', unsafe_allow_html=True)
    st.markdown(
        """
<div class="feature-card">
  <div class="feature-icon">&#128230;</div>
  <h3>Fetcher</h3>
  <p>Pulls raw listings from job-board APIs and filters them by keyword and
  city, so only relevant roles enter the pipeline.</p>
</div>
<div class="feature-card">
  <div class="feature-icon">&#127919;</div>
  <h3>Scorer</h3>
  <p>Extracts structured facts from each listing and computes a deterministic
  0&ndash;100 fit score. Scores come from a fixed, auditable formula &mdash;
  never an LLM's judgment call.</p>
</div>
<div class="feature-card">
  <div class="feature-icon">&#128295;</div>
  <h3>GapAnalyzer</h3>
  <p>Ranks the skills you're missing by real opportunity cost: how many
  good-fit listings each missing skill is locking you out of.</p>
</div>
<div class="feature-card">
  <div class="feature-icon">&#9989;</div>
  <h3>Verifier</h3>
  <p>Runs sanity checks on each cycle's output before it's trusted. A failing
  cycle never overwrites the last known-good data.</p>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("## Why trust the numbers")
    st.markdown(
        """
- **Deterministic scoring, not LLM-judged scoring.** Fit scores come from a
  fixed weighted formula (skills match, seniority, location, recency) — every
  score is reproducible and explainable.
- **No model-generated SQL.** "Ask your data" answers questions through a fixed
  set of pre-written, parameterized query tools — never raw SQL from an LLM.
- **Fail loud, never silent.** Failed and degraded runs stay visible in the
  activity log. An unattended system's most dangerous failure mode is silence.
- **Stale verified data beats fresh unverified data.** The dashboard only shows
  output from cycles that passed verification.
"""
    )

    st.divider()
    st.caption(
        "Built by V Sree Kirthana &middot; "
        '[GitHub](https://github.com/sreekirthana123/edgedash) &middot; '
        "[LinkedIn](https://www.linkedin.com/in/v-sree-kirthana)"
    )


# Page registration must come after _render_home is defined. Dashboard is a
# file-based page: views/dashboard.py renders the live, read-only data view.
home_page = st.Page(
    _render_home,
    title="Home",
    icon=":material/home:",
    default=True,
)
dashboard_page = st.Page(
    "views/dashboard.py",
    title="Dashboard",
    icon=":material/monitoring:",
    default=False,
)

page = st.navigation([home_page, dashboard_page])
page.run()
