# Modular11 Elite Academy League (EA) Scraper — Step 1: One Age Group at a Time

## Revision (2026-10-04): run one age group at a time

The user asked to "go one age group at a time. So it starts with u11 scrapes those games and
matches to u11 teams. Then next u12 and so on." Every run takes `--age u11` (then `u12`, …) and
produces that age's roster, its games and its match report. Later sections that describe the
whole-league roster still apply, filtered to the one age.

**Per-team schedules settle team identity (verified 2026-10-04).** `get_matches` with
`team=<UID_team>` (and `age=0`) returns only that team's games, and its rows show a
**team-specific display name**: team 7343 shows `FLYTE SC- Inland Empire`, team 9176 shows
`FLYTE SC Blue- Inland Empire` (same club, U13, EA, same region). Each row carries a match number
(first column), and a game appears in both teams' schedules. Match 123269 is in both lists above,
so those two played each other. Joining on the match number gives **both team ids for every
game**, which removes the 39-pair ambiguity noted under "Later steps". It also gives real team
names, so the built `"{club} {U-age} {tier}"` name is only a fallback.

Revised step-1 flow, per age:
1. Roster for that age from the embedded `dependencies:` array (Component 1, filtered).
2. For each team in it, page through `get_matches?tournament=27&team=<id>&status=all` for the
   current season (Aug 1 – Jul 31). **Always page.** Every response carries
   `"<n> page out of <N>"` (the MLS NEXT spider parses the same marker). Request
   `open_page=0…N-1` until the last page. A response with no marker fails the run rather than
   being read as one page. Verified 2026-10-04: team 7343's 20 games were "1 page out of 1" (its
   full season, 09/12/26 to 05/25/27), while an age-wide U13 query was 1 of 64 pages of 25. So a
   single team rarely needs a second page, and the loop still must not assume that. Keep the
   team's display name and each game's match number, date, score and both club names.
   **Pages are 1-indexed, and `open_page=0` silently returns page 1** (verified 2026-10-04 on
   the age-wide U13 query: `open_page` 0 and 1 both return "1 page out of 64" with identical rows,
   and 64 returns the last 8). Start at 1 and check that the marker's current page equals the page
   requested. An empty schedule returns `No data available.` with no marker, which is read as zero
   games; any other marker-less body fails the run.
   **Unplayed fixtures** (future dates, score shown as `TBD`) are kept with empty scores and `status=scheduled`,
   matching how `games` already stores upcoming fixtures as NULL-score rows.
3. Pair games by match number to get `(match_no, home_team_id, away_team_id, date, scores)`. A
   match seen from only one side (an opponent outside the roster, such as a cross-age game) is kept
   and flagged, not dropped.
4. Match report for that age (Component 2), now able to use the real display name as well as club,
   age and tier.

Outputs: `data/modular11_ea/<age>/teams.csv`, `games.csv` and `match_report.csv`. Still **no
database writes**: importing the games and writing teams and aliases is the next step, again
one age at a time, after the user reviews that age's report.

**Date:** 2026-10-04
**Status:** Draft (pending user review)
**Slug:** `modular11-ea-scraper`

## Goal

Add a Modular11 EA scraper that is separate from the existing MLS NEXT spider. Step 1 collects
every Elite Academy League team and reports which ones are teams we already hold. **Step 1 does
not write to the database.** Game results come in a later step, and so does writing teams or
aliases.

The user chose this (2026-10-04): "Team list + match report", then "Link to the existing team".

## What the source exposes (verified 2026-10-04)

- EA is Modular11 tournament **27** (MLS NEXT is 12 for HD and 35 for AD). The public page is
  `https://www.modular11.com/league-schedule/elite-academy-league`. One GET, no login, no proxy.
  `eliteacademyleague.com` returns 403 and is not needed.
- The page embeds a `dependencies:` JSON array in an inline script. Each row is
  `{UID_bracket, UID_group, UID_age, UID_academy, UID_team}`: 1,667 rows, **1,239 unique team
  ids** and 162 academies (clubs).
- **Brackets (tiers):** `47` = EA (901 teams), `48` = EA2 (344), `51` = EA National (236).
  Every EA National team is also an EA team under the same `UID_team`, so National is a second
  competition for existing squads, not a separate tier of teams. Six team ids appear in both EA
  and EA2.
- **Ages (`UID_age`):** 20=U11, 17=U12, 21=U13, 22=U14, 33=U15, 14=U16, 15=U17, 26=U19. The
  codes for U13 to U19 match `AGE_GROUP_IDS` in the MLS NEXT spider.
- **Regions (`UID_group`):** 19, with names taken from the page's `js-groups` select (Florida,
  LA North, PACNW, …).
- **Club names:** from the page's `js-academy` select (`value` = `UID_academy`).
- **Gender:** every match row sampled reads `MALE`, so the league is boys only. The scraper
  asserts this rather than assuming it (see Failure handling).
- **No team names.** The roster carries ids only, so a display name is built as
  `"{club} {U-age} {tier}"`, e.g. `Emerald City FC U13 EA`.
- Match rows (`/public_schedule/league/get_matches?tournament=27…`) use the same markup as MLS
  NEXT and show only the club name, the academy id (in the crest URL), the age and the bracket,
  **never the team id**.

## Component 1 — `scripts/scrape_modular11_ea.py` (roster + games; renamed from `scrape_modular11_ea_teams.py` once it took on games)

Fetches the page, parses the roster, and writes
`data/modular11_ea/teams_<YYYYMMDD>.csv` with one row per `UID_team`:

| column | example |
|---|---|
| `provider_team_id` | `7155` (`UID_team`) |
| `academy_id` | `1386` |
| `club_name` | from `js-academy` |
| `age_group` | `u13` (stored form) |
| `tiers` | `EA;EA National`, sorted, `;`-joined |
| `regions` | region names, `;`-joined |
| `gender` | `Male` |
| `team_name` | `{club} U13 EA`, built from the lowest tier the team plays in (EA before EA2; National is never the name tier) |

The script makes plain `requests` calls with no Scrapy. It is read-only against the provider and
writes no database rows, so it needs no `--dry-run`. It takes `--out` to choose the output path.

### Failure handling

The script exits non-zero, and writes no CSV, when:
- the `dependencies:` array is missing or does not parse;
- an age, bracket, region or academy code is not in the page's own lookup lists or the
  age mapping (a new code means the site changed, so the script must not guess);
- fewer than 1,000 unique teams are found, a floor set against today's 1,239.

## Component 2 — `scripts/match_modular11_ea_teams.py`

Reads the CSV and live (non-deprecated) `teams` rows, read-only. Writes
`data/modular11_ea/match_report_<YYYYMMDD>.csv` and prints a summary of counts per bucket and
per tier.

**Candidates** for an EA team are live teams that have:
- the same gender (`Male`) and the same `age_group`;
- a club that matches the EA club name after normalization (reuse `normalize_club_name` from
  `scripts/match_modular11_teams.py` or `src/utils/club_normalizer.py`, whichever that script
  uses, rather than writing a third one);
- the **same tier marker** in the team name: whole-word `EA` for EA, whole-word `EA2` for EA2.
  `EA` must not match inside `EA2`.

**Never a candidate:** a team whose name carries `HD`, `AD` or `MLS NEXT`, or a team that is
already a `modular11` provider row.

**Buckets:**
- **Confident link:** exactly one candidate.
- **Needs review:** more than one candidate, or the club and age match but the name has no tier
  marker (an untagged tournament team that may or may not be the EA squad).
- **No match:** no candidate. In a later step these become new teams.

Each report row carries the EA team's columns, the bucket, and for every candidate its
`team_id_master`, `team_name`, `club_name`, provider and state, so a reviewer can decide from the
file alone.

Teams are read in pages ordered by a unique column, with `.in_()` batches of 100 or fewer.

## Component 3 — GitHub Action "EA Scraper"

`.github/workflows/ea-scraper.yml`, with `name: EA Scraper`. The user asked for it by that name.

- **Trigger:** `workflow_dispatch` only, with a required `age` choice input (`u11` … `u19`, the
  ages in the EA roster). One age per run, so no cron in step 1.
- **Steps:** check out, install `requirements.lock`, run the roster/games scrape and then the match
  report for the chosen age, and upload `data/modular11_ea/<age>/` as an artifact
  (`ea-scraper-<age>-<run id>`). A step fails when either script exits non-zero. The step summary
  prints team, game and bucket counts, so a green run with zero games is visible at a glance.
- **Secrets:** the match report reads `teams`, so the job needs `SUPABASE_URL` and the service
  role key. No `ZENROWS_API_KEY`: the scrape is direct and unproxied.
- **Concurrency:** group `ea-scraper`, so two runs never overlap. No database writes in step 1,
  so it is not on the `AGE_ROLLOVER_FREEZE` list yet. It joins that list when it starts importing.

## Context for the review

About 1,400 live teams already have whole-word `EA`/`EA2` in their names: roughly 880 GotSport,
280 TGS and 210 SincSports, with 9 from `modular11`. The existing protected-division guard
(`has_protected_division`, `scripts/find_queue_matches.py`) keeps EA, HD, AD and MLS NEXT names
out of general fuzzy matching. This report does **not** loosen that guard. It is its own
same-tier rule, applied only to EA league teams.

## Testing

- **Scraper:** a saved copy of the EA page as a fixture. Assert the team count, a known team's
  row (tiers merged, age `u13`, region names), and that each failure case above exits non-zero.
  Write one fixture per failure, each breaking exactly one thing.
- **Matcher:** drive the composition (`main`/`run`) through a Supabase double that records at
  `execute()`, per CLAUDE.md. Fixture rows cover: one EA candidate → confident; EA2 squad vs EA
  team → no candidate; a `U13 HD` team → excluded; two EA candidates → review; untagged club+age
  team → review; and a deprecated row → ignored.
- Mutation-check the tier rule (`EA` vs `EA2`) and the HD/AD exclusion one conjunct at a time.

## Later steps (each needs its own approval)

1. **Write teams:** create a `modular11_ea` provider row, write the approved links as
   `team_alias_map` rows, and create the no-match teams with full metadata. This needs a
   `--dry-run`. State is unknown from the roster, so regions are the only geography;
   state assignment goes through the `assigning-team-states` flow, not a guess.
2. **Importing game results:** the games are scraped in step 1 (see Revision). Importing them goes
   through `import_games_enhanced.py` under `modular11_ea`, one age at a time. The 39
   same-club, same-age pairs are settled by the per-team schedules and match-number pairing.
3. **Workflow:** once importing works, add an import step to "EA Scraper", decide on a schedule,
   and add it to the `AGE_ROLLOVER_FREEZE` gate list and its coverage test.

## Non-goals

- No change to the MLS NEXT spider, `src/models/modular11_matcher.py` or the `modular11-*.yml`
  workflows.
- No database writes in step 1.
