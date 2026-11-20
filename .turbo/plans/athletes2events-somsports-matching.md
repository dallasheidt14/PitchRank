---
status: done
---

# Plan: Teach the Athletes2Events matcher the club and squad rules event 198 exposed

## Context

The 2026 Surf College Cup Youngers (Athletes2Events event 198, host `somsports.athletes2events.com`, Nov 28-29) had 71 rankable teams, 66 of which PitchRank already held. The roster matcher on origin/main found 28 of them; it would have created duplicates of 22 more and sent 13 to review. The owner hand-matched the rest ("show me the teams that didn't match and I can find their match so you can learn that way"), those answers were saved as 40 approved `manual` aliases, and PR #1471 (merged 2026-11-19) fixed the Jul 31 division cutoff. Event 198 itself is therefore covered. This plan is PR 2: turn what the hand-matches taught into matcher rules so the next Athletes2Events event links its teams without the owner doing it by hand ("But for This instance can we make Matcher better so it finds it?").

A write-guarded replay of event 198 against the owner's answers measured each rule. Applied together they took the matcher from 28 to 43 correct links with no team linked to the wrong squad; the only wrong links left pointed at duplicate twin rows that have since been merged. Owner decisions for this PR (2026-11-19): the new rules apply to **Athletes2Events only** (Tourney Central, Demosphere, Heartland, HTG and YSSL, which share the matcher, keep today's behavior); names that are only a club (`LeonFC`, `TopBallers`) get no rule of their own and end in review or as new teams (step 5); the backlog item to share the three drivers' club split (IMP-388) stays separate. Owner club facts: LASC = Los Angeles Soccer Club, Slammers FC and HB Slammers = CDA Slammers, LAFC = LAFC So Cal, Progressive = Progressive Soccer Ozzy, AVSC = Apple Valley SC, NW Elite = Northwest Elite Soccer Club, South Valley = South Valley Surf SC, LAOT = LA Overtime; and "Fsc is not flagstaff", so FSC United gets no mapping.

### Revision after implementing steps 1-11 (2026-11-19)

Steps 1-11 are implemented, uncommitted, in `C:\pitchrank-a2e-matching` (branch `feat/a2e-somsports-matching`). Event 198 met its bar (46 right, 0 wrong) and the sibling providers showed no change. The event-137 replay, however, found three links to the wrong squad, which this plan's own bar blocks:

- **`LASC-SCV BU15 N1`** linked a generic `Los Angeles SC` row. The somsports `^LASC\b` entry also matches the hyphenated branch club LASC-SCV.
- **`City SC Carlsbad Gold GU11-Dennis`** linked `City SC - Carlsbad 2016 Gold - Cordeiro`, which has no games this season. The cut-back's three-word cut, `City SC Carlsbad`, let that row through on the club read from its *name*. The active `Carlsbad GU11 Gold - Dennis` passes only at the shorter cut; its stored club is `City SC`, and it is where the real import's merges put this team. No gate reads coach surnames.
- **`Sant Cruz United 14-15 Boys Blue`** linked `14/15 Boys Blue 2`. That row played Almaden Events (GotSport) on Sep 5-6, the event's own weekend, and an active `2015 Blue` exists. The shared rule counts a squad number only when both names carry one.

Owner decision (2026-11-19): for Athletes2Events, keep a plain squad apart from a numbered one, as YSSL already does. The owner answered "Keep them apart"; YSSL's ruling was "White1 and white2 are clearly different teams". Steps 12-17 add the fixes. The variants below were measured as monkeypatches (scratch `variants.py`); Verification re-measures the shipped code.

Each variant was scored on 198 against the picks, and on 137 and 130 against where each team's real alias ended up after merges, all with the same isolation:

| Variant | 198 right / wrong | 137 / 130 |
|---|---|---|
| Steps 1-11 | 46 / 0 | the three wrong links above |
| V1: hyphen terminator + number rule | 46 / 0 | LASC-SCV and Santa Cruz fixed; Carlsbad still wrong |
| **V2: V1 + cut-back vouched for by the stored club only** | **46 / 0** | all three fixed (Carlsbad goes to review) |
| V3: V1 + pool every cut length | 46 / 0 | Carlsbad still wrong |
| V4: V1 + `SquadWordRules` squad words | 42 / 3 | about 95 outcomes move; rejected |

V2 against origin/main:

- **Costs.**
  - `Albion Riverside, BU12 EA , Gutierrez` goes from its real link to review.
  - `Next Level U12 Boys Red` stops linking `Northwest U12 Boys Red`, a link origin/main's own fuzzy pass made for a name that states no direction.
  - On 130, `XF BU17 ECNL 2 - Heimbigner` moves from `B2010 XF ECNL Regional` to the gameless `XF ECNL B2009/10 2`.
- **Gains that steps 1-11 had and V2 gives back.**
  - `SDSC Surf Pre-ECNL BU12 I` no longer finds its exact-name row and is created as a copy.
  - `SDSC Surf - Aspire 08/09` goes from review to created.
- **Changes V2 makes deliberately.** `XF U16 B10-11 ENCL 2` and `XF U14 B12-13 ECNL 2 - Cruz` stop linking ECNL-1 rows (`2011 ECNL`, `XF B13 ECNL`). The scraper skill already treats two event squads on one such row as a conflict.

Considered and not taken:

- **Ending the Athletes2Events club at `Pre-ECNL`.** Measured on the saved names, it changes 15 splits, loses one link and recovers none. The older risk it touches goes to the backlog in step 16.
- **Refusing a host pattern that backtracks to its shorter alias on a hyphenated suffix** (`LAFC So Cal-SCV`). No saved name in events 130, 137 or 198 has that shape, and the real case, LASC-SCV, is covered by step 12.

## Pattern Survey

Everything below was checked against baseline `93b407449` with `git show` and `git grep`. Line numbers are as they stand at that commit. The local data files listed under Convention Anchors are gitignored and exist only in this checkout.

### Analogous Features

**Class tree.** Whatever goes into `Athletes2EventsGameMatcher._fuzzy_match_team` is inherited by the other matchers unless it is opted out:
- `TourneyCentralGameMatcher(Athletes2EventsGameMatcher)` — `src/models/tourneycentral_matcher.py:44`
- `DemosphereGameMatcher(TourneyCentralGameMatcher)` — `src/models/demosphere_matcher.py:29`
- `HeartlandGameMatcher(SquadWordRules, TourneyCentralGameMatcher)` — `src/models/heartland_matcher.py:35`
- `HtgSportsGameMatcher(SquadWordRules, TourneyCentralGameMatcher)` — `src/models/htgsports_matcher.py:16`
- `YSSLGameMatcher(Athletes2EventsGameMatcher)` — `src/models/yssl_matcher.py:104`. It overrides `_match_team` and `_fetch_candidates`, but not `_fuzzy_match_team`.

**Who calls the importer's club helpers:**
- `split_club` has three callers:
  - The A2E roster pass, `scripts/import_athletes2events_event.py:664`. It passes the raw name: A2E never calls `respell_ages`, which is opt-in (`:542-550`).
  - Tourney Central's `club_for`, `scripts/import_tourneycentral_event.py:616-640`. It calls `split_club(respell_ages(name), host)` at `:629`, then cuts the guess at `_BAND` (`:630-632`). HTG reaches it through TC's `build_roster` (`scripts/import_htgsports_event.py:76-109`, host `events.htgsports.net`). Heartland reaches it through `club_for("", name, HOST)` (`scripts/import_heartland.py:468`, host `heartlandsoccer.net`).
  - Demosphere's `club_for`, `scripts/import_demosphere.py:520-536`. It passes host `""` and cuts with `_before_age` (`:512-517`, at `_BAND`, `_BARE_YEAR` or a Boys/Girls word) both before and after the split.
- `HOST_CLUBS` is read only inside `split_club` (`:635`).
- `_CLUB_STOP` is read only inside `split_club` (`:639`).
- The A2E `parse_event_url` is called only by A2E `main` (`:1046`). TC (`:369`) and HTG (`:178`) have their own.
- YSSL never calls `split_club`. Its written club comes from `scripts/import_yssl.py:724-744`.

**Blast radius, rule by rule:**
- **Rule 1, bare two-digit band in `_CLUB_STOP`.**
  - Changes output only for A2E. TC, HTG and Heartland already cut at `_BAND`, and Demosphere at `_before_age`, so a bare band is already handled for them.
  - The same rule is already documented for matchers: scraper-patterns `SKILL.md:1460-1464` says to "cut the name at a bare two-digit band". The matcher-side `club_from_team_name` already does it with `_TWO_DIGIT_BAND = r"\b\d{2}/\d{2}(?!\d)"` (`src/models/tournament_name_gates.py:40`, used at `:70-78`). Its comment notes there is no trailing `\b` "because the gender letter is often glued on" (`15/16B`).
  - Today the band needs a B/G prefix in `_CLUB_STOP` (`[BG]\d{2}(?:[/-]\d{2})?`, `:237`).
- **Rule 1, no 19xx year in `_CLUB_STOP`.**
  - No sibling's own cut covers this. `_BARE_YEAR` (`:209`) reads only 20xx, so it is not redundant for siblings.
  - TC, HTG, Heartland and Demosphere club guesses change for any name with a 19xx token. A guess that is `None` today would run through the year.
  - Where TC has no club cell, `club_for` returns `(guessed, club_before_squad_marks(guessed))` (`:634-635`). Today that is `(None, None)`, and the matcher falls back to `club_from_team_name`.
- **Rule 2, cut-back retry.**
  - If it lives in the A2E `_fuzzy_match_team` body, all five subclasses get it.
  - TC's first pass gates on the club field, and TC deliberately never cuts a club field that opens the name (docstring at `tourneycentral_matcher.py:27-37`; `club_for` `:636-639`).
  - YSSL's `club_name` comes from the reviewed `config/yssl_club_map.csv`. Its branch separation is deliberate (`import_yssl.py:724-735`: "A branch row's prefix is not used").
- **Rule 3, somsports `HOST_CLUBS` entries.** These are keyed by host. Only A2E passes an `*.athletes2events.com` host, so the new entries reach only somsports events.
  - Existing test `test_another_host_does_not_get_this_hosts_club_table` (`tests/unit/test_import_athletes2events_event.py:342-343`) asserts that somsports `XF U10 RCL 2` gives `XF`.
- **Rule 3, written-club second pass.**
  - In A2E, `club_name` differs from `club_as_written` only when `HOST_CLUBS` matched. Otherwise `split_club` returns the same value twice (`:638` vs `:641`).
  - TC already runs this pass (`tourneycentral_matcher.py:61-69`). Putting it in the A2E body would run it twice under TC, Heartland, HTG and Demosphere.
  - Under YSSL, `club_name` (from the club map) and `written_club` (YSSL's spelling) almost always differ, so YSSL would start gating on its own spelling.
  - `SquadWordRules` expects the second pass to come from TC while `_filed_club` holds the filed club (`squad_word_rules.py:153-158`).
- **Rule 4, spacing-blind club compare.**
  - `is_same_club` (`src/models/squad_name_gates.py:24-54`) is shared by Affinity OR, UT and GA (HI through them), Soccer Events Group, and the A2E family.
  - `are_same_club` (`src/utils/club_normalizer.py:858`) is shared by Affinity WA, PlayMetrics, `src/tournaments/roster_resolver.py`, `scripts/find_cross_provider_duplicates.py` and `squad_name_gates`.
  - A wrapper local to A2E would still be inherited by all five subclasses through the gate at `athletes2events_matcher.py:245-255`.
  - Why it fails today: `similarity_score` (`club_normalizer.py:823-855`) scores 0.0 for two different one-word cores when either is five letters or fewer. "leonfc" against "leon" (after FC is peeled off) fails that way.
- **Rule 5, spelled compound directions.**
  - Besides the matcher's own gates, the A2E `_squad_marks` is used by TC's `club_before_squad_marks` (`tourneycentral_matcher.py:39`). That function is imported by the TC importer (`:104`, used at `:635`/`:640`) and Demosphere (`import_demosphere.py:87`, `:535`), and reaches HTG and Heartland through TC's `club_for`.
  - So a spelled "Southwest" read as a direction would make those drivers cut a guessed club before it.
  - Soccer Events Group uses the shared `squad_marks` directly (`soccereventsgroup_matcher.py:36,54`) and is unaffected.
- **Rule 6, page links in `parse_event_url`.** Only A2E `main` is affected.
  - The skill text contradicts the change: scraper-patterns `SKILL.md:784-785` says a page link such as `https://<host>.athletes2events.com/events/<id>/groups` "is refused".

**Prior art for the planned rules:**
- `tourneycentral_matcher.py:47-69`, TC's second pass. It builds `gate_clubs = [club_name]` and appends `self._written_club` when that differs case-insensitively. It calls `super()._fuzzy_match_team` per club and returns the first non-None result.
  - A tie demoted to `REVIEW_QUEUE_CLAMP` still counts as a result, so it stops the loop.
  - `_written_club` is set in A2E `_match_team` and cleared in `finally` (`athletes2events_matcher.py:313-319`). It is initialised in `__init__` (`:108-111`).
- `tourneycentral_matcher.py:27-41`, `club_before_squad_marks`. It pops trailing words while `_squad_marks` of the remainder is non-empty. This is the existing word-by-word cut-back shape, but it cuts on marks, not on a failed match.
- `src/models/yssl_matcher.py:84-101,142-147`, the squad-word requirement:
  - `distinguishing_words` gives the required words.
  - `_carries(words, candidate)` needs each word in the stored name, or a stored word that `begins` it (four or more letters).
  - The filter runs inside `_fetch_candidates`, using instance state set in `_match_team` and cleared in `finally`.
  - This is the "candidate must carry the cut words" idea rule 2 borrows.
- `src/models/squad_word_rules.py:152-214`, `SquadWordRules`, the Heartland and HTG squad-word gate:
  - It wraps `_fuzzy_match_team` and sets `_filed_club` around `super()`.
  - `_names_another_squad` refuses a candidate when each name has a squad word the other lacks (`_unmatched`, `:134-149`).
  - `_names_no_squad` demotes to review.
- `athletes2events_matcher.py:173-180`. The `_names_another_squad` hook is "Off here; a host whose clubs name squads that way turns it on". This is the family's opt-in hook.
- `scripts/import_heartland.py:173-205` (`HeartlandClub`, `HEARTLAND_CLUBS`) and `src/models/playmetrics_matcher.py:55,515` (`STORED_CLUB_NAMES`) are other per-provider maps from written club to stored club, like `HOST_CLUBS` (`import_athletes2events_event.py:242-253`, "first match wins, so the longer name is listed first").
- `scripts/import_tourneycentral_event.py:218` and `scripts/import_htgsports_event.py:139-141`: TC and HTG URL regexes that accept any page of an event. TC's is `^https?://((sub)\.tourneycentral\.com)(?:/\S*)?$` with `re.IGNORECASE | re.ASCII`. Their tests are at `tests/unit/test_import_tourneycentral_event.py:154-179`.
- `src/models/playmetrics_matcher.py:269,273-277` folds directions and colours locally, not in `extract_distinctions`. The `_distinctions` docstring says why: "`teams.distinction` stores its output".

**Negative prior art (backlog):**
- `.turbo/improvements.md:2821-2826`, an entry with no ID. On the HTG events, accepting a stored name that starts with a provider club of two or more words linked 6 more teams but sent 18 weak reviews pairing different Sporting BV squads, and it was rejected as the fix.
- IMP-396 (`.turbo/improvements.md:3174-3188`): `is_same_club` already admits KC Atletico as KC Athletics.

### Reusable Utilities
- `scripts/import_athletes2events_event.py:202-205` — `_BAND`. A two-year band in two- or four-digit years, with `/`, `-` or a space. TC and Demosphere already cut clubs with it.
- `src/models/tournament_name_gates.py:40` — `_TWO_DIGIT_BAND`. A bare band with the gender letter allowed to be glued on, the shape rule 1 adds.
- `src/models/tournament_name_gates.py:83-94` — `AGE_WORD`, `begins` (abbreviations of four letters or more), `initials`. These are the shared single-word readers.
- `src/models/tournament_name_gates.py:97-101` — `without_club`. It removes one exact, case-insensitive substring, once.
  - A2E `_without_club` (`athletes2events_matcher.py:156-167`) strips the full `self._written_club` first, then the gate club. A retry with a shorter gate club still strips the full written club, but only from a name that contains it in full.
- `src/models/tournament_name_gates.py:119-153` — `squad_marks` (with the `pre` and `tier_extra` hooks) and `squads_conflict`. Directions must match exactly (`:147`).
- `src/models/athletes2events_matcher.py:64-83` — `_presplit` and `_squad_marks`. The local wrapper adds squad letters and `RCL<n>` codes; this is where rule 5's local fold belongs.
  - `_presplit` is also imported by `squad_word_rules.py:16,191-192` and feeds `canonical_team_name` for scoring (`:135`), so a fold in `_presplit` reaches further than one in `_squad_marks`.
- `src/utils/team_name_utils.py:55-71` — `DIRECTION_CANONICAL`. It maps `nw/ne/sw/se` to the spelled compounds, but has no spelled-compound keys of its own. Neither does the copy in `scripts/_team_distinction.py:48`.
  - `extract_distinctions` (`:1060`) feeds `resolve_distinction` (`:1305`, directions at `:1348-1349`), which writes `teams.distinction`. A global change would therefore alter what gets stored for every created team.
  - `_SPELLED_DIRECTIONS` (`:697`) is the only derived map.
- `src/models/squad_name_gates.py:24-54` — `is_same_club(provider, candidate, threshold)`. It needs both `are_same_club` and `token_sort_ratio` (on `normalize_club_name`) to reach the threshold. A2E's threshold is `affinity_club_similarity_threshold`, 0.9 (`config/settings.py:198`).
- `src/utils/club_normalizer.py`:
  - `normalize_club_name` (`:567-619`) removes punctuation but keeps spaces (`_remove_punctuation`, `:512-519`).
  - `_light_form`, `lookup_canonical` and `normalize_to_club` (`:623-707`) match registry spellings exactly.
  - `CANONICAL_CLUBS` already holds run-together spellings: LAFC with `losangelesfc` (`:337`), `real socal` (`:354`), LOS ANGELES SC with `lasc` (`:398`).
  - `PLACE_WORDS` (`:187-195`) includes `so cal socal`.
  - A registry entry affects every `are_same_club` caller.
- Space-insensitive comparison: none exists in `src/models` or the club normaliser. The nearest are:
  - `scripts/find_cross_provider_duplicates.py:141,173` — `normalize` (`_NON_ALNUM` strip)
  - `scripts/team_name_normalizer.py:499-500` — squad compare
  - `squad_word_rules._unmatched` / `_runs` (`:53-56`, `:134-149`) — joins adjacent words ("Mc Nutt" = "McNutt") on word lists. This is the closest in-family analogue.
- `src/models/athletes2events_matcher.py:182-202` — `_fetch_candidates`, which pages 1000 rows at a time and is the YSSL filter hook. Every `_fuzzy_match_team` pass re-queries, with no cache.
- Test doubles:
  - `tests/unit/test_athletes2events_matcher.py:25-140` (`_Query`, `_DB`). It records at `execute()`, applies the `or_` state filter and ordering, raises PGRST116 on a zero-row `.single()`, and refuses review rows outside 0.75 to 0.90. It is reused by the TC, Heartland, HTG and Heartland-import tests.
  - `_matcher` (`:143`) and `_candidate` (`:158-166`).
  - `test_tourneycentral_matcher.py` adds `_KeepingDB` (`:17-29`) and `_register_as_listed` (`:57-60`), which builds the club as the driver does.

### Convention Anchors
- **Per-team context travels on the instance.** It is set in `_match_team` and cleared in `finally`, because the base calls `_fuzzy_match_team(team_name, age_group, gender, club_name, state_code)` only (`src/models/game_matcher.py:898`). Examples: A2E `_written_club` (`:313-319`), YSSL `_required_words`, `_squad_number` and `_yssl_name` (`yssl_matcher.py:111-140`), SquadWordRules `_filed_club` (`:170-174`).
- **Retries go through `super()`, never `self._fuzzy_match_team`.**
  - TC loops with `super()`.
  - SquadWordRules, Heartland (`REGION_SEARCH` swap, `heartland_matcher.py:43-56`) and Demosphere (`expand_club_code`, `demosphere_matcher.py:32-45`) wrap the outermost call.
  - Re-dispatching through `self` would re-run those wrappers, and SquadWordRules would reset `_filed_club` to None in the middle of a call.
  - Pinned by `tests/unit/test_htgsports_matcher.py:138` (`test_a_match_leaves_no_filed_club_behind`) and `:172` (mixin order).
- **Return contract.** Every `_fuzzy_match_team` returns `{"team_id", "team_name", "confidence"}`, or `None` for no candidate. The birth-year guard reads `team_name` (`tests/unit/test_birth_year_guard_wiring.py:75-97`, `_SUBCLASS_PATHS`).
  - Ties are demoted to `REVIEW_QUEUE_CLAMP` (`athletes2events_matcher.py:281-284`).
  - A failed query raises rather than reading as no candidate (`:213-218`).
  - No state means no query (`:219-220`), so game imports stay alias-only.
- **Opt-in behaviour per subclass:**
  - Hooks that are off in the base: `_names_another_squad`, `_candidate_state_filter`.
  - Class flags: `refuse_tied_best` (`affinity_or_matcher.py:111`, set True at `affinity_ut_matcher.py:144`), `_affinity_variant_gate_required` (`affinity_ga_matcher.py:80`).
- **Driver/matcher split.** The club split and the per-host club map live in the importer script and travel as `TeamRow.club_name` / `club_as_written` (`import_athletes2events_event.py:280-294`, passed at `:724-726`). Gates live in the matcher module, and shared name helpers in `tournament_name_gates.py`.
- **URL parsing.** The pattern is `re.IGNORECASE | re.ASCII`, deliberately, so the U+017F fold and non-ASCII digits are refused (comment at `:175-179`). A2E is https-only, and the test refuses `http://` (`test_import_athletes2events_event.py:74-87`).
- **Tests to update or watch:**
  - A2E importer: `TestParseEventUrl` (`test_import_athletes2events_event.py:59-87`), `TestSplitClub` (`:316-343`).
  - A2E matcher: `TestWrittenClub` (`test_athletes2events_matcher.py:447-503`), `TestSquadMarks` (`:199-255`).
  - TC: `TestClubBeforeSquadMarks` (`test_tourneycentral_matcher.py:151-165`); `TestWrittenClubGate` (`:168+`), including `test_the_club_field_is_tried_before_the_written_club` and the "guessed club never links another squad" cases; `TestClubFor` (`test_import_tourneycentral_event.py:443-465`).
  - Demosphere: `TestClubFor` (`test_import_demosphere.py:199-242`).
  - Heartland: `TestSquadWords` (`test_heartland_matcher.py:193+`), `TestClubAndState` (`test_import_heartland.py:167+`).
  - HTG: `test_htgsports_matcher.py:94,119`.
  - YSSL has its own double: `test_yssl_matcher.py:21-170`.
  - Skill text is scanned by `tests/unit/test_agent_doc_references.py`. #1471's first CI run failed there on the `/groups` example.
- **Docs to keep in step:** scraper-patterns `SKILL.md`:
  - `:784-785` — the /groups link "is refused"
  - `:847-851` — the club-split rule
  - `:855-869` — A2E matching
  - `:1128-1139` — TC written club
  - `:1458-1464` — bare-band cut
- **Backlog:** IMP-388 (`.turbo/improvements.md:2562-2571`, "share the club-name cut") has the trigger "The next change to club extraction in any of the three drivers". This change trips it.
- **Measuring blast radius (no committed harness):**
  - Recipes in scraper-patterns `SKILL.md`:
    - `:1487-1511` — guarded replay with a fail-closed write guard; save the inputs; diff round to round using a `git write-tree` copy.
    - `:1435-1443` — dry run of a cup event under the guard.
    - `:1699-1719` — near-duplicate SQL over created rows, similarity ≥ 0.55.
    - `:1721-1738` — replay the copies a past import made, from the `data/backups` merge lists, on the branch and on `origin/main`.
  - Memory note `smoke-test-importer-dry-run-against-production.md`: patch `httpx` and `requests` `send`, allow GET/HEAD plus `POST rpc/get_approved_aliases`, run `origin/main` from a `git archive` copy as the control, and use the service key (the anon key sees no `team_alias_map` rows).
  - Saved sibling inputs in this checkout only:
    - `data/raw/athletes2events/{130,137}_*_teams.csv`
    - `data/raw/tourneycentral/{wfc,partyonthepitch,terrorisland}_*_teams.csv`
    - `data/raw/htgsports/htg14130_*_teams.csv`
    - `data/raw/heartland/2026fall_*_teams.csv`
    - `data/raw/yssl/*_teams.csv`
  - The reports carry the name, filed club, state and outcome, but no written club (`REPORT_COLUMNS`, `:125-141`), so a replay has to re-derive the split. There is no local Demosphere directory; it runs on Actions.
  - Event 198's owner answers and pre-links: `data/backups/a2e_198_prelink/prelink_2026-11-19.json`.

### Proposed Alignment
Keep all six rules local to Athletes2Events, following the existing pattern.
- Put the somsports clubs in `HOST_CLUBS`, which is already keyed by host.
- Fold the spelled compounds in the A2E `_squad_marks` wrapper, not in `DIRECTION_CANONICAL` or `_presplit`. PlayMetrics already does this kind of local fold, and `teams.distinction` stores `extract_distinctions` output.
- Make the URL change in A2E's own regex, modelled on TC's "any page" pattern and keeping `re.ASCII`.

Rules 2, 3 and 4 need gating, not a plain edit to the inherited `_fuzzy_match_team`:
- TC and its three subclasses already run the written-club pass and deliberately never cut a club field.
- YSSL gates on a reviewed club map.
- The shared `is_same_club` and `are_same_club` feed six other matchers.
So put them behind an A2E-only opt-in (a hook or flag that is off in subclasses, in the style of `_names_another_squad` or `refuse_tied_best`), and run any retry through `super()`/the A2E body rather than `self._fuzzy_match_team`.

Rule 1 goes in the shared `_CLUB_STOP` and so reaches TC, HTG, Heartland and Demosphere:
- The bare-band half is already redundant for them.
- The 19xx half is not. Replay their saved team reports on the branch and on `origin/main` before shipping.
- This change also trips IMP-388's trigger.

**Decision taken over the survey's last point:** the owner chose "Athletes2Events only", so rule 1 does **not** go into the shared `_CLUB_STOP`. It goes into an A2E-only stop pattern passed by the A2E roster pass, and `split_club`'s other callers keep today's split exactly (step 2).

## Implementation Steps

1. **Set up the branch off origin/main, not the shared checkout**
   - `C:\PitchRank` is on an unrelated branch, dozens of commits behind, with staged unrelated work. Create a worktree: `git -C C:/PitchRank fetch origin` then `git -C C:/PitchRank worktree add -b feat/a2e-somsports-matching C:/pitchrank-a2e-matching origin/main`.
   - Before editing, confirm `git -C C:/pitchrank-a2e-matching status --short` prints nothing and `git -C C:/pitchrank-a2e-matching log -1 --format=%h` equals `git -C C:/PitchRank rev-parse --short origin/main`. If either fails, stop and recreate the worktree.
   - A parallel worktree `C:/pitchrank-tc-clubs` (branch `feat/tourneycentral-club-spellings`, uncommitted) edits `.claude/skills/scraper-patterns/SKILL.md`, `scripts/import_tourneycentral_event.py` and `scripts/full_club_analysis.py`. This plan touches none of those scripts, but both edit the skill file; if that branch merges first, resolve the skill-file conflict by keeping both texts.

2. **A2E-only club stop: a bare band ends the club, a 19xx year does not** (`scripts/import_athletes2events_event.py`)
   - Leave `_CLUB_STOP` (`:236`) unchanged. Add `_A2E_CLUB_STOP` beside it as its own full regex literal (not built by string replacement): the same alternatives as `_CLUB_STOP`, plus a bare two-digit band with an optional glued gender letter (`\d{2}[/-]\d{2}[BG]?`, the shape of `_TWO_DIGIT_BAND` in `tournament_name_gates.py:40`), and with the year alternative narrowed from `(?:19|20)\d{2}` to `20\d{2}`.
   - Give `split_club(team_name, host)` (`:626`) a keyword-only `stop: re.Pattern = _CLUB_STOP` and use it where `_CLUB_STOP.search(body)` is called. The A2E roster pass call at `:664` passes `stop=_A2E_CLUB_STOP`; Tourney Central's `club_for` (`import_tourneycentral_event.py:629`) and Demosphere's (`import_demosphere.py:520-536`) are not touched and keep the default.
   - Tests in `tests/unit/test_import_athletes2events_event.py` `TestSplitClub` (literal expected values): with the A2E stop, `"Santa Clara Sporting 16/17B White"` → `("Santa Clara Sporting", "Santa Clara Sporting")`, `"Inland Surf Elite U10, Coach Lopez"` unchanged at `"Inland Surf Elite"`, `"1974 Newark Fc, Ecnl RL B2012/13, Ayllon"` → `("1974 Newark Fc", "1974 Newark Fc")`; with the default stop, both band and 19xx names give today's values (`"Santa Clara Sporting 16/17B White"` and `(None, None)`), which pins the siblings' split. Each half (band, 19xx) needs a case that fails when only that half is reverted.
   - Call-site test: run `build_roster` (`:647`, which holds the `:664` call) on a somsports-host event with the `Santa Clara Sporting 16/17B White` and `1974 Newark Fc, …` names and assert the rows' `club_name` and `club_as_written` are the A2E-stop values above, so dropping `stop=_A2E_CLUB_STOP` at the call site fails a test.

3. **Somsports club facts in `HOST_CLUBS`** (`scripts/import_athletes2events_event.py:245`)
   - Add a `"somsports.athletes2events.com"` entry, longer names first: `^LAFC(?:\s+So\s*Cal)?\b` → `LAFC So Cal`; `^HB\s+Slammers\b` and `^Slammers\s+FC\b` → `CDA Slammers`; `^South\s+Valley\b` → `South Valley Surf SC`; `^NW\s+Elite\b` → `Northwest Elite Soccer Club`; `^LASC\b` → `Los Angeles Soccer Club`; `^AVSC\b` → `Apple Valley SC`; `^Progressive\b` → `Progressive Soccer Ozzy`; `^LAOT\b` → `LA Overtime`. Compile with `re.IGNORECASE` as the crossfire entries are. Add no entry for FSC United (owner: "Fsc is not flagstaff").
   - The `AVSC` entry depends on one data fix (owner, 2026-11-19: the empty "AVSC Storm Black B13" row is "Same as Storm N1"). That row (`5c4e0f17…`, SincSports, 0 games) must be merged into "Apple Valley SC Storm N1" (`ea0363c9…`) before the event-198 replay; otherwise `AVSC BU14 Black N1` links the empty row on its colour. Before the replay, confirm with a read-only query that `5c4e0f17…` has a `team_merge_map` row pointing at `ea0363c9…`; if it does not, merge it through `scripts/apply_vetted_team_merges.py` (dry run first) as the merging-duplicate-teams skill says.
   - Before writing each target, confirm it is a stored `club_name` with a read-only query (`SELECT club_name, count(*) FROM teams WHERE club_name IN (...) AND NOT is_deprecated GROUP BY 1`); an entry whose target matches no stored club is dropped and reported rather than guessed.
   - Tests: each entry maps a real event 198 name to `(stored club, written club)` — `"LASC PRE MLS NEXT U11"` → `("Los Angeles Soccer Club", "LASC")`, `"HB Slammers Pre-ECNL GU12 Crowley"` → `("CDA Slammers", "HB Slammers")`, `"FSC United 12/13 Girls"` keeps its own club; `test_another_host_does_not_get_this_hosts_club_table` must still pass.

4. **Extract the matcher's single gate pass before adding retries** (`src/models/athletes2events_matcher.py`)
   - Move the body of `_fuzzy_match_team` (`:204-292`) into `_fuzzy_match_once(self, team_name, age_group, gender, club_name, state_code, extended: bool = False, must_carry: FrozenSet[str] = frozenset())`, returning exactly what the body returns today when `extended` is false and `must_carry` is empty. `_fuzzy_match_team` keeps its signature and, with the new flag off, is `return self._fuzzy_match_once(...)`. Run the full A2E, TC, Heartland, HTG, Demosphere and YSSL matcher tests plus `tests/unit/test_birth_year_guard_wiring.py` after this step alone: they must pass, with the one adaptation below.
   - `test_subclass_fuzzy_match_returns_team_name` (`tests/unit/test_birth_year_guard_wiring.py:100-114`) inspects `_fuzzy_match_team`'s own source for a `"team_name"` literal, which moves into `_fuzzy_match_once`. Extend that check to also accept the literal in `_fuzzy_match_once` when `_fuzzy_match_team` calls it, and add a behavior test that calls `Athletes2EventsGameMatcher._fuzzy_match_team` against the `_DB` double with one passing candidate and asserts the result's `team_name` equals that candidate's name, so the contract is pinned through the wrapper and not only by source text.
   - `must_carry` filters the fetched candidates: a candidate is kept only when the set of its `team_name` tokens, lowercased and split on `[\s\-,()/]+`, contains every word in `must_carry`. Empty means no filter. Exact token match is deliberate: YSSL's `_carries` (`yssl_matcher.py:99`) also admits four-letter prefixes, which the replay did not measure.
   - `extended` switches on the gate changes of steps 8 and 9 inside the pass (spacing-blind club compare, spelled compound directions). It is a parameter, not a read of the flag, so `_fuzzy_match_team` decides once per team (step 5).

5. **An A2E-only flag, off for every subclass**
   - Add `athletes2events_rules: bool = True` as a class attribute on `Athletes2EventsGameMatcher`, and set `athletes2events_rules = False` on `TourneyCentralGameMatcher` (`tourneycentral_matcher.py:44`, which Demosphere, Heartland and HTG inherit) and on `YSSLGameMatcher` (`yssl_matcher.py:104`), each with a one-line docstring note that the subclass keeps its own club rules. Pattern: `refuse_tied_best` (`affinity_or_matcher.py:111`).
   - A test asserts the flag's value on each of the six classes by literal (`True` for A2E, `False` for the other five), so a new subclass's choice is deliberate.
   - `_fuzzy_match_team` sets `extended = self.athletes2events_rules` once per team and passes it to every `_fuzzy_match_once` call; when it is false, `_fuzzy_match_team` is the single `_fuzzy_match_once(..., extended=False)` pass of today and steps 6 and 7 do not run.
   - **Names that are only a club get no rule of their own** (owner, 2026-11-19: "Leave them for review"; and, asked again once a special-case guard proved fragile, "Drop the guard"). No step links a club-only name by itself, and none holds it back either: such names go through the same rules as every other name. Measured on event 198 with the rules on and no guard, `TopBallers` (U12, a2e 13098) went to review at 0.817 and `LeonFC` (a2e 13687) was created as new, which is the owner's "review or new team". The event-198 replay pins those two outcomes (Verification).

6. **Second gate pass with the club as written** (in `_fuzzy_match_team`, only when `extended`)
   - When `_fuzzy_match_once(..., extended=True)` with `club_name` returns `None` and `self._written_club` is set and differs from `club_name` case-insensitively, call `_fuzzy_match_once(..., extended=True)` again with `self._written_club`. A review-clamped result counts as a result and stops the retries, as in TC's loop (`tourneycentral_matcher.py:61-69`).
   - Retries call `self._fuzzy_match_once`, never `self._fuzzy_match_team`, so no subclass wrapper re-runs (survey: retries go through the base body).
   - Test (`TestWrittenClub`): a somsports `HB Slammers U10 Blue` team (a real squad word, so the squad gate is exercised) whose stored row `HB Slammers U10 Blue` is filed under a club that fails `is_same_club` against `CDA Slammers` but whose name club passes against `HB Slammers` links on the second pass, and is not found by the first; the same setup under `TourneyCentralGameMatcher` behaves as today.

7. **Cut-back retry that only admits candidates carrying the cut words** (only when `extended`)
   - After step 6 returns `None`, and only when `club_name` equals `self._written_club` (no host club map hit): for `n` from `len(words) - 1` down to 2 (an empty range for a club of two words or fewer, which is the only floor; add no separate word-count guard), set `cut = words[:n]` and `must_carry` = the lowercased dropped words, temporarily set `self._written_club` to the cut club (so `_without_club` strips it), call `_fuzzy_match_once(team_name, age_group, gender, cut_club, state_code, extended=True, must_carry=must_carry)`, restore `self._written_club` in `finally`, and return the first non-`None` result.
   - Tests with literal expected team ids, each from event 198: `"Next Level Soccer Southeast U12 Boys Red"` (club split `Next Level Soccer Southeast`) links a stored `SOUTHEAST U12 BOYS RED` under `Next Level Soccer (AZ)`; `"Legends FC SB U11 Garcia"` must **not** link a stored `Legends SC Sacramento` row that lacks `SB` (the plain retry's wrong link), and does link a `Legends FC (CA)` row whose name carries `SB`. Floor test: a three-word written club whose two-word cut finds nothing, while a one-word cut would match a stored row whose name carries both dropped words, returns `None` (lowering the floor to 1 makes it link). Forwarding test: a written club `SoCal Tsunami Elite` whose cut `SoCal Tsunami` matches a stored row named `So Cal Tsunami Elite U14` only through the spacing rule links on the cut-back; with the cut-back's call passing `extended=False` it does not, so that mutation fails this test. Under `TourneyCentralGameMatcher` none of these retries run.

8. **Club comparison that ignores spacing and punctuation** (only when `extended`)
   - Add a module helper `_same_club_ignoring_spacing(a, b)`: both sides lowercased with every non-alphanumeric removed, non-empty and equal. In `_fuzzy_match_once`'s club gate (`:245-255` today), when `extended` is true, accept a candidate when `is_same_club(...)` passes **or** this helper does, for the name club and the stored club alike. `is_same_club` and `are_same_club` stay unchanged (six other matchers use them).
   - Tests on the helper: `LeonFC`/`Leon FC`, `TopBallers`/`Top Ballers`, `SoCal Tsunami`/`So Cal Tsunami` are equal; `Leon FC`/`Leon United` are not. Test through `_fuzzy_match_team` (so the call site is pinned): `SoCal Tsunami U14 - Anthony` links a stored `So Cal Tsunami` row with the flag on and does not with `athletes2events_rules = False`.

9. **Spelled compound directions read as SW/NW/NE/SE in A2E squad marks**
   - Give the module-level `_squad_marks(name, boys=False)` (`athletes2events_matcher.py:73`) a keyword-only `spelled_compounds: bool = False`; when true, add any of `northwest`, `northeast`, `southwest`, `southeast` found as a whole word in the name to `directions`. `_fuzzy_match_once` passes `spelled_compounds=extended` for both the provider and the candidate marks. TC's `club_before_squad_marks` (`tourneycentral_matcher.py:39`) keeps the default, so the TC, HTG, Heartland and Demosphere drivers' club guesses do not move. `DIRECTION_CANONICAL` and `_presplit` are not touched (they feed `teams.distinction` and Heartland's squad words).
   - Tests (`TestSquadMarks`): `"ECNL RL SW Girls U14"` and `"ECNL RL Southwest G13"` give equal `directions` with `spelled_compounds=True`; with the default they differ, as today. Call-site test through `_fuzzy_match_team`: `"SD Surf ECNL RL SW Girls U14 (Gonzalez)"` links a stored `San Diego Surf ECNL RL Southwest G13` with the flag on and is refused by the squad gate with `athletes2events_rules = False`.

10. **Accept any page of an event in `--event-url`** (`scripts/import_athletes2events_event.py:180`, `parse_event_url` `:352`)
    - Let `_EVENT_URL` take an optional trailing path or query after the event id, as TC's `(?:/\S*)?` does, keeping `https` only and the `re.IGNORECASE | re.ASCII` flags; the id must still be followed by `/`, `?` or the end (so `/events/198x` is refused). Update the error message's expected form.
    - Tests (`TestParseEventUrl`): `/events/198/groups`, `/events/198/schedules?flight-id=2224` and `/events/198/` give `("somsports.athletes2events.com", 198)`; `http://`, a non-ASCII digit and `/events/198x` stay refused.
    - Close the backlog entry "Let the Athletes2Events importer take any page of an event, not only its bare URL" in this PR: set `- **Status**: done`, add `- **Refs**:` with the branch, and move it into `.turbo/improvements-archive.md` by hand.

11. **Keep the skill and backlog in step**
    - `.claude/skills/scraper-patterns/SKILL.md`, Athletes2Events section: replace "a page link ... is refused" with "any page of the event works"; in *Reading an Athletes2Events team* add that a bare band (`16/17B`) ends the club and a 19xx founding year (`1974 Newark FC`) does not, for Athletes2Events only; in *Matching Athletes2Events teams* add the somsports club facts, the written-club second pass, the cut-back retry with its carried-words condition, spacing-blind club names and spelled compound directions, each marked Athletes2Events-only with the flag's name, and that no rule links a name that is only a club (owner choice; on event 198 such names ended in review or as new teams). Write paths and URLs with `<...>` placeholders or `https://`, never bare `.../x` (the doc-path test reads backticked tokens as paths).
    - `.claude/skills/scraper-patterns/SKILL.md`, *Provider Matcher Name Parsing*, the replay paragraph that says to use "a provider id that has no aliases": add that a branch-versus-control comparison must pass the **same** alias-free provider id to both runs, because a dry run's created team id is `uuid5` of the provider id and the team (`GameHistoryMatcher._new_team_id_master`); and that saved team reports hold the club split the old code made (and no written club), so a replay re-splits each row with the code under test before matching.
    - `.turbo/improvements.md` IMP-388: add `- **Update (<date>)**:` saying this change added an A2E-only stop beside `_CLUB_STOP` rather than sharing the cut, by owner choice, and the trigger has now fired once.

Steps 12-17 come from the revision above. Each is Athletes2Events-only: it runs only where `extended` is true or under the somsports host.

12. **A host club code ends at a hyphen too** (`scripts/import_athletes2events_event.py`, `HOST_CLUBS["somsports.athletes2events.com"]`)
    - End every somsports pattern with `(?![\w-])` instead of `\b`, so `LASC-SCV` (a separate branch club) keeps its own split. The Crossfire entries are unchanged.
    - Tests. Add `("LASC-SCV BU15 N1", ("LASC-SCV", "LASC-SCV"))` to `test_surf_cups_own_club_names_are_resolved`. Add a matcher-level case in `tests/unit/test_athletes2events_matcher.py`: `LASC-SCV BU15 N1`, registered with that split, does not link a stored `Los Angeles SC` row (club `Los Angeles Soccer Club`, u15 Male CA). Mutation: restore `\b` on the `LASC` entry alone, and the split case fails.

13. **Squad numbers must agree** (owner, 2026-11-19; `src/models/tournament_name_gates.py`, `src/models/yssl_matcher.py`, `src/models/athletes2events_matcher.py`)
    - Move `_ROMAN`, `_SQUAD_NUMBER`, `_BAND` and `squad_numbers` unchanged from `yssl_matcher.py:43-65` into `tournament_name_gates.py`, the home of the shared name readers. `yssl_matcher.py` imports `_ROMAN`, `_BAND` and `squad_numbers` from there; it already imports from that module at `:30`. It keeps `roman_to_digits`, `yssl_squad_number` and `_fits_squad_number`, so YSSL's behavior does not change. The A2E matcher cannot import from the YSSL module, because `yssl_matcher.py:29` imports the A2E matcher.
    - Add a module helper `_squad_numbers_agree(provider_text, candidate_text)` to `athletes2events_matcher.py`. It applies YSSL's rule (`yssl_matcher.py:78-81`): the provider's number is the smallest it carries; an unnumbered or `1` provider fits only a candidate carrying no number or a 1; a provider numbered 2 or more fits only a candidate carrying that number.
    - Call it in `_fuzzy_match_once`'s candidate loop beside `squads_conflict` (`athletes2events_matcher.py:351`), only when `extended` is true. Read both sides from the club-stripped canonical text the squad marks already read: `self._without_club(provider_team_name, provider_club_name)` and `self._without_club(candidate_name, club_in_name)`. That keeps a club's own digit from reading as a squad number (event 198's `7 Elite Academy u14B Copa South`). The rule lives in the loop, not in `_fetch_candidates`, so no per-team filter sits inside a candidate cache.
    - Tests in `tests/unit/test_athletes2events_matcher.py`, with literal expected team ids:
      - (a) Unnumbered half. Stored rows `2015 Blue` and `14/15 Boys Blue 2`, both under `Santa Cruz United Football Club`, u12 Male CA. `Sant Cruz United 14-15 Boys Blue`, split with the A2E stop, links `2015 Blue`.
      - (b) 2+ half. `XF U14 B12-13 ECNL 2 - Cruz`, split under the crossfire host, is created rather than linked to a stored `XF B13 ECNL` (club `Crossfire Premier`, u14 Male WA).
      - (c) 1 means unnumbered. `XF B13 Red 1` links a stored `XF B13 Red` under `Crossfire Premier`.
      - (d) A club digit is not a squad number. `7 Elite Academy u14B Copa South` links a stored `7 Elite Academy U14 Copa South` and not a stored `7 Elite Academy U14 Copa South 2`, with both candidates present.
      - (e) Glued forms, parametrized on `squad_numbers(canonical_team_name(name, _presplit))`. `SoCal Reds EA2`, `Legends G2010/11 NL1`, `XF U10 RCL 2` and `XF N1 B13` read no number; `Crossfire ECNL2 B13` reads `{2}`.
      - (f) Same cohort in sequence. One matcher registers `… Blue 2` and then `… Blue`, and each links its own row.
      - (g) Tourney Central is unchanged. The (a) fixture under `TourneyCentralGameMatcher` links the row it links today. Assert that row's id as a literal, read from a run without step 13.
    - Mutations, each killing its named new test: remove the unnumbered half (kills a); remove the 2+ half (kills b); make 1 match only 1 (kills c); read the unstripped canonical names (kills d); drop the `extended` gate (kills g).

14. **A shortened club counts only when the stored club vouches for it** (`src/models/athletes2events_matcher.py`)
    - Add `name_club_vouches: bool = True` to `_fuzzy_match_once`. When it is false, the candidate loop treats the club read from the candidate's name as absent: `name_club = None`, so `club_in_name` stays `None`, only the stored `club_name` can pass the club gate, and `_without_club` strips only the written and gate clubs. Only `_match_cut_back_club` passes `False`; the first pass and the written-club pass keep `True`.
    - Tests, with literal expected outcomes:
      - (a) Carlsbad, from the real rows. Stored `Carlsbad GU11 Gold - Dennis`, `City SC - Carlsbad 2016 Gold - Cordeiro` and `Carlsbad G18 Gold - Cardenas`, all under club `City SC`, u11 Female CA. `City SC Carlsbad Gold GU11-Dennis`, with its club from `split_club(name, "somsports.athletes2events.com", stop=_A2E_CLUB_STOP)`, goes to review at 0.89 and writes no alias. Passing `True` from the cut-back instead links the Cordeiro row.
      - (b) A carried word is missing while the stored club agrees. Re-point the existing `SACRAMENTO` fixture (`test_a_cut_back_club_never_links_a_row_without_the_cut_word`) to stored club `Legends FC (CA)`, so `must_carry` alone refuses it.
      - (c) The written-club pass still lets the name club vouch. `test_a_row_only_the_written_club_vouches_for_links_on_the_second_pass` must fail when that pass passes `False`.
    - Mutations: `True` in the cut-back (kills a); dropping `must_carry` (kills b); `False` in the written pass (kills c).
    - Accepted cost, from V2: on 137, `SDSC Surf Pre-ECNL BU12 I` is created rather than linking its exact-name row.

15. **Split the cut-back's club the way it splits candidate names** (step 7, already implemented)
    - The cut-back's words are the non-empty pieces of `_NAME_WORDS.split(club_name)`, for the cut and for `must_carry` alike. `words = club_name.split()` (`athletes2events_matcher.py:258`) makes a bare `-` a word: `Legends FC - San Diego` then cuts to `Legends FC -`, which is effectively one word, below the two-word floor, and a last level that must carry `-` can never match. Keep each cut club as the original prefix of `club_name` up to the end of its last kept word, so `_without_club` still finds it in the team name.
    - Tests:
      - `Legends FC - San Diego GU15 Elite I`, whose club split is `Legends FC - San Diego`, links a stored `San Diego GU15 Elite I` under `Legends FC (CA)`.
      - The same team does not link a stored `GU15 Elite I` under that club.
      - Mutation: splitting on whitespace again kills the first test. If it survives, change the fixture until it does not, and record why.

16. **Docs and backlog for steps 12-15**
    - `.claude/skills/scraper-patterns/SKILL.md`:
      - *Matching Athletes2Events teams*: replace "Count a label only when both names carry one" (`:866`) with: Athletes2Events squad numbers must agree even when only one name carries one (owner, 2026-11-19, as for YSSL). `RCL` and `N` labels still count only when both carry one; `ECNL2` reads as ECNL squad 2, so its number must agree too.
      - Add that a host club code ends at a hyphen (`LASC-SCV` is not `LASC`).
      - Add that a shortened club counts only when the stored club vouches for it.
      - In *Provider Matcher Name Parsing* (`:1486`), add one line pointing at the Athletes2Events exception, as the Utah exception at `:1565` does.
    - `.turbo/improvements.md`: add an entry for the Pre-tier risk the measurement found. A long club guess ending in `Pre` (`ECNL\d*` stops inside `Pre-ECNL`) strips the Pre tier from the provider's name, so a Pre-ECNL team can match an ECNL row through `is_same_club`; this was shown on a synthetic `Sporting California USA South Bay ECNL G2014` row. A created team is filed under club `X Pre` with a name reading `ECNL …`. A fix must keep `SDSC Pre-ECNL BU12 II, Mouhamed`'s link, and `Pre NPL` needs covering too.

17. **Tests that must catch what steps 4-9 claim**
    - Step 5's flag test derives the class list. Import every module in `src/models`, collect `Athletes2EventsGameMatcher` and its transitive subclasses, and assert `{cls.__name__: cls.athletes2events_rules}` equals the literal six-entry dict. A scratch subclass without an opt-out must fail it by name, per CLAUDE.md's "derive a guarded file list".
    - Step 9, reverse direction: a provider spelling `Southwest` links a stored row abbreviating `SW`. This kills the provider-side `spelled_compounds=False` mutation, which today only the Next Level test catches.
    - Step 6, extended reading: a written-club pass that links only through an extended reading, such as a stored name spelling the written club without its space. It must fail when that pass passes `extended=False`.
    - `test_the_athletes2events_retries_still_return_the_stored_team_name` must actually retry. Use a cut-back fixture (Next Level) and a written-club fixture (HB Slammers) instead of a first-pass link.

## Verification

- **Unit tests.** `python -m pytest tests/unit/test_import_athletes2events_event.py tests/unit/test_athletes2events_matcher.py tests/unit/test_tourneycentral_matcher.py tests/unit/test_import_tourneycentral_event.py tests/unit/test_heartland_matcher.py tests/unit/test_import_heartland.py tests/unit/test_htgsports_matcher.py tests/unit/test_import_demosphere.py tests/unit/test_yssl_matcher.py tests/unit/test_import_yssl.py tests/unit/test_tournament_name_gates.py tests/unit/test_affinity_hi_matcher.py tests/unit/test_provider_matcher_dry_run.py tests/unit/test_birth_year_guard_wiring.py tests/unit/test_agent_doc_references.py tests/unit/test_improvements_backlog.py -q` passes, then the full suite in CI's form. Step 13 moves `_ROMAN` out of the YSSL module, and `affinity_hi_matcher.py:20` imports `roman_to_digits` from it, which is why the HI tests are in the list. A local run without `frontend/node_modules` fails 5 Compare-predictor tests that CI passes; any other failure is real.
- **One mutation per rule.** For each rule below, revert only that rule in a scratch copy. Collect the failing test node ids, and confirm that the *new* test written for the rule is among them; a red suite alone does not count, and neither does a failing helper test. Record each mutation with its failing ids.
  - Step 2: the band half and the 19xx half separately.
  - Steps 3, 6, 8 and 9.
  - Step 7: the `must_carry` filter and the two-word floor separately.
  - Steps 12-15: the mutations listed in each step.
  - Step 17's cases.
  - Each call site alone: drop `stop=_A2E_CLUB_STOP` at the `build_roster` call; pass `extended=False` or `spelled_compounds=False` wherever `_fuzzy_match_once` and `_squad_marks` are called (the first pass, the written pass, the cut-back, and the provider and candidate marks); and pass `name_club_vouches` the wrong way at each of its three calls.
- **Isolate every replay from saved links.** `already = {}` skips only the importer's own lookup; `GameHistoryMatcher._match_team` still resolves approved aliases by provider id before fuzzy matching (`src/models/game_matcher.py`, its "Strategy 1/2" provider-id and alias lookups). So build each replay's matcher with a provider id that has no `team_alias_map` rows (the recipe under *Provider Matcher Name Parsing* in scraper-patterns): generate one UUID once, record it beside the replay output, pass that same value to the branch run and the origin/main control (a dry run's created team id is `uuid5` of the provider id and the team, `GameHistoryMatcher._new_team_id_master`, so two different ids would make every created row differ), pass it everywhere the harness passes the real one, and assert once with a read-only count that it has zero aliases. Every link the replay then reports came through fuzzy matching.
- **Re-split every row with the code under test.** `roster.json` and the saved team reports hold the club split origin/main made. Before matching, rebuild each row's `club_name` and `club_as_written` with the copy being run: on the branch through `split_club(team_name, host, stop=imp._A2E_CLUB_STOP)` (the same arguments `build_roster` passes), on the origin/main control through `split_club(team_name, host)`, choosing by `hasattr(imp, "_A2E_CLUB_STOP")`. Use the host each event was scraped from: `somsports.athletes2events.com` for 198 and 137 (its saved games link only to that host), `crossfire.athletes2events.com` for 130.
- **The harness.** `replay.py` (runs one code copy: `a2e` mode for events 198, 137 and 130, `siblings` mode for the six sibling reports), `prep_siblings.py` (builds the sibling inputs once from the control copy, so both sides read identical rows), `truth.py` (read-only: where each Athletes2Events id's approved alias ends after `team_merge_map`, with its `match_method`) and `compare.py` (scores a run). On 2026-11-19 these lived in the session scratchpad; copy them, with `sibling_inputs.json`, into `C:\PitchRank\data\athletes2events\event198_replay\harness\` (gitignored) before the final runs, and write outputs beside them. The isolated provider id is `1c3ff7d2-117a-427e-bbc2-608021e49dec`: zero aliases, teams and review rows on 2026-11-19, and `replay.py` asserts zero aliases again at start. `replay.py` memoizes candidate reads per age, gender and state filter. That is safe only while no team-dependent filter lives in `_fetch_candidates`, which is why step 13 puts its rule in the candidate loop. The final runs use the shipped code with no `VARIANT` set.
- **Event 198 replay (the ship bar).** Run `replay.py` in `a2e` mode on the code under test as is (`replay_198.py`'s monkeypatched variants are not used), under its fail-closed write guard (GET/HEAD plus `POST /rest/v1/rpc/get_approved_aliases` only, service key, `C:/PitchRank/.env` loaded in-process), with the isolation and re-split above. Score against `harness/picks_198.py` (PICKS and UNMATCHED, which include the owner's answers). Pass: right links ≥ 43, `WRONG LINK` = 0, refused writes = 0, and the two club-only names end as measured, `TopBallers` U12 (a2e 13098) in review and `LeonFC` (a2e 13687) created as new. Every twin row an earlier measurement's wrong links pointed at is merged by the time of the replay (LA Bulls and Slammers Maroon on 2026-11-19, AVSC per step 3), so any wrong link is a real one. Run the same harness on an origin/main copy (`git archive origin/main scripts src config | tar -x` into a scratch folder) the same day as the control, and report both counts with every link that differs between them.
- **Sibling replay (no change allowed).** For the saved team reports under `C:\PitchRank\data\raw\` — Tourney Central `wfc`, `partyonthepitch`, `terrorisland`; HTG `htg14130`; Heartland `2026fall`; YSSL — run each driver's matcher `_match_team` (`dry_run=True`, the isolated provider id, `already = {}`, same write guard) on the branch and on the origin/main copy, feeding **identical inputs to both sides**, and diff the outcome and team id per team. Pass: zero differences. This shows the branch changes nothing for these providers on these inputs; it is not a reproduction of the original imports, because Tourney Central and HTG reports keep the filed club but not the original club cell or the written club. For those, pass the report's `club_name` as the club and re-derive the written club with the driver's own `club_for` on both sides; for YSSL use the report's saved `club_as_written`. Demosphere has no local report; its no-change rests on step 5's flag test and `test_import_demosphere.py`, and the PR says so. The 2026-11-19 run (steps 1-11 against origin/main) showed zero differences over 2,720 teams. Re-run it on the finished code, because step 13 moves code out of the YSSL module. Report it as finished code against origin/main.
- **Other Athletes2Events events (grade every change).** Event 137 (somsports, `data/raw/athletes2events/137_20261022_140155_teams.csv`) and event 130 (Crossfire, `130_20260920_001940_teams.csv`) do get the new rules. Run the finished code against origin/main with the isolation and re-split above, using the outcome the importer would end with: a `shared_links` conflict is withheld, not a link. Give every team whose outcome or linked team differs one verdict, using `truth.json`:
  - **Confirmed:** links the team its approved alias resolves to, where that alias is neither the event's own created row nor a `fuzzy_auto` alias origin/main's own pass wrote.
  - **Corroborated:** agrees only with such a `fuzzy_auto` alias. That is not independent evidence; list it.
  - **Same squad, another record:** a different row of the same club, board, gender and squad label, usually a stale twin. Allowed; list it.
  - **Wrong squad:** blocks the PR. Use the games the stored rows played on the event's own dates where they settle it, as they did for Santa Cruz.
  - **Unverifiable:** the target has no games this season, or a name with no squad word links a row that names one. List these for the owner as a numbered list of team and link, and hold the merge until the owner answers. On V2 this covers `LAFC SO CAL YOUTH BU10` → `LAFC So Cal - The Sharks`, `LAFC BU12 PRE-ECNL I PLATINUM` → `25/26 B2015 PRE-ECNL`, and on 130 `XF BU17 ECNL 2 - Heimbigner` → `XF ECNL B2009/10 2`, unless that one is settled first from the two candidates' opponents. `B2010 XF ECNL Regional` reads tiers `{ecnl}`, and "Regional" is not read.
  - Also list every team that loses a link or moves to review or created, each against the costs named in the revision above. A cost not named there is a finding.
- **The club-only rule, operationally.** A newly automatic link blocks the PR as club-only when nothing but an age remains of the provider's name after removing three things:
  - the club the link was gated on (the cut club, for a cut-back link);
  - the linked row's stored `club_name` words;
  - the generic club words `fc`, `sc`, `soccer`, `club`, `youth`, `academy`.

  Tier words (`GA`, `Premier`) count as squad words. This still catches `LeonFC` and `TopBallers`, and it flags `LAFC SO CAL YOUTH BU10` and `Possible FC Academy` for the hand check. The Almaden, City SC, SoCal Reds and Inland links that the literal reading would flag stay exempt (measured on the saved names, 2026-11-19).
- **Read-only throughout.** No replay passes `--execute` or writes; each run prints its refused-write list, which must be empty.

## As built (2026-11-19)

Steps 1-17 are implemented in `C:\pitchrank-a2e-matching`. Three fixtures and two pieces of code differ from the steps as written:

- **Step 13(d).** The right row has to omit the club from its name (`U14 Copa South` under `7 Elite Academy`). With the club's 7 in both candidates' names, reading the whole name still linked the right row on exact name.
- **Step 15.** The designated kill is a floor case, `Desert - Storm Rangers U12 Red` against `Storm Rangers U12 Red` under `Desert`. For `Legends FC - San Diego`, the whitespace split's `Legends FC -` level behaves like `Legends FC`, so that test passes either way. It stays, as a check of the right behavior.
- **Step 17, written pass.** `HB Slammers` against `HBSlammers` passes `is_same_club` (0.95) without the spacing rule, so the fixture is `SlammersFC ECNL U13` under `Independent`, written club `Slammers FC`.
- **Steps 4 and 13, code (code review, 2026-11-19).** The squad-number rule is `squad_number_fits` in `tournament_name_gates.py`, beside `squad_numbers`, not a matcher-local `_squad_numbers_agree`; YSSL's `_fits_squad_number` calls it, and the old and new rule agree on all 12,097 saved provider/candidate pairs. The moved `_SQUAD_NUMBER` and YSSL's `_ROMAN_SQUAD` read the numeral ASCII-only, because under `IGNORECASE` alone `İ` and `ı` match `i` and raised `KeyError` at the numeral table. `_fuzzy_match_once` also takes `rows`: `_fuzzy_match_team` reads the candidates once per team and every pass gates those rows.

The three fixtures changed because their first versions could not fail their mutation.

Verification results, all on the finished code with no variant patches:

- **Tests.** The unit list passes. The full suite (CI form) fails only the 5 Compare and weekend-tuning tests that need `frontend/node_modules`: 14,722 passed.
- **Mutations.** 34 of 34 killed, each by its named new test. The receipt, with failing node ids, is `data/athletes2events/event198_replay/runs_2026-11-19/mutation_receipt_final.json`. After the code-review fixes, 40 of 40 (the 34 plus six for those fixes), receipt `mutation_receipt_round2.json` beside it; re-running both replays on that code changed no team's outcome (`out_smoke`, `out_smoke_sib`).
- **Event 198.** 46 right, 0 wrong (origin/main: 28). `TopBallers` U12 goes to review at 0.817 and `LeonFC` is created. 0 refused writes.
- **Event 137.** 55 teams change against origin/main.
  - 19 links are confirmed by where the real import's aliases ended up after merges.
  - No link is to a different squad.
  - 4 links are withheld as conflicts.
  - 8 teams that origin/main created as copies now go to review instead.
  - The rest are costs named in the revision, plus links to the event's own earlier rows.
- **Event 130.** 7 teams change: `ECNL 1` teams link the ECNL rows, and `ECNL 2` teams stop doing so.
- **Owner list.** 9 links were flagged, by a target with no games this season or by the club-only check.
  - Seven settle on the evidence. `Possible FC Academy` matches its real link. Six are an older record of the same club, board and squad label: AVSC Storm 2012 Black, Albion 2015 Pre-GA, LASC 2007 NG, LA Surf Hollywood Black, Almaden GA 08, XF ECNL 2.
  - Two cannot be confirmed: `LAFC SO CAL YOUTH BU10` → `LAFC So Cal - The Sharks` and `LAFC BU12 PRE-ECNL I PLATINUM` → `25/26 B2015 PRE-ECNL`. The owner chose "Ship as is" (2026-11-19).
- **Siblings.** 0 differences over 2,720 teams (Tourney Central ×3, HTG, Heartland, YSSL). 0 refused writes.

Run outputs and the harness are in `C:\PitchRank\data\athletes2events\event198_replay\` (`harness\`, `runs_2026-11-19\`).

## Context Files

- `scripts/import_athletes2events_event.py` — `_EVENT_URL`, `_CLUB_STOP`, `HOST_CLUBS`, `parse_event_url`, `split_club` and the roster pass that calls it.
- `src/models/athletes2events_matcher.py` — `_squad_marks`, `_without_club`, `_fetch_candidates`, `_fuzzy_match_team`, `_match_team` (where `_written_club` is set and cleared).
- `src/models/tourneycentral_matcher.py` — `club_before_squad_marks` and the written-club loop the A2E second pass mirrors; the subclass that must keep today's behavior.
- `src/models/yssl_matcher.py` — `distinguishing_words` and `_carries`, the carried-words precedent; `squad_numbers` and `_fits_squad_number`, the squad-number rule step 13 reuses (moving the reader to `tournament_name_gates.py`).
- `src/models/tournament_name_gates.py` — shared name readers; step 13's new home for `squad_numbers`.
- `src/models/squad_word_rules.py` — the `_filed_club` contract a retry must not disturb.
- `src/models/squad_name_gates.py` — `is_same_club`, which stays unchanged.
- `tests/unit/test_athletes2events_matcher.py` — the `_DB`/`_Query` double every new matcher test uses.
- `C:\PitchRank\data\athletes2events\event198_replay\` (gitignored) — event 198's pages, roster, owner answers, prior replay results and the replay harness. The saved `replay_*.json` files are not a baseline: the last ones were produced after the 40 event-198 aliases were written and before replay isolation, so the saved links mask the matcher in them. The measured figures this plan quotes (28, 43, TopBallers 0.817 review, LeonFC created) come from the earlier, un-masked runs; regenerate the control with the isolated harness.
