# Gap Analyzer: Deterministic Skill Gap Ranking

## Core Algorithm: Opportunity Cost

The Gap Analyzer ranks skill gaps by **opportunity cost** — a deterministic metric that weights skill gaps by the value of opportunities they block.

### Formula

```
opportunity_cost = sum(fit_score / 100 for each listing where skill is missing)
```

### Example

```
Listing A: requires kubernetes, fit_score 85
Listing B: requires kubernetes, fit_score 72
Listing C: requires kubernetes, fit_score 40

opportunity_cost = (85/100) + (72/100) + (40/100) = 1.97
```

**Why this metric?** Per rule 24:
- A skill gap in a 85-score listing (strong opportunity) is worth ~2x a gap in a 40-score listing (weak opportunity)
- Ranking by raw frequency alone wrongly prioritizes skills from low-fit jobs
- Weighted by score, we learn *which* skills matter most to the *best* opportunities

### Supplementary Statistics

For each gap, the Gap Analyzer also computes:

- **listings_blocked**: Count of listings requiring this skill that you don't have (sample size per rule 27)
- **mean_score**: Average fit score of those listings
- **example_ids**: Top 5 listing IDs (highest score first) for drilling down (rule 26)
- **nice_to_have_count**: Tracked separately, never mixed with required count

### Confidence Flagging (Rule 27)

```
listings_blocked < 3  → "LOW CONFIDENCE" ⚠
listings_blocked 3-5  → "PROVISIONAL"
listings_blocked >= 6 → "RELIABLE"
```

## Skill Canonicalisation (Rule 23)

Before gap analysis, all required_skills are canonicalised via explicit alias map in config.yaml:

```python
# Input: raw_skill from listing extraction
canonical_skill = canonical(raw_skill, config.skill_aliases)

# Example:
canonical("k8s", aliases) → "kubernetes"
canonical("postgres", aliases) → "postgresql"
canonical("ML", aliases) → "machine learning"
```

This ensures:
- Same skill under different names (k8s, kubernetes) counts as one gap
- User controls all mappings (no auto-merge by string similarity)
- Fully auditable via `python -m edgedash.skills --audit`

## Timestamped Snapshots (Rule 25)

Every gap analysis run:
1. Generates a unique `run_id`
2. Writes timestamped rows to `gap_snapshots` table
3. Never overwrites previous runs

This creates an audit trail for trend analysis over time.

## Full Traceability (Rule 26)

Each gap report includes up to 5 specific listing IDs, allowing you to:

```
Gap: kubernetes (opportunity_cost 24.1, 31 listings)
  example_ids: [listing_a, listing_b, listing_c, listing_d, listing_e]
  
→ Click listing_a → see full job details + why it scored 85
→ Search "kubernetes" in job description
```

No number in the report exists that you can't drill into.

## CLI Usage

### View Latest Gaps

```bash
python -m edgedash.gaps
```

Terminal table output:

```
==== SKILL GAPS ========================================
SKILL              BLOCKED    OPPORTUNITY    MEAN SCORE
kubernetes         31         24.1 ████████   72.5     RELIABLE
docker             28         19.2 ███████    68.3     RELIABLE
terraform          15         12.8 █████      85.4     PROVISIONAL
postgresql         8          6.2  ██          77.5     LOW CONFIDENCE ⚠
...
```

### Audit Skills

```bash
python -m edgedash.skills --audit
```

Shows top 40 most common raw skills + singletons (typos/junk), helps you spot missing aliases in config.yaml.

## Architecture

### Run Path

```
1. Scorer runs: extracts required_skills for each listing, computes fit_score
2. GapAnalyzer runs: reads scored listings, canonicalises skills, computes gaps
3. Gap snapshots written to DB (timestamped, never overwrite)
4. CLI queries latest snapshot, formats as table
```

### Data Flow

```
Job listing description
  ↓ [Extractor]
  → required_skills: ["k8s", "postgres", ...]
  ↓ [Scorer]
  → fit_score: 85
  ↓ [GapAnalyzer]
  → canonicalise each skill
  → check against config.my_skills
  → accumulate opportunity_cost
  ↓ [Storage]
  → gap_snapshots table
  ↓ [CLI]
  → Terminal table with ranks, confidence, example IDs
```

## Key Decisions

| Decision | Why |
|----------|-----|
| Deterministic, no LLM | All aggregates must be reproducible and auditable (rule 22) |
| Explicit alias map | User owns canonicalisation, no auto-merge (rule 23) |
| Weighted by fit score | Prioritizes gaps from better opportunities (rule 24) |
| Timestamped snapshots | Trend over time is first-class output (rule 25) |
| Example listing IDs | Every number must be drillable (rule 26) |
| Sample size reported | Low-confidence gaps flagged (rule 27) |

## Integration

Gap Analyzer is registered in the agent registry and runs after Scorer in the cycle:

```python
AGENT_REGISTRY = {
    "fetcher": None,      # Dynamically chosen
    "scorer": Scorer,     # Extracts facts, scores listings
    "gap_analyzer": GapAnalyzer,  # Analyzes gaps from scored listings
}

# Run sequence in orchestrator:
# 1. Fetch listings
# 2. Score listings
# 3. Analyze gaps
# 4. Log cycle
```

## Testing

9 tests in `tests/test_gap_analyzer.py` cover:
- Single/multiple listings
- Opportunity cost aggregation
- Skill canonicalisation
- Nice-to-have tracking
- Top example IDs sorting
- Edge cases (missing extracted data)
- End-to-end run flow

All tests pass.
