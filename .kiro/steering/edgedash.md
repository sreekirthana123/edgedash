# EdgeDash Steering

## Project Overview

**EdgeDash** is an autonomous AI career intelligence agent. It runs as a scheduled loop that:

1. Fetches live job listings
2. Scores them for fit against the user's profile
3. Surfaces skill gaps
4. Verifies its own output
5. Publishes a Streamlit dashboard

## Architecture (Do Not Deviate Without Explicit Approval)

```
Trigger (scheduled) 
  → Orchestrator 
    → sub-agents (Fetcher, Scorer, GapAnalyzer) 
      → Verifier 
        → Storage 
          → Dashboard (read-only)
```

### Architecture Rules

- **Orchestrator**: Reads state and delegates. It **never** fetches or scores directly.
- **Sub-agents**: Each has exactly one goal and one stop condition.
- **Verifier**: Validates output before storage.
- **Storage**: Persists cycle logs and results.
- **Dashboard**: Read-only consumer of storage.

## Hard Rules

### 1. Configuration Management
- Python 3.11+ keywords and skills profile configuration.
- **Everything user-specific lives in config**, not code.
- Config format: clearly documented (e.g., YAML, JSON, or Python dataclass).

### 2. Secrets & Environment Variables
- **No secrets in code. Ever.**
- All sensitive data (API keys, credentials, connection strings) loaded from environment variables only.
- Load environment variables in **exactly one place** in the codebase.
- Use a dedicated config or bootstrap module for this.

### 3. Cycle Logging (Mandatory)
Every agent run writes a row to `cycle_log` table with:
- What ran (agent name)
- When (timestamp)
- How many records touched (count)
- Pass/fail status
- Any retry reason (if applicable)

### 4. Error Handling
- **Fail loudly. No bare `except: pass`.**
- If something is wrong, the error must be visible and loggable.
- Expected exceptions should be caught specifically and logged with context.
- Use structured logging for all errors.

### 5. Type Hints & Documentation
- **Type hints on every function signature.** No exceptions.
- Docstrings only where intent is not obvious from the function name.
- Keep docstrings concise (1-2 lines preferred).

### 6. File Size Constraint
- **Keep files under ~150 lines.**
- Split modules before that limit becomes a problem.
- Aim for focused, single-responsibility modules.

## Style Guidelines

### Code Quality
- Small, testable functions.
- Plain readable Python over clever Python.
- Favor clarity and maintainability.

### Scope & Scaffolding
- When asked for one module, build one module.
- **Do not scaffold the whole app** unless explicitly requested.
- Implement exactly what is asked for, no premature abstractions.

### Naming & Structure
- Use clear, descriptive names for functions, variables, and modules.
- Follow PEP 8 conventions.
- Group related functions into focused modules.

## Implementation Notes

### Python Version
- Target Python 3.11+ for modern syntax and features.
- Use type hints extensively (supported natively in 3.11+).

### Testing
- Write tests alongside modules.
- Keep test coverage for critical paths.
- Use standard testing frameworks (pytest recommended).

### Logging & Observability
- Structured logging for all significant operations.
- Cycle log is the source of truth for agent run history.
- Include relevant context in log entries (user ID, job ID, score, etc.).

## Network & Sources

### 9. Source Abstraction
- Every external source lives behind a `Source` class with a uniform interface.
- The Fetcher never contains source-specific parsing.
- Adding a new source must never require editing the Fetcher.

### 10. Normalized Output
- Every Source returns a list of normalized dicts with EXACTLY these keys:
  - `source`, `external_id`, `title`, `company`, `location`, `url`, `description`, `posted_at`, `raw`
- Missing values are `None`, never empty string, never `"N/A"`.

### 11. Network Helper
- All network calls go through one centralized helper with:
  - Timeout: 10 seconds (default, overridable per-call)
  - Explicit retry: 2 attempts with exponential backoff
  - User-Agent header: Real, descriptive user agent
- No bare `requests` calls anywhere else in the codebase.

### 12. Source Failure Isolation
- A source failing must NEVER kill the cycle.
- Catch exceptions per-source, log the failure to `cycle_log` with status `"failed"`, continue to next source.
- One dead job board must not stop other sources.

### 13. Secrets from Environment
- Secrets come from environment variables via a `.env` file (gitignored).
- Never a literal key in code, never a key in `config.yaml`.
- If a required key is missing, that source skips itself with a clear log line — it does not crash the cycle.

### 14. Respect the Source
- Rate limit to at most 1 request per second per source.
- Set a real, descriptive User-Agent header.
- Honor any documented page limits, pagination, or API rate limits.
- Log rate-limit headers and backoff delays when respected.

## Intelligence & Scoring

### 15. LLM Centralization
- All LLM calls go through one module: `edgedash/llm.py`, exposing one function.
- Provider and model name come from config, never hardcoded.
- Rate limit to stay inside a free tier: default 1 request per second, max 15 per minute.
- No other file imports an LLM SDK.

### 16. Structured Extraction, Deterministic Scoring
- Never ask a model for a final score, ranking, or numeric rating.
- The model extracts structured facts only.
- All scoring arithmetic is deterministic Python in ONE function.
- The model never sees the scoring weights.

### 17. Response Validation & Repair
- Every model response is validated against an explicit schema before use.
- A response that fails validation is retried once, then logged as a failure for THAT listing only.
- Failures must not crash the cycle or stop remaining listings.
- Never `json.loads` raw model text without a validation and repair path.

### 18. Idempotent Scoring
- Never re-score a listing that already has a score.
- Select only listings WHERE `fit_score IS NULL`.
- Cache extraction results keyed on a hash of the job description.
- The same text is never sent to the model twice.

### 19. Human-Readable Reasons
- Every score carries a human-readable reason GENERATED FROM THE SCORE COMPONENTS by our code.
- Never free text written by the model.
- Reasons must be deterministic and reproducible from score components.

### 20. Score Distribution Logging
- Log the score distribution (count, min, max, mean, spread) to `cycle_log` on every scoring run.
- A run where all scores fall within 10 points is suspect and must be flagged as such.
- Include distribution analysis in cycle notes.

### 21. Batch Size Cap
- Cap listings scored per cycle at a configurable batch size (default 25).
- A cost or rate-limit blowup is structurally impossible.
- If more than batch size unscored listings exist, process exactly batch size and continue next cycle.

## Aggregate Analysis

### 22. Deterministic Aggregates Only
- Aggregate analysis is deterministic SQL and Python. No exceptions.
- No LLM call may produce, adjust, or rank an aggregate number.
- A model may only SUGGEST canonical groupings for a human to approve.
- All numbers in reports must be traceable to deterministic computation.

### 23. Explicit Skill Canonicalization
- Skill names are canonicalised through an explicit alias map in `config.yaml`.
- The user owns and can read this map — it is not hidden or auto-generated.
- Never auto-merge skill names by model judgement or string similarity alone.
- All skill merging is explicit and auditable.

### 24. Weighted Gap Ranking
- Gap ranking is weighted by the fit score of the listing the gap came from.
- A gap in a listing scored 20 is worth far less than a gap in a listing scored 85.
- Never rank gaps by raw frequency alone.
- Weight formula: gap priority = gap_frequency × average_score_of_listings_with_gap.

### 25. Timestamped Snapshots
- Every gap report run writes a timestamped SNAPSHOT.
- Never overwrite the previous report.
- Trend over time is a first-class output, not an afterthought.
- Archive historical snapshots for trend analysis.

### 26. Full Traceability
- Every aggregate number must be traceable to the rows that produced it.
- Any reported gap must be able to list the specific listing IDs it was computed from.
- No number appears in the dashboard that cannot be drilled into.
- Maintain audit trail: gap → listings → scores → extraction facts.

### 27. Sample Size Reporting
- Report the sample size alongside every aggregate.
- A gap computed from 3 listings and a gap computed from 90 listings must never be presented as equally reliable.
- Display confidence indicators (e.g., "gap: kubernetes (5 listings, avg score 72)").
- Highlight low-sample gaps as provisional or uncertain.

## Orchestration

### 28. The Orchestrator reads system state and decides which agents to run.
- It never runs a fixed sequence.
- Skipping an agent because there is no work for it is a SUCCESSFUL outcome, not a failure.

### 29. Every delegation carries an explicit goal and an explicit stop condition.
- Max items, max duration — set by the Orchestrator.
- A sub-agent never decides its own limits — the Orchestrator sets them.

### 30. The Orchestrator never does an agent's work.
- It reads state, delegates, collects results, logs.
- No fetching, scoring, or analysis logic in the Orchestrator.

### 31. The Orchestrator prints and logs its PLAN before executing it.
- Which agents will run, which are skipped, and the state value that caused each decision.

### 32. One sub-agent failing does not stop the cycle.
- Log the failure, continue with the remaining plan, and mark the cycle partial.

### 33. Every cycle writes exactly one summary row.
- What ran, what was skipped, why, duration per agent, and the outcome.

## VERIFICATION

34. The Verifier judges output plausibility and NEVER repairs, rewrites,
or adjusts data. It returns a verdict and a reason. The Orchestrator
decides what to do about a failure.
35. Verification checks plausibility, never correctness. There is no
ground truth for a fit score. Checks assert properties of the output
distribution and shape, not the accuracy of any single value.
36. A failed verification triggers at most ONE retry of the failing agent
with adjusted context. After that the cycle is marked "degraded" and
stops. Never retry in an unbounded loop.
37. Every verdict is logged to cycle_log with the check that failed and
the observed value that failed it — never just "failed".
38. Only cycles with a passing verdict may be read by the dashboard. A
failed cycle must never overwrite the last known-good data. Stale
verified data always beats fresh unverified data.
39. Verification thresholds live in config.yaml, not in code, and every
threshold has a comment saying what failure it is designed to catch.

## NATURAL LANGUAGE QUERIES

40. NEVER generate SQL from a model. No text-to-SQL, ever, in any form.
  The model selects from a fixed registry of parameterised query
  functions that I wrote. It never composes a query.
41. Every query tool is read-only, parameterised, and takes typed
  parameters that are validated and clamped to a safe range before
  execution. A model-supplied parameter is untrusted input.
42. The model appears exactly twice per question: once to ROUTE (pick a
  tool and its parameters) and once to PHRASE (turn returned rows into
  prose). It never touches the database in either call.
43. The phrasing call may use ONLY the numbers present in the rows it was
  given. It must not estimate, extrapolate, add outside context, or
  infer a value that is not in the data. If the rows are empty it must
  say so plainly.
44. Every answer displays the underlying rows alongside it. No prose
  answer appears without the data that produced it.
45. If no tool matches the question, say so and list what CAN be asked.
  Never guess at the closest tool and never answer from general
  knowledge.
46. Query tools read from the last passing cycle only, per rule 38.

## DEPLOYMENT

47. Never rely on the local filesystem for anything that must survive a
  restart. Hosting filesystems are ephemeral. All persistent state is in
  the hosted database.
48. Every secret comes from an environment variable read in one place.
  No secret is ever committed, printed, logged, or shown in an error
  message or traceback.
49. The scheduled job and the dashboard are separate processes that share
  only the database. The dashboard never runs a cycle; the scheduler
  never serves a page.
50. The deployed app must start and render even when the database is
  empty, unreachable, or mid-migration. It shows a clear status message
  instead of a stack trace. A stranger must never see a traceback.
51. The scheduled job is idempotent and safe to run twice. It must have a
  hard timeout and stay inside free-tier limits.

## When Deviating

If architecture changes, performance concerns, or design trade-offs require deviation from these rules, **explicitly discuss and get approval before implementing**.
