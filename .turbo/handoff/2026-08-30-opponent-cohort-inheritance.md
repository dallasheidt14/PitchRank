# Handoff: Opponent-cohort inheritance — fixed at source, existing rows partly repaired

## What this was

The user noticed ~12,000 teams created in a week and asked where they came from. The volume was
normal (the Tuesday hygiene chain). The real finding was 21 of them landing in cohorts that do
not exist — `u3`, `u8`, `u20`. Root cause: every stage of `unknown-opponent-hygiene-weekly.yml`
read GotSport `team_details` keys the endpoint has never returned, so lookups came back empty and
`build_unknown_profile` fell through to `top_known_team_age_group` — the cohort of the team the
unknown side had *played*. One mislabelled row seeded its cohort into every opponent it faced.

## Status: complete and merged. Nothing in flight.

Working tree clean, on `main`. Three PRs merged:

| PR | What |
|---|---|
| #1060 | Fixed all four resolvers, extracted `src/utils/age_group.py`, name-before-opponent ordering, 404-vs-transient handling |
| #1061 | Recorded the GotSport payload contract and the derive-your-guard rule in project docs |
| #1062 | `scripts/repair_out_of_board_cohorts.py` + 13 live corrections |

## Live data change

13 teams re-resolved out of `u3` onto real boards (u10/u12/u13/u14/u15). `u3` went 44 → 31.
Revert log: `data/exports/repair_out_of_board_cohorts_20260830_132157.csv` — **gitignored**, so
the durable copy of that table is in PR #1062's body. `--revert <csv>` was dry-run verified
against it: all 13 restore correctly.

## Two backlog entries were WRONG and are now corrected

Written earlier in the same session, then refuted by measurement. Do not re-derive:

- **IMP-142** claimed fixing two backfill resolvers would repair the state backfill. False.
  Missing `state_code` is a **TGS** problem — 2,192 of 2,345 — and only **6** teams missing a
  state have a GotSport alias at all. `backfill_missing_club_names.py` is not broken either: it
  reads `club_name`, a real key, and GotSport genuinely returns `null` for its candidates
  (verified against four live records). What remains there is consistency, not impact.
- **IMP-147** treated 2,937 out-of-board rows as one population. It is three: u8/u9 (2,871) are
  accurate and should be left; u20 (1,597) needs season evidence; the impossible cohorts were the
  tractable part and are done.

## The trap that nearly shipped

The repair's first dry run wanted to change 71 rows. 58 were `u3→u4`, `u4→u5`, `u5→u6`, `u6→u7`
— a uniform +1. That is the Aug 1 rollover, not a correction: GotSport's U-age advances every
year while a stored label does not. Writing it would move teams between two unboarded cohorts and
reproduce the identical diff next August. The rule now enforced in `decide()`: **only write a
cohort PitchRank actually boards**, and never a label that folds into u19 (`skipped_needs_season_evidence`).

## New shared modules

- `src/utils/age_group.py` — the one normalizer. ASCII-bounded (`str.isdigit()` is Unicode-aware
  and unbounded), folds U18 and U20 into u19 as `team_utils` does.
- `src/utils/gotsport_team_details.py` — the corrected `team_details` reader.

Seven older resolver copies still exist. Two still read absent keys and are named in
`KNOWN_BROKEN` in `tests/unit/test_team_association_map.py`, which now **derives** its script
list by globbing for the endpoint rather than listing files. A companion test fails if either is
fixed and left on the list.

## Next step

**Work the 1,597 `u20` teams (IMP-147 remainder).** Highest remaining impact — they sit on no
board, and many belong on U19.

It was deliberately deferred rather than folded, and the reason is the whole difficulty: a stored
U-age does not say which season wrote it. Sampled names put genuine `U19 MLS NEXT HD` next to
`Milan 2006` and `Delaware County FC 2006 1`, which are **aged out** and must not join the board.
So it needs per-team evidence — birth year in the name, last game date, current GotSport label —
not a fold. And because it adds teams to a live board, it wants a ranking-aware review before any
write. `scripts/repair_out_of_board_cohorts.py --cohorts u20` is the starting point but its
current guard will refuse every one of them by design; the u20 pass needs its own decision rule.

## Also queued

- **IMP-143** — due-diligence gate approves when GotSport returns nothing (`!= "mismatch"`).
  #1060 made it live for the first time, and it writes immutable game FKs under the service key.
- **IMP-144** — no retry, User-Agent or delay on any GotSport resolver, against a WAF-fronted
  endpoint. `src/scrapers/gotsport.py` has the hardened probe but imports bs4, which the hygiene
  workflow does not install.
- **IMP-145** — the repo asserts two contradictory readings of `display_age_group`.
- **IMP-148** — provenance, so an opponent-derived cohort can never be persisted.
- **IMP-149** — U21 aged-out teams are still created by the discovery path.

## Watch on the first Tuesday run

Both shipped unobserved:

1. The export-stage fix shifts match-versus-create outcomes across ~6,400 teams/week. The backlog
   entry had asked for a measured before/after; it was not taken, because leaving that stage
   broken made every other stage's fix inert.
2. `due_diligence`'s `state_check` is live for the first time. `team_association` agrees with
   stored `state_code` on only 91.3% of probes, so expect roughly **one correct link in twelve**
   demoted to manual review. Fail-safe, but it costs throughput.
