# Inactive teams (no game played since 2024)

Investigated 2026-08-27 against production Supabase. Query saved at
`scripts/find_inactive_teams.sql`.

## Answer

**6,344 non-deprecated teams have no completed game on or after 2025-01-01.**
6,304 of those also have zero upcoming fixtures.

Two corrections applied that a naive query gets wrong:

- **Merge resolution.** `execute_team_merge` cascades `teams` and `team_alias_map` but
  leaves `games` pointing at the pre-merge master id, so history resolves through
  `team_merge_map` at read time. Without resolving, 772 teams look dead that are not.
- **Played vs scheduled.** Only rows with both scores set count. Null-score rows are
  unscraped or future fixtures.

## Where the 200,161 non-deprecated teams sit

| Bucket | Teams |
|---|---:|
| Played since 2025-01-01 | 163,635 |
| No game rows at all | 16,315 |
| Game rows but none played, latest row 2025+ | 13,867 |
| **Last played before 2025-01-01** | **6,344** |

The 13,867 are scrape gaps or future fixtures, not stale teams — every one has a 2025+
row. The 16,315 with no games at all are a separate question from the one asked.

## What these 6,344 actually are

| Provider | Teams | Avg played games | Exactly 1 game |
|---|---:|---:|---:|
| tgs | 3,681 | 4.0 | 8 |
| gotsport | 2,659 | 2.1 | 1,399 |
| sincsports | 4 | 3.8 | 0 |

Last-played year: 2024 → 5,923 · 2023 → 288 · 2022 → 114 · 2021 → 18 · 2020 → 1.

**This is not a junk pile.** Only 1 row has a placeholder `unknown%` name, none are blank,
797 have 5+ played games. The heaviest members are well-formed real teams — e.g.
`Midwest United FC ECNL RL 2008` (u19F, 28 games, last played 2024-12-08),
`Diablo Valley FC 2010 NC West` (u17M, 30 games). The cohort is dominated by three
legitimate patterns:

1. **Tournament-only rosters** (the TGS 3,681, avg 4 games) — an event roster plays a
   handful of games once and never returns. Working as designed.
2. **Aged-out / season-retired squads** — names like `ECNL RL G07/06`, `B07/06` are
   2024-25 season labels. u19 is the largest cohort (953), which is exactly where teams
   age out permanently.
3. **Thin GotSport records** — 1,399 with a single played game.

`created_at` is useless as an age signal: the minimum across the whole `teams` table is
2025-11-03, so every row looks "new". It reflects a table rebuild, not team age.

## Safety check before deleting anything

Clean:

| Reference | Cohort hits |
|---|---:|
| `watchlist_items` (user-facing) | **0** |
| `rankings_full` | **0** |
| `current_rankings` | **0** |
| `report_card_leads` | **0** |
| `user_corrections` | **0** |

Not clean:

| Reference | Cohort hits | Consequence of a hard delete |
|---|---:|---|
| `team_alias_map` | 6,338 | Orphaned aliases; a re-scrape resurrects or mis-resolves the team |
| `scrape_requests` | 954 | Queue rows pointing at nothing |
| `ranking_history` | 518 | Orphaned historical snapshots |
| `team_merge_map.canonical_team_id` | 109 | **Breaks merge resolution** — 109 of these are targets other teams merged into |

### The blocking finding

**`teams` carries 18 inbound foreign keys, and a `DELETE` fails or destroys.** Nine are
`ON DELETE NO ACTION` — including `games` on both the home and away columns — so deleting
any team that has games **errors outright**. Seven are `ON DELETE CASCADE`
(`rankings_full`, `ranking_history`, `team_scrape_log`, `team_social_profiles`,
`prediction_feature_history`, `game_explainability` ×2), so a team without games deletes
cleanly and **takes its ranking history with it**. Two are `ON DELETE SET NULL`.

Of the 25 base tables carrying a team-id column, the seven with no FK — `watchlist_items`
among them — would orphan silently.

> **Correction.** An earlier version of this report claimed `teams` had *no* inbound
> foreign keys and that a delete would silently orphan ~30 tables. That was wrong. The
> query behind it used `information_schema.constraint_column_usage`, which is
> privilege-filtered and returns nothing to a read-only role. `pg_constraint` with
> `confrelid = 'public.teams'::regclass` is the unfiltered form and shows all 18. The
> recommendation below is unchanged, and better supported: the database actively blocks
> the delete rather than quietly permitting it.

And the cohort is load-bearing for active teams' history:

- 16,010 games involve a cohort team.
- **11,509 of those have an opponent that is still active**, touching **6,451 distinct
  active teams**.

`lib/api.ts:718` (`getTeamGames`) applies no lower date bound — team pages show history
back to 2020. Deleting these rows turns 11,509 games on 6,451 *active* teams' pages into
unresolvable opponents, which is precisely what `unknown-opponent-hygiene-weekly.yml`
exists to clean up.

## Recommendation

Do not hard-delete. The cohort is real historical data, it is already excluded from every
user-facing surface (0 in rankings, 0 in watchlists), and deleting it damages 6,451 active
teams' game history to reclaim 3% of one table.

The defensible win is narrower and is about **cost, not storage**: 954 of these sit in
`scrape_requests`, and 3,318 of the 5,923 that last played in 2024 were scraped in the last
90 days. The scraper is repeatedly re-checking teams that have been dead for 18+ months.

Suggested order:

1. **Stop scraping them.** Add a "no played game in 18 months and no future fixture" filter
   to the enqueue jobs (`enqueue_safety_net.py` is the main offender — it targets teams not
   scraped in 90+ days, which is this cohort by construction). Zero deletion risk.
2. **Mark, don't delete.** If they need to disappear from admin surfaces, add an
   `is_inactive` flag rather than removing rows. Preserves opponent history.
3. **Only then consider deletion**, and only for a much tighter slice: no aliases, not a
   merge target, not in ranking_history, and no still-active opponent. Excluding just the
   first three drops the candidate set to 5,697; the active-opponent filter would cut it
   much further.
