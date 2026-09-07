---
name: matching-tournament-rosters
description: "Matches an external tournament, event or league roster (club name, team name, state — often pasted as a tab-separated block) against the PitchRank teams table read-only, and builds an .xlsx report giving each matched team its national and state rank, PowerScore, ranking status and game counts. Use when handed a list of teams and asked which of them exist in the database, to check which of a tournament's accepted teams we hold, to cross-reference or look up an event or league roster, to export a list of teams with their rankings, to seed or preview a bracket from a submitted team list, or to resolve team names to team_id_master UUIDs."
---

# Matching tournament rosters

A roster names teams as the provider registered them this season. The database stores them under a
different cohort convention, often from a different season, and sometimes under a normalised name.
Matching on name shape alone produces confident wrong answers, so every match is decided from the
row's own fixtures.

This is a read-only lookup. Run every query through `mcp__supabase__execute_sql`, which is read-only
by construction — that is what makes the guarantee hold. Duplicates and misfiled rows found along
the way are reported, never merged or corrected; hand those to the `merging-duplicate-teams` skill.

Copy this checklist and check off items as you complete them:

```
Task Progress:
- [ ] Step 1: Read the roster and decompose each row
- [ ] Step 2: Retrieve candidates from the name space alone
- [ ] Step 3: Decide each candidate from fixtures
- [ ] Step 4: Pick one row per roster row
- [ ] Step 5: Build the report
- [ ] Step 6: Report the headline and the gaps
```

## Retrieval rules

**Search `team_name` both verbatim and normalised.** `team_name` is normalised only on rows that
also carry a `team_name_original` — there the gender letter is stripped and a 2-digit year expanded,
almost without exception. On rows with no original, which is nearly everything the current season
creates, no normalisation was recorded and `team_name` is often the provider's literal string,
gender letter and all. So the registered string may match `team_name` exactly. Retrieval must run
against `team_name` regardless: it is the only trigram-indexed column. Read `team_name_original`
from the rows already fetched — where it exists it is the authoritative gender and cohort check, and
a NULL is no evidence either way.

**Keep attributes out of the WHERE clause.** `gender`, `age_group`, `state_code` and `club_name` are
ranking signals, never predicates. Each is wrong or missing often enough to discard the correct row,
and fresh rows are the least reliable —
[references/field-reliability.md](references/field-reliability.md) carries the measured rates.

**Translate the cohort token before searching, and never filter on it.** A roster `BU13` is a birth
year, not a string to match: convert through the season (`age = season_end_year − birth_year`, U18
folded into U19), then search every spelling that birth year takes. Most current-season rows carry
no cohort token at all, so its absence proves nothing.

**Absence needs its own test.** The `%` similarity operator always returns a plausible ranked list —
a fabricated club name returns hundreds of rows built from `United`/`FC`/`SC` collisions. Decide "we
do not have this club" with a `<%` probe on the single most distinctive token, which does return
empty.

## Step 1: Read the roster and decompose each row

The roster arrives as a pasted tab-separated block with a header row, or as a path to a `.csv`,
`.tsv` or `.xlsx`. Read it into an ordered list and keep that order — every later step keys on a
row's position in it, and Step 5 reconciles against its length.

A roster without a state column is normal. State is a ranking signal rather than a predicate, so
matching is unaffected: leave `roster_state` empty. The one query that needs it is the `unknown_`
placeholder sweep in Step 2 — run that across every state the club's other rows appear in, and rank
on opponent overlap alone.

Split each roster team name into club, league/flight tokens, cohort token, and qualifier tail. Read
[references/name-decomposition.md](references/name-decomposition.md) for the token vocabulary, the
cohort-token shapes, and the club-matching rules that trigram similarity cannot handle on its own.

Import the repo's own parser rather than writing a regex: `src/utils/team_name_utils.py` is DB-free
and import-safe. Use `birth_years()` on the **raw** name, and `extract_distinctions(name)` — one
positional argument — whose `coach_name` key already holds the parsed surname tail.

The qualifier tail carries most of the identifying signal. A surname or mascot tail is close to
definitive; a colour is nearly worthless on its own.

## Step 2: Retrieve candidates from the name space alone

Search on the club token and the qualifier tail, across `team_name` and `club_name` independently,
and union the results — a club's identifying word is absent from `team_name` on about half of rows,
and the roster's club string may share nothing with either.

Batch the retrieval rather than querying per roster row. Pull one candidate pool per cohort and
gender with the distinctive tokens passed as `= ANY(:tokens)`, hold it in memory, and score the
roster against it. Reserve per-row queries for the fixture check in Step 3, and run those only for
rows that survived scoring. A roster of a few dozen rows can be done row by row; a roster of several
hundred cannot, and the MCP result cap will stop you partway.

Use the recipes in [references/search-recipes.md](references/search-recipes.md). They cover which
pg_trgm operator to use in which direction, why `SET pg_trgm.*` silently fails across calls, and how
to probe for absence.

Include deprecated rows and `unknown_<provider_team_id>` placeholders in the candidate pool. A
placeholder is an identified team missing only its name, and it often already holds the fixtures the
roster row refers to.

## Step 3: Decide each candidate from fixtures

Read the candidate's own games — `competition` and opponents. `games.division_name` is empty on
current-season rows, so filter on `competition`.

A current-season registration looks like a row created in the most recent ingest batch carrying
several future-dated fixtures with NULL scores. Requiring a scored game rejects about two thirds of
valid current-season rows; requiring a PowerScore rejects more than three quarters.

The discriminator between the live row and its dormant prior-season twin is **a fixture dated in the
current season**. It is not clean: a substantial minority of older rows were reused rather than
re-created, so absence of a current fixture weakens a candidate rather than eliminating it.

Record the sentence that decided each row as you go. It becomes the report's `match_basis`, and it
is the only column from which a reader can audit the pick.

Before concluding a roster row is absent, confirm the ingest clock — registrations land in weekly
batches, so a name missing today may simply predate this week's run. The query is in
[references/search-recipes.md](references/search-recipes.md).

## Step 4: Pick one row per roster row

Every roster row ends up in exactly one of `matches` or `unmatched`. Alternates belong in the
Alternates column, never as extra rows.

Assign a tier:

| Tier | Meaning |
|---|---|
| A | Current-season registration row, confirmed by a fixture in the expected competition |
| B | Prior-season row for the same club and cohort; identity inferred from the name, not proven |
| C | Two or more candidates fit equally well; one reported, the rest named in Alternates |

A row settled only by recency — `created_at`, or an arbitrary tiebreak — is still tier C. Say what
the alternates were.

Put a roster row in `unmatched` when nothing defensible matches; it is carried into the Notes sheet
rather than the Matches sheet. Resolve a deprecated pick through `team_merge_map` and report the
survivor; the map resolves all but about twenty deprecated rows, and where it has no entry, say so
rather than inventing a survivor.

A provider registration ID cannot link a squad's two seasons. No `(provider_id, provider_team_id)`
pair is ever shared by two canonical teams, and the provider mints a new ID each season, so an ID
lookup for a current roster name returns nothing. A bare `provider_team_id` on its own is not unique
— thousands are shared across two teams from different providers — so always pair it with
`provider_id`. Squad continuity comes from club plus game evidence, or from `team_merge_map` where
someone has already made the link, and usually nobody has.

Read the surviving row's `team_alias_map` entries, joined to `providers`, for the provider codes and
registration IDs the report needs.

## Step 5: Build the report

Read [references/reading-the-rankings.md](references/reading-the-rankings.md) before selecting any
rank or game count. `rankings_full.national_rank` and `.state_rank` are always NULL; the published
values live in `state_rankings_view`, whose `gender` comes back as `F`/`M` and whose `age` is a bare
integer.

Assemble the JSON payload:

- `title`, `season`, `generated`, `ranking_run` — strings. `ranking_run` is
  `SELECT max(last_calculated) FROM rankings_full`; `generated` is today; `season` is the current
  soccer season as `YYYY-YY`.
- `matches` — one object per matched roster row, keyed by the second element of each tuple in the
  script's `COLUMNS` list. Every value is a string, number, or null; join multi-valued cells
  (`provider_ids`, `alternates`) with `"; "`.
- `unmatched` — one object per omitted roster row, keys `roster_club`, `roster_team`, `note`.
- `notes` — a flat list of strings, one finding per entry.

Then, from the repo root:

```bash
python .claude/skills/matching-tournament-rosters/scripts/build_roster_report.py \
  --input .turbo/<slug>-roster.json --out ~/Downloads/<slug>-roster-report.xlsx
```

The script asserts that `matches` and `unmatched` together account for every roster row — pass
`--roster-rows <n>` so it can. It needs `openpyxl`, which is in neither requirements file; it falls
back to CSV plus a notes text file when the import fails or the workbook cannot be written.

## Step 6: Report the headline and the gaps

Lead with the count matched and the single most important finding, then hand over the file.

Name explicitly:

- Roster rows omitted, and what the club does hold instead
- Duplicate clusters found, with UUIDs, for `merging-duplicate-teams`
- Rows whose stored fields look misfiled, with the evidence that says so
- Any team whose newest scored game postdates the last ranking run, so its rank predates that result

State the date the ranks were read and the run they came from. Rank membership is recomputed on
every read while the scores are frozen at the run, so a figure without its timestamp is not
reproducible.
