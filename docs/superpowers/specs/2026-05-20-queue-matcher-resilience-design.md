# Queue Matcher Resilience — Design

**Date:** 2026-05-20
**Context:** Follow-up to PR #827. Drains the ~70% of `team_match_review_queue` rows that currently hit `no_candidates` in `scripts/find_queue_matches.py` before the scorer even runs.

## Problem

A live dry-run against the newest 200 pending queue rows showed:

| Failure mode | Count | % |
|---|---|---|
| `would_score` (fetch returned candidates) | 61 | 30% |
| `no_match_club_token_exists` (provider's club doesn't exact-match any master, but first word does) | 82 | 41% |
| `club_exists_filter_rejected` (club exists, but age/gender/state filter killed all) | 33 | 17% |
| `no_match_club_unknown` (club genuinely absent) | 16 | 8% |
| `protected_division` | 8 | 4% |

Three independent causes:

1. **Exact-match `ilike`** — `find_best_match` calls `.ilike("club_name", club_name)` without wildcards. PostgREST treats that as an exact case-insensitive match, so `"Jackson SC"` doesn't match a master named `"Jackson Soccer Club"`.
2. **Wrong stored `club_name`** — for some providers (TGS, squadi), `match_details.club_name` is the scraped value, and scrapers occasionally write the wrong club (e.g., every `La Roca FC` provider team has `match_details.club_name = "LOS ANGELES SC"`). The queue matcher uses that bad value for lookup → empty results.
3. **No fallback when club lookup fails** — script gives up rather than trying any wider net.

The scraper bug (#2) is a separate follow-up PR. This design fixes the queue matcher's resilience so existing stuck rows can be drained regardless of whether the stored data is wrong.

## Scope

**In scope** — `scripts/find_queue_matches.py`:
- Three layered changes to the candidate-fetch path in `find_best_match`.
- Add named resolution-method strings for new code paths so dry-run breakdowns show what drained what.

**Out of scope** — separate PRs:
- Fixing the scraper(s) that write wrong `match_details.club_name`.
- Touching `event_team_matcher.py` (scrape-time logic, already updated in PR #827).
- Lowering the auto-merge confidence threshold.

## Design

### 1. Substring `ilike` with wildcards

Wrap the `club_name` pattern with `%...%` so the lookup performs a real substring match instead of an exact one.

```python
# Before:
.ilike("club_name", club_name)

# After:
.ilike("club_name", f"%{club_name}%")
```

Also applied to the upstream state-of-club lookup that resolves `state_code`. This alone fixes the largest single bucket (the `no_match_club_token_exists` 41%).

### 2. Re-derive club from team_name when stored data conflicts

When the script reaches the candidate fetch:

1. Pull `stored_club = match_details.club_name` and `extracted_club = extract_club_from_name(provider_team_name)`.
2. Determine `stored_looks_wrong`:
   - `stored_club` is non-empty
   - `stored_club` has at least one token of length ≥ 4 characters
   - **None** of those ≥4-char tokens appear (case-insensitive substring) in `provider_team_name`
3. If `stored_looks_wrong`, try the candidate fetch with `extracted_club` instead of `stored_club`.
4. If both have value, try `stored_club` first; if that returns zero candidates, retry with `extracted_club`.

Why the ≥4-char threshold: avoids false positives from short acronyms (`EBU` ↔ `Elmbrook United`, `CASA` ↔ `Clemson Anderson Soccer Alliance`) where the stored full name is legitimately different from the provider abbreviation. Long-token mismatch is a much stronger signal of the wrong-club-name bug (`LOS ANGELES SC` having zero overlap with `La Roca FC AV Pre-ECNL B15`).

Resolution method label for matches via this path: `"fuzzy_re_derived_club"`.

### 3. Cohort fallback gated by `should_skip_pair`

If neither stored nor extracted club produces candidates, fall back to a cohort search:

```python
query = (
    supabase.table("teams")
    .select("id, team_id_master, team_name, club_name, gender, age_group, state_code")
    .ilike("gender", gender)
    .or_(build_age_group_filter_clause(age_group))   # already used elsewhere
)
if state_code:
    query = query.eq("state_code", state_code)
candidates = query.limit(200).execute().data
```

Then immediately filter through `should_skip_pair(provider_team_name, candidate.team_name, require_age_token_match=False)` to drop everything with different colors, programs, directions, etc. The structured-distinction gate added in PR #827 makes this fallback safe — it typically reduces 200 raw cohort rows to under 10 plausible candidates.

The state filter is applied only when we have a `state_code` to scope by. If neither stored nor extracted club resolved to a state, the cohort search runs nation-wide for the cohort. That's noisier but `should_skip_pair` still does most of the rejection work.

Resolution method label: `"fuzzy_cohort_fallback"`.

### 4. Resolution method visibility

The display breakdown added in PR #827 now lists more methods. After this PR, dry runs will report counts like:

```
Resolution method breakdown:
  fuzzy                                15
  fuzzy_re_derived_club                 8
  fuzzy_cohort_fallback                12
  stored_tiebreak:normalized_name_exact 4
  no_candidates                        12
  ...
```

So we can see exactly which code path drained which rows, and which paths are still failing.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Wildcard `ilike` returns too many candidates (matches across clubs) | The variant + program + structured-distinction gates already filter ruthlessly. SequenceMatcher score is still computed. Auto-merge gate stays at 0.95+. |
| Re-derive heuristic mis-classifies a legit different-club case as "wrong stored data" | The ≥4-char-token-overlap test is conservative. If wrong, we just try a second lookup — no harm. |
| Cohort fallback creates false positives | `should_skip_pair` is strict. Auto-merge gate still 0.95+. Dry-run breakdown lets operator see what's coming through `fuzzy_cohort_fallback` before flipping to `--execute`. |
| Slower per-row processing (extra DB roundtrips when first lookup misses) | Roughly 1–2 extra queries per failing row. Script already takes minutes for 1000 rows; ~2× worst case still in single-digit minutes. |

## Auto-merge gate

**Unchanged.** Auto-merges only at `score ≥ 0.95` unless the caller passes `--include-high`. The workflow today uses `--execute --yes` without `--include-high`, and that stays the safe default. Operator can opt into `--include-high` after reviewing a dry-run breakdown.

## Validation plan

1. **Unit-test the `stored_looks_wrong` heuristic** with the actual mismatch cases observed (`La Roca FC` / `LOS ANGELES SC`, `Deptford Premier` / `VENTURA COUNTY FUSION`) and the acronym false-positive cases (`EBU` / `Elmbrook United`, `CASA` / `Clemson Anderson Soccer Alliance`).
2. **Tiny dry-run** against the newest 100 pending rows. Compare resolution-method breakdown before and after. Expect `would_score` count to roughly double and the new `fuzzy_re_derived_club` + `fuzzy_cohort_fallback` buckets to absorb most of the previous `no_candidates`.
3. **Full backlog dry-run** (`--limit 12971 --force --dry-run`) before any live execute.
4. **Live single-step run** via `gh workflow run data-hygiene-weekly.yml -f skip_steps=1,1b,2,3` once dry-run looks clean.

## Estimated impact

Combining the three changes on the newest-200 sample's failure breakdown:

- Wildcard `ilike` likely converts most of the 82 `no_match_club_token_exists` rows into successful candidate lookups → ~+41%.
- Re-derive helps the subset of `club_exists_filter_rejected` rows where the stored club was wrong → ~+5–10% (subset of 17%).
- Cohort fallback covers the genuinely unknown-club rows (8%) and the residual filter-rejected cases — likely +5–10% more.

Total: an expected **55–65% drain rate** on rich-format newest rows, up from ~30%. Legacy backlog should see similar uplift since the same fetch logic runs against them — but the scraper-bug-affected subset will still need the follow-up scraper PR for clean resolution.

## Out of scope (follow-up PRs)

1. **Scraper fix** — investigate `src/models/tgs_matcher.py` and squadi-related scrapers to find why `match_details.club_name` gets the wrong value. Likely the scraper is pulling event-level club instead of team-level. Separate PR with its own validation against live scrape runs.
2. **Lowering the auto-merge bar** — once dry runs show `fuzzy_cohort_fallback` is producing clean 0.95+ matches reliably, consider whether to extend `--include-high` to default-on in the workflow.
