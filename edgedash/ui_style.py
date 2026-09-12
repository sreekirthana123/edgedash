"""Shared dashboard presentation constants and helpers.

Both pages (Home and Dashboard) import this so the visual language — colors,
spacing, typography — stays consistent. Purely presentational; no data access.
"""

# The single source of truth for the dashboard CSS. Injected via st.markdown
# with unsafe_allow_html=True at the top of each page.
CSS = """
:root {
  --ink: #f1f5f9;
  --muted: #94a3b8;
  --line: #334155;
  --teal: #2dd4bf;
  --teal-dim: #0d3d3a;
  --red: #f87171;
  --red-dim: #7f1d1d;
  --amber: #fbbf24;
  --amber-dim: #78350f;
  --card: #1e293b;
  --card-border: #334155;
  --bg: #0f172a;
}

.stApp { background: var(--background-color, var(--bg)); color: var(--text-color, var(--ink)); }
[data-testid="stHeader"] { background: transparent; }
.block-container { max-width: 1400px; padding: 2.4rem 1.5rem 3.2rem; }

/* ---------- Typography ---------- */
h1 { color: var(--ink); font-size: 2.4rem; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 0.4rem; line-height: 1.15; }
h2 { color: var(--ink); font-size: 1.25rem; font-weight: 600; letter-spacing: -0.01em; margin: 2.2rem 0 0.8rem; }
h3 { color: var(--ink); font-size: 1.05rem; font-weight: 600; margin: 1.6rem 0 0.5rem; }
.subtitle { color: var(--muted); font-size: 1.05rem; line-height: 1.65; margin-bottom: 1.8rem; max-width: 760px; }
.eyebrow { color: var(--teal); font-size: 0.72rem; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase; }
.lead { color: var(--ink); font-size: 1.1rem; line-height: 1.7; margin-bottom: 1.2rem; }

/* ---------- Cards ---------- */
.card { background: var(--card); border: 1px solid var(--card-border); border-radius: 10px; padding: 1.4rem 1.5rem; }
.metric { background: var(--card); border: 1px solid var(--card-border); border-top: 3px solid var(--teal); border-radius: 10px; padding: 1.15rem 1.25rem; min-height: 6.8rem; }
.metric-label { color: var(--muted); font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.07em; }
.metric-value { color: var(--ink); font-size: 1.55rem; font-weight: 800; margin-top: 0.45rem; }

/* ---------- Feature grid (Home page) ---------- */
.feature-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.1rem; margin: 1.4rem 0; }
.feature-card { background: var(--card); border: 1px solid var(--card-border); border-radius: 10px; padding: 1.4rem 1.5rem; transition: border-color 0.15s ease; }
.feature-card:hover { border-color: var(--teal); }
.feature-icon { font-size: 1.7rem; margin-bottom: 0.35rem; line-height: 1; }
.feature-card h3 { margin: 0.4rem 0 0.4rem; }
.feature-card p { color: var(--muted); font-size: 0.92rem; line-height: 1.55; margin: 0; }

/* ---------- Pipeline (Home page) ---------- */
.pipeline { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; margin: 1.4rem 0; }
.pipeline-step { background: var(--teal-dim); border: 1px solid var(--teal); border-radius: 8px; padding: 0.7rem 1.1rem; font-weight: 600; font-size: 0.92rem; color: var(--ink); }
.pipeline-arrow { color: var(--teal); font-weight: 700; font-size: 1.1rem; }

/* ---------- Tables ---------- */
.activity-table-wrap { background: var(--card); border: 1px solid var(--card-border); border-radius: 10px; overflow-x: auto; }
.activity-table { border-collapse: collapse; min-width: 100%; font-size: 0.85rem; }
.activity-table th { background: #0c1424; color: var(--muted); font-size: 0.72rem; letter-spacing: 0.06em; padding: 0.85rem 0.95rem; text-align: left; text-transform: uppercase; white-space: nowrap; }
.activity-table td { border-top: 1px solid #243044; padding: 0.85rem 0.95rem; vertical-align: top; }
.activity-table .activity-fail { background: #2d1416; color: #fca5a5; }
.activity-table .activity-suspect { background: #2d2410; color: #fcd34d; }
.activity-table .raw-error-detail { color: var(--muted); font-size: 0.75rem; }
.activity-table .raw-error-detail summary { cursor: pointer; }
.activity-table .raw-error-detail pre { max-height: 180px; overflow: auto; white-space: pre-wrap; word-break: break-word; margin: 0.2rem 0 0; padding: 0.55rem 0.75rem; border: 1px solid #4c1d1d; background: #1a0e0e; color: #fca5a5; }

/* ---------- Status pills (health indicator) ---------- */
.status-pill { display: inline-flex; align-items: center; gap: 0.45rem; border-radius: 999px; padding: 0.45rem 1.1rem; margin-bottom: 1.2rem; font-size: 0.9rem; }
.status-pill-ok { background: var(--teal-dim); border: 1px solid var(--teal); }
.status-pill-warn { background: var(--amber-dim); border: 1px solid var(--amber); }
.status-pill-bad { background: var(--red-dim); border: 1px solid var(--red); }
.dot { font-size: 0.8rem; }
.dot-ok { color: #4ade80; }
.dot-warn { color: var(--amber); }
.dot-bad { color: var(--red); }
.pill-muted { color: var(--muted); font-weight: 400; }

/* ---------- Listing detail text ---------- */
.listing-reason { color: var(--muted); font-size: 0.88rem; line-height: 1.5; }

/* ---------- Status colors ---------- */
.status-pass { color: #4ade80; }
.status-fail { color: var(--red); }
.status-degraded { color: var(--amber); }
.status-not-run { color: var(--muted); }

/* ---------- Links & misc ---------- */
a { color: var(--teal); text-decoration: none; }
a:hover { text-decoration: underline; }
hr { border-color: var(--line); margin: 2.2rem 0; }
"""

# CSS block tailored for the Home page — adds a hero section plus the shared rules.
CSS_HOME = CSS + """
.hero { padding: 1.5rem 0 0.5rem; }
.hero-tagline { color: var(--muted); font-size: 1.15rem; line-height: 1.65; max-width: 720px; margin-bottom: 1.6rem; }
.cta-row { display: flex; gap: 1rem; flex-wrap: wrap; margin: 1.6rem 0; }
"""


def apply_style(home: bool = False) -> None:
    """Inject the shared CSS into the current page."""
    import streamlit as st
    st.markdown(CSS_HOME if home else CSS, unsafe_allow_html=True)
