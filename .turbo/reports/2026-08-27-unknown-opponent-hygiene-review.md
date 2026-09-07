# Unknown Opponent Hygiene Weekly — pre-rerun review

**Date**: 2026-08-27
**Scope**: `.github/workflows/unknown-opponent-hygiene-weekly.yml` and its four scripts
**Evidence**: run 32885274005 (2026-08-25), its artifact bundle, and a local re-run of the export step
**Verdict**: do not re-run as-is. The GotSport enrichment the whole pipeline depends on is dead, and has been failing silently.

---

## Bottom line

The job's fuzzy matcher has almost nothing to match on. GotSport's team-details API returns
nothing to the export step, so 95% of unknown opponents reach the matcher named
`unknown_<provider_id>` — a placeholder, not a name. Matching a placeholder against real team
names cannot succeed, so 97.6% of rows fall through to team *creation* instead of team
*matching*.

The teams it then creates are given the **opponent's** age group, gender, and state, because
that is the fallback when the API gives nothing. Those values are fabricated, they are written
to `teams`, and the ranking engine reads them.

Nothing in the workflow reports any of this. Every step exits 0 and the summary reads healthy.

---

## What the 2026-08-25 run actually did

| Stage | Result |
|---|---|
| Export: rows found | 16,671 unknown opponents |
| Export: GotSport age / gender / state resolved | **0 / 0 / 0** |
| Export: names resolved | 838 of 16,671 (5%) |
| Match: fed a `unknown_<pid>` placeholder name | **15,833 (95%)** |
| Match: `no_match` | **16,263 (97.6%)** — vs 108 `auto_link`, 43 `review` |
| Discover: teams created | **11,350** |
| Discover: skipped for missing metadata | **0** — the fallback guarantees this never fires |
| Games backfilled | 21,308 |
| Runtime | 3h 12m of a 4h timeout |

### The created teams inherit their opponent's identity

Of the 11,350 teams created, compared against the opponent they were discovered from:

- **94.0%** got the opponent's `age_group`
- **99.8%** got the opponent's `gender`
- **97.4%** got the opponent's `state_code`

This is not a coincidence of similar teams playing each other. It is
`auto_match_unknown_opponents.build_unknown_profile` (`scripts/auto_match_unknown_opponents.py:186-192`)
copying `top_known_team_age_group` / `_gender` / `_state` onto the unknown team when the API
returns nothing, which is always.

---

## Findings

### 1. The three scripts read four fields the API has never returned (critical)

**This is the root cause, and it is not the 403.**

A live 200 response from `team_details?team_id=739722` contains exactly these keys:

```
city_state_country, club_name, coach_names, display_age_group, display_gender, id,
image, login_url, manager_names, name, primary_coach_name, primary_manager_name,
team_association, team_logo_url_full, website_url
```

The three hygiene scripts parse `full_name`, `age`, `gender`, and `state`
(`export_unknown_opponents.py:133-137`, `auto_match_unknown_opponents.py:141-146`,
`discover_teams_from_opponents.py:143-148`). **None of those four keys exists.** They return
`None` on every successful call, forever. The real fields are `display_age_group`,
`display_gender`, and `team_association` (which carries the state).

`name` and `club_name` *are* correct, which is why those two are the only columns that ever
come back populated — 838 names and 827 clubs on 08-25.

`scripts/backfill_unknown_team_names.py:167-172` already reads the correct names. It was added
later (#964) and got it right; the hygiene scripts were never corrected.

This has always been broken, not recently: the 2026-08-11 run shows the identical signature —
0 age, 0 gender, 0 state, 494 of 10,977 names.

**Fix**: read `display_age_group`, `display_gender`, `team_association`. Mirror the resolver in
`backfill_unknown_team_names.py`.

### 1b. CloudFront rate-limits the callers that don't throttle (high)

The 403 is real but secondary — and it is **not** an IP block. The same machine that got 403 on
six rapid requests got a clean 200 minutes later. It is WAF rate limiting.

The repo already knows this: `_is_cloudfront_waf_block()` (403 + `Server: CloudFront`), a shared
`get_waf_breaker()`, and `GOTSPORT_WAF_COOLDOWN_SEC` all exist.
`backfill_unknown_team_names.py` sleeps **12 seconds** between calls and trips the breaker on a
block — which is why it succeeds every 15 minutes. `src/scrapers/gotsport.py` routes through
ZenRows residential proxies instead.

The three hygiene scripts use none of it: no delay, no breaker, no proxy, and
`except Exception: payload = {}` swallows the 403 so it is indistinguishable from "team not
found". 16,671 requests fired flat out is why only ~5% of names survive.

**Fix**: use the existing breaker and a delay, or route through ZenRows. Count outcomes
(`ok` / `waf` / `404` / `error`) and fail the step when the success rate collapses. A run that
resolves 0 of 16,671 should be red, not green.

### 2. Fabricated age/gender/state written to `teams` (critical)

The fallback in `build_unknown_profile` exists to give the *fuzzy matcher* a hint. But
`discover_teams_from_opponents._build_team_metadata` reads those same
`unknown_age_group_used` / `unknown_gender_used` / `unknown_state_used` columns and treats them
as facts about the team it is about to INSERT. `_has_minimum_metadata` then always passes,
which is why `DISCOVERY_SKIPPED_METADATA=0`.

Cross-age and cross-gender fixtures are real — the ranking engine models play-up games
explicitly — so every unknown opponent in one of those is filed into the wrong cohort
permanently, and `rank_in_cohort_final` is computed against the wrong peer group.

**Fix**: keep the inherited values for matching only. Discovery should require metadata that
came from the provider, and skip (or queue for review) when it did not.

### 3. Duplicate teams created (high)

Because matching ran on placeholder names, teams that already existed were not matched:
**517 of the 11,348** teams created on 2026-08-25 are exact `name + age_group + gender + state`
duplicates of a team that already existed; 919 match on name + age + gender. Duplicates split a
team's game history across two rows, which is a direct ranking-accuracy problem, and cleaning
them up is the `merging-duplicate-teams` skill's job.

### 4. The 3-hour step is redundant work (high)

Every id is resolved twice — once in the export step (fails fast, ~2 min) and again in the
discover step (~1.05s/row, 3h 06m). The discover step is 97% of the job's runtime and is
approaching the 240-minute timeout as the backlog grows.

Consolidating on one resolver with a shared cache, and adding modest concurrency, should cut
the job to well under an hour. The three-way duplication of `GotSportResolver` is also a
correctness hazard in its own right — a fix applied to one copy silently misses the others.

### 5. `--resolve-gotsport-details` is not passed to the matcher (medium)

The workflow passes it to the export step but not to `auto_match_unknown_opponents.py`, so that
script's resolver is always `None` and its backfill branch is dead code. Harmless today only
because the API is blocked anyway.

### 6. Cleanup is deferred to a different workflow (medium)

`backfill-unknown-team-names.yml` runs every 15 minutes to rename the `unknown_<pid>` rows this
job creates. That is why only 11 placeholder names from the 08-25 run survive today, and why
4,235 remain across the table — the residue this loop cannot resolve. The weekly job creates
the mess the 15-minute job spends the week cleaning up.

---

## What is *not* wrong

- The workflow YAML passes the full `review-workflows` audit — 0 findings across 41 files.
- `AGE_ROLLOVER_FREEZE` is correctly wired on both the apply and discover steps.
- The dry-run plumbing works; `--execute` is properly gated.
- Discovery is **not** the source of the 4,235 `unknown_<numeric>` teams in the table — it
  contributed 11 on 08-25, and the backfill loop handles the rest.

---

## Why AFC Union's three opponents are still unresolved

They are unrelated to the above. Those games were created 2026-08-26 19:48 UTC — a day *after*
the 08-25 run — so they were simply not in scope. The next scheduled run would pick them up.
Whether it resolves them correctly, or invents three U14 Female Wisconsin teams from AFC
Union's own attributes, depends on finding #2.

---

## Suggested order

1. Restore GotSport access (the real blocker — proxy via ZenRows, which the scrapers already
   use, or find the endpoint's current auth requirement) and make failure loud.
2. Stop discovery from inventing metadata; require provider-sourced age/gender.
3. Deduplicate the resolver into one module; drop the double resolution pass.
4. Re-run, and check `auto_link` rises well above 108 before trusting the output.
