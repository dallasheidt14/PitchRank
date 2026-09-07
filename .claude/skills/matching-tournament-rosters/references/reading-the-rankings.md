# Reading the rankings

Which column holds each published value, what each status means, and how to state a rank so it is
reproducible.

## Contents

- Where the values live
- The three statuses
- Reporting a rank
- Game counts for the report
- Staleness
- games_played is not a career total
- Merged teams read as 0-0-0
- Teams that hold a national rank but no state board

## Where the values live

`rankings_full.national_rank` and `rankings_full.state_rank` are **always NULL**. A report that
selects them ships a column of blanks.

The published values are:

| Value | Column | Source |
|---|---|---|
| National rank | `rank_in_cohort_final` | Frozen at the last ranking run |
| State rank | `rank_in_state_final` | Recomputed live on every read |
| PowerScore | `power_score_final` | Frozen at the last ranking run; always in [0.0, 1.0] |

There is no column called `power_score` — `rankings_full` carries `powerscore_core`,
`powerscore_adj`, `powerscore_ml`, `power_score_true` and `power_score_final`, and only the last is
the published value.

`state_rankings_view` carries all three and is the right single-query source for a roster report,
filtered by `team_id_master`. Three traps in it:

- `gender` comes back as `F` / `M`, not `Female` / `Male` — and so does `rankings_view.gender`
- `age` is a bare integer (`15`), not `u15`
- there is no `state_rank` column — asking for one returns a PostgREST `42703` error

`rankings_full` keys on **`team_id`**, not `team_id_master`. Joining it on `team_id_master` fails
with `42703`. The two views do use `team_id_master`.

State rank is a `row_number()` over Active teams with a state, evaluated at query time, while
national rank is passed through from the run. So a state rank moves when a neighbour is merged away
or gains a state code, with no rerun. National rank does not.

Read ranks from `state_rankings_view` and `rankings_view` only — they are the two views built on
`rankings_full`. `rankings_by_age_gender` and `state_rankings` are built on `current_rankings`,
which is months stale for the overwhelming majority of its rows.

`rank_in_cohort_ml` is a pre-gate intermediate, not the published rank, and it differs from
`rank_in_cohort_final` for almost every Active team — by up to a couple of thousand places. The
state-rankings RPC reports that intermediate, so the national rank shown on a state page is not the
published one. Read `rank_in_cohort_final` and flag the discrepancy rather than reconciling it
silently.

## The three statuses

| Status | In `state_rankings_view`? | Has ranks? | What the site shows |
|---|---|---|---|
| `Active` | yes | national and state | A normal ranked row |
| `Not Enough Ranked Games` | yes | neither, both NULL | The row, with an em dash where the rank would be, plus PowerScore and record |
| `Inactive` | **no** | n/a | Nothing — the team is absent from the board |

Use these three strings verbatim in the report's `status` column. Copy the value from
`state_rankings_view.status` where the view returns a row, and supply `Inactive` yourself where it
does not and `rankings_view` shows the team.

A `Not Enough Ranked Games` team **is on the rankings page**. Reporting it as "not in the rankings"
is wrong; it is listed but unranked.

`Inactive` is a recency verdict — no game in the inactivity window — not a sample-size one. An
Inactive team can have a full slate of games; thousands of them have twelve or more.

A team is absent from `state_rankings_view` for one of three reasons, in decreasing order of
likelihood: its status is `Inactive`, its `state` is NULL, or it has no scored game in the window at
all. Check `rankings_view` before concluding which — it carries the Inactive rows the state view
drops.

The Active boundary is **12 games** in the ranking window (`MIN_GAMES_PROVISIONAL` in
`src/etl/glicko_config.py`). The stale comment in `src/etl/v53e.py` saying six is the legacy
engine's, not the live value.

## Reporting a rank

`rank_in_cohort_final` is a dense 1..N over exactly the Active teams in each age-and-gender cohort,
with no gaps and no ties. N is therefore the correct denominator and is a simple count — note the
`F`/`M` gender values:

```sql
SELECT count(*) FROM rankings_view
WHERE status = 'Active' AND age = :age_int AND gender = :f_or_m;
```

`#708` alone means nothing. `#708 of 5,622 Active U11 Male teams` is the report. The denominator
excludes the `Not Enough Ranked Games` teams shown on the same page, so it is smaller than that
page's row count.

A PowerScore of `0.0` is a real published value, not missing data. Over two thousand Active teams
sit at exactly zero, and they tie — the view breaks the tie on `team_id_master` but the state RPC
has no tiebreaker at all, so a rank at the bottom of a board can move between page loads with no
games played.

`state_rankings_view` membership is read live from `teams` while every score is frozen at the run,
so its row counts are not reproducible across a session. Pin any count to the timestamp it was
measured.

## Game counts for the report

Three counts the report carries, all of them resolved through `team_merge_map` first — see
"Merged teams read as 0-0-0" below for why the raw ID undercounts.

```sql
WITH ids AS (
  SELECT :canonical_id::uuid AS id
  UNION SELECT deprecated_team_id FROM team_merge_map WHERE canonical_team_id = :canonical_id
)
SELECT
  count(*) FILTER (
    WHERE g.home_score IS NOT NULL AND g.away_score IS NOT NULL
      AND COALESCE(g.is_excluded, false) = false
      AND g.game_date BETWEEN :run_date::date - 393 AND :run_date::date
  ) AS ranked_games_window,
  count(*) FILTER (
    WHERE g.home_score IS NOT NULL AND g.away_score IS NOT NULL
      AND COALESCE(g.is_excluded, false) = false
      AND g.game_date BETWEEN current_date - 90 AND current_date
  ) AS games_90d,
  count(*) AS games_all,
  max(g.game_date) FILTER (
    WHERE g.home_score IS NOT NULL AND g.game_date <= current_date
  ) AS last_played
FROM games g
WHERE g.home_team_master_id IN (SELECT id FROM ids)
   OR g.away_team_master_id IN (SELECT id FROM ids);
```

`games_all` deliberately counts every row, including unplayed future fixtures — that is what makes
it diverge from `ranked_games_window`, and the divergence is informative.

The provider codes and registration IDs come from `team_alias_map` joined to `providers` on
`provider_id`; collapse multiple alias rows into one `"; "`-joined cell.

## Staleness

The last ranking run is a single uniform timestamp across every `rankings_full` row, so
`SELECT max(last_calculated) FROM rankings_full` is exact and cheap. `current_rankings.
last_calculated` is not a substitute — most of its rows are far older.

Two different populations get called "stale", and they differ by two orders of magnitude:

- **Played since the run** — a handful of teams on a midweek day, growing to thousands by the
  following Monday. Strongly day-of-week dependent, so any figure must be stated with the day it was
  measured.
- **Result imported after the run for a date the run already covered** — late-arriving scrapes,
  routinely a thousand-plus teams. This is the dominant cause, and a query keyed only on
  `game_date > last_calculated` misses all of it.

Cap every last-game query at today. A small number of scored games carry future dates, so without
the cap a "played since the run" count is a large overstatement and "days since last game" goes
negative:

```sql
AND g.game_date <= current_date
```

`last_game` in the ranking views is the newest game in the engine's selected window. It is a safe
lower bound — it can overstate the gap by a few days for a late-scrape team, but never understates
it.

## games_played is not a career total

`games_played` is windowed, capped at 30, and drawn from a balanced selection — not a career count.
A meaningful share of `Not Enough Ranked Games` teams have twelve or more scored games all-time.

The correct answer to "my team played twenty games, why does it say Not Enough" is that twelve must
fall inside the window and survive selection. A team that played fifteen games fourteen months ago
and four recently is unranked. Never explain the status using the site's own `total_games_played`.

The window is a hard cutoff of 365 days plus a 28-day grace, with games in the grace tail linearly
down-weighted from about 0.97 to about 0.03. It is a weight taper, not an inclusion taper: a game
380 days old still counts, at roughly half its nominal weight, and the taper only falls to a third
at about 384 days. Reproducing the window with 365 alone drops a few percent of the evidence —
enough to push a borderline team across the Active threshold.

The `ranked_games_window` query above reproduces the engine's count closely for an unmerged team,
and for one it never undercounts — so a result under twelve proves that team cannot be Active. That
proof holds only because the query resolves through `team_merge_map` first; on a raw ID a merged
team undercounts severalfold. Above thirty the count stops tracking `games_played`, which the cap
has flattened.

## Merged teams read as 0-0-0

The engine resolves merges before counting games; the views do not. So a merged team can show a full
`games_played` and a real rank beside a `total_games_played` of zero and a blank win percentage. It
looks like a bug and is not.

Read `games_played`, `wins`, `losses` and `draws` from `rankings_full` when you want the engine's
own resolved figures, joining on `rankings_full.team_id`.

## Teams that hold a national rank but no state board

Around two thousand `rankings_full` rows carry the literal string `UNKNOWN` in `state_code` while
`teams.state_code` is NULL. Almost all are unranked anyway — the large majority are
`Not Enough Ranked Games`, most of the rest `Inactive` — and only a handful are Active and hold a
national rank, one as high as #90.

When someone says "we're ranked nationally but not in our state", check for this before assuming a
bug in the state rank computation, but expect the answer to be "unranked" rather than "ranked
nationally, missing from state".
