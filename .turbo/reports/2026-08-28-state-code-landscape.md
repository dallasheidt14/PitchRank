# State code landscape — what's actually true (2026-08-28)

Research pass before designing a state-assignment skill. Seven agents mapped the
pipeline, every other writer, the live DB, the current failure, repo conventions,
and unused signals; a verifier re-ran the load-bearing claims.

## Bottom line

The missing-state problem is nearly solved (1.8% of teams). The real problems are
that **the pipeline has been dead since 2026-08-20**, that **nothing can correct a
wrong state**, and that **several code paths manufacture wrong states every week**.

---

## 1. The pipeline is dead, and has been for a cycle

`update-missing-club-and-state.yml` Step 0 (`backfill_state_from_team_name.py`)
connects over psycopg2 to `db.<project>.supabase.co:5432`. That host has an **AAAA
record only**, and GitHub-hosted runners have no IPv6 egress →
`OperationalError: Network is unreachable`.

- Failing 1-for-1 since PR #995 (2026-08-20) added Step 0. All runs before that: success.
- No step carries `continue-on-error`, so Steps 1–6 never ran either. **The whole
  club+state backfill is off**, not just the name heuristic.
- Will fail identically on 2026-08-31.
- Fix: repoint `DATABASE_URL` at the IPv4 Supavisor pooler, or give Step 0 a
  PostgREST path (as `normalize_team_names.py` already has).

Second latent bug: `set -o pipefail` appears **only** in Step 0. Steps 1–6 pipe into
`tee` without it, so a crash in any of them exits 0 and reports "0 updated".

## 2. Actual scope in the database

`teams` = 211,401 rows.

| Measure | Count |
|---|---|
| `state_code` NULL | 3,845 (1.82%) — 3,761 live, 84 deprecated |
| empty string / whitespace | 0 (column is `CHAR(2)`, so `= ''` filters are dead code) |
| malformed (not `^[A-Z]{2}$`) | 7 |
| NULL-state teams with ≥1 game | 3,182 · with ≥5 games: 251 · played last 90d: 997 |
| **NULL-state teams that are TGS** | **3,697 of 3,845** |
| Canadian provinces | 1,412 (ON 1,211, BC 94, AB 57, QC 45, MB/NS/NB) |

Fill capacity for the NULLs with today's signals: clubmate dominance reaches
**1,173**; opponent dominance reaches **18**.

## 3. Detecting *wrong* states is much weaker than it looks

| Signal | Teams flagged |
|---|---|
| Clubmate dominance (≥90% of clubmates in another state) | 4,192 |
| Opponent dominance (≥5 distinct opponents, ≥90% elsewhere) | 477 |
| **Both agree** | **49** (and all 49 name the same replacement state) |
| Team name contains exactly one state contradicting stored code | 794 |

Of the flagged set, ~346 are Active in `rankings_full` (i.e. visible on state boards).

Both dominance signals are polluted:
- `club_name` is sometimes a **league bucket**, not a club — "El Paso Premier League"
  (640 teams), "HTX" (536), "Legends FC (CA)" (525, with unrelated teams fused in).
- Border-region clubs legitimately play out of state. Confirmed true-negatives:
  Shreveport Strikers (LA, plays 100% TX), Western Wisconsin (WI, plays MN),
  Sierra Surf (NV, plays CA).

The name signal found unambiguous **real** errors in a 20-row sample: `Michigan
Wolves 19` stored KY, `Alabama FC 2013 ECRL` stored TN, `Wisconsin ODP 2013 Boys
Younger` stored IL.

**No hand-labelled ground truth exists anywhere.** Every precision number above is
measured against `teams.state_code` — the column being audited. Circular.

## 4. Who manufactures wrong states

~22 code paths write `state_code`. Ranked by damage:

1. **Unknown-opponent chain** — `auto_match_unknown_opponents.py:192` fills a missing
   state with `top_known_team_state`, i.e. **the state of the team it played**. That
   flows to `discover_teams_from_opponents.py:291` and becomes the new team's state.
   False for every interstate/tournament game — which is exactly the population that
   generates unknown opponents. Runs weekly.
2. **`affinity_wa_matcher.py:26,390`** — hardcodes `WA` on every auto-created team.
   Fine for the WA state league; wrong for every out-of-state visitor to the WA
   tournaments that `wa-scraper.yml` also runs.
3. **`enhanced_pipeline.py:536` → `game_matcher.py:569,579`** — the game-import path
   calls `_match_team()` **without** `state_code`, so the correct per-team state that
   PlayMetrics/SincSports scrapers put in the CSV is discarded. Auto-creates land NULL.
4. **`tgs_matcher.py` and `modular11_matcher.py`** omit `state_code` entirely (both
   carry TODOs). TGS being the tournament provider is why 3,697 of 3,845 NULLs are TGS.
5. **`frontend/app/api/create-team/route.ts:83-84`** — writes the 2-letter code into
   `state`, the full-name column, and validates nothing.
6. **`update_teams_state.py`** — bulk CSV overwrite, length-only validation, `--auto-yes`.
7. **Merges** — `execute_team_merge` sets only `is_deprecated`; it never reconciles
   `state_code`, so a merge can discard a correct state for the survivor's wrong one.
   16,070 `team_merge_audit` snapshots carry a prior `state_code` (a recovery source).

## 5. Safety facts the design must respect

- **"These scripts can't overwrite" is false.** That's a property of each script's
  SELECT, not its write. All four state-writing UPDATEs are unguarded
  (`backfill_state_from_team_name.py:325`, `match_state_from_club.py:667`,
  `backfill_missing_state_codes.py:361,403`, `backfill_state_from_opponents.py:288`).
  Only `discover_sincsports_teams.py:315` puts `.is_("state_code","null")` on the
  UPDATE itself — that is the pattern to copy.
- **No provenance anywhere.** No `state_source`, no `state_confidence`, no history
  table. `teams.updated_at` is field-agnostic. A correction run today has no rollback.
- **State boards read `rankings_full.state_code`**, a weekly denormalized copy
  (`data_adapter.py:724-725,1009`). A `teams` fix is invisible to users until the
  Monday 12:30 UTC ranking run. Currently in sync (3 mismatched rows of 200K).
- The state dictionary is duplicated in **six** scripts outside `src/utils/us_states.py`
  (that module's own docstring says four — it's stale).

## 6. Unused signals worth having

- **TGS event details — a live bug hiding an authoritative answer.**
  `scrape_tgs_event.py:735` reads `event_details.get("eventName")`, but the API returns
  the key **`name`**. So the fallback always fires: 153,815 of 168,782 TGS games (91%)
  store `event_name = 'Event <id>'`. The same payload carries `stateCode`, `city`,
  `zip`, `address` — all discarded. Verified live against events 3118 and 4291.
  Only **254 event ids** need resolving to cover the stateless TGS teams.
  Caveat: 2,906 of 3,063 stateless TGS teams appear in exactly **one** event, so host
  state is a single observation of a possibly-travelling team.
- **`games.venue` → learned gazetteer.** 93.9% filled (1,031,626 rows), read by nothing
  in the state pipeline. Venue is a bare facility name (no address), so it must be
  learned, not parsed: 6,421 venues with ≥6 known-state sides, 72% are ≥90% single-state.
  Scales to the populated 98% — the only verification signal that does.
- **`games.competition`.** 90.8% filled; 1,053 competitions are ≥90% single-state,
  covering 498,521 game-sides ("Indiana Soccer League", "South Jersey Soccer League"…).
- **Negative finding — `teams.league` is NOT a state signal.** ECNL_RL spans 44 states,
  GA 44, MLS_NEXT_AD 42, ECNL 41. Don't try it.
- **Negative finding — `teams.state` is not a source.** 52.9% filled, and only 14 teams
  have `state` without `state_code`.

## 7. Unrelated, but surfaced and worth acting on

`list_tables` returned a critical advisory: **RLS is disabled on 11 tables** readable
with the anon key — `game_history`, `team_trajectory`, `team_momentum`, `rankings_full`,
`ranking_history`, `team_link_audit`, `team_merge_map`, `team_merge_audit`,
`scheduled_games`, `announcements`, `team_social_profiles`. Not part of this work; do
not auto-remediate (enabling RLS without policies breaks reads).
