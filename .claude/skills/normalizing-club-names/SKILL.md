---
name: normalizing-club-names
description: "Restores and standardizes PitchRank teams' club_name from the provider, the team's own name and the weekly cleanup's log rather than one heuristic, with every write compared against the value it read and reversible from its log. Use when asked to fix a club name, repair swapped, all-caps or mis-cased club names, restore names the importer overwrote, review or approve club-name proposals, undo a club-name batch, decide which club a team belongs to, check whether the weekly club cleanup damaged a name, or investigate why a team is filed under a club it does not belong to."
---

# Normalizing club names

A club name is not an identity key, and treating it as one is what puts wrong values in
this column: a blank collapses unrelated teams together, and one club split across two
spellings reads as two clubs. Two faults wrote most of the wrong values — the importer
replaced an incoming club with whichever canonical club the normalizer matched it to, and
the weekly cleanup re-cased names that were already right.

Downstream this column decides what a duplicate is. The fuzzy scan compares candidates on
byte-identical lowercased `club_name`, so a team under a variant spelling is invisible to
it at any threshold — fixing a name here is what makes that pair proposable.

`scripts/repair_swapped_club_names.py` does the work. Run it from the repo root: its
exports directory and its `.env.local` lookup are both relative to the working directory,
so a run from elsewhere puts the snapshot and its only undo record somewhere else. A list of
club moves a person has already decided team by team goes through
`scripts/apply_vetted_club_names.py` instead (**Applying a hand-vetted list** below).

Copy this checklist and check off items as you complete them:

```
Task Progress:
- [ ] Step 1: Preflight — the self-check, credentials, and the run logs the abbreviation source reads
- [ ] Step 2: Take a snapshot with a dry run
- [ ] Step 3: Read the evidence before approving anything
- [ ] Step 4: Rehearse the replay, then apply it and verify against the database
- [ ] Step 5: Record what ran, and what you could not decide
```

## Propose-only mode

Run Step 2 and stop. The dry run **writes nothing to the database**; it leaves a snapshot
CSV under `data/exports`, named on the run's last line. Resume at Step 3 to approve rows,
or hand the snapshot on as it stands.

Nothing is written at this stage, so there is nothing to undo — `--revert` replays an apply
log, and no log exists until Step 4 runs.

## What each source is worth

Each proposal carries the `source` that made it and a `tier`. The tiers decide which rows
arrive approved and which arrive listed for a person to read.

| `source` | `tier` | Weight |
|---|---|---|
| `playmetrics` — that league's own club for the team id | `provider` | Decides. The provider's record of its own registration. |
| `team_name` — the team's own name, to its first age or level token | `swap` | Decides. The stored club is still the canonical upper case the importer wrote, which is that fault's signature. |
| `team_name` | `recased` | Listed. The cleanup has since re-cased the stored club, and a squad label reads the same way. |
| `team_name` | `unclear` | Listed. No level token, fewer than two words, or a name opening with one run said twice. |
| `abbreviation` — the weekly cleanup's own log | `word`, `bracket` | Decides. The rename only lowered an all-caps run or an all-caps bracketed segment. |
| `abbreviation` | `capital` | Listed. The rename re-cased a word holding a capital some other way, which the cleanup may have been right to do. |

GotSport and PlayMetrics teams are excluded from the `team_name` source: GotSport's clubs
come from GotSport, and PlayMetrics has its own source above. NEFC is excluded by stored
club, because it is a genuine all-caps registered club and would otherwise read as the
importer's signature.

No measured yield exists for these tiers yet. Record one the first time a batch runs.

## Hold rather than write

- **Two sources propose different clubs for one team** — *automatic*. The row arrives
  `needs_review` and unapproved. The snapshot keeps only the first proposal, in source
  order, so the losing offer exists only in the run's terminal output — capture that output
  before closing it. To take the other value, edit `proposed_club` by hand; the replay
  checks the row's shape, not its provenance.
- **The team's state disagrees with its league's** — *automatic*, as `state_note` on the
  row. The matcher derived that state from the swapped club, so the state is wrong too.
  Leave it here and fix it through the `assigning-team-states` skill, which decides a state
  from ranked evidence; writing one from this side would be a guess.
- **A club branch is not its parent** — *not enforced in this script*. "Albion SC San Diego"
  is its own club, and a proposal that shortens a branch to its parent merges two clubs. Read
  any proposal that drops a place or a qualifier from the stored club. One fold is approved,
  so do not read *it* as damage to repair: MVLA East and MVLA San Jose belong to "Mountain
  View Los Altos Soccer Club" by the owner's call of 2026-09-30, recorded beside the entries
  in `scripts/full_club_analysis.py`. It does not generalize — the next branch is still a
  question for the owner, and `tests/unit/test_club_overrides_keep_provider_branches.py`
  holds the default rule.

## Judging a listed change

A listed row is a guess, and each listed tier guesses a different way, so read it by how it
was made:

- **`capital`** restores a spelling the weekly cleanup replaced: that cleanup re-cased the
  proposed spelling to the stored one ("SoCal" to "Socal", "La Jolla" to "LA Jolla") on every
  team of the state holding it. So in that state the stored spelling is expected to be the only
  one, and the proposed one held by no team: that is the damage, not evidence against the
  restore. Judge it by the team and registered names, the club's spelling in other states and
  how the club writes its own name; the restore is right when the proposed spelling is that
  name.
- **`recased`** is the team name up to its first age or level word, where the stored club no
  longer matches it. A squad label reads exactly the same way, so it is suspect by default.
- **`unclear`** is where the scan could not tell where the club ends in the team name.
  Suspect by default.
- **A deciding tier left unapproved** (two sources disagreed) carries the offer the scan
  kept; the other is in the propose log. The kept offer is right only when the other is
  plainly wrong; the stored club stands only when it is right; otherwise a person decides.

Whatever the tier, these mean the proposal is wrong:

- **A squad label is not a club.** Age, birth year, level (ECNL, RL, NPL, Academy, Elite,
  Premier), colour, coach surname, gender, or a league or state tag in the proposed name
  ("LSC White USC TX RL", "Galaxy '12") means the name was cut in the wrong place.
- **An abbreviation for a full name** ("Concorde Fire" to "CF", "Solar SC" to "SOLAR") is
  wrong unless the club itself writes the short form, which the name its other teams carry
  shows.
- **For `recased` and `unclear`, a proposed name no team uses** while the stored one is what
  the club's other teams carry: the stored name is likely right. Not for `capital`, above.

And these are a person's call: a spelling right in one state and wrong in another, and an
unresolved conflict between two sources. A club name is text, never an identity: judge only
whether the text is the club's name, never whether two teams are one, and leave a state note
to the `assigning-team-states` skill.

## Step 1: Preflight

**Prove this skill is still true.** Run the self-check before trusting the rest:

```bash
python scripts/check_club_skill_assumptions.py --code-only
```

`scripts/check_club_skill_assumptions.py` turns this skill's claims about the code into
assertions (the tier table under **What each source is worth** against the scan, the saved-log
reader, the replay's and the undo's guards, the service-key refusal, and the club steps of
`update-missing-club-and-state.yml`) without reading the database, the network or `gh`. **A failure means this skill is
now wrong, not that the codebase is broken** — fix the prose, then continue. It parses the tier
table, so a change to that table has to match the code in the same commit. The weekly
team-cleanup loop runs it before proposing club changes (`SELF_CHECKS` in
`scripts/team_cleanup/propose_week.py`) and parks the clubs stage as `skill_stale` when it
fails.

**Credentials.** `.env.local` *replaces* root `.env` rather than layering over it — when
that file exists it is the only one loaded, so one holding just frontend variables leaves
no Supabase credentials at all. `--execute` needs `SUPABASE_SERVICE_ROLE_KEY` or
`SUPABASE_SERVICE_KEY` and refuses to run without one: `anon` holds the UPDATE grant but no
UPDATE policy, so RLS filters the write to zero rows and PostgREST answers 200 with an
empty body — a run that reports success and changes nothing.

**The abbreviation source reads the run logs of `update-missing-club-and-state.yml`.** It parses
the rename lines out of each run's log; a dry run of that workflow logs no renames, so only an executed run is
worth reading. Given a run id (`--abbreviation-run`) the scan fetches the log with
`gh run view <run> --log`, so `gh` has to be authenticated. Given a saved copy
(`--abbreviation-log <file>`) it reads the file and never calls `gh`. Save the copy from Git
Bash (`gh run view <run> --log > <file>`): PowerShell mangles the `✅` and `→` the rename lines
are found by, and Windows PowerShell's `>` writes UTF-16. The scan refuses a copy that is not
UTF-8 or holds no rename line rather than read it as a run that renamed nothing. The weekly
team-cleanup loop reads saved copies only, from `<store>/inputs/abbreviation_logs/`. Until that
folder holds the damage run's log (the default below) as `<run id>.log`, it fails its clubs
stage with the `gh run view` command that saves it.

**Passing a repeatable flag replaces its defaults.** `--abbreviation-run` and
`--abbreviation-log` share one default, the original damage run, and passing either one alone
drops it; a saved copy of the damage run's log counts as passing it. `--league-url` falls back
to the two default leagues only when absent, so naming one league alone drops the other
league's proposals. Re-pass the defaults alongside any addition.

## Step 2: Take a snapshot with a dry run

```bash
python scripts/repair_swapped_club_names.py
```

Reads every live team whose club is a canonical club name — which is what the `playmetrics`
and `team_name` sources judge — and separately every team holding a value the cleanup
lowered, whatever its club, which is what `abbreviation` judges. It writes one row per team
that has a proposal to a snapshot CSV under `data/exports`, and nothing to the database.

**The dry run is the only thing that decides.** `--execute` replays the snapshot and never
recomputes, so the rows read are the rows written.

## Step 3: Read the evidence before approving anything

Open the snapshot. `approved` is already true on the deciding tiers above and false on the
listed ones. Set it to true on any listed row accepted, and leave the rest.

Two things are worth reading in full rather than sampling. Every `needs_review` row, since
those are the conflicts and the names the `team_name` source could not parse. And every
`recased` row, because that tier cannot tell a club the cleanup re-cased from a squad label
that happens to read like one.

Under the weekly team-cleanup loop the listed rows that propose a club, and any `needs_review` row of a
deciding tier, go to unattended reviewers first (`scripts/team_cleanup/review_clubs.py`, the `running-team-cleanup` skill's
**Clubs**). They judge each distinct change once by this skill itself, which each run copies into its review, above
all by **Judging a listed change**: a change they approve applies on
its own, one they find wrong (upheld by a second reviewer) is recorded Don't apply, which the loop's page
and review then leave off, and one they hold is the owner's card.

**There is no pilot flag.** The other hygiene tools take `--limit` and apply the first N;
this one applies exactly the rows marked approved. The pilot is therefore a choice about
rows: approve a handful of a tier, apply, verify, then approve the rest of it.

Under the weekly team-cleanup loop the apply (`scripts/team_cleanup/apply_stage.py`) writes the
Apply rows of the lane (the owner's or the automatic lane's) into two cut files, a pilot of the first 50 by team id and a rest, and
replays each in turn, reading each batch back from the database and stopping before the rest
when a write it expected is missing.

## Step 4: Rehearse the replay, then apply it and verify against the database

Rehearse first — `--dry-run` wins over `--execute`, so this prints every due write and
writes a dry-run log without touching the database:

```bash
python scripts/repair_swapped_club_names.py --execute data/exports/repair_swapped_club_names_<timestamp>.csv --dry-run
```

Then apply it:

```bash
python scripts/repair_swapped_club_names.py --execute data/exports/repair_swapped_club_names_<timestamp>.csv
```

Two guards stand between the snapshot and the write, and they report differently. A team
whose club no longer matches the snapshot is `skipped_changed_since_snapshot`, case aside.
A team that moves between that check and the write itself is `skipped_changed_since_read`,
because the write carries the freshly-read value as its predicate rather than the
snapshot's. A run stopped by an error or Ctrl+C logs every row it never reached as
`not_attempted`: those were never sent, and a re-run of the same snapshot writes them. The one
row whose write was under way stays logged as `updated`, and it is the only one whose outcome is
unknown — check it in the verification below. A run killed outright (a closed window,
`taskkill /F`, the loop's step timeout) leaves the log written before the first write, with
every due row `updated`, so check them all.

Verify from the database rather than from the run's summary: read a sample of the written
teams back and check the club reads as a club, not as a squad label or a truncated name.

**To undo the batch**, replay its log backwards. Without `--execute` this previews the undo
the same way:

```bash
python scripts/repair_swapped_club_names.py --revert data/exports/repair_swapped_club_names_log_<timestamp>.csv --execute
```

It restores only rows still holding what the run wrote. A dry run's log is refused, since
nothing was written and restoring its rows would overwrite live values.

## Step 5: Record what ran, and what you could not decide

Note the snapshot and log paths and the undo command. Then record the rows left unapproved
with the reason — a listed row with no stated reason is re-listed and re-argued on the next
run, and a conflict left undecided stays a conflict.

A hand run keeps no database ledger for this column, so its logs are the whole record. They
live under `data/exports`, which is gitignored, or in the folder `--exports-dir` named, so they
exist only where the batch ran. A record that has to outlive it goes somewhere tracked. Under
the weekly team-cleanup loop the apply (`scripts/team_cleanup/apply_stage.py`) also reads each
batch's log back and writes a `team_cleanup_changes` row for every change the log records as
written and the database holds; those logs land in the loop's store, under `<store>/exports`.

## Applying a hand-vetted list

`scripts/apply_vetted_club_names.py` writes `club_name` from a list a person has already
decided: a JSON array with one entry per team, each carrying `team_id_master`, `from_club`,
`to_club` and the `evidence` that decided it. It decides nothing itself. Use it for moves none of
the sources above proposes, such as a team filed under the host club whose code a provider put
in front of its name (`XL - BUFC B17 Blue`, a Bellevue United team at a Crossfire event). The
branch rule under **Hold rather than write** applies to every entry.

```bash
python scripts/apply_vetted_club_names.py --file <vetted.json>
python scripts/apply_vetted_club_names.py --file <vetted.json> --execute --log <log.csv>
python scripts/apply_vetted_club_names.py --revert <log.csv> --execute
```

It is a dry run unless given `--execute`, and `--dry-run` wins. Each write carries `from_club`
and requires a live team, so a team whose club changed or that was merged since it was read is
skipped and left out of the log. The log records each move as it lands, in
`data/logs/club_name_changes_<time>.csv` unless `--log` names another file, and the script
refuses a log file that already exists. `--revert` replays a log backwards under the same
guard. It needs `SUPABASE_SERVICE_ROLE_KEY` even for a dry run, read from `.env.local` in the
working directory when that file exists, else from `.env` there. The weekly team-cleanup loop
does not run it, but its apply refuses to start while it is running.

## Keeping the weekly cleanup in agreement

`update-missing-club-and-state.yml` runs every Monday and its club steps are live. Two of
them fill a blank `club_name`: `scripts/backfill_missing_club_names.py` from GotSport and
`scripts/extract_missing_club_names.py` from the team's own name. They choose only teams whose
club is blank, but each write filters on the team id alone, so a club another writer sets
between that read and the write is overwritten. Both write by default: they take `--dry-run`
and have no `--execute`, so pass `--dry-run` when running either by hand (the workflow passes
it only on a dispatch with `dry_run` set). The third step standardizes spellings through
`scripts/full_club_analysis.py`, which carries its own canonical overrides and casing rules.

So a naming rule decided here belongs in that script. A rule applied to rows alone is
re-derived away the following Monday, and the only visible symptom is the same repair
proposing the same names again.

Two passes there write casing. The caps pass reaches `caps_winner` only for a club spelled
more than one way within a state, and the merge of those spellings always decides it: two
spellings sharing a lowercased key must differ in case, so the `proper_case` branch beside
it never runs. The provider pass, SincSports and PlayMetrics only, calls `proper_case`
directly and only on an all-caps name.

So put a casing rule in `merge_case_variants`, or in `apply_provider_rules` for the provider
pass, and test it on a group holding two spellings of one club.
