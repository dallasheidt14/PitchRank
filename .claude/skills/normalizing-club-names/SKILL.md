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
so a run from elsewhere puts the snapshot and its only undo record somewhere else.

Copy this checklist and check off items as you complete them:

```
Task Progress:
- [ ] Step 1: Preflight — credentials, and the run logs the abbreviation source reads
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
- **A club branch is not its parent** — *not enforced anywhere*. "Albion SC San Diego" is
  its own club, and a proposal that shortens a branch to its parent merges two clubs. Read
  any proposal that drops a place or a qualifier from the stored club.

## Step 1: Preflight

**Credentials.** `.env.local` *replaces* root `.env` rather than layering over it — when
that file exists it is the only one loaded, so one holding just frontend variables leaves
no Supabase credentials at all. `--execute` needs `SUPABASE_SERVICE_ROLE_KEY` or
`SUPABASE_SERVICE_KEY` and refuses to run without one: `anon` holds the UPDATE grant but no
UPDATE policy, so RLS filters the write to zero rows and PostgREST answers 200 with an
empty body — a run that reports success and changes nothing.

**The abbreviation source reads GitHub logs.** It parses the rename lines out of
`gh run view <run> --log` for the weekly cleanup's runs, so `gh` has to be authenticated.
A dry run of that cleanup logs no renames, so only an executed run's id is worth passing.

**Passing either repeatable flag replaces its defaults.** `--abbreviation-run` and
`--league-url` each fall back to a default list only when absent, so naming a later cleanup
run alone drops the original damage run, and naming one league alone drops the other
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

**There is no pilot flag.** The other hygiene tools take `--limit` and apply the first N;
this one applies exactly the rows marked approved. The pilot is therefore a choice about
rows: approve a handful of a tier, apply, verify, then approve the rest of it.

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
snapshot's. A run interrupted mid-write leaves `not_attempted` rows, which are the only
ones whose outcome is unknown — those are what the verification below is for.

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

There is no database ledger for this column, so those logs are the whole record. They live
under `data/exports`, which is gitignored, so they exist only in the checkout that ran the
batch. A record that has to outlive it goes somewhere tracked.

## Keeping the weekly cleanup in agreement

`update-missing-club-and-state.yml` runs every Monday and its club steps are live: two of
them fill a blank `club_name` and never overwrite, and the third standardizes spellings
through `scripts/full_club_analysis.py`, which carries its own canonical overrides and
casing rules.

So a naming rule decided here belongs in that script. A rule applied to rows alone is
re-derived away the following Monday, and the only visible symptom is the same repair
proposing the same names again.
