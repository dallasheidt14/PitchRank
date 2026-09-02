# MatchBalance Seeding Intake — Design

- **Date**: 2026-09-02
- **Status**: draft, awaiting review
- **Mode**: seeding (upcoming tournaments). The backtest path is untouched.

## Problem

A tournament director sends a list of accepted teams for an event that has not been played
yet, and asks us to seed it. Today there is no way to get that list into MatchBalance.

The existing intake (`tournament_intake.py`) takes a provider event URL and scrapes it.
That works for backtests, where the event has already happened, but it cannot serve seeding:
`GotsportScraper.fetch_teams_by_cohort` discovers teams by reading **schedule** pages, and an
upcoming tournament has no schedule — producing one is what we are being asked to help with.
The app already models both modes and disables the one we need: `_resolve_intake_mode`
(`tournament_intake.py:163`) coerces every request for `seeding` back to `backtest`.

So the pasted list is the input, and the job is to turn team names into `team_id_master`
values with as little operator time as possible.

## The key finding

**GotSport publishes a public, unauthenticated team search, and its team IDs are the same
IDs we already store.**

```
GET https://system.gotsport.com/api/v1/team_ranking_data
    ?search[team_country]=USA
    &search[age]=14           # U-age, not birth year. Required.
    &search[gender]=m         # m | f. Required.
    &search[page]=1
    &search[team_or_club_name]=Barcelona SC 13B Aztecas
```

```json
{"team_ranking_data": [{"team_id": 534748,
                        "team_name": "Barcelona SC 13B Aztecas",
                        "club_name": "Barcelona Soccer Club", ...}],
 "pagination": {"current_page": 1, "total_pages": 1, "total_count": 1}}
```

This is the endpoint behind the green "Team Rankings Search" on `rankings.gotsport.com`,
found by reading that site's JS bundle (`/assets/index-*.js`). It needs no login, returns
JSON, and is not CAPTCHA-gated.

The returned `team_id` **is** our `teams.provider_team_id` / `team_alias_map.provider_team_id`
for the `gotsport` provider. It resolves to a `team_id_master` by direct lookup — the
100%-confidence tier of the matching hierarchy, not a fuzzy score.

Why it matches so well: the rankings index and the tournament's accepted-teams list are both
generated from GotSport registration, so the roster string is usually the stored string.

**Only `team_id` is used.** GotSport's own `national_rank`, `state_rank` and `points` are
deliberately discarded — PitchRank's ratings are the product.

## Evidence

Measured 2026-09-02 against a real GotSport accepted-teams list: one Texas event, 105 teams
across four Boys cohorts (U11–U14).

| Route | Teams resolved |
| --- | --- |
| GotSport ID lookup | 56 |
| Exact name already in `teams` | 37 |
| **Either** | **84 of 105 (80%)** |
| Left for the operator | **21 (20%)** |

- **All 58 GotSport IDs resolved.** Every one was present in `team_alias_map`, approved and
  GotSport-owned; 53 were also directly on `teams`. Zero misses.
- **A single hit is not proof of identity.** `team_or_club_name` matches club names too, so 2
  of the 58 named a different club's squad — searching `Pre-ECNL B2014/15 Gold` for a San
  Antonio City SC team returned one row named `Beach FC Pre-ECNL B2014/15 Gold`. The resolver
  requires the returned name to match the roster name and sends the rest to review, which is
  what takes the id route from 58 to 56.
- The GotSport route rescued **49 teams that exact-name matching could not find**, including
  `Barcelona SC 13B Aztecas` → `Barcelona SC Aztecas U14`.
- 105 lookups took about a minute at a 0.4s delay.

### Why 44 lookups returned nothing

The rankings index holds only teams with enough ranked games, and stores GotSport's *current*
team name, which is not always the name the tournament registered. Searching the same name at
age ±1 does not help — those names are absent from the index, not misfiled. Searching the club
name does return the club's ranked teams at that age, but under names that need judgement to
match, so it belongs in the review sheet rather than the automatic path.

### Roster string markers

Two suffixes appear on the roster and nowhere in our data.

- **`-c`** — 15 of 105. Meaning unknown.
- **`*`** — 6 of 105. In 5 of those the birth year in the name is one cohort younger than the
  section heading, which reads as *playing up*. The sixth (`Gt18 B16*`) does not fit.

**8 of the 105 only matched after stripping them**, so the lookup tries the raw string first
and the stripped string second. Both markers are recorded as flags so their meaning can be
established from accumulated data rather than guessed.

### The heading is authoritative

`BLACK LIONS 14/15 U13B SELECT` sits in the U13 section, but its band (younger year 2015) is
U12, and it carries no `*`. The cohort token inside a team name is a hint, never a decision.
The section heading wins, and it is what the `search[age]` parameter is built from.

## Architecture

Four stages. Only stage 2 touches the network.

### Stage 1 — Parse (`src/tournaments/roster_paste.py`)

Input: pasted text or a file path. Output: an ordered list of `RosterRow`.

Carries section-heading state (`Male U14`) down onto each row until the next heading. Skips
the `Teams Accepted (n of m)` counter and the `Club Team State` header row.

| Field | Meaning |
| --- | --- |
| `source_index` | Position in the list. Ordering is preserved throughout and is the round-trip key. |
| `club_raw`, `team_name_raw`, `state` | Verbatim, never modified. |
| `section_age_group`, `section_gender` | From the heading. Authoritative. |
| `team_name_stripped` | `*` and trailing `-c` removed. |
| `has_star_marker`, `has_c_marker` | Preserved for later analysis. |

Malformed rows (wrong column count, a row before any heading) collect into `parse_warnings`
and surface in the report; they never abort the run.

### Stage 2 — Resolve (`src/tournaments/roster_resolver.py`)

Two passes per row, stopping at the first that yields a single confident answer.

**Pass A — GotSport ID.** Query `team_ranking_data` with the section's age and gender and the
raw team name; if that returns nothing and the name carried a marker, retry with
`team_name_stripped`. On exactly one result, take `team_id` and resolve it locally:

1. `teams.provider_team_id = <id>` where not deprecated, else
2. `team_alias_map.provider_team_id = <id>` → `team_id_master`

then run the result through `MergeResolver`, because an alias can point at a team that has
since been merged away.

More than one result goes to the review sheet with the candidates attached — never
auto-picked.

**Pass B — exact local name.** Case-insensitive exact match of `team_name_stripped` against
`teams.team_name`, constrained to the section's cohort and gender. Accepted only when it
returns exactly one row; otherwise the row goes to review.

Pass A runs first because it is an identity lookup. Pass B is a name comparison and is
demonstrably weaker — of the 37 rows it matched, only 26 were unique within the right cohort.

Anything unresolved after both passes goes to stage 3.

**Politeness.** Serial requests with a fixed delay (0.4s measured comfortable), a bounded
retry on transient errors, and a `--max-lookups` ceiling. This is someone else's public
endpoint and the volume is small; there is no case for concurrency.

### Stage 3 — Review sheet

The unresolved rows (about 18%) go to an `.xlsx` with candidates attached so the choice is a
pick, not a search. Candidates come from two cheap sources:

- the GotSport club-name search at that age, which returns the club's ranked teams;
- `event_team_matcher.rank_db_candidates` over the local cohort — reused as-is, since it
  already handles coach surnames, program tiers and colours.

Sheets: **Resolved** (what matched and by which pass), **Review** (one row per unresolved
team, its candidates, and an empty `chosen_team_id_master`), **Notes** (parse warnings, marker
counts, data problems seen in passing).

The operator fills `chosen_team_id_master` and re-runs with `--apply <xlsx>`. Decisions key on
`source_index`, so a re-run applies them without re-asking and without repeating stage 2.

### Stage 4 — Estimate

Whatever is still unresolved after review gets a stand-in strength so it can be seeded, since
intake must never block. First rung that produces a value wins:

1. mean `power_score_true` of the club's teams at the cohorts either side;
2. mean across all of that club's ranked teams;
3. state-and-cohort median.

Flagged `strength_source = estimated_*` and never presented as a real rating.

## Output contract

Writes `event_team_registry.csv` in the existing format (`storage/registry.py` `FIELDNAMES`)
so storage, resume and the Report Card keep working unchanged. `resolved_gotsport_provider_team_id`
carries the GotSport id and `canonical_resolution_status` is `direct_provider_id` for pass-A
rows, which is what that column already means.

Seeding-only fields (`has_star_marker`, `has_c_marker`, `strength_source`, `resolution_pass`)
go in a sibling `seeding_intake_meta.csv` keyed on `event_registration_id`, rather than
widening a format the backtest CLI also reads.

A pasted list has no provider registration id, so `event_registration_id` is
`paste_<source_index>`, stable across re-runs because ordering is preserved.

## CLI

```
python scripts/seed_intake.py --roster <path> --event-key <key> [--dry-run] [--apply <xlsx>] [--max-lookups N]
```

`--dry-run` writes nothing and makes no network calls.

## Testing

- **Parser**: golden-file tests from the four real cohorts, including
  `Mortega Soccer Club Laredo Youth Soccer Academy` (a club string that looks like two clubs),
  `Fenómenos 2015` (non-ASCII), every `*` and `-c` row, and `BLACK LIONS 14/15 U13B SELECT`
  (heading disagrees with the name's own band).
- **Resolver**: against a stubbed HTTP client and a stubbed database. No network. Covers
  one hit, zero hits, several hits, marker-retry, an id found only via `team_alias_map`, and an
  alias pointing at a merged-away team.
- **Estimator**: each rung, plus the empty-club case.
- Assertions are scoped to the statement under test, per the repo's verification rule.

## Rejected alternatives

- **Scrape the event's own team list.** `/org_event/events/{id}/teams?showall=groups` exists
  and is not CAPTCHA-gated, but returns "Team List is not available for this event" on both
  events tested — organisers switch it off. `/clubs` does work and returns the participating
  club list, which is not team-level.
- **Enqueue unresolved teams for scraping.** `enqueue_scrape_request` is keyed on
  `team_id_master`, so a team with no row cannot be enqueued. The only route would be
  scraping the club's known teams and hoping the squad appears as an opponent — indirect,
  slow, and unnecessary now that resolution reaches 82%.
- **Club-scoped fuzzy matching as the primary path.** Was the previous design. The GotSport
  ID route makes it redundant; it survives only as a candidate source for the review sheet.
- **Using GotSport's published rank or points.** Out of scope by decision — PitchRank's own
  ratings are the product.

## What shipped (2026-09-02)

A first cut, driven from a **Seeding** tab in `tournament_intake.py` rather than a CLI. The
app's existing flow moved unchanged into a **Backtest** tab beside it; the triage screen was
not touched.

| Piece | State |
| --- | --- |
| `src/tournaments/roster_paste.py` — heading-aware parser, marker split | shipped, 15 tests |
| `src/tournaments/roster_resolver.py` — both passes, search contract, Supabase lookups | shipped, 21 tests |
| Seeding tab — paste box, progress, per-row table, CSV of rows needing a decision | shipped |
| `event_team_registry.csv` output | **not yet** |
| `--apply` decision round trip | **not yet** — the CSV is currently read-only |
| Stage 4 estimate ladder | **not yet** |
| `scripts/seed_intake.py` CLI | **not yet** |

Verified end to end against the live endpoint and the production database: of six mixed
teams, two resolved by GotSport id, one by exact name, two went to review and one was
unresolved — every branch exercised on real data.

An earlier draft of this document listed "build it into the Streamlit app" as rejected. That
was overturned by the operator, who asked for a tab; the reasoning against it applied to
reusing the triage screen, which this does not do.

## Open questions

- **What does `-c` mean?** Carried as a flag until enough events accumulate to tell.
- **`Gt18 B16*`** is the one `*` row that does not fit the playing-up reading.
- **Girls cohorts and non-Texas events are unmeasured.** The 82% figure comes from one Boys
  event in one state; the parser and resolver are state-agnostic, but the rate is not yet
  known to generalise.

## Data problems noticed (not fixed here)

Backlog material rather than part of this change:

- The same club exists under two names: `Mortega SC` and
  `Mortega Soccer Club Laredo Youth Soccer Academy`.
- `SA Athletic FC Wolves 14/15B Blue` is filed at `u13`; its band (younger year 2015) is `u12`.
