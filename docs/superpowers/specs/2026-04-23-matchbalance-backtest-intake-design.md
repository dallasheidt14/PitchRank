# MatchBalance by PitchRank — Backtest Intake Design

**Status**: Design approved, ready for implementation planning
**Owner**: Dallas Heidt + Claude Code
**Date**: 2026-04-23
**Branch**: `codex/tournament-seeding-beta`
**Scope**: Backtesting completed tournaments (prospective seeding is future work)
**Target outcome**: Go from "copy-paste UUIDs from gotsport into CSVs" to "paste event URL → triage gaps in a dashboard → click Run → get a Report Card"

---

## 1. Summary

MatchBalance is PitchRank's tournament-seeding product. This design covers its first phase: an intake dashboard that ingests completed tournaments, resolves every team against the PitchRank database, lets the user triage gaps, captures tournament structure, and produces a Report Card comparing the actual event to what MatchBalance would have seeded.

The engine pieces (scraper, team matcher, seeding optimizer, schedule simulator, backtest pipeline) already exist on the `codex/tournament-seeding-beta` branch. The missing layer is orchestration: a Streamlit sibling app (`tournament_intake.py`) that ties them into a single workflow and replaces the CSV-and-CLI grind that cost hours per tournament on Phoenix Cup 2026.

Commercial goal: the Report Card is the proof-of-value artifact. When MatchBalance goes to tournament directors, this is what closes a sale.

---

## 2. Goals and non-goals

**Goals**
- One dashboard page, paste URL or resume, see all cohorts, triage teams, enter tournament structure, run backtest, see Report Card.
- Per-cohort readiness and per-cohort runs — ship U14 Boys while U10 Boys is still blocked.
- Registry CSV stays the source of truth; dashboard reads and writes the same files the existing CLI consumes.
- Design shapes (not implementations) account for prospective seeding, multi-provider scraping, mixed-gender events, multi-scenario comparison, year-over-year trend, and exportable/shareable reports.

**Non-goals (for this phase)**
- Prospective seeding implementation (design-compatible, not built)
- Eligibility / sanctioning / roster validation (per deep-research scope)
- Venue / referee / medical-coverage scheduling
- Live day-two re-balance during tournaments
- Multi-user auth, customer-facing branding, shareable URLs
- PDF export (HTML-first; PDF deferred)
- Any provider other than gotsport (abstraction in place, impl stays single)

---

## 3. Users and modes

**Current user**: Dallas (single operator, internal use). Tournament directors become users later, at which point the UI re-platforms to Next.js. Until then, Streamlit is the right stack — same language as every engine, zero plumbing tax, fast iteration.

**Modes** (stored in event metadata, hardcoded to `backtest` today):
- `backtest` — completed events. Divisions come from scrape; we compare actual vs optimized.
- `seeding` — upcoming events, future work. Divisions user-defined; optimizer proposes placements.

The UI supports both shapes in the same layout; the mode flag gates features (games-coverage check, "actual vs" side of the Report Card, etc.) without requiring separate pages.

---

## 4. Architecture and data flow

```
[1] Event URL (gotsport, future: playmetrics, ...)
      ↓
[2] ProviderScraper           ← FIX FIRST: current gotsport scraper broken
      ↓                          returns cohorts + teams + canonical IDs
[3] EventTeamMatcher          ← existing, works: scored candidates per team
      ↓
[4] Dashboard triage UI       ← NEW: resolve gaps, mark externals, add teams
      ↓
[5] Structure inputs          ← NEW: per-division name/teams/pools/format
      ↓
[6] event_team_registry.csv + group_structure.csv + event_metadata.json
      ↓
[7] backtest_tournament_event.py → seeding_optimizer → schedule_simulator
      ↓
[8] Report Card (HTML) + exports
```

Only steps 2 (fix), 4 (new), and 5 (new) involve new code. Steps 3, 6, 7 already exist.

---

## 5. Dashboard layout

Single Streamlit page, `tournament_intake.py`, top-to-bottom scroll, no tabs.

**Top — Intake section (labeled)**
Three side-by-side controls: scrape new URL, resume existing event (dropdown of `reports/<event>/`), mode toggle (backtest today, seeding later). Below them, a compact event banner appears once loaded, with counts, snapshot/model metadata behind an "⚙ run details" disclosure.

**Cohort summary strip**
One compact card per `(age_group, gender)` cohort. Shows team count, status tint (green / amber / red), short status note ("ready" / "2 review" / "games gap" / "mostly ext"). Totals row underneath: Boys / Girls counts, cohorts ready to run, play-up percentage. Click a card to expand/collapse that cohort.

**Expanded cohort — split view**
- Cohort header: name, team count, division count, play-up count, status dots for Teams and Games, "Run backtest" button (disabled when not ready).
- **Left pane** — Division setup, fully editable. One card per division with: Name, Teams, Pools, Pool-play games, Knockout format, ✕ Remove. "+ Add division" button above the list. Inside each division card, team rows with ● status colors (green / amber / red), inline actions (review / fix / edit), and "+ Add team manually" at the bottom.
- **Right pane** — Power ranking, same cohort, all teams sorted by `power_score` descending. Toggle between **Grouped** (respects current division assignments, with dashed cut line between divisions) and **Flat** (pure sort, lets misplacements pop visually). Externals show with ★ and their assumed median score. ⚠ markers on placeholder matches.

**Four team-row states** (not three):
- ✓ resolved (direct_provider_id / strict_exact / high_confidence)
- ⚠ fuzzy candidates (requires review modal)
- ⚠ matched-to-placeholder (separate from ✓ because placeholder matches silently simulate badly)
- ✗ unresolved / external

Full mockups saved at `.superpowers/brainstorm/11406-1776984436/content/layout-v4.html` and `report-card.html`.

---

## 6. Scraper debug + provider abstraction

The gotsport event scraper (`src/scrapers/gotsport_event.py`) already has the right shape — `extract_event_teams_by_bracket` + `_resolve_api_team_id_from_event_page` targets the "View rankings" canonical-ID flow. It failed on Phoenix Cup 2026 for unknown reasons, forcing Dallas to collect canonical IDs by hand.

**Phase A — diagnose** (step 0 of implementation): run `scripts/scrape_specific_event.py 45224` with verbose logging. Compare to ground-truth UUID list Dallas manually collected. Failure modes in order of likelihood:
1. Anti-bot / User-Agent check
2. HTML structure drift on event schedule pages
3. JS-rendered content that BeautifulSoup can't see (fallback: Playwright via the existing MCP server)
4. Rate limiting (429s)
5. Rankings URL pattern change

Fix scope derives from findings. The dashboard's "+ Add team manually" path is the safety net if scraping degrades for any reason.

**Phase B — fix scope**
- Restore `extract_event_teams_by_bracket` and `_resolve_api_team_id_from_event_page` to produce correct output for gotsport event URLs
- Target: ≥95% canonical-ID resolution for non-external teams

**Phase C — additions alongside the fix**

*Provider abstraction* (design fold-in from round 2):
```python
# src/scrapers/provider.py
class ProviderScraper(Protocol):
    provider_code: str
    def fetch_event_metadata(self, event_url: str) -> EventMetadata: ...
    def fetch_teams_by_cohort(self, event_url: str) -> dict[CohortKey, list[EventTeam]]: ...
    def resolve_canonical_team_id(self, event_team: EventTeam) -> str | None: ...
```
Gotsport becomes the first impl. A factory picks the right implementation by URL pattern.

*Scrape resumability* (round 3 fold-in): incremental `raw_scrape.jsonl`, restart skips already-resolved teams.

*Rate-limit backoff*: exponential, on 429/5xx.

*Team alias cache* (round 3 fold-in): `(provider, provider_team_id) → team_id_master` append-only CSV. First resolution wins. Reused across events.

**Phase D — verification**
1. Phoenix Cup 2026 produces clean `raw_scrape.jsonl`
2. ≥95% canonical resolution for non-external teams
3. Re-run skips already-resolved teams unless `--force`
4. Sanity check on a second small gotsport event

---

## 7. Structure inputs data model

**Per-division fields** (all editable after scrape):

| Field | Type | Default | Validation |
|---|---|---|---|
| `division_name` | str | from scrape | unique within cohort |
| `team_count` | int | from scrape | ≥ assigned teams |
| `pool_count` | int | from scrape | `1..team_count` |
| `pool_play_games` | int | `pool_size − 1` | `0..10` |
| `knockout_format` | enum | inferred | see template list |
| `pool_sizes` | list[int] | auto-derived | sum = `team_count`; manually editable for uneven splits |

**Knockout format templates**:
- `SF_F_3P`, `SF_F`, `QF_SF_F`, `QF_SF_F_3P`, `F_ONLY`, `CROSSOVER_F`, `ROUND_ROBIN`, `CUSTOM` (free-form editor: `stage,from_rule_a,from_rule_b` rows)
- New templates added as real tournaments surface them

**Per-cohort seeding constraints** (collapsed panel at bottom of expanded cohort):

| Constraint | Default | Scope |
|---|---|---|
| `avoid_same_club_early` | on | pool play + first KO round |
| `avoid_same_coach_early` | on | same scope; null-safe if no coach data |
| `avoid_same_state_pool` | off | pool play |
| `rematch_avoidance_scope` | `same_event` | enum: same_event / same_season / prior_weekend |

Optimizer signature takes `constraints: list[Constraint]` from day one. Initial impls: `SameClubEarlyAvoidance`, `SameCoachEarlyAvoidance`.

**Event-level advanced settings** (behind "⚙ Advanced" disclosure):

| Setting | Default | Purpose |
|---|---|---|
| `model_version_pin` | `poisson_draw_gate_v1` | reproducibility |
| `ranking_snapshot_date` | `"latest"` | or specific date |
| `simulation_runs` | 100 | confidence bands |
| `capped_gd_limit` | 3 | capped-GD metric |
| `scenario_name` | `"default"` | for multi-scenario |
| `series_id` | auto-slug | year-over-year linking |
| `balance_score_weights` | preset `"default"` | Balance Score composition |

**Validation (blocker severity)**:
- `sum(division.team_count) ≠ cohort.team_count`
- `pool_count > team_count`
- `sum(pool_sizes) ≠ team_count`
- `pool_play_games > pool_size − 1`
- Knockout format requires N qualifiers, pool structure produces M ≠ N
- Any team ✗ without external annotation
- Games coverage < 100% (mode=backtest only)

---

## 8. Storage model

Files live under `reports/<event_slug>/`:

```
reports/<event_slug>/
  scenarios/
    default/
      event_metadata.json             # event-level settings, series_id, mode
      group_structure.csv             # per-division structure, schema_version=1
      event_team_registry.csv         # per-team registry, schema_version=1
      constraints.json                # per-cohort seeding constraints
      raw_scrape.jsonl                # incremental scraper output
      runs/
        <run_id>/
          optimization_run.json       # weights, relaxations, metrics
          standings_actual.csv
          standings_optimized.csv
          comparison.json             # Report Card data
          risk_flags.json
          overrides.jsonl             # manual override audit log
          progress.jsonl              # streamed during run
```

Branching a scenario copies the `scenarios/<name>/` directory to a new name (`scenarios/alternate_3_divisions/`). Scenarios share scrape output but can diverge on structure, constraints, and weights.

All CSVs and JSON files carry a `schema_version` field. Loader migrates older versions forward.

---

## 9. Run flow and Report Card

### Run flow (per-cohort click)

1. Pre-flight validation (all blockers above)
2. Fire run in subprocess, not the Streamlit process — UI stays responsive
3. Progress streams to `progress.jsonl`, rendered in-dashboard via `st.status`
4. Progress phases:
   - Loading teams and games
   - Running seeding optimizer
   - Simulating optimized bracket (N of 100 runs)
   - Computing Report Card metrics
5. On completion, Report Card HTML rendered inline below the cohort
6. On error, stack + message inline; no partial-success state

### Report Card structure

Hero: **Balance Score** composite (0–100), side-by-side actual vs optimized, with 80% CI subtitle from Monte Carlo sims (round 3 fold-in #5). Initial formula (weights in `event_metadata.balance_score_weights`, default preset): `50 * one_goal_rate + 30 * (1 - blowout_5plus_rate) + 10 * (1 - same_club_early_rate) + 10 * (1 - rematch_rate)`. Tunable per ruleset; formula versioned via `balance_score_weights.preset_id`.

Auto-generated **"Why MatchBalance beats the status quo"** bullets (round 4 fold-in #4) — templated from biggest metric deltas. 3–5 plain-language reasons.

**Side-by-side metrics table**:
- Expected avg GD (raw)
- Expected avg GD (capped at `capped_gd_limit`, default 3) ← round 4 fold-in #1
- One-goal game rate
- 3+ goal blowout rate
- 5+ goal blowout rate
- Same-club early meetings count ← round 4 fold-in #2
- Same-coach early meetings count
- Intra-event rematches count ← round 4 fold-in #3

Δ column color-coded for improvement.

**Risk flags** (amber block, not buried): low strength confidence, externals in ranking, stale snapshot, low-games teams, placeholder matches. Honesty builds trust.

**Team movements**: plain list of Super Elite ⇄ Super Pro moves and within-pool moves. "View full brackets" link to a separate page.

**Override audit log**: collapsed by default. Each manual override logs `{ts, actor, type, before, after, reason, delta_balance_score}`.

### Exports

- CSV — flat metrics table
- JSON — full Report Card structure
- HTML — standalone, self-contained, shareable
- PDF — deferred; HTML → PDF is cheap when needed

### Report library (round 2 fold-in #6)

```
src/tournaments/reports/
  schema.py           # dataclasses: ReportCard, Metric, RiskFlag, etc.
  compute.py          # build ReportCard from run results
  render_html.py      # Jinja → HTML
  render_csv.py       # flatten to comparison.csv
  templates/
    report_card.html
```

Streamlit embeds the HTML output — does no rendering logic itself. Same HTML whether rendered in-app, exported standalone, or eventually served by a web route. Next.js migration later reuses `compute.py` + `render_html.py` directly.

### Multi-scenario comparison (round 2 fold-in #4)

Scenarios dropdown on cohort header. "Compare scenarios" button opens 3-column metrics table. Each scenario is an independent run; comparison is pure rendering.

### Year-over-year (round 3 fold-in #4, data-only for now)

`series_id` field on event metadata links Phoenix Cup 2025/2026/2027. UI panel for series trend is a later visual; data model enables it from day one.

---

## 10. The 28 design decisions (fold-ins)

All baked into the design above. Grouped by the round in which they surfaced during brainstorming.

**Round 1 — from first-pass red-team review**
1. Games-coverage gate separate from team resolution
2. External team strength via median-of-seed-group (default) + manual override (opt-in)
3. Placeholder-match detection as distinct status
4. Load-existing event from `reports/<event>/` (resume, not rescrape-overwrite)
5. Per-cohort readiness and run (not event-wide)
6. Run metadata (model, snapshot, weights, registry version) per run
7. Report shape designed intentionally, not ad hoc

**Round 2 — forward-looking fold-ins**
8. Multi-provider scraper abstraction
9. Mixed-gender events (cohort keyed on `(age, gender)`)
10. Seeding-constraints hook on the optimizer
11. Multi-scenario comparison (directory-per-scenario)
12. Model-version pinning per run
13. Report library as a reusable module
14. Overrides survive rescrape (merge semantics, not overwrite)

**Round 3 — deeper future-proofing**
15. Forfeit / cancelled / rescheduled policy via `result_type` field
16. Schema version on every CSV / JSON
17. Scrape resumability with `raw_scrape.jsonl` + backoff
18. `series_id` for year-over-year
19. Confidence bands via Monte Carlo sim reruns
20. Team-alias cache keyed on `(provider, provider_team_id) → team_id_master`
21. Rankings-snapshot-freshness warning

**Round 4 — from MatchBalance deep-research report**
22. Capped goal differential metric alongside raw
23. Same-club / same-coach early-meetings metric
24. Intra-event rematch count
25. Plain-language "Top reasons for recommendation"
26. Composite Balance Score headline
27. Risk flags as first-class field in run output
28. Override audit with before/after metrics

---

## 11. What is explicitly NOT in scope

Deferred, retrofittable without design pain when the time comes:
- Eligibility / sanctioning / passcard / roster validation layer
- Venue / field / referee / medical coverage scheduling
- Ruleset versioning library (national / state / local overlays)
- Live day-two re-balance during tournaments
- Format recommendation engine (prospective seeding)
- Anti-discrimination governance on placement features
- Undo / redo, bulk multi-select actions, keyboard shortcuts
- Consolation / promotion-relegation bracket formats
- Per-team narrative impact ("Team X would have gone 2-1 instead of 0-3")
- PDF export
- Multi-user auth, per-org data isolation, shareable read-only URLs

---

## 12. Open questions and risks

**Risks**
- **Scraper fix effort is unknown until Phase A diagnosis.** Could be one hour (UA spoof + selector update) or half a day (Playwright switch). Plan absorbs either.
- **If gotsport requires authentication** for the team-detail pages, the trade-off is: maintain login credentials (TOS risk) vs. accept that some teams always need manual UUID entry. The dashboard's manual-entry path is the safety net.
- **External team strength assumption (median-of-seed-group) is a heuristic.** U19, which is mostly externals in Phoenix Cup 2026, may surface its weakness. Fix path: the (c) manual-strength option is available per team.
- **Monte Carlo with 100 sim runs × 8 cohorts × N divisions may be slow.** Budget for runtime characterization during Phase A.

**Open questions**
- Does the gotsport schedule page require a cookie/session even without login? Determined in Phase A.
- What exact set of knockout templates covers the bulk of the tournaments Dallas wants to backtest next? Answered by running v1 against ~5 events.
- When constraints relax (e.g., same-club avoidance is impossible in a 6-club cohort), what's the user-visible policy? Default: silent relaxation with a risk flag. Escalate to explicit if it causes confusion.

---

## 13. Implementation readiness

This design is complete enough to hand off to `/superpowers:writing-plans` for a step-by-step implementation plan. Implementation ordering at a high level:

1. **Scraper diagnosis (Phase A)** — blocks nothing downstream; might be quick or reshape everything
2. **Provider abstraction + scraper fixes + resumability** — library-level work
3. **Structure data model + schema versioning** — library-level work
4. **Streamlit page: intake + cohort summary + expanded cohort layout**
5. **Triage UI: review modal, fix modal, external edit drawer, manual team add**
6. **Structure input forms** (already data-modelled; UI wiring)
7. **Run subprocess + progress streaming**
8. **Report library: compute + render_html + Jinja template**
9. **Report Card embedded in dashboard**
10. **Export buttons (CSV, JSON, HTML)**
11. **Multi-scenario branch UI (thin; directory structure already supports it)**

The writing-plans skill will turn this into sequenced, testable steps.
