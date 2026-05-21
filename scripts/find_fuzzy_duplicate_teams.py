#!/usr/bin/env python3
"""
Find duplicate teams using the SAME fuzzy logic as auto-merge queue:
normalized name similarity (SequenceMatcher), variant match, club boost, league boost.

Example: finds "2010 EA2" (Chula Vista FC) and "Chula Vista FC 2010 ea2" (chula vista fc)
as the same team and suggests a merge.

Usage:
    python scripts/find_fuzzy_duplicate_teams.py --age-group u16 --gender male
    python scripts/find_fuzzy_duplicate_teams.py --age-group u16 --gender male --state OR --min-score 0.95
    python scripts/find_fuzzy_duplicate_teams.py --age-group u16 --gender male --auto-merge
"""

import argparse
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

# Two-level path idiom: parent lets us import sibling scripts (find_queue_matches),
# grandparent lets us import src.utils.team_name_utils (_canonicalize_age_token).
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _team_distinction import (  # noqa: E402
    NOISE_WORDS,
    extract_distinctions,
)
from _team_distinction import (
    should_skip_pair as _should_skip_pair,
)
from find_queue_matches import (  # noqa: E402
    extract_team_variant,
    get_supabase,
    has_protected_division,
    normalize_team_name,
)

from src.utils.team_name_utils import _canonicalize_age_token  # noqa: E402

# Structured-distinction logic moved to scripts/_team_distinction.py.



def score_team_pair(team_a: dict, team_b: dict) -> float | None:
    """
    Score how similar two teams are using queue auto-merge logic.
    Returns 0.0-1.0 or None if variant mismatch / protected division.
    """
    name_a = (team_a.get("team_name") or "").strip()
    name_b = (team_b.get("team_name") or "").strip()
    if not name_a or not name_b:
        return None
    if has_protected_division(name_a) or has_protected_division(name_b):
        return None

    norm_a = normalize_team_name(name_a)
    norm_b = normalize_team_name(name_b)
    club_a = (team_a.get("club_name") or "").strip().lower()
    club_b = (team_b.get("club_name") or "").strip().lower()
    # Pass club name so club words (e.g. 'Union' in 'Rush Union Wisconsin')
    # aren't returned as a phantom variant when the duplicate omits the club.
    var_a = extract_team_variant(name_a, club_a)
    var_b = extract_team_variant(name_b, club_b)
    if var_a != var_b:
        return None

    score = SequenceMatcher(None, norm_a, norm_b).ratio()

    if club_a and club_b and club_a == club_b:
        score = min(1.0, score + 0.15)
        # When clubs match, also score with club words stripped —
        # handles "FC PRE-ECNL 2014 Mee" vs "Fever United 2014 Mee"
        # where the club name appears differently in each team name
        club_words = set(club_a.split()) | NOISE_WORDS
        stripped_a = " ".join(w for w in norm_a.split() if w not in club_words)
        stripped_b = " ".join(w for w in norm_b.split() if w not in club_words)
        if stripped_a and stripped_b:
            stripped_score = SequenceMatcher(None, stripped_a, stripped_b).ratio()
            # Use the better of the two scores (with club boost already applied)
            score = max(score, min(1.0, stripped_score + 0.15))

    name_a_lower = name_a.lower()
    name_b_lower = name_b.lower()
    has_rl_a = " rl" in name_a_lower or "-rl" in name_a_lower or "ecnl rl" in name_a_lower or "ecnl-rl" in name_a_lower
    has_rl_b = " rl" in name_b_lower or "-rl" in name_b_lower or "ecnl rl" in name_b_lower or "ecnl-rl" in name_b_lower
    has_ecnl_a = "ecnl" in name_a_lower and not has_rl_a
    has_ecnl_b = "ecnl" in name_b_lower and not has_rl_b
    if has_rl_a and has_rl_b:
        score = min(1.0, score + 0.05)
    elif has_ecnl_a and has_ecnl_b and not has_rl_a:
        score = min(1.0, score + 0.05)
    elif has_rl_a != has_rl_b:
        score = max(0.0, score - 0.08)

    return score


def pick_canonical_pair(team_a: dict, team_b: dict) -> tuple[dict, dict]:
    """Pick which team to keep (canonical) vs merge into it (deprecated). Same logic as run_all_merges."""

    def score_team(t):
        name = t.get("team_name") or ""
        club = t.get("club_name") or ""
        s = 0
        if club and club.lower() in name.lower():
            s += 100
        if name != name.upper():
            s += 10
        s += len(name) / 100
        return s

    a_scr = score_team({"team_name": team_a["team_name"], "club_name": team_a.get("club_name")})
    b_scr = score_team({"team_name": team_b["team_name"], "club_name": team_b.get("club_name")})
    if a_scr >= b_scr:
        return team_a, team_b
    return team_b, team_a


def _normalize_cohort_age_group(age_group: str) -> str:
    """Map legacy U18 requests into the merged U19 cohort."""
    age_num = re.sub(r"[^0-9]", "", age_group or "")
    if not age_num:
        raise ValueError("age_group must contain digits")
    if age_num in {"18", "19"}:
        return "U19"
    return f"U{int(age_num)}"


def _build_age_group_or_filter(age_group: str) -> str:
    """Build a Supabase OR filter for a cohort age query."""
    normalized_age = _normalize_cohort_age_group(age_group)
    if normalized_age == "U19":
        values = ("U18", "u18", "U19", "u19")
    else:
        values = (normalized_age, normalized_age.lower())
    return ",".join(f"age_group.eq.{value}" for value in values)


def _normalize_stored_age_group(age_group: str | None) -> str | None:
    """Normalize a stored team age_group without merging cohorts."""
    if not age_group:
        return None
    digits = re.sub(r"[^0-9]", "", age_group)
    if not digits:
        return None
    return f"u{int(digits)}"


def fetch_teams(supabase, age_group: str, gender: str, state: str | None = None):
    """Fetch non-deprecated teams for cohort (paginated). age_group: u16/U16, gender: male/female/Male/Female."""
    age = _normalize_cohort_age_group(age_group)
    g = gender.strip().capitalize()
    if g not in ("Male", "Female"):
        raise ValueError("gender must be male or female")

    all_data = []
    page_size = 1000
    offset = 0
    while True:
        q = (
            supabase.table("teams")
            .select("team_id_master, team_name, club_name, state_code, age_group, gender")
            .eq("is_deprecated", False)
            .ilike("gender", g)
            .or_(_build_age_group_or_filter(age))
        )
        if state:
            q = q.eq("state_code", state.upper())
        result = q.range(offset, offset + page_size - 1).execute()
        data = result.data or []
        if not data:
            break
        all_data.extend(data)
        if len(data) < page_size:
            break
        offset += page_size
    return all_data


def run_fuzzy_duplicates(
    age_group: str,
    gender: str,
    state: str | None = None,
    min_score: float = 0.95,
    dry_run: bool = True,
    auto_merge: bool = False,
):
    age_group = _normalize_cohort_age_group(age_group).lower()
    supabase = get_supabase()
    teams = fetch_teams(supabase, age_group, gender, state)
    if not teams:
        print("No teams found for this cohort.")
        return []

    # Group by state so we only compare within state (same club names / area)
    by_state = defaultdict(list)
    for t in teams:
        st = (t.get("state_code") or "").strip() or "_no_state"
        by_state[st].append(t)

    suggestions = []  # list of (canonical, deprecated, score)
    seen_pairs = set()  # (id1, id2) with id1 < id2 to avoid duplicates

    for st, state_teams in by_state.items():
        n = len(state_teams)
        for i in range(n):
            for j in range(i + 1, n):
                ta, tb = state_teams[i], state_teams[j]
                # U19 is the umbrella filter, but never merge stored U18 teams
                # with stored U19 teams.
                if _normalize_stored_age_group(ta.get("age_group")) != _normalize_stored_age_group(tb.get("age_group")):
                    continue
                score = score_team_pair(ta, tb)
                if score is None or score < min_score:
                    continue
                # Only suggest merge if same club (avoid merging "2010 White" from different clubs)
                club_a = (ta.get("club_name") or "").strip().lower()
                club_b = (tb.get("club_name") or "").strip().lower()
                if club_a != club_b:
                    continue
                # Red 1 vs Red 2, Academy vs Premier, or one generic name without age — skip
                if _should_skip_pair(ta["team_name"], tb["team_name"], club_name=club_a):
                    continue
                id_a, id_b = ta["team_id_master"], tb["team_id_master"]
                key = (min(id_a, id_b), max(id_a, id_b))
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                canonical, deprecated = pick_canonical_pair(ta, tb)
                suggestions.append(
                    {
                        "canonical": canonical,
                        "deprecated": deprecated,
                        "score": score,
                        "state": st,
                    }
                )

    # Report
    print("=" * 70)
    print("FUZZY DUPLICATE TEAMS (queue-style matching)")
    print("=" * 70)
    print(f"Cohort: {age_group} {gender}" + (f" state={state}" if state else " (all states)"))
    print(f"Teams scanned: {len(teams)}")
    print(f"Suggested merges (score >= {min_score:.0%}): {len(suggestions)}")
    print()

    if suggestions:
        for i, s in enumerate(suggestions[:50], 1):
            c = s["canonical"]
            d = s["deprecated"]
            print(f"  {i}. [{s['score']:.1%}] [{s['state']}]")
            print(f"     KEEP:  {c['team_name']}  club: {c.get('club_name') or ''}")
            print(f"     MERGE: {d['team_name']}  club: {d.get('club_name') or ''}")
            print()
        if len(suggestions) > 50:
            print(f"  ... and {len(suggestions) - 50} more")
        print()

    if auto_merge and suggestions and not dry_run:
        from run_all_merges import execute_merge

        print(f"Auto-merging {len(suggestions)} pairs...")
        merged, failed = 0, 0
        for s in suggestions:
            result = execute_merge(
                s["deprecated"]["team_id_master"],
                s["canonical"]["team_id_master"],
            )
            if result.get("success"):
                merged += 1
                print(f"  ✓ {s['deprecated']['team_name'][:40]} → {s['canonical']['team_name'][:30]}")
            else:
                failed += 1
                print(f"  ✗ {s['deprecated']['team_name'][:40]} - {result.get('error', '')[:50]}")
        print(f"Done: {merged} merged, {failed} failed.")
    elif suggestions and dry_run:
        print("DRY RUN: No merges executed. Use --auto-merge to apply (and omit --dry-run).")

    return suggestions


def main():
    parser = argparse.ArgumentParser(
        description="Find duplicate teams using queue auto-merge fuzzy logic (e.g. Chula Vista FC 2010 ea2 vs 2010 EA2)"
    )
    parser.add_argument("--age-group", required=True, help="e.g. u16, U16")
    parser.add_argument("--gender", required=True, choices=["male", "female", "Male", "Female"])
    parser.add_argument("--state", default=None, help="Optional state code (e.g. OR, CA)")
    parser.add_argument("--min-score", type=float, default=0.95, help="Min similarity to suggest merge (default 0.95)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Only report (default)")
    parser.add_argument("--no-dry-run", action="store_false", dest="dry_run")
    parser.add_argument("--auto-merge", action="store_true", help="Execute merges for all suggestions")
    args = parser.parse_args()

    dry_run = args.dry_run and not args.auto_merge

    run_fuzzy_duplicates(
        age_group=args.age_group,
        gender=args.gender,
        state=args.state,
        min_score=args.min_score,
        dry_run=dry_run,
        auto_merge=args.auto_merge,
    )


def _run_inline_tests() -> int:
    """Sanity-check the canonicalization path end-to-end. Returns non-zero on failure."""
    from src.utils.team_name_utils import _canonicalize_age_token as utils_canon

    passed = failed = 0

    def check(desc: str, cond: bool) -> None:
        nonlocal passed, failed
        status = "✅" if cond else "❌"
        print(f"  {status} {desc}")
        if cond:
            passed += 1
        else:
            failed += 1

    # Cross-file equivalence (should be trivial identity since we now import the helper)
    for tok in ["14U", "U14", "2012", "10/11", "14ub"]:
        check(
            f"cross-file canonical equivalence for {tok!r}",
            _canonicalize_age_token(tok) == utils_canon(tok),
        )

    # Pass-4 leak regression — 14U must be classified, not dumped into squad_words
    d = extract_distinctions("EBU 14U Premier 1", "EBU")
    check("14u not in squad_words for 'EBU 14U Premier 1'", "14u" not in d["squad_words"])

    # Canonicalization regression — birth year and digit-U form yield same cohort
    d_a = extract_distinctions("EBU 2012 Premier 1", "EBU")
    d_b = extract_distinctions("EBU 14U Premier 1", "EBU")
    check(
        "age_tokens match for EBU 2012 vs EBU 14U",
        d_a["age_tokens"] == d_b["age_tokens"] == ("u14",),
    )

    # secondary_nums masking regression — "2012" AFTER "14U" must not leak as secondary
    d = extract_distinctions("14U 2012 Rush Union WI Select", "Rush Union WI")
    check(
        "secondary_nums masks age matches for '14U 2012 Rush Union WI Select'",
        d["secondary_nums"] == (),
    )

    # Full-pair match — the two failure pairs from the 2026-04-22 incident
    check(
        "EBU 14U Premier 1 ↔ EBU 2012 Premier 1 merges",
        _should_skip_pair("EBU 14U Premier 1", "EBU 2012 Premier 1", club_name="EBU") is False,
    )
    check(
        "14U 2012 Rush Union WI Select ↔ Rush Union WI 2012 Select merges",
        _should_skip_pair(
            "14U 2012 Rush Union WI Select",
            "Rush Union WI 2012 Select",
            club_name="Rush Union WI",
        )
        is False,
    )

    # Pass-3 preserves birth-year semantic for fused gender-suffix tokens —
    # 'b2012' must canonicalize to u14, not be wrapped to 'u2012' and dropped.
    d = extract_distinctions("Phoenix B2012 Red", "Phoenix")
    check(
        "Pass-3 'B2012' yields age_tokens ('u14',)",
        d["age_tokens"] == ("u14",),
    )
    d = extract_distinctions("Phoenix 14B Red", "Phoenix")
    check(
        "Pass-3 '14B' (birth year 2014) yields age_tokens ('u12',)",
        d["age_tokens"] == ("u12",),
    )

    # Regression guardrails
    check(
        "same-club different-color still skipped",
        _should_skip_pair("Phoenix FC 2012 Red", "Phoenix FC 2012 Blue", club_name="Phoenix FC") is True,
    )
    check(
        "cross-cohort still skipped",
        _should_skip_pair("Phoenix 2012 Red", "Phoenix 2013 Red", club_name="Phoenix") is True,
    )
    check(
        "U18 ↔ 2007 birth year merges (both canonicalize to u19)",
        _should_skip_pair("Phoenix U18 Red", "Phoenix 2007 Red", club_name="Phoenix") is False,
    )
    check(
        "slash-form '10/11 (u15) stays distinct from '10 (u16)",
        _should_skip_pair("Phoenix '10/11 Red", "Phoenix '10 Red", club_name="Phoenix") is True,
    )

    # Variant-gate regression — club words like 'Union' must not leak as a
    # phantom variant when the duplicate side omits the club prefix.
    rush_a = {"team_id_master": "A", "team_name": "2012 Premier", "club_name": "Rush Union Wisconsin"}
    rush_b = {
        "team_id_master": "B",
        "team_name": "Rush Union Wisconsin 2012 Premier",
        "club_name": "Rush Union Wisconsin",
    }
    rush_score = score_team_pair(rush_a, rush_b)
    check(
        "Rush Union 2012 Premier (no-club ↔ with-club) scores instead of None",
        rush_score is not None and rush_score >= 0.90,
    )

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(_run_inline_tests())
    main()
