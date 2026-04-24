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
- **Monte Carlo confidence bands** — v1 runs a single deterministic simulation; confidence-band plumbing is data-model-ready but deferred
- **Constraint-aware optimizer** — `avoid_same_club_early` et al. are persisted and computed as post-run metrics, but the optimizer input signature is unchanged in v1
- **Multi-scenario comparison UI** — directory structure supports branching; the "compare scenarios" view is deferred
- **Year-over-year series history panel** — `series_id` is persisted; the UI rendering it is deferred
- **Extended knockout templates beyond the 4 simulator shapes** — `QF_SF_F`, `CROSSOVER_F`, `CUSTOM` are disabled in the v1 dropdown
- **Parallel alias cache** — MatchBalance reuses `team_alias_map` + `team_match_review_queue` rather than building its own

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
[1] Event URL (gotsport; future: playmetrics, ...)
      ↓
[2] ProviderScraper           ← must build: gotsport scraper fix + abstraction layer
      ↓                          returns cohorts + teams + canonical IDs
[3] EventTeamMatcher          ← exists: scored candidates per team (confirmed)
      ↓
[4] Dashboard triage UI       ← must build: resolve gaps, mark externals, add teams
      ↓
[5] Structure inputs          ← must build: per-division name/teams/pools/format
      ↓
[6] event_team_registry.csv + group_structure_summary.csv + event_metadata.json
      ↓
[7] backtest_tournament_event.py (existing CLI) → seeding_optimizer → schedule_simulator
      ↓
[8] Report library            ← must build: compute + render_html + render_csv
      ↓
[9] Report Card (HTML) + exports
```

### Existing vs must-build breakdown (verified against the codebase)

| Component | Status | Notes |
|---|---|---|
| `event_team_matcher.py` | **Exists** | Returns scored candidates; matcher API unchanged |
| `seeding_optimizer.py` | **Exists, no constraint API** | `DivisionSpec` = `{name, team_count, pool_sizes, advancement}`; `optimize_tournament_format()` takes no `constraints` parameter today |
| `schedule_simulator.py` | **Exists, 4 playoff shapes only** | `infer_division_schedule_template()` supports: `none` (pool-only), `pool_winners_final` (2 pools + 1 extra), `cross_semis_final` (2 pools + 3), `cross_semis_final_third` (2 pools + 4), `one_pool_final` (1 pool + 1). Shape is INFERRED from `actual_game_count`, not chosen by the user |
| `backtest_tournament_event.py` | **Exists** | CLI args: `--event-name`, `--group-structure-csv`, `--event-team-registry-csv`, `--output-dir`, `--predictor-source`, `--point-in-time-model-artifact`, `--history-lookback-days`, `--snapshot-buffer-days`. Legacy output layout: `<output-dir>/{summary.json, cohorts/, requests/}` |
| `ProviderScraper` abstraction | **Must build** | New protocol; gotsport is first impl |
| Gotsport scraper fix | **Must build** (Phase A diagnose first) | Existing `_resolve_api_team_id_from_event_page` targets the right flow but failed on Phoenix Cup 2026 |
| Streamlit intake app `tournament_intake.py` | **Must build** | Triage + structure + run wiring |
| Run orchestration (state machine, locks, atomic writes) | **Must build** | Current writers have no atomicity or locking |
| Report library (`src/tournaments/reports/`) | **Must build** | `compute.py`, `render_html.py`, `render_csv.py`, Jinja templates |
| Risk-flags first-class field | **Must build** | New field on run output |
| `team_alias_map` / `team_match_review_queue` | **Exists** (PitchRank platform) | Canonical alias system; MatchBalance reuses, does not duplicate |
| Constraint-aware optimizer | **v2 — data-model only in v1** | `constraints` stored on scenario; not wired to `optimize_tournament_format()` until v2 |
| Monte Carlo confidence bands | **v2 — data-model only in v1** | v1 does a single deterministic run |
| Extended knockout templates (beyond the 4 simulator shapes) | **v2 — disabled in v1 dropdown** | `QF_SF_F`, `CROSSOVER_F`, `CUSTOM` selectable in UI but render as "coming in v2" |
| Multi-scenario comparison UI | **v2 — directory structure ready in v1** | Scenarios directory shape supports it; UI is deferred |
| Multi-provider implementations beyond gotsport | **v2 — abstraction ready in v1** | Provider protocol defined; only gotsport impl ships |

The v1 critical path is: steps 2 (scraper fix + abstraction), 4 (triage UI), 5 (structure UI), 8 (report library), and the run orchestration around step 7.

---

## 5. Dashboard layout

Single Streamlit page, `tournament_intake.py`, top-to-bottom scroll, no tabs.

**Top — Intake section (labeled)**
Three side-by-side controls: scrape new URL, resume existing event (dropdown of `reports/<event>/`), mode toggle (backtest today, seeding later). Below them, a compact event banner appears once loaded, with counts, snapshot/model metadata behind an "⚙ run details" disclosure.

**Cohort summary strip**
One compact card per `(age_group, gender)` cohort. Shows team count, status tint (green / amber / red), short status note ("ready" / "2 review" / "games gap" / "mostly ext"). Totals row underneath: Boys / Girls counts, cohorts ready to run, play-up percentage. Click a card to expand/collapse that cohort.

**Play-up percentage definition:** the percentage of teams in the cohort whose resolved team's canonical `age_group` is younger than the division's `age_group`. Example: a team with `teams.age_group = "u12"` playing in a `U14` division counts as playing up. Computed from the registry after all teams resolve.

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

**Phase A — diagnose** (step 0 of implementation): run `scripts/scrape_specific_event.py 45224` with verbose logging (set `LOG_LEVEL=DEBUG` env var, or add a `--verbose` flag to the script as part of Phase A since it doesn't exist today). Compare to ground-truth UUID list Dallas manually collected. Failure modes in order of likelihood:
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

*Scrape resumability* (round 3 fold-in): incremental `raw_scrape.jsonl` under `intake/`, restart skips already-resolved teams.

*Rate-limit backoff*: exponential, on 429/5xx.

*Alias persistence via existing platform primitives* (revised round 3 fold-in #20): **MatchBalance does not build a parallel alias cache.** Resolutions write directly to PitchRank's canonical `team_alias_map` table (fields: `provider_team_id`, `team_id_master`, `match_method ∈ {direct_id, fuzzy, manual}`, plus confidence and provenance metadata per CLAUDE.md:160-164). Uncertain matches (confidence 0.75–0.90) route to `team_match_review_queue` rather than being auto-applied. This avoids (a) the cache-poisoning risk of "first resolution wins" and (b) duplicating an already-canonical system.

### Event identity

**Primary event key:** `(provider_code, provider_event_id, season_year)`. Every intake record, scenario, and run ultimately keys back to this tuple.

Storage directory name: `event_key = f"{provider_code}__{provider_event_id}__{season_year}"` (e.g., `gotsport__45224__2026`).

`event_name` (the string games are tagged with in the `games` table) is kept as metadata in `intake/event_metadata.json`. Same-title events across seasons are distinguished by `season_year`; different providers with colliding IDs are distinguished by `provider_code`.

**Games import checkpoint:** before a cohort's "Games X/Y ✓" indicator can turn green, the pipeline explicitly verifies that games for this event are present in the `games` table tagged with the canonical `event_name`. If games are missing, the cohort blocks with a "games not yet imported" status, not "games coverage incomplete" (different remediation).

**Phase D — verification**
1. Phoenix Cup 2026 produces clean `raw_scrape.jsonl`
2. ≥95% canonical resolution for non-external teams
3. Re-run skips already-resolved teams unless `--force`
4. Sanity check on a second small gotsport event

---

## 7. Structure inputs data model

**Per-division fields** (all editable after scrape):

| Field | Type | Default | Validation | v1 status |
|---|---|---|---|---|
| `division_name` | str | from scrape | unique within cohort | Wired |
| `team_count` | int | from scrape | ≥ assigned teams | Wired |
| `pool_count` | int | from scrape | `1..team_count` | Wired |
| `pool_play_games` | int | `max(pool_sizes) − 1` | `0..min(pool_sizes) − 1` across all pools; see uneven-pools note | **Data-model only** (simulator currently infers schedule from `actual_game_count`) |
| `knockout_format` | enum | inferred from simulator | see template list | Wired for the 4 supported templates; v2 templates are data-model only |
| `pool_sizes` | list[int] | auto-derived | sum = `team_count`; manually editable for uneven splits | Wired |

**Uneven-pools note:** for divisions with non-uniform pool sizes (e.g., `[7, 6]`), default `pool_play_games = max(pool_sizes) - 1` and validate against `min(pool_sizes) - 1` (the largest a team in the smallest pool could play). User can override per-division; v2 extension may add per-pool game counts.

**Knockout format templates** (v1 shipped vs v2 deferred):

| Template | v1 status | Simulator mapping |
|---|---|---|
| `SF_F_3P` | **v1 active** | `cross_semis_final_third` (2 pools + 4 extra games) |
| `SF_F` | **v1 active** | `cross_semis_final` (2 pools + 3 extra games) |
| `F_ONLY` | **v1 active** | `pool_winners_final` (2 pools + 1 extra) OR `one_pool_final` (1 pool + 1 extra) |
| `ROUND_ROBIN` | **v1 active** | `none` (pool play only) |
| `QF_SF_F` | **v2 — disabled in v1 dropdown** | Requires simulator extension (4 pools + playoff chain) |
| `QF_SF_F_3P` | **v2 — disabled in v1 dropdown** | Requires simulator extension |
| `CROSSOVER_F` | **v2 — disabled in v1 dropdown** | Requires simulator extension |
| `CUSTOM` | **v2 — disabled in v1 dropdown** | Free-form editor `stage,from_rule_a,from_rule_b`; requires generic simulator |

v2 templates render as selectable-but-greyed with a "coming in v2" tooltip so the data model persists but the UI is honest about what runs today. The simulator currently infers template from `actual_game_count`; the intake UI exposes template as a user choice that validates against that inferred shape for v1.

**Per-cohort seeding constraints** (collapsed panel at bottom of expanded cohort):

| Constraint | Default | Scope | v1 status |
|---|---|---|---|
| `avoid_same_club_early` | on | pool play + first KO round | **Data-model only (v2 wires optimizer)** |
| `avoid_same_coach_early` | on | same scope; null-safe if no coach data | **Data-model only** |
| `avoid_same_state_pool` | off | pool play | **Data-model only** |
| `rematch_avoidance_scope` | `same_event` | enum: same_event / same_season / prior_weekend | **Data-model only** |

**v1 scope:** constraints are persisted to `constraints.json` on the scenario, and the *post-run* Report Card metrics (`same_club_early_meetings`, `same_coach_early_meetings`, `intra_event_rematches`) are computed from the optimizer output so the user can compare the actual tournament's constraint violations against the MatchBalance-proposed bracket. The optimizer does **not** yet take `constraints` as an input — that is a v2 extension ("optimizer contract extensions").

**v2 scope:** `optimize_tournament_format()` signature extended to accept `constraints: list[Constraint]`; initial impls `SameClubEarlyAvoidance`, `SameCoachEarlyAvoidance`.

**Event-level advanced settings** (behind "⚙ Advanced" disclosure):

| Setting | Default | Purpose | v1 status |
|---|---|---|---|
| `model_version_pin` | `poisson_draw_gate_v1` | reproducibility | Wired |
| `ranking_snapshot_date` | `event_start_date - 1 day` (explicit as-of) | avoid silent synthetic fallback | Wired; fallback surfaces as risk flag |
| `simulation_runs` | 1 | v1 single deterministic run | Data-model only (v2 enables > 1) |
| `capped_gd_limit` | 3 | capped-GD metric cap | Wired |
| `scenario_name` | `"default"` | for multi-scenario | Wired; branch UI deferred to v2 |
| `series_id` | `event_slug` on first event in series; user-set on subsequent | year-over-year linking | Wired as field; no series panel UI in v1 |
| `balance_score_weights` | preset `"default"` | Balance Score composition | Wired |

**`ranking_snapshot_date` policy:** default to event-date-derived as-of (typically `event_start_date - 1`). If `backtest_tournament_cohort.py` falls back to `future_snapshot_fallback` or `synthetic_snapshot_fallback` for any entrant (the existing fallback logic in `_resolve_prediction_snapshot` at `scripts/backtest_tournament_cohort.py:432`), **that fallback must be surfaced as a Report Card risk flag** with the team and fallback type. No silent fallback.

**`series_id` policy:** on the first event in a series, auto-populated as the event_slug. The user sets `series_id` explicitly on subsequent events to link them (no auto-slug stripping — deterministic only via user intent).

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

Files live under `reports/<event_key>/` where `event_key = f"{provider_code}__{provider_event_id}__{season_year}"` (primary identity; see Section 6 on event identity). An `event_slug` is a derived display value persisted inside `intake/event_metadata.json`, not used as a path component.

```
reports/<event_key>/
  intake/                               ← immutable scrape output, SHARED across scenarios
    raw_scrape.jsonl                    # incremental scraper output (resumable)
    event_metadata.json                 # (provider_code, provider_event_id, season_year),
                                        # event_name, event_slug, event_start_date,
                                        # scrape_ts, series_id
  scenarios/
    default/
      overrides.jsonl                   # intake-time manual overrides (scenario-level;
                                        # survives rescrape via merge on provider_team_id)
      group_structure_summary.csv       # per-division structure (preserves CLI filename)
      event_team_registry.csv           # per-team registry
      constraints.json                  # per-cohort seeding constraints (data-model only in v1)
      runs/
        <run_id>/                       # per-run outputs only
          optimization_run.json
          standings_actual.csv
          standings_optimized.csv
          comparison.json               # Report Card data
          risk_flags.json
          run_overrides_audit.jsonl     # per-run override deltas (distinct from scenario overrides)
          progress.jsonl                # streamed during run
          done.json                     # completion marker
```

### Rescrape semantics

Rescrape writes only to `intake/` — scenario files are untouched. After rescrape:
1. The new `raw_scrape.jsonl` is merged against `scenarios/<name>/overrides.jsonl` keyed on `provider_team_id`.
2. Teams that appeared in both the old and new scrape retain their scenario-level overrides.
3. Teams added by the new scrape enter the triage UI as new rows.
4. Teams that disappeared from the new scrape are surfaced in a risk flag ("team X was removed by rescrape; its override is now orphaned") but not auto-deleted.

### Scenario branching

Copying `scenarios/<src>/` to `scenarios/<dst>/` creates a new scenario with the same overrides, structure, constraints, and run history. The `intake/` directory is **not** copied — scenarios genuinely share the same scrape. Branches can diverge on structure, constraints, weights, and per-run outputs.

### CLI integration

The existing `backtest_tournament_event.py` CLI is **unchanged for v1.** The Streamlit layer translates between the new layout and the legacy CLI args:
- `--group-structure-csv` → `scenarios/<name>/group_structure_summary.csv`
- `--event-team-registry-csv` → `scenarios/<name>/event_team_registry.csv`
- `--event-name` → read from `intake/event_metadata.json` → `event_name`
- `--output-dir` → `scenarios/<name>/runs/<run_id>.tmp/` (staging, see Section 9 run safety)

After the CLI completes, Streamlit atomically renames the staging dir to `runs/<run_id>/`, writes `done.json`, and copies any CLI-side outputs into the expected shape for the report library.

### Schema versioning

Every CSV and JSON file carries a `schema_version: 1` field (stamp only). **Forward migration logic is deferred** until a v2 schema exists — no automatic migrations today. Loading a `schema_version` newer than the code supports raises an explicit error.

---

## 9. Run flow and Report Card

### Run flow (per-cohort click)

1. **Pre-flight validation** — all blockers above; abort before fork if any fail.
2. **Acquire per-scenario advisory lock** — file lock at `scenarios/<name>/.run.lock` (opened with `fcntl.flock` on POSIX, `msvcrt.locking` on Windows). If another run is active against the same scenario, show "scenario is already running; cancel it or wait" and stop.
3. **Create staging dir** `runs/<run_id>.tmp/` and transition state to `running`. `run_id = f"{timestamp}_{uuid4_short}"`.
4. **Fork subprocess** calling the existing `backtest_tournament_event.py` with translated args (Section 8). Streamlit's main process stays live.
5. **Stream progress**: `subprocess.Popen(..., stdout=PIPE, stderr=STDOUT, text=True, bufsize=1)` plus `iter(proc.stdout.readline, '')` feeds an `st.status(...)` block in the Streamlit thread. The subprocess writes structured progress lines (`PHASE: loading-games`, `PHASE: simulating`, `PROGRESS: 45%`) which the reader parses for phase + pct. Also mirrors to `runs/<run_id>.tmp/progress.jsonl`. **No background threads, no autorefresh plugin.**
6. **Progress phases (v1):**
   - Loading teams and games
   - Running seeding optimizer
   - Simulating optimized bracket (single deterministic run — Monte Carlo confidence bands are v2)
   - Computing Report Card metrics
7. **On success**: write `done.json` with final metrics summary; `os.replace()` atomic rename staging dir → `runs/<run_id>/`; release lock; transition state to `completed`.
8. **On error**: retain staging dir with `error.json` for diagnosis; rename to `runs/<run_id>.failed/`; release lock; transition state to `failed`. No partial `runs/<run_id>/` ever exists without `done.json`.
9. **On cancel** (user-initiated via Streamlit button): terminate subprocess; retain staging dir with `cancelled.json`; rename to `runs/<run_id>.cancelled/`; release lock; transition state to `cancelled`.
10. Report Card renders inline from `runs/<run_id>/comparison.json` below the cohort.

### Run state machine

```
pending → running → completed  (rename .tmp → <run_id>/, done.json)
                 → failed      (rename .tmp → .failed/, error.json)
                 → cancelled   (rename .tmp → .cancelled/, cancelled.json)
```

Only `runs/<run_id>/` directories (no suffix) with a `done.json` inside are valid completed runs. Failed/cancelled runs are kept for diagnosis but excluded from the "latest run" dropdown.

### Report Card structure

Hero: **Balance Score** composite (0–100), side-by-side actual vs optimized. **v1 is a single deterministic point estimate** — the 80% CI subtitle from Monte Carlo sims (round 3 fold-in #19) is v2. Initial formula (weights in `event_metadata.balance_score_weights`, default preset): `50 * one_goal_rate + 30 * (1 - blowout_5plus_rate) + 10 * (1 - same_club_early_rate) + 10 * (1 - rematch_rate)`. Tunable per ruleset; formula versioned via `balance_score_weights.preset_id`.

**Rationale for default weights:** `one_goal_rate` carries the highest weight (50) because the MatchBalance deep-research report found tournament-director FAQ language consistently foregrounds "competitive games" as the primary quality marker; `blowout_5plus_rate` is next because 5+ goal mismatches are the most damaging to retention; same-club and rematch avoidance are weighted lower as qualitative polish. Weights are tunable; the default preset is a starting point that can be tuned as proof-of-value data accumulates.

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

## 10. The 28 design decisions (fold-ins) — v1 status per decision

Per the user-approved v1 scope decision (visible minimum), every fold-in is kept in the data model / interface shape; the column below says whether v1 also *wires* it to runtime behavior or defers the wiring to v2.

**Round 1 — first-pass red-team review**

| # | Fold-in | v1 status |
|---|---|---|
| 1 | Games-coverage gate separate from team resolution | **Wired** |
| 2 | External team strength via median-of-seed-group + manual override | **Wired**; seed group frozen at scenario creation (see Section 12) |
| 3 | Placeholder-match detection as distinct status | **Wired** |
| 4 | Load-existing event from `reports/<event_key>/` (resume, not rescrape-overwrite) | **Wired** |
| 5 | Per-cohort readiness and run (not event-wide) | **Wired** |
| 6 | Run metadata per run (model, snapshot, weights, registry version) | **Wired** |
| 7 | Report shape designed intentionally, not ad hoc | **Wired** (report library) |

**Round 2 — forward-looking fold-ins**

| # | Fold-in | v1 status |
|---|---|---|
| 8 | Multi-provider scraper abstraction (`ProviderScraper` protocol) | **Protocol wired; only gotsport impl ships** |
| 9 | Mixed-gender events (cohort keyed on `(age, gender)`) | **Wired** |
| 10 | Seeding-constraints hook on the optimizer | **Data-model only** — constraints persisted, optimizer signature unchanged in v1 |
| 11 | Multi-scenario comparison (directory-per-scenario) | **Storage wired; comparison UI deferred** |
| 12 | Model-version pinning per run | **Wired** |
| 13 | Report library as a reusable module | **Wired** |
| 14 | Overrides survive rescrape (merge semantics) | **Wired** |

**Round 3 — deeper future-proofing**

| # | Fold-in | v1 status |
|---|---|---|
| 15 | Forfeit / cancelled / rescheduled policy via `result_type` | **Data-model only** — field stamped; policy hardcoded to "exclude forfeits" |
| 16 | Schema version on every CSV / JSON | **Stamp only**; forward-migration logic deferred to v2 |
| 17 | Scrape resumability with `raw_scrape.jsonl` + backoff | **Wired** |
| 18 | `series_id` for year-over-year | **Field wired; series-panel UI deferred** |
| 19 | Confidence bands via Monte Carlo sim reruns | **Deferred to v2** — v1 runs single deterministic sim; field `simulation_runs` stamped, default 1 |
| 20 | ~~Team-alias cache keyed on `(provider, provider_team_id) → team_id_master`~~ **Revised: reuse `team_alias_map`** | **Wired via existing platform primitive** (no parallel cache) |
| 21 | Rankings-snapshot-freshness warning | **Wired** — silent fallback surfaces as risk flag |

**Round 4 — MatchBalance deep-research report**

| # | Fold-in | v1 status |
|---|---|---|
| 22 | Capped goal differential metric alongside raw | **Wired** |
| 23 | Same-club / same-coach early-meetings metric | **Wired** (computed post-run from optimizer output) |
| 24 | Intra-event rematch count | **Wired** |
| 25 | Plain-language "Top reasons for recommendation" | **Wired** |
| 26 | Composite Balance Score headline | **Wired** (point estimate only; CI is v2) |
| 27 | Risk flags as first-class field | **Wired** |
| 28 | Override audit with before/after metrics | **Wired at per-run level**; scenario-level overrides.jsonl survives rescrape

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
- **External team strength assumption** is a heuristic. U19 (mostly externals in Phoenix Cup 2026) may surface its weakness. Fix path: manual strength option per team.
- **Ranking snapshot drift.** The existing `_resolve_prediction_snapshot` logic can silently fall back to `future_snapshot_fallback` or `synthetic_snapshot_fallback` when as-of data is missing. v1 surfaces these as risk flags; it does not resolve them. Post-event backtests against older tournaments may show more fallbacks than recent ones.

### Definitions (grounded for planning)

- **"Seed group"** = the division the team is currently assigned to within the scenario. For external-team strength, the "median of seed group" is the median `power_score` of the non-external teams in the team's current division, computed once at scenario creation and re-computed only on explicit request. Division reassignment during triage does NOT silently mutate external team strength.
- **"Play-up"** (defined earlier in Section 5): team's canonical `age_group` is younger than the division's `age_group`.
- **"Event key"** = `(provider_code, provider_event_id, season_year)` (Section 6). Storage path uses `event_key = f"{provider_code}__{provider_event_id}__{season_year}"`.
- **"Series"** = group of events sharing a user-set `series_id`. No automatic series detection.

**Open questions**
- Does the gotsport schedule page require a cookie/session even without login? Determined in Phase A.
- What exact set of knockout templates covers the bulk of the tournaments Dallas wants to backtest next? Answered by running v1 against ~5 events. The 4 simulator-supported templates cover Phoenix Cup 2026.
- When constraints relax (e.g., same-club avoidance is impossible in a 6-club cohort), what's the user-visible policy? v2 problem — constraints don't fire in the v1 optimizer.
- Does the CLI get extended to read the new layout in v2, or does Streamlit keep translating? TBD when v2 is planned; v1 uses Streamlit-translates and leaves the CLI untouched.

---

## 13. Implementation readiness

This design is complete enough to hand off to `/draft-plan-shells` for a step-by-step implementation plan.

### v1 implementation ordering (visible-minimum scope)

1. **Scraper diagnosis (Phase A)** — run existing gotsport scraper against Phoenix Cup 2026, identify failure mode, scope the fix.
2. **`ProviderScraper` abstraction + gotsport fix + scrape resumability** — library-level work. Writes to `intake/raw_scrape.jsonl`, persists to `team_alias_map` / `team_match_review_queue`.
3. **Storage layout + event identity** — `event_key = (provider_code, provider_event_id, season_year)`, `intake/` tier above `scenarios/`, rescrape merge semantics, schema_version stamps.
4. **Structure data model (library)** — dataclasses for `DivisionStructure`, `CohortConstraints`, `EventMetadata`, `RunMetadata`; loaders/writers for `group_structure_summary.csv`, `event_team_registry.csv`, `constraints.json`, `event_metadata.json`.
5. **Streamlit intake page shell** — header/banner, cohort summary strip, cohort expand/collapse. No triage yet.
6. **Triage UI** — 4 row states, review modal, fix modal, external edit drawer, manual-add-team flow.
7. **Structure input forms** — per-division editor (name, teams, pools, pool-play games, knockout format — with v2 templates disabled), validation.
8. **Run orchestration** — state machine, per-scenario file lock, Popen + stdout streaming to `st.status`, atomic staging-dir rename on success, error/cancel handling.
9. **Report library (`src/tournaments/reports/`)** — `schema.py`, `compute.py` (builds `comparison.json` + `risk_flags.json` from run outputs), `render_html.py` (Jinja template), `render_csv.py`.
10. **Report Card embedded in dashboard** — Streamlit embeds the HTML from `render_html.py`, no in-app rendering logic.
11. **Export buttons** — CSV, JSON, HTML (PDF deferred).

### v2 items (out of scope for this spec's planning)

- Monte Carlo confidence bands (wire `simulation_runs > 1`)
- Constraint-aware optimizer extensions (`SameClubEarlyAvoidance`, etc., added to `optimize_tournament_format()` signature)
- Extended knockout templates (`QF_SF_F`, `CROSSOVER_F`, `CUSTOM`)
- Multi-scenario comparison UI
- Year-over-year series history panel
- Second `ProviderScraper` impl (e.g., PlayMetrics)

The draft-plan-shells skill will turn this into sequenced, testable steps.
