# Fix plan: team matching birth-year guard

**Written:** 2026-08-19 · Supersedes the diagnosis in the 2026-08-19 handoff.

## Diagnosis verdict

PARTLY RIGHT — your conclusion is correct and your mechanism is wrong, and the wrong mechanism pointed the fix at the wrong writer.

RIGHT, and it is the whole reason to do this work: an age label cannot separate cohorts and a birth year can. U19 holds 2008 and 2009 simultaneously (calculate_age_group_from_birth_year folds age 18 into 19), so no age-token setting at any strictness separates 'G09' from '2008'. I confirmed live that game_matcher._fuzzy_match_team — the import-path scorer — compares colors, directions, programs, team numbers, location codes, squad words and coach names in its candidate loop and does NOT compare age or birth year at all. A birth-year guard catches all 20 defective aliases in the database. Nothing else does.

WRONG (the crux): 'find_best_match narrows candidates using the stale stamp.' It does not. find_queue_matches.py:1002 calls extract_age_group(name, details), whose docstring at :592 reads 'ALWAYS parse from name first, metadata is unreliable'; the stamp is consulted only at :628-630 after five name patterns miss. Over all 11,202 pending rows: 5,866 name-derived, 5,335 stamp-fallback, 1 no age.

WRONG: 'require_age_token_match=False is the one guard that could have caught it, and it is off by design.' Verified live: should_skip_pair('Stateline SC-2011G Bears','Stateline SC-2013G Bears', require_age_token_match=False) returns True — that guard already blocks that pair. It was defeated by match_details.club_name being the ENTIRE provider team name (queue row 25260), which makes extract_distinctions strip the provider side down to nothing so the relaxed branch short-circuits on 'da and db'. 165 pending rows are in that state.

WRONG: '5,028 approvals did not join to teams — that is a real gap.' Not a gap. All 5,698 resolve; 5,028 hold teams.id and 670 hold teams.team_id_master, a clean cutover on 2026-06-01.

WRONG: two of your four named bad writes never happened. The upsert passes ignore_duplicates=True -> ON CONFLICT DO NOTHING, so 'Plant City 2007B Premier' still resolves to 'Plant City FC - Plant City 2007 Premier' (direct_id, 1.0) and 'Sporting San Diego - G2009 Black' still resolves to '2009 Black' (direct_id, 1.0). You read queue.suggested_master_team_id, which IS updated on approval, as if it were the alias. Only the two Stateline rows are real.

WRONG, and this is the one that matters most: 'this makes its errors LESS recoverable than the 5,016 bad merges.' find_queue_matches has written 52 aliases in its entire life, 7 of them defective, and ZERO games have flowed through those 7. The writer actually doing damage is the 15-minute import path: process_missing_games -> import_games_enhanced -> game_matcher.GameHistoryMatcher, which writes match_method='fuzzy_auto' at a LOWER threshold (0.90, config/settings.py:194) with no age comparison in its scoring loop. It produced 24 fuzzy_auto aliases in Aug, 30 in Jul, 68 in Jun, 800 (sincsports) in Apr — and all 8 remaining defective aliases, carrying ALL 75 misfiled games. Its Affinity-WA subclass runs weekly on wa-scraper.yml (Mon 06:00/07:00 UTC), five hours BEFORE data-hygiene-weekly, gated only by AGE_ROLLOVER_FREEZE which is currently 'false'. PR #980 does not touch it.

So: gate it, port the guard to the real writer first, then the batch scripts.

## Corrections to the earlier diagnosis

- The stamp is a last-resort fallback, not the filter driver. 5,866 of 11,202 pending rows derive their cohort from the name and discard the stamp entirely. Your '3,872 disagreeing stamps' is mostly inert; the live at-risk population (stamp load-bearing AND disagreeing with the name's birth year) is 875 rows.
- The mechanical gateway to the stamp is a regex boundary bug, not a design decision. `\b(20\d{2})\b` at :624 cannot match between '1' and 'G', so '2011G' / '2007B' / '2013G' are invisible to name parsing. Fixing that one lookaround moves 463 rows from stamp-driven to name-driven with only 3 regressions, measured against ground truth.
- Do NOT also 'fix' the U-age regex at :598. I measured it against ground truth (7,837 pending rows that already hold an alias; the aliased master's stored age_group is the cohort the SQL must hit): the `[bg]?u-?` change is +5 gains / 26 regressions, net -21. It inverts priority so a season-relative U-age beats an absolute birth year in the same name — 'SC del Sol U-11 (2015) Girls' currently reads 2015 -> u12 correctly and would start reading u11. That contradicts CLAUDE.md's own TGS rule.
- Your severity ordering is inverted. The 12 queue-path defective aliases carry 0 games. The 8 affinity_wa ones carry all 75. The queue-path script is now gated by PR #980; the affinity_wa writer is not gated by anything and runs weekly.
- 'match_method=fuzzy_auto' is not a fingerprint for find_queue_matches — at least six writers use that label (game_matcher, apply_unknown_opponent_matches, auto_match_unknown_opponents, dashboard, two sincsports discovery scripts). Key audits on team_match_review_queue.reviewed_by='auto-merge-script' or on the provider.
- A queue row marked 'approved' is not evidence of where games file. Of 5,698 auto-approvals, 5,458 still carry a pre-existing direct_id alias the DO-NOTHING upsert preserved, and the script printed 'Merged' for all of them. Any remediation keyed on the queue is wrong by two orders of magnitude.
- The revert tool's 93 dual-year exclusions were 'we cannot tell', not 'these are correct'. The new lossless extractor can tell, and it says 88 of them conflict — 79 of one shape ('<club> 2008' folded into '<club> B07/06'). That is a real backlog item you have not seen yet, not a cost of the guard.
- There is a second, unexamined population the same size problem could live in: 250 of 18,644 scannable direct_id alias pairs have provider-name/master-name birth years that conflict, carrying 7,834 games, and 196 of them have a same-club master whose year DOES match. Your census of '20 defective aliases' covers 549 of ~205,000 aliases.

## Steps

### 0. PRECONDITION — cut every branch from origin/main, not from this working tree

**File:** `(git hygiene; no file edit)`

The current tree (branch fix/emailed-auth-links-spent-before-click) has a data-hygiene-weekly.yml that PREDATES the commit adding FUZZY_AUTO_MERGE_ENABLED. Verified: `git diff origin/main --stat -- .github/workflows/` shows data-hygiene-weekly.yml at 11 lines changed, and the diff REMOVES `FUZZY_AUTO_MERGE_ENABLED: 'false'` plus Step 3's gate on it. Step 3 is find_fuzzy_duplicate_teams --auto-merge, the writer that produced the 5,016 merges you just reverted. Branching steps 1-10 off this tree silently un-gates it.

This is not a footnote — after step 8, that env flag is the ONLY containment for the 86 new merges the normalizer fix creates. Run `git fetch --all --prune` then `git checkout -b <branch> origin/main` for every step below, and confirm `git diff origin/main -- .github/workflows/data-hygiene-weekly.yml` is empty before opening any PR.

**Verify:** `git diff origin/main -- .github/workflows/data-hygiene-weekly.yml` returns empty on each new branch. `grep -c FUZZY_AUTO_MERGE_ENABLED .github/workflows/data-hygiene-weekly.yml` returns 2 (the env declaration and Step 3's gate).

**Rollback:** N/A — this is a check, not a change.

### 1. Merge PR #980 (gate the queue auto-approve). Correct its body first.

**File:** `.github/workflows/data-hygiene-weekly.yml, .github/workflows/auto-merge-queue.yml`

No redesign — the gate is correct as written (`QUEUE_AUTO_APPROVE_ENABLED: 'false'` ANDed into Step 4's `if:`, testing `== 'true'` so a renamed flag leaves the step skipped, applied to both workflows).

Two things to act on:
(a) `gh pr list` shows #980 still OPEN, mergeable. Step 4 runs Monday 11:00 UTC. Merge it.
(b) Correct two sentences in the body before merging. It says 'narrows candidates by the age_group stamped on a queue row' — that is wrong (extract_age_group is name-first; the stamp is a fallback reached on 5,335 of 11,202 rows). And it says 'the 6 links already written also need reverting' — the verified figure is 20 defective aliases of which 12 are on this path, and they are handled in step 9, not here. The gate itself is right regardless of the rationale text.

Approvals also landed on 2026-08-17 and 2026-08-19 (a Wednesday), so someone is invoking this off the Monday cron — most likely auto-merge-queue.yml's workflow_dispatch, whose dry_run defaults to 'false'. #980 gates both triggers.

**Verify:** Already green in the PR: tests/unit/test_age_rollover_freeze_coverage.py, 38 passed / 1 skipped. Post-merge, confirm the next scheduled run reports Step 4 as SKIPPED, not as 'analyzed 0'.

**Rollback:** Set QUEUE_AUTO_APPROVE_ENABLED back to 'true' in both workflows. Containment only; nothing is lost by leaving it off.

### 2. Gate the Affinity-WA import matcher — the writer holding all 75 misfiled games

**File:** `.github/workflows/wa-scraper.yml`

This is the correction to your severity ordering, and it is the only step that touches the writer with actual game-level damage.

Verified: wa-scraper.yml is on a live weekly cron (`- cron: '0 6 * * 1'` and `'0 7 * * 1'`, DST-gated in-job at :52-72), its import step at :143 is gated ONLY by `env.AGE_ROLLOVER_FREEZE == 'false'` (:29, currently lifted), and it runs five hours before data-hygiene-weekly's 11:00 slot. AffinityWAGameMatcher (src/models/affinity_wa_matcher.py:89) subclasses GameHistoryMatcher, whose accept path at game_matcher.py:774-786 writes match_method='fuzzy_auto' at `auto_approve_threshold` = 0.90. Its 8 defective aliases (2026-02-28 and 2026-03-15) carry 17+12+12+11+10+5+5+3 = 75 games — every misfiled game in the investigation. PR #980 does not cover it.

Add `AFFINITY_WA_AUTOMATCH_ENABLED: 'false'` to the env block and AND it into the :143 step's `if:`, in the same `== 'true'` shape #980 uses. Lift it after step 4 ships. Scraping keeps running and CSVs still upload as artifacts, so a gate costs a backfill, not a gap — the same trade the rollover freeze already makes.

If you would rather not pause WA collection for one week, the alternative is to reorder: ship step 4 first and skip this gate. I would not — step 4 needs the measurement in step 3, and this writer reproduces the exact U19 collapse (six of its eight defects are B09/G09 linked to a 2008 team) every Monday morning until then.

**Verify:** 1. `gh workflow view wa-scraper.yml` after merge, then confirm the next Monday run reports the import step as skipped.
2. Add wa-scraper.yml's import step to tests/unit/test_age_rollover_freeze_coverage.py's gated-step list so the gate cannot be silently widened by a top-level `||`.
3. Re-run the step-9 scan the following Tuesday and assert the affinity_wa defective count is still 8, not 9+.

**Rollback:** Flip AFFINITY_WA_AUTOMATCH_ENABLED to 'true'. One workflow file, one line.

### 3. Add the birth-year guard in ONE place: src/utils/team_name_utils.py

**File:** `src/utils/team_name_utils.py (new functions), scripts/_team_distinction.py (re-export)`

Placement is load-bearing. src/utils/team_name_utils.py imports only src/utils/team_utils (verified — no cycle), and it is already imported by src/models/game_matcher.py:42, by scripts/_team_distinction.py:21, and by scripts/find_fuzzy_duplicate_teams.py:40. It is the only module both the import path and the batch scripts already reach. Putting it in scripts/ would leave the real writer unable to use it; putting it in find_queue_matches would create a cycle (find_fuzzy_duplicate_teams imports normalize_team_name FROM there).

SEMANTICS = SUBSET. Refuse only when neither year-set contains the other. Measured: EXACT refuses 55 of 2,929 human-approved never-reverted merges (1.88%); SUBSET refuses 6 (0.20%). EXACT breaks the dual-year band convention — 'B08/07' vs '2008' is one team written from one end. SUBSET still refuses the case the shipped comment at find_fuzzy_duplicate_teams.py:105-107 defends ('Union 2010 FC 2009' vs '... 2008' -> {2009,2010} vs {2008,2010}, neither a subset), so nothing is lost.

READ THE RAW NAME. normalize_team_name's `\b(\d{2})\s+(boys|girls)\b` rule rewrites '08/07 Girls' to '08/2007', so the currently-shipped birth_years() reports a band label as a single wrong year — verified, it returns {'2007'}. Reading raw also decouples this guard from step 8 entirely, which is what makes the ship order safe.

Do NOT carry revert_fuzzy_auto_merges.DUAL_YEAR_RE's exemption into the guard. That exemption exists because the OLD extractor loses a year on 2-digit shorthand ('09/10B' -> {2010}); the new one does not, so the exemption's rationale is gone. It does mean the guard now refuses 88 of the 93 merges that exemption spared — see step 10; surface them, do not silently reverse them.

Leave require_age_token_match=False alone. Flipping it catches only 19-32 of the defects, over-rejects on names with no age token (the Codex P1 on PR #827), and is redundant once the year guard is in.

```python
# src/utils/team_name_utils.py — appended near AGE_PATTERN. Tested; all 16 pinned pairs pass.

_BIRTH_YEAR_MIN, _BIRTH_YEAR_MAX = 2005, 2020

# U-age tokens are cohort labels, not birth years: what they mean depends on the
# season that wrote them, so they are removed before any year is read.
_UAGE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:[BGMF]?U-?\d{1,2}[BGMF]?|[BGMF]?\d{1,2}U[BGMF]?)(?![\dA-Za-z])", re.I)
_DUAL_4_4 = re.compile(r"(?<!\d)(20\d{2})\s*[/-]\s*(20\d{2})(?!\d)")
_DUAL_4_2 = re.compile(r"(?<!\d)(20\d{2})\s*[/-]\s*'?(\d{2})(?!\d)")
_DUAL_2_2 = re.compile(r"(?<![\dA-Za-z])'?([BG])?(\d{2})\s*[/-]\s*'?(\d{2})([BG])?(?![\dA-Za-z])", re.I)
_YEAR_4 = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_APOS_2 = re.compile(r"'(\d{2})(?!\d)")
# A bare two-digit number is a squad number until a B/G affix or an adjacent
# Boys/Girls makes it a year: "Arsenal 11 B" is not a 2011 team.
_AFFIX_2 = re.compile(
    r"(?<![A-Za-z0-9])[BG](\d{2})(?:(?![Uu])[A-Za-z])?(?![\dA-Za-z])"
    r"|(?<![\dA-Za-z])(\d{2})[BG](?:(?![Uu])[A-Za-z])?(?![\dA-Za-z])", re.I)
_GENDER_WORD = re.compile(
    r"(?<!\d)(\d{2})\s+(?:boys|girls)\b|\b(?:boys|girls)\s+(\d{2})(?!\d)", re.I)


def _four_digit_year(two_digits: str) -> int:
    n = int(two_digits)
    return 2000 + n if n < 50 else 1900 + n


def birth_years(team_name: str | None) -> set[int]:
    """Birth years a team name states, as a set of ints. Empty = the name states none.

    Reads the RAW name. normalize_team_name is the wrong substrate: its
    "<2 digits> boys|girls" rule rewrites "08/07 Girls" to "08/2007", turning a
    band label into a single wrong year.
    """
    if not team_name:
        return set()
    text = _UAGE_TOKEN.sub(" ", team_name)
    years: set[int] = set()
    spans: list[tuple[int, int]] = []

    def _blanked() -> str:
        chars = list(text)
        for start, end in spans:
            for i in range(start, min(end, len(chars))):
                chars[i] = " "
        return "".join(chars)

    def _harvest(pattern, to_years):
        for m in pattern.finditer(_blanked()):
            spans.append((m.start(), m.end()))
            for y in to_years(m):
                if y is not None and _BIRTH_YEAR_MIN <= y <= _BIRTH_YEAR_MAX:
                    years.add(y)

    _harvest(_DUAL_4_4, lambda m: (int(m.group(1)), int(m.group(2))))
    _harvest(_DUAL_4_2, lambda m: (int(m.group(1)), _four_digit_year(m.group(2))))
    # An unmarked two-digit pair is only a band when the years are consecutive
    # ("08/07"); "6/7 Grinch Unit" is not a cohort.
    _harvest(
        _DUAL_2_2,
        lambda m: (_four_digit_year(m.group(2)), _four_digit_year(m.group(3)))
        if (m.group(1) or m.group(4) or "'" in m.group(0)
            or abs(int(m.group(2)) - int(m.group(3))) == 1)
        else (),
    )
    _harvest(_YEAR_4, lambda m: (int(m.group(1)),))
    _harvest(_APOS_2, lambda m: (_four_digit_year(m.group(1)),))
    _harvest(_AFFIX_2, lambda m: (_four_digit_year(m.group(1) or m.group(2)),))
    _harvest(_GENDER_WORD, lambda m: (_four_digit_year(m.group(1) or m.group(2)),))
    return years


def birth_years_conflict(name_a: str | None, name_b: str | None) -> bool:
    """True when two names state birth years that cannot belong to the same team.

    A birth year means the same cohort forever; an age label only means one against
    the season that wrote it, and U19 holds 2008 and 2009 at once — so age tokens
    cannot separate "G09" from "2008" and this is the only test that can.

    Subset, not equality: a band label carries both of its years ("Dallas Texans
    ECNL B08/07") and the same team is often written from one end ("... 2008").
    Two bands that merely overlap are NOT compatible: a club's 08/07 side and its
    06/07 side are different teams that happen to share 2007.
    """
    years_a = birth_years(name_a)
    years_b = birth_years(name_b)
    if not years_a or not years_b:
        return False
    return not (years_a <= years_b or years_b <= years_a)


# scripts/_team_distinction.py — re-export so both batch scripts reach one copy.
from src.utils.team_name_utils import birth_years, birth_years_conflict  # noqa: F401
```

**Verify:** 1. NEW UNIT TEST (tests/unit/test_birth_years_guard.py) pinning the 16 shapes: '2011', 'B2011', '2011B', 'G2011', "Surf SC Elite '09", '11G', '14B', 'B08/07', '2013/14', 'B2016/17', 'Team 08/07 Girls' -> {2007,2008}, 'GU18/19' -> set(), 'U14' -> set(), '14U' -> set(), 'Arsenal 11 B' -> set(), '6/7 Grinch Unit' -> set().
2. FALSE-REFUSAL BUDGET, TWO POPULATIONS (this is the check critique 2 was right that the design lacked). Replay over team_merge_audit where reverted_at IS NULL and action='merge':
   - performed_by in the human set (n=2,929): assert refusals <= 6.
   - performed_by='pitchrank-bot' (n=7,172): assert refusals <= 113, and assert that the 88 inside the DUAL_YEAR_RE-exempted set are enumerated in the test's docstring by name rather than silently absorbed.
   Fail the build if either rises. This is what stops a future re-tighten to EXACT (which would be 55 and 191).
3. REGRESSION PIN (not correctness evidence — see rejected critique): replay over the 549 fuzzy_auto alias pairs with a recoverable provider name and assert exactly 20 refused, pinned by alias_id.
4. `ruff check src/utils/team_name_utils.py scripts/_team_distinction.py`; `ruff format --diff` first and keep reformatting to touched lines only.

**Rollback:** Pure addition — nothing calls it until step 4. `git revert` the commit.

### 4. Wire the guard into the REAL writer: game_matcher's fuzzy accept path

**File:** `src/models/game_matcher.py:774 (accept path) and ~:1200 (base candidate loop)`

**Blocked by:** step 3

This is the step your diagnosis was missing and the one that actually stops the bleeding.

WHY THE ACCEPT PATH AND NOT ONLY THE LOOP: five subclasses OVERRIDE _fuzzy_match_team (affinity_wa:106, playmetrics, tgs, sincsports, modular11), so a guard placed only in the base candidate loop misses exactly the matchers that produced the defects. But every subclass's _match_team calls `super()._match_team(...)` (affinity_wa_matcher.py:276, playmetrics_matcher.py:~340), so game_matcher.py:774 is the shared choke point. Guard BOTH: :774 catches everyone, the loop keeps a wrong-year candidate from winning over a right-year one.

At :774 the guard must DEMOTE, not accept-and-alias: fall through to the review-queue branch rather than dropping the team entirely, so a genuinely-ambiguous name still lands in front of a human instead of silently vanishing.

In the base loop (~:1200, immediately after the existing distinctions gates) use `continue`, so a wrong-year candidate does not block a right-year one.

Subclass returns carry 'team_name' (verified: affinity_wa_matcher.py:230, playmetrics_matcher.py:281, base at ~:1284). Use `.get('team_name')` and add the assertion in verification #3 — if a subclass ever stops returning it the guard would silently fail open, which is the inert-guard failure mode.

```python
# src/models/game_matcher.py — import alongside the existing team_name_utils import at :42
from src.utils.team_name_utils import birth_years_conflict

# --- game_matcher.py:774, replacing the bare `if confidence >= self.auto_approve_threshold:` ---
            if fuzzy_match:
                confidence = fuzzy_match["confidence"]
                candidate_name = fuzzy_match.get("team_name")

                # A birth year means the same cohort forever; the age_group this
                # candidate was filtered by is derived from the wall clock and U19
                # holds 2008 and 2009 at once — so nothing above this line can tell
                # "G09" from "2008". Demote rather than drop: an ambiguous name still
                # deserves a human, it just must not auto-alias.
                # This is the choke point every provider subclass reaches via
                # super()._match_team(); the subclasses override _fuzzy_match_team.
                year_conflict = birth_years_conflict(team_name, candidate_name)

                # Auto-approve high confidence matches (0.9+)
                if confidence >= self.auto_approve_threshold and not year_conflict:
                    ...unchanged _create_alias block...

                # Flag for review if between 0.75-0.9, or if the years disagree
                elif confidence >= self.review_threshold or year_conflict:
                    ...unchanged _create_review_queue_entry block...

# --- game_matcher.py ~:1200, inside the candidate loop, after the squad_words gate ---
                # Drop, don't reject the whole search: a wrong-year candidate must
                # not shadow a right-year one further down the same result set.
                if birth_years_conflict(team_name, cand_name):
                    continue
```

**Verify:** 1. UNIT TEST with a fake db client covering both branches at :774 — confidence 0.97 with agreeing years -> _create_alias called with fuzzy_auto; confidence 0.97 with conflicting years ('Eastside FC B09 Red' vs 'Eastside FC 2008 Red') -> NO alias write, one review-queue row, returned method is the review method.
2. REPLAY THE 8 KNOWN AFFINITY DEFECTS through the guard and assert all 8 are demoted: XF B13 RCL 1 / Eastside FC B09 Red / Seattle United B09 Copa A / Whatcom FC Rangers G09 Gold / Eastside FC G09 White / XF B17 RCL 1 / XF G11 ECNL RL / Seattle United G09 Copa A.
3. ANTI-INERT: assert each overriding matcher's _fuzzy_match_team return dict contains 'team_name' — parametrize over AffinityWAGameMatcher, PlayMetricsGameMatcher, TGSGameMatcher, SincSportsGameMatcher, Modular11GameMatcher. A missing key makes the guard silently pass.
4. DRY-RUN PROOF (CLAUDE.md rule): confirm an EnhancedETLPipeline dry run still issues zero writes with the guard in place.
5. Run the existing tests/ suite for the matchers.

**Rollback:** `git revert`. The guard is additive — reverting restores the prior accept behaviour exactly; no data is written or migrated by this step.

### 5. Wire the guard into the batch scripts (queue matcher + masters dedup)

**File:** `scripts/find_queue_matches.py:886-889 and :1132, scripts/find_fuzzy_duplicate_teams.py:64 and :105-110`

**Blocked by:** step 3

THREE CALL SITES, all verified to have the fields they read:

(a) find_queue_matches.py:1132, immediately AFTER the should_skip_pair call, as `continue` not `return None`. Reads queue_entry['provider_team_name'] (selected by analyze_queue at :1198) and team['team_name'] (selected by _build_base_query at :1009 and _cohort_fallback_candidates at :940-954). Cohort-fallback candidates re-enter this same loop, so one guard covers both.

(b) find_queue_matches.py:886-889, replacing the `_extract_birth_year_token` guard in resolve_via_stored_candidates. That helper returns a SINGLE year and so cannot express a dual-year band ('B08/07' vs '2008' reads as a conflict to it). This path is live, not defensive: 196 pending rows and 82 already-approved rows carry a non-empty candidates array, and it returns early at :993-996 BEFORE the variant, program-tier and should_skip_pair gates, so it is the least-guarded path in the file.

(c) find_fuzzy_duplicate_teams.py:105-110, replacing the EXACT test, and delete the now-dead local birth_years() at :64 in favour of the shared import. Leaving EXACT costs ~55 legitimate merges per full pass.

UNNAMED CONSUMERS YOU MUST KNOW ABOUT (both critiques were right that the design undercounted). score_team_pair and normalize_team_name are also imported by:
- scripts/auto_match_unknown_opponents.py:41-42 — runs weekly on unknown-opponent-hygiene-weekly.yml (`cron: '0 18 * * 2'`), --auto-threshold 0.95, gated only by AGE_ROLLOVER_FREEZE (:59, 'false'). It upserts team_alias_map AND UPDATEs games.home_team_master_id / away_team_master_id. This one mutates game rows.
- src/tournaments/event_team_matcher.py:15 — imports score_team_pair, _should_skip_pair and normalize_team_name; feeds gotsport tournament canonical resolution.
- scripts/validate_normalizer.py:25 — imports should_skip_pair.
The guard is a TIGHTENING at all three, so it cannot start new links there. Measure anyway (verification #4) — auto_match_unknown_opponents writing to games means a surprise there is not alias-only.

```python
# --- find_queue_matches.py, in the candidate loop right after the should_skip_pair call at :1132 ---
        # should_skip_pair cannot separate cohorts: extract_distinctions converts
        # birth years to age bands first, and u19 holds 2008 and 2009 at once, so
        # "Surf SC Elite '09" and "'08" both yield age_tokens=('u19',).
        # continue, not return: a wrong-year candidate must not block a right-year one.
        if birth_years_conflict(name, team["team_name"]):
            continue

# --- find_queue_matches.py, replacing the _extract_birth_year_token guard at :886-889 ---
    # _extract_birth_year_token returns a single year and cannot express a dual-year
    # band label, so "B08/07" against "2008" reads as a conflict when it is one team
    # written from one end.
    if birth_years_conflict(provider_name, best.get("team_name")):
        return None, 0.0, None

# --- find_fuzzy_duplicate_teams.py, replacing the EXACT test at :105-110 ---
    # Subset, not equality: "FCDA 2015/16B" and "FCDA 2015" are one team written two
    # ways, and exact equality refuses 55 of 2,929 known-good human merges. Two bands
    # that merely overlap are still refused (08/07 vs 06/07 share 2007 and are not
    # the same team).
    if birth_years_conflict(name_a, name_b):
        return None

# --- find_fuzzy_duplicate_teams.py:64 — delete the local birth_years() and import the shared one.
# Note revert_fuzzy_auto_merges.py:52 imports birth_years FROM this module; the
# re-export keeps that caller working, but its DUAL_YEAR_RE exemption is now
# redundant against the lossless extractor — see step 10.
```

**Verify:** 1. Extend tests/unit/test_find_queue_matches_age.py (it already imports find_best_match, has _FakeClient, and sets _disable_tiebreaks) with the two Stateline rows end-to-end: assert the wrong-year sibling is dropped and, where the right-year master is in the fake candidate set, that it wins. This is the anti-inert check — if provider_team_name or team_name were unavailable the guard would silently pass and this test fails.
2. Add a case for the stored-candidates path at :886-889 with a 'B08/07' vs '2008' pair, asserting it is NOT refused (the old single-year guard refuses it).
3. Re-run step 3's two false-refusal budgets — they must be unchanged, because birth_years reads the raw name and is not affected by anything in these files.
4. MEASURE THE THREE UNNAMED CONSUMERS before merging: replay auto_match_unknown_opponents' scoring over its candidate set at 0.95 and report links started/stopped (expect started=0); replay event_team_matcher.search over one real event and report the resolved_status distribution shift. If either shows a NEW link, stop — the guard should only ever remove.
5. `ruff check` on the touched files.

**Rollback:** `git revert`. Both scripts' writers are gated off (Step 3 by FUZZY_AUTO_MERGE_ENABLED, Step 4 by step 1), so a revert cannot leave a half-state.

### 6. Fix ONE extract_age_group regex — the 4-digit-year boundary. Do NOT touch the U-age one.

**File:** `scripts/find_queue_matches.py:624`

**Blocked by:** step 5

`\b(20\d{2})\b` cannot match between '1' and 'G', so the very common suffix form '2011G' / '2007B' / '2013G' is invisible to name parsing and falls through to the stored stamp. Verified: extract_age_group('Stateline SC-2011G Bears', {}) returns None.

I measured both proposed regex changes separately against ground truth — the 7,837 pending rows that already hold an alias, where the aliased master's stored age_group is the cohort the candidate SQL must hit (both _build_base_query and _cohort_fallback_candidates filter teams.age_group exactly, so a disagreement makes the true target unreachable):
  P3 (this change):      +463 gains, 3 regressions, net +460
  P1 ([bg]?u-? for GU11): +5 gains, 26 regressions, net -21
SHIP P3 ONLY. P1 promotes a season-relative U-age above an absolute birth year in the same name: 'SC del Sol U-11 (2015) Girls Pre Academy Blue' currently reads 2015 -> u12 and matches its target's stored label; after P1 it reads u11 and the candidate set goes empty. 'Black Hills Rapids GU11 Burgundy' (true target 'BH Rapids 2015 Burgundy', stored u12) has the same shape. CLAUDE.md's TGS section says a U-age 'must be resolved against the event's own game dates, never the wall clock' — P1 resolves it against the wall clock. If TGS's GU11 format genuinely needs reading later, it has to go BELOW the birth-year priorities, which is a different change with its own measurement.

DROP the _team_distinction.py:218 AGE_PATTERN edit entirely — see step 7's blocked_by note; it is the one change in the original design that actively undoes the guard.

```python
# scripts/find_queue_matches.py:624 — Priority 3, digit boundary not word boundary.
#   \b cannot match between '1' and 'G', so the very common suffix form
#   "2011G"/"2007B" is unparseable and falls through to the stored stamp.
#   Priority 1's U-age pattern is deliberately left alone: promoting a
#   season-relative U-age above an absolute birth year in the same name is a
#   net regression (+5/-26 against the aliased-master ground truth).
    match = re.search(r"(?<!\d)(20\d{2})(?!\d)", name)
```

**Verify:** 1. Unit tests in tests/unit/test_find_queue_matches_age.py pinning extract_age_group('Stateline SC-2011G Bears', {}) == 'u16' and extract_age_group('DME Academy 2014B Blue', {}) == 'u13' — both currently return None. Add a NEGATIVE pin that extract_age_group('SC del Sol U-11 (2015) Girls Pre Academy Blue', {}) still returns 'u12', so nobody adds P1 later without noticing.
2. GROUND-TRUTH DIFFERENTIAL before merging (this is the check that catches what a naive 'no name-derived row changes' check cannot, because the regressions previously derived from the STAMP): re-run extract_age_group(name, match_details) over the 7,837 pending rows that hold an alias, compare against the aliased master's stored age_group, and assert agreement rises from 4,325 and regressions are <= 3.
3. Confirm stamp-fallback drops from 5,335 toward ~4,870 over the full 11,202.

**Rollback:** One-line `git revert`. Reverting restores the stamp fallback for those 463 rows; the step-5 guard remains and keeps a wrong cohort non-fatal either way.

### 7. Fix normalize_team_name's word-boundary bug — letter boundaries, NOT \b

**File:** `scripts/find_queue_matches.py:94`

**Blocked by:** step 5 (the guard), step 0 (the branch precondition is the ONLY containment for the 86 new merges)

The obvious fix is wrong. Adding `\b` over-corrects: across all 188,637 non-deprecated teams, `\b` and the letter-boundary form disagree on 208 values and EVERY disagreement is `\b` refusing to strip a tier token providers glue to digits — 'GA10/11' stays 'ga10/11', 'ECNL11G' stays 'ecnl11g', 'G2010GA' stays 'g2010ga', '13GA' stays '13ga'. Use letter-boundary lookarounds. Input is already lowercased at :79, so [a-z] suffices. Reorder longest-first so 'ecnl-rl' matches whole; cosmetic only (:95 eats the orphan hyphen) but it makes the intent readable.

Current damage: 16,357 team_name/club_name values mangled ('Michigan Jaguars 2013' -> 'michi n jaguars 2013'; 'Charlotte Independence SC' -> 'cha otte independence sc'). One genuine win: the bug currently force-collapses 'ECNL' / 'ECNLRL' / 'RL' into one normalized identity (44 collision buckets, 230 teams) — a direct ECNL != ECNL-RL tier violation the fix removes.

SHIPS LAST, AND ITS CONTAINMENT IS NOT WHAT THE ORIGINAL DESIGN CLAIMED. The design said 'item 2's guard closes the ones that state years'. That is FALSE and I am correcting it: of the 86 new merges this unmasks at find_fuzzy_duplicate_teams' 0.90 bar, 67 have MATCHING years, 19 have no year on one side, and ZERO have disagreeing years — so the birth-year guard blocks 0 of 86. The 86 come from the club-word-stripping branch at find_fuzzy_duplicate_teams.py:128-136, which the mangled normalizer was accidentally suppressing for every club containing ga/rl/ecnl/academy. The ONLY containment is FUZZY_AUTO_MERGE_ENABLED='false' on origin/main. That is why step 0 is a hard precondition and not a footnote.

ALSO UNMEASURED: event_team_matcher.py:296-299 sets normalized_name_exact by comparing normalized names and forces score to 0.995, which routes to 'strict_exact' (:374-380) and thence to match_method 'fuzzy_auto' in gotsport.py:3667-3676. This fix moves that flag in BOTH directions — 230 teams stop colliding, 16,357 restored values create new exact pairs. Measure before merging.

```python
# scripts/find_queue_matches.py:94
# Letter boundaries, not \b: providers glue tier tokens to digits ("GA10/11",
# "ECNL11G", "13GA"), and \b would stop stripping those — 208 values regress.
# Without any boundary the substrings tear real words apart: "Michigan" ->
# "michi n", "Charlotte" -> "cha otte", across 16,357 name values.
# Longest-first so "ecnl-rl" matches whole rather than as "ecnl" then "rl".
    n = re.sub(
        r"\s*(?<![a-z])(pre-?ecnl|ecnl-?rl|mls[- ]?next|academy|ecnl|rl|ga)(?![a-z])\s*",
        " ",
        n,
    )
```

**Verify:** 1. Unit test pinning BOTH directions in one table. Must be fixed: 'Orlando City 2010' -> 'orlando city 2010'; 'Michigan Jaguars 2013' -> 'michigan jaguars 2013'; 'Galaxy 2014 Blue' -> 'galaxy 2014 blue'; 'Vargas SC' -> 'vargas sc'. Must STILL strip: 'GA10/11' -> '10/11'; 'ECNL11G' -> '2011'; '2011 ECNLRL' -> '2011'; 'FC Dallas ECNL RL 2011' -> 'fc dallas 2011'; 'MLS NEXT 2010' -> '2010'. The second half is what fails if someone simplifies this to \b.
2. WHOLE-CORPUS DIFF before merging: old vs new over every team_name and club_name; assert the only changes are letters restored and NO value loses a digit (verified today: 16,357 values change, 0 lose a year under letter-boundary; a plain \b loses 13).
3. RE-RUN step 3's regression pin and both false-refusal budgets and assert they are bit-identical. birth_years reads the RAW name, so if any of those move, the guard was accidentally wired to the normalized name and is now coupled to this fix.
4. MEASURE event_team_matcher: replay .search over one real event's candidate set old-vs-new and report the resolved_status distribution shift in both directions. Do not merge on an unmeasured strict_exact change — that path writes fuzzy_auto aliases through gotsport.py.
5. Re-confirm on origin/main that FUZZY_AUTO_MERGE_ENABLED: 'false' is still present in data-hygiene-weekly.yml.

**Rollback:** `git revert`. No data is migrated. Because Step 3 is gated off, no merge has been written from the new normalization, so a revert leaves nothing behind.

### 8. Make the queue writer honest about what it actually wrote

**File:** `scripts/find_queue_matches.py:1367-1428 (execute_merges)`

**Blocked by:** step 6

This is what the stale-stamp framing hid, and it is the reason any audit keyed on the queue is wrong by two orders of magnitude. The upsert at :1388 passes ignore_duplicates=True -> ON CONFLICT DO NOTHING, so the write is a guaranteed no-op on the 7,837 of 11,202 pending rows that already hold an alias. But the queue UPDATE at :1401 is unconditional and inside the same try, so the row is stamped 'approved' with a suggested_master_team_id that never took effect and the operator sees '✅ Merged'. That is how 5,698 approvals produced 52 aliases.

BOTH CRITIQUES CAUGHT A REAL BUG IN THE ORIGINAL SNIPPET AND I HAVE FIXED IT: the design assigned `landed` inside `if not dry_run:` but read it at the outer level, and never initialized `skipped`. execute_merges declares only `approved = 0` and `failed = 0` at :1367-1368. On a DRY RUN — the argparse default and the branch main() takes without --execute — `landed` is unbound, UnboundLocalError is swallowed by the existing `except Exception`, and every candidate prints '❌ Failed' while nothing is wrong. On --execute, `skipped` is unbound on the first iteration and raises AFTER the alias upsert and the queue UPDATE have both run, so a successful write is counted as a failure. The code below hoists both.

Also corrected: the read-back must compare match_method, not just team_id_master. Without it, `landed` is True whenever ANY alias points at the chosen master — including the ~4,408 pre-existing direct_id ones — so the post-deploy invariant 'every approved row has a matching fuzzy_auto alias' would fail on the majority by construction.

OPEN QUESTION CLOSED: I checked pg_constraint. team_match_review_queue carries only its PK and `confidence_range CHECK (confidence_score >= 0.75 AND confidence_score < 0.90)`. There is NO CHECK or enum on status (live values: approved 11,611 / pending 11,202 / rejected 150), so 'already_aliased' is safe and needs no migration. The real consumer risk is the admin UI: dashboard.py:419 is `{'pending','approved','rejected'}.get(status, '⚪')` and the filter selectbox at :330 drives `.eq('status', ...)` at :363 — a fourth value renders with a blank icon, no action controls, and never appears in the dropdown. Extend both in the same PR.

Do NOT bundle the one-off backlog trim (closing the 7,837 already-aliased rows) into this PR. Per CLAUDE.md, automated pipelines and manual operator tools are separate concerns. It is bookkeeping, not risk.

```python
# scripts/find_queue_matches.py — execute_merges. Initialize alongside approved/failed:
    approved = 0
    failed = 0
    skipped = 0

    for r in candidates:
        q = r["queue_entry"]
        m = r["match"]
        landed = False  # hoisted: read below on BOTH the dry-run and execute paths

        try:
            if not dry_run:
                ...unchanged provider lookup and db_score...

                # ignore_duplicates=True compiles to ON CONFLICT DO NOTHING, so this
                # is a silent no-op whenever an alias already exists — 7,837 of 11,202
                # pending rows. Marking those "approved" records a decision that never
                # took effect and prints "Merged": 5,698 approvals produced 52 aliases.
                supabase.table("team_alias_map").upsert(
                    {...unchanged...},
                    on_conflict="provider_id,provider_team_id",
                    ignore_duplicates=True,
                ).execute()

                # Read back rather than trusting the upsert's return, which is empty
                # under ignore-duplicates. match_method matters: a pre-existing
                # direct_id alias pointing at the same master is NOT our write.
                live = (
                    supabase.table("team_alias_map")
                    .select("team_id_master, match_method")
                    .eq("provider_id", provider_uuid)
                    .eq("provider_team_id", q["provider_team_id"])
                    .limit(1)
                    .execute()
                ).data
                landed = bool(live) and live[0]["team_id_master"] == m["team_id_master"] \
                    and live[0]["match_method"] == "fuzzy_auto"

                supabase.table("team_match_review_queue").update(
                    {
                        "status": "approved" if landed else "already_aliased",
                        # Only claim the suggestion when the alias actually points there.
                        "suggested_master_team_id": m["team_id_master"] if landed else None,
                        "reviewed_by": "auto-merge-script",
                        "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    }
                ).eq("id", q["id"]).execute()

            if dry_run:
                approved += 1
                verb = "Would merge"
                icon = "✅"
            else:
                approved += landed
                skipped += (not landed)
                verb = "Merged" if landed else "Kept existing alias"
                icon = "✅" if landed else "↔️"
            print(f"  {icon} {verb}: {q['provider_team_name']} → {m['team_name']} ({r['score']:.1%})")

        except Exception as e:
            failed += 1
            print(f"  ❌ Failed [{q['id']}]: {e}")

    return approved, failed, skipped   # main()'s summary line must unpack three

# dashboard.py:419 — a fourth status must not render blank with no controls.
    status_icon = {"pending": "🟡", "approved": "🟢", "rejected": "🔴",
                   "already_aliased": "↔️"}.get(status, "⚪")
# dashboard.py:330 — add "already_aliased" to the selectbox options.
```

**Verify:** 1. DRY-RUN TEST (the one that would have caught the design's bug): assert a dry run completes, issues ZERO writes, and increments neither `failed` nor `skipped`. CLAUDE.md's dry-run rule, and 'a dry run is only as good as its weakest writer'.
2. Fake-client test for both execute branches: no alias -> status 'approved', suggestion set, approved+=1; alias present pointing elsewhere or with a different match_method -> status 'already_aliased', suggestion NULL, skipped+=1, printed line reads 'Kept existing alias'.
3. Assert main() unpacks three values — the return arity changed.
4. POST-DEPLOY, once step 1's gate is lifted: `SELECT status, count(*) FROM team_match_review_queue WHERE reviewed_at > <run start> GROUP BY 1` should show a large already_aliased bucket and a small approved bucket, and every approved row must have a fuzzy_auto alias pointing at its recorded suggestion. That invariant holds for 52 of 5,698 today.
5. ANTI-INERT: the read-back selects team_id_master and match_method explicitly. Do not shorten to select('*') and do not infer landing from the upsert's return value, which is empty under ignore-duplicates and would pin `landed` False forever.

**Rollback:** `git revert`. It writes a new status value but no schema change, so rollback is `UPDATE team_match_review_queue SET status='approved' WHERE status='already_aliased'` if you want the old vocabulary back — though the honest value is the point.

### 9. Repair the 12 queue-path defective aliases — RE-POINT, do not delete, and only after the guard

**File:** `scripts/repair_defective_aliases.py (new), read-only scan first`

**Blocked by:** step 4 and step 5

REORDERED AFTER THE GUARD, and the method changed from delete to re-point. Both critiques were right and I verified why: the provider matchers AUTOCREATE on an alias miss. src/models/playmetrics_matcher.py:337-346 ('Try base matching (alias / direct_id / fuzzy). On miss, autocreate a new team'), affinity_wa_matcher.py:307, sincsports_matcher.py:596, modular11_matcher.py:592. Deleting an alias for those providers does not park the team awaiting a guarded re-match — the next import creates a DUPLICATE canonical team with a wall-clock-derived age and writes a fresh direct_id alias to it, invisible to any fuzzy_auto-filtered scan. playmetrics-scrape-import.yml runs weekly and is deliberately ungated. That is strictly worse than the defect. (The base GameHistoryMatcher does NOT autocreate — it returns matched:False — so gotsport alone would have been safe to delete. Not worth two code paths.)

RE-POINT is available for at least 8 of the 12: I queried same-club, same-gender, non-deprecated masters whose birth years match the provider name and found an exact-name target for Stateline SC-2011G/2011B/2012B/2013B/2013G Bears, 'West Pines United FC 2009 Elite', 'Real FA 2014 Pre-MLS' and 'SJEBFC ECNL RL 2011'. Re-point those. For the three playmetrics_tournament 'Blue' rows only 'Tan' siblings exist and for 'CSC 14 Girls Navy North' the candidates are 'SC Navy North 2014' and 'CSC 2014 Navy South' — do NOT guess. Leave those four alone and list them in step 10.

DRIVE THE SCAN FROM team_alias_map, NEVER FROM THE QUEUE. The queue records 5,698 'approvals' of which 52 produced an alias; a queue-driven scan is wrong by two orders of magnitude. Two joins that must be commented or they will be 'tidied' into silence: team_match_review_queue.provider_id holds the provider CODE as text while team_alias_map.provider_id holds the providers UUID — `q.provider_id = p.code` is correct and `q.provider_id = a.provider_id` returns zero rows and a clean bill of health.

STATE THE BLIND SPOT HONESTLY IN THE OUTPUT. Not '20 defective'. Say: 20 defective of 549 scannable fuzzy_auto aliases; 1,596 fuzzy_auto aliases unscannable (no provider_team_name column); and the entire direct_id population (18,644 scannable pairs, 250 conflicting, 7,834 games) deliberately out of scope — see step 10.

Sequence after PR #979 merges. #979 (repair_zero_alias_teams.py) exists to eliminate alias-less live teams; do not race it from the same session.

```python
# --- scan (read-only). ORDER BY is required: 270 (provider_id, provider_team_id)
# groups hold multiple queue rows and 16 carry more than one distinct name, so a
# bare DISTINCT ON is one data change away from a nondeterministic verdict.
# NOTE: queue.provider_id is the provider CODE (text); alias.provider_id is the
# providers UUID. Do not "fix" this join.
SELECT DISTINCT ON (a.id)
       a.id AS alias_id, p.code AS provider, a.provider_team_id,
       q.provider_team_name, t.team_name AS current_target, a.team_id_master
FROM team_alias_map a
JOIN providers p               ON p.id = a.provider_id
JOIN team_match_review_queue q ON q.provider_id = p.code
                              AND q.provider_team_id = a.provider_team_id
JOIN teams t                   ON t.team_id_master = a.team_id_master
WHERE a.match_method = 'fuzzy_auto'
ORDER BY a.id, q.created_at DESC, q.id DESC;
-- then in Python: keep rows where birth_years_conflict(provider_team_name, current_target)
-- ABORT THE WHOLE RUN if this returns zero rows: a zero-row scan is a broken join,
-- not a clean database.

# --- for each row, find the re-point target; refuse rather than guess ---
SELECT team_id_master, team_name FROM teams
 WHERE club_name = %(club)s AND gender = %(gender)s AND is_deprecated = false;
-- keep candidates where birth_years(cand) is non-empty AND
--   NOT birth_years_conflict(provider_team_name, cand).
-- Exactly one exact normalized-name match -> re-point. Otherwise SKIP and report.

# --- the safety assertion, inside the same transaction as the update ---
SELECT count(*) FROM games g JOIN providers p ON p.id = g.provider_id
 WHERE p.code = %(provider_code)s
   AND (g.home_provider_id = %(provider_team_id)s
     OR g.away_provider_id = %(provider_team_id)s);
-- must be 0. Verified 0 for all 12 today, but 2 of them (gotsport/3738758 and
-- playmetrics/45471) sit on providers writing 1,260,832 and 2,319 game rows, and
-- the gotsport drainer runs every 15 minutes — so this can change between scan
-- and run. Non-zero: abort that row and re-plan it as a game re-attribution.

# --- the repair, per row ---
UPDATE team_alias_map
   SET team_id_master = %(correct_master)s,
       match_confidence = 1.0,
       review_status = 'approved'
 WHERE id = %(alias_id)s;
-- leave the queue row's status alone: it is already 'approved' and the alias now
-- points at the right master, so there is nothing for a human to re-decide.
```

**Verify:** 1. `--dry-run` is the default (CLAUDE.md rule), printing alias_id / provider / old target / new target / years on each side, plus an explicit SKIPPED list with the reason. A live `--execute`.
2. Write every acted-on row to CSV BEFORE the update — old team_id_master, old match_confidence, old review_status. team_alias_map has no audit table and no revert RPC (PR #979 confirms this), so the CSV is the only rollback that exists. Mirror #979's convention.
3. Re-run the game-count assertion inside the same transaction as each UPDATE and abort that row on non-zero.
4. Post-run: re-run the scan and assert the repaired alias_ids no longer appear in the defective set, and that the skipped ones still do (they should — they are deliberately untouched).
5. POST-IMPORT WATCH, one cycle per affected provider: assert no NEW team was created for those provider_team_ids and no new alias row appeared. This is the check that would catch an autocreate if re-pointing somehow missed.

**Rollback:** Replay the pre-change CSV: UPDATE team_alias_map SET team_id_master/match_confidence/review_status back per alias_id. Because the repair is an UPDATE rather than a DELETE, no autocreate can fire in between and no queue row changes state — the rollback is exact.

### 10. REPORT ONLY — three populations this plan deliberately does not fix

**File:** `(GitHub issues; no code)`

**Blocked by:** step 9

Do not let these get quietly absorbed. None of them blocks steps 1-9, and none of them should be attempted inside them.

(a) THE 8 AFFINITY_WA ALIASES AND THEIR 75 GAMES. 'XF B13 RCL 1' -> 'XF 2014 RCL 1' (17 games), 'Eastside FC B09 Red' -> 'Eastside FC 2008 Red' (12), 'Seattle United B09 Copa A' -> '2008 COPA A' (12), 'Whatcom FC Rangers G09 Gold' -> 'WFC Rangers - G08/07 Gold' (11), 'Eastside FC G09 White' -> 'Eastside FC 2008 White' (10), 'XF B17 RCL 1' -> 'XF 2016 RCL 1' (5), 'XF G11 ECNL RL' -> 'XF 2010 ECNL RL' (5), 'Seattle United G09 Copa A' -> 'Seattle United 2008 COPA A' (3). Six of the eight are B09/G09 linked to a 2008 team — the U19 collapse, in a different writer. These cannot be re-pointed the way step 9's can: 75 immutable game rows point at the wrong master, and per CLAUDE.md games are never updated, only quarantined. That is a merge-style remediation with an audit trail — a different design. Step 2 stops the bleeding; this issue cleans it up.

(b) THE DIRECT_ID POPULATION, WHICH IS 12x LARGER AND UNEXAMINED. Applying the same test to the 18,644 direct_id alias pairs whose provider name is recoverable finds 250 conflicts carrying 7,834 games (tgs 176, gotsport 74). Signature examples: 'FSA FC ECNL B09' -> 'FSA FC 2008 ECNL', 'XF ECNL B09' -> 'XF ECNL 2008', 'Santa Clara Sporting 2016G Green' -> 'Santa Clara Sporting 2015 Green'. 196 of the 250 have a same-club, same-gender master whose birth years DO match the provider name, which argues these are misfilings rather than naming drift — but I have not proven that and neither has anyone else. Open it as an investigation, not a fix. Note also that team_alias_map has no provider_team_name column, which is why 1,596 of 2,145 fuzzy_auto aliases cannot be audited at all; adding it (backfilled from the queue where a row exists) is what makes the next scan complete.

(c) THE 88 DUAL-YEAR MERGES THE REVERT TOOL SPARED. revert_fuzzy_auto_merges.keep_birth_year_conflicts excludes 2-digit shorthand via DUAL_YEAR_RE because the OLD extractor drops a year ('09/10B' -> {2010}). That produced 93 live pitchrank-bot merges left un-reverted. The new lossless extractor says 88 of them conflict, and 79 are one shape: '<club> 2008' merged into '<club> B07/06' (AHFC West, SOLAR Red, FC Dallas NPL NTX Gold and Silver, McLean Green, East Meadow, Charlotte Independence South, Charlotte SA White, CFC North, PSA North, Renegades SC Navy, West Coast FC, Empire SC...). The 5 the new guard correctly ALLOWS are the true subset shapes ('Sun Warriors 15/16 Boys' -> 'Sun Warriors 2015'). This is not a cost of the guard — it is 88 merges you have not yet been given the evidence to judge. Once step 3 ships, revert_fuzzy_auto_merges' DUAL_YEAR_RE exemption is obsolete and should be removed in its own PR, which will surface all 88 through the existing revert machinery you already trust.

(d) Two smaller ones worth an issue each: match_details.club_name is the ENTIRE provider team name on 165 pending rows and empty on 6,879 more, which blanks the provider side's distinctions in should_skip_pair on every axis — that is what actually defeated the guard on the Stateline pair, and the scraper defect behind it is untouched. And _lookup_state (find_queue_matches.py:1017-1027) issues an unordered LIMIT 1 and applies the result as a hard .eq('state_code', ...) filter, so the same row can match or find nothing on different runs — which means a forensic replay of any past decision is not reproducible.

**Verify:** N/A — reporting. Re-run step 9's scan a week after step 2 merges and assert the affinity_wa defective count is still 8; if it grew, the gate is not holding.

**Rollback:** N/A.


## Key numbers

- 52 — aliases find_queue_matches has written in its entire life, out of 5,698 queue rows it marked approved and printed 'Merged' for. 5,458 of those 5,698 still carry a pre-existing direct_id alias that ON CONFLICT DO NOTHING preserved.
- 24 / 30 / 68 / 800 — fuzzy_auto aliases written by the IMPORT path (game_matcher) in Aug-2026 gotsport, Jul gotsport, Jun gotsport, Apr sincsports. This is the real ongoing writer, at threshold 0.90 (config/settings.py:194) versus the queue script's 0.95.
- 20 — birth-year-defective fuzzy_auto aliases across all 549 whose provider-side name is recoverable. Split: 12 queue-path (7 find_queue_matches + 5 squadi), 8 affinity_wa.
- 75 — games misfiled through defective aliases. ALL 75 sit on the 8 affinity_wa aliases (17, 12, 12, 11, 10, 5, 5, 3). The 12 queue-path aliases carry ZERO — 10 structurally (squadi and playmetrics_tournament have written no game rows at all) and 2 contingently (gotsport/3738758 and playmetrics/45471, whose providers write 1,260,832 and 2,319 game rows respectively).
- 70 strict / 78 relaxed — should_skip_pair verdicts that flip from allow to BLOCK if the _team_distinction.AGE_PATTERN edit ships, on pairs the birth-year guard would ALLOW. Measured over 428,790 same-club/age/gender/state pairs. These are unrecoverable: should_skip_pair runs BEFORE the year guard at both call sites. This is why that edit is dropped.
- +460 vs -21 — net ground-truth gain of the two proposed extract_age_group regex fixes, measured separately over 7,837 pending rows that already hold an alias. P3 (the 4-digit-year lookaround): +463 gains, 3 regressions. P1 (the [bg]?u-? U-age change): +5 gains, 26 regressions. Ship P3 only.
- 6 of 2,929 (0.20%) — birth_years_conflict SUBSET refusals over human-approved never-reverted merges. EXACT refuses 55 (1.88%). SUBSET is the semantics; do not let anyone re-tighten to EXACT.
- 113 of 7,172 (1.58%) — SUBSET refusals over live pitchrank-bot merges. 88 of those 113 are inside the 93 the revert tool exempted via DUAL_YEAR_RE, and 79 of the 88 are one shape: '<club> 2008' merged into '<club> B07/06'.
- 250 / 7,834 — direct_id alias pairs whose provider name and master name state conflicting birth years, and the games filed through them. 196 of the 250 have a same-club same-gender master whose years DO match the provider name. Unexamined population; not covered by any step here.
- 1,596 of 2,145 — fuzzy_auto aliases that cannot be scanned at all: team_alias_map has no provider_team_name column and only 549 join to a queue row.
- 16,357 — team_name/club_name values across 188,637 non-deprecated teams currently mangled by the line-94 tier strip ('Michigan Jaguars 2013' -> 'michi n jaguars 2013'). 208 values where a plain \b fix differs from the letter-boundary fix, all of them \b regressions on digit-glued tokens (GA10/11, ECNL11G, 13GA).
- 7,837 of 11,202 — pending rows that already hold an alias, on which the queue script's write is a guaranteed no-op. No CHECK constraint exists on team_match_review_queue.status (only confidence_range and the PK), so a new 'already_aliased' value is safe at the DB layer.

## Still uncertain

- Are the 250 conflicting direct_id aliases defects or naming drift? 196 of them have a same-club same-gender master whose birth years match the provider name, which leans defect — but direct_id links come from provider-ID lookup, not name matching, so a disagreeing master name could just be an older or differently-written label for the same roster. 7,834 games hang on the answer. I did not resolve it and step 10(b) exists to. Until it is resolved, treat '20 defective aliases' as covering 549 of ~205,000 aliases, not as a census.
- Are the 79 '<club> 2008 -> <club> B07/06' merges wrong? Every signal says yes (79 clubs, one shape, disjoint year sets under a lossless extractor), but I did not confirm a single one against the clubs' actual rosters. If they are somehow right, the guard has a 1.1% false-refusal rate on the bot population rather than 0.35%. Worth hand-checking three of them before removing DUAL_YEAR_RE from the revert tool.
- What happens to the 26.3% of rows the guard cannot see? 2,951 of 11,202 pending provider names yield an empty year set (2,401 have no age token at all), and 3,868 of the 18,644 direct_id ground-truth pairs are pair-level blind. birth_years_conflict returns False for all of them by construction. Step 7 raises scores over exactly that population (19 of its 86 new merges are U-label-vs-birth-year pairs the guard structurally cannot fire on). The only thing protecting them is FUZZY_AUTO_MERGE_ENABLED='false' — an env flag with no expiry, whose VALUE no test pins. A second guard for the U-age-vs-birth-year case, resolved against the event's own game dates per CLAUDE.md's TGS rule, is the real answer and is not in this plan.
- Who ran the queue matcher on Wednesday 2026-08-19? 58 approvals landed that day and 18 on 2026-08-17, off the Monday cron — most likely auto-merge-queue.yml's workflow_dispatch (dry_run defaults to 'false', limit 2000) or its workflow_call trigger. PR #980 gates both, but before you lift that gate it is worth knowing who was invoking it and why.
- Do the four unrepairable rows in step 9 have a correct target at all? For the three playmetrics_tournament '14 Boys Pre-MLS Academy North/South | Blue' rows only 'Tan' siblings exist, and for 'CSC 14 Girls Navy North' the candidates are 'SC Navy North 2014' and 'CSC 2014 Navy South' — neither is an obvious match. They may need a new canonical team rather than a re-point, which is a decision I am not making for you.
- Does anything downstream filter team_match_review_queue.status besides dashboard.py? I confirmed there is no CHECK constraint and found the two dashboard consumers (:330 selectbox and :419 icon map), but I did not audit the review VIEW referenced in the migration comment at find_queue_matches.py:1403 or any frontend admin route. A new status value that a view filters out would make those rows invisible rather than wrong.
- Is the +0.15 exact-club-match boost a separate bug worth its own fix? 'West Pines United FC ... 2009 Elite' vs '... 2007 Elite' differ by two characters in ~50 and the boost saturates the score to 0.99, which is why raising the 0.95 threshold would not have caught it. The birth-year guard blocks that specific case, but the boost still lets near-identical siblings clear the bar on any axis the guard is blind to. I did not size it and it is not in this plan.