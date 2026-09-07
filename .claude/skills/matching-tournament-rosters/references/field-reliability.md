# Field reliability

How far each `teams` column can be trusted, and why none of them belongs in a WHERE clause.

## Contents

- The rule
- gender
- age_group and birth_year
- state_code and state
- club_name
- is_deprecated
- unknown_ placeholders
- What fresh rows are missing
- Same-name rows

## The rule

Retrieve on the name space. Return the attribute columns and score agreement as a bonus; score
disagreement as close to no penalty at all.

Every attribute predicate is also an implicit NOT NULL filter, and null rates are worst on exactly
the rows a current roster needs. The candidate pool for one cohort in one state is a few thousand
rows — small enough to rank in full, so the filter buys nothing and can lose the answer.

Rates below were measured against the live table. Treat them as the shape of the problem rather than
as constants; the direction of each has been stable, the decimals have not.

## gender

Reliable, and usually unverifiable from the name.

- Around 87% of `team_name` values carry no gender token at all. Where normalisation ran it stripped
  the token; `team_name_original` keeps it, on the rows that have an original.
- Where a name does carry an unambiguous token, the stored value contradicts it on roughly 0.4% of
  rows — about one in 260. Stored gender is overwhelmingly right.
- Contradictions skew heavily toward recently created rows, but they are not exclusively recent: the
  earliest sits about ten months back, and a small minority predate the last six months. Row
  recency raises the risk; an older row is not thereby cleared.

So a gender predicate does little harm and little good — but it cannot be checked from `team_name`,
and it is the wrong tool for splitting two same-named rows. Read `team_name_original` before ever
concluding a row's gender is wrong. If the original carries a `B`/`G` token, the stored gender was
derived from it and is right.

## age_group and birth_year

The single most damaging predicate on fresh rows.

- Against the birth year printed in the team's own name, `age_group` disagrees on around a third of
  rows created since the last rollover — roughly twenty times the all-time rate. Errors run in both
  directions.
- Where a name carries a U-age token, the stored cohort matches it only about one time in four.
  Stored exactly one cohort **higher** is the single most common outcome — commoner than a match —
  because the label is a season behind. Read a U-age in a stored name as "this cohort or one lower".
- For two-birth-year band names the younger-year rule holds only about half the time, and for names
  with two full 4-digit years the stored value usually follows the **older** year.

`birth_year` is a rare field rather than an unreliable one: it is NULL on roughly 92% of rows and on
essentially every row created since the rollover, but where it is set it agrees with `age_group`
almost perfectly — on the order of fourteen disagreements across sixteen thousand rows. Use it when
present; do not expect it.

When age must be narrowed at all, accept the cohort either side of the believed one. For a two-year
band token, both cohorts are legitimate — the split runs roughly three to one toward the younger
year, so filtering to the younger alone discards about a fifth of true candidates.

## state_code and state

`teams` has two state columns and the obvious-looking one is abandoned. `teams.state` is NULL on
essentially all rows created since the rollover; `state_code` is the live column.

`state_code` is populated on nearly every row, which is why it gets used as a hard filter. Where it
can be checked against a state printed in the team's own name it is wrong about one time in eight,
and the errors are unrelated neighbouring states with no pattern to correct for. Some team names
appear on rows carrying several different state codes.

## club_name

Absent or empty on a large minority of rows, and roughly three and a half times worse on fresh rows
than overall — around 39% against 11%. The club's distinctive word is missing from `team_name` on
about half of all rows.

It also cannot disambiguate: about a fifth of duplicate-name groups carry more than one distinct
`club_name`, and the values are sometimes simply wrong — two rows both named `Barca Academy Austin
ECNL RL STXCL 2013` carry `JS Legends` and `Legends FC - San Antonio`, neither of which is Barca.

## is_deprecated

Around 5% of rows are deprecated, and they look alive from every angle a search can see: about half
share an exact `team_name` with a live row, most still carry games, and their scrape timestamps are
as recent as live rows'. Game counts and `last_scraped_at` do not distinguish them.

Check `is_deprecated` explicitly and resolve the survivor through `team_merge_map` rather than
inferring it from activity. When every name-matched candidate is deprecated the merge map resolves
all but about twenty rows table-wide — so never report "not in the database" for that case, and
where the map has no entry, say so rather than inventing a survivor.

## unknown_ placeholders

Rows named `unknown_<provider_team_id>` are real, numerous, and concentrated in recent ingests —
they can be the majority of a single day's new rows. Every one has at least one game, and many
already have scored results. They carry a valid `team_id_master`, `state_code` and `age_group`, and
are missing only the name.

Around one current-season game in six has a side pointing at one of these. Treat `unknown_` as
*unnamed but identified*. A roster row with no name match may already exist as one; creating a fresh
row would duplicate a team that already holds results.

They never surface in a name-similarity search, because they share no trigrams with a real club
name. They have to be looked for deliberately, by cohort and state.

## What fresh rows are missing

Rows created since the last rollover arrive stripped of the metadata a matcher would want:

| Column | Fresh rows | Older rows |
|---|---|---|
| `league` | never set | set on a minority |
| `distinction` | almost never set | set on most |
| `birth_year` | almost never set | set on a small minority |
| `club_name` | absent on a large minority | mostly present |
| `team_name_original` | mostly NULL | mostly present |

The data-hygiene backfill fills these in later in a row's life, so a fresh row and its prior-season
twin always read as a mismatch on them. Comparing `distinction` or `league` across the two seasons
therefore proves nothing. Only `club_name`, `state_code`, `age_group`, `gender` and `team_name` are
comparable across the two at all.

## Same-name rows

A meaningful share of the table shares a `team_name` with at least one other row. Within those
groups, most span both genders, and a minority span several age groups or state codes. Gender is
therefore not a tiebreaker between same-named rows — choosing on it is choosing arbitrarily.

The disambiguator has to come from game evidence: which row holds the fixtures, in which
competition, against which opponents.
