---
name: user-activity-retention-hygiene
description: Weekly pass that keeps PitchRank data fresh for every team a real user has shown interest in - watchlisted teams, report-card lead captures, and teams a user clicked "find missing game" on. Audits last week's batch, grades each team's record against the season, and re-enqueues the whole set at priority 1. Use when asked to "run retention hygiene", "check the user activity teams", "refresh watchlisted teams", "run the weekly user hygiene pass", or when reviewing whether the teams users actually look at have up-to-date games.
---

# User Activity Retention Hygiene

A user who comes back to a team page and finds stale games has a reason to cancel.
This pass keeps the teams they actually look at current.

Three interest signals, unioned and merge-resolved:

| Signal | Table | Meaning |
|---|---|---|
| Watchlisted | `watchlist_items` | a premium user saved the team |
| Report-card lead | `report_card_leads` | someone traded an email for that team's report card |
| User-requested | `scrape_requests` at priority 1, `request_type = 'missing_game'` | a user clicked "find missing game" |

Audit before enqueueing. The audit reads the outcome of the previous batch, and
enqueueing displaces it with a fresh set of pending rows.

## Step 1: Audit

```bash
python scripts/audit_user_interest_teams.py --out .turbo/reports/<YYYY-MM-DD>-user-interest-audit.md
```

Read-only. It prints the interest counts, the previous batch's completed/failed
split, a verdict tally, and the teams that need review.

Before interpreting anything, read [references/reading-staleness.md](references/reading-staleness.md).
Judging these teams by calendar days produces a list that is almost entirely
false positives.

Four verdicts are defects worth acting on:

- **no games** / **no games played** — the team page shows nothing. Open the team's provider page to check the squad still exists.
- **dormant** — no game in over a year. Almost always a disbanded or renamed squad; confirm before telling anyone data is missing.
- **unranked** — playing this season but absent from `rankings_full`. Compare the team's last game against `rankings_full.last_calculated`; a team whose first game postdates the Monday ranking run has not been rated yet, which is expected rather than broken.

`between seasons` and `active this season` are healthy. Report them as counts, never as a worklist.

Game counts exclude `is_excluded` rows, matching what the team page shows.

## Step 2: Enqueue

```bash
python scripts/enqueue_user_interest_teams.py
```

Writes one priority-1 `scrape_requests` row per team, tagged
`request_type = 'retention_hygiene'`. Add `--dry-run` to see the targets first.

The tag keeps the user-click signal readable. Reading priority-1 rows back
without filtering would re-collect whatever this job wrote last week, and the
interest set would grow on its own forever.

Teams that already hold a pending request are skipped rather than re-enqueued.
The RPC's update branch would rewrite their `game_date` to today, moving a
user's own "find missing game" request off the date they asked about.

`process_missing_games` drains 40 teams every 15 minutes — 160 an hour — so
divide the batch size by that for the drain time. It holds the front of the
queue while it drains, and live user clicks land at the same priority behind it.

## Step 3: Report

Lead with whether anything is actually wrong, then the counts.

Give the user:

- The defect list from Step 1, by team name, with what is wrong with each
- What the previous batch recovered — the report's "Previous batch" section carries the enqueued count and the games found across it
- Failures from the previous batch, grouped by reason rather than listed per team
- The report path

Teams with games on record but no score belong in the report as a count and a
top-few list. Re-scraping does not recover them, so presenting them as a
worklist wastes the user's time.
