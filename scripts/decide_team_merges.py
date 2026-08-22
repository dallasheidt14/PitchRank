#!/usr/bin/env python3
"""Decide each duplicate-team candidate from game evidence rather than name similarity.

Name similarity cannot separate a duplicate from two real squads: clubs give different teams
nearly identical names, and some pairs are byte-identical. What separates them is behaviour.

Verdicts, in the order they are applied:

  REFUSE  the two records played each other, or both played on the same calendar day.
          A squad cannot be in two places, so this is decisive.
  REFUSE  their birth years disagree once U-labels are resolved through the season the games
          were played in. "U11" names no cohort on its own -- it moves every Aug 1 -- but
          "U11 playing in 2026-27" is the 2016 birth year.
  REVIEW  one name gives a two-year band and the other a single year. Clubs use both
          conventions for both situations, so this needs a person.
  MERGE   both names resolve to the SAME birth-year set, and either the two schedules never
          share a season (a re-registration) or they share opponents (one schedule split
          across two records).
  MERGE   one side has no games and comes from a different provider.
  REVIEW  everything else.

Absence of contradiction is not evidence of duplication, so a merge needs a positive reason.
Measured against independently adjudicated pairs, this setting destroyed no real teams while
merging about a third of true duplicates; every looser setting started destroying teams.

Game counts and dates are read THROUGH team_merge_map. A row that is itself the canonical
target of an earlier merge holds inherited games, and reading raw ids makes it look empty --
which is how a 2008 squad nearly got merged into a 2009 one.

Usage:
    python scripts/decide_team_merges.py --all-cohorts --out decisions.json
    python scripts/decide_team_merges.py --age-group u14 --gender male --out decisions.json
    python scripts/decide_team_merges.py --candidates pairs.json --out decisions.json
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

from src.utils.team_name_utils import _UAGE_TOKEN, birth_years  # noqa: E402
from supabase import create_client  # noqa: E402

# The weekly workflow passes --min-score 0.90, not the script default. Matching it here keeps
# the candidate set identical to what Step 3 would actually propose.
WORKFLOW_MIN_SCORE = 0.90
AGE_GROUPS = ["u10", "u11", "u12", "u13", "u14", "u15", "u16", "u17", "u19"]
GENDERS = ["male", "female"]

# A U-label plus the season it was played in gives a birth year. U19 spans two, because U18
# folds into the U19 board.
_LABEL_DIGITS = re.compile(r"\d{1,2}")
_MIN_LABEL, _MAX_LABEL = 5, 23

# Several registrations from one provider are normal when sequential -- a club re-registers
# each season and the provider issues a new id. Three or more concurrent ones indicate squads
# already fused at the alias layer, and merging into such a row compounds that.
FUSED_REGISTRATION_THRESHOLD = 3

# Two shared opponents in a shared season distinguish one schedule split across two records
# from two squads that merely never clashed. One is too easily a coincidence.
MIN_SHARED_OPPONENTS = 2


def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(url, key)


def season_of(game_date: str) -> int:
    """US youth soccer seasons run Aug 1 - Jul 31; label a season by its starting year."""
    return int(game_date[:4]) if int(game_date[5:7]) >= 8 else int(game_date[:4]) - 1


def label_numbers(name: str | None) -> set[int]:
    """U-age numbers in a name.

    Uses team_name_utils._UAGE_TOKEN rather than a fresh pattern: it already matches the
    gender-affixed forms (GU11, U11G, BU12, U12B) that make up most real labels, and a
    hand-rolled regex that misses them silently reads no cohort at all.
    """
    out = set()
    for match in _UAGE_TOKEN.finditer(name or ""):
        digits = _LABEL_DIGITS.search(match.group(0))
        if digits and _MIN_LABEL <= int(digits.group(0)) <= _MAX_LABEL:
            out.add(int(digits.group(0)))
    return out


def cohort_of(name: str | None, seasons: set[int]) -> tuple[set[int], str]:
    """Birth years a name identifies, reading U-labels through the seasons actually played."""
    stated = set(birth_years(name or ""))
    if stated:
        return stated, "stated"
    numbers = label_numbers(name)
    if not numbers:
        return set(), "unknown"
    if not seasons:
        return set(), "label but no games to date it"
    years = set()
    for n in numbers:
        for season in seasons:
            years.add((season + 1) - n)
            if n == 19:
                years.add((season + 1) - 18)
            if n == 18:
                years.add((season + 1) - 19)
    return years, "from label"


def generate_candidates(sb, age_groups, genders, min_score):
    """Run the duplicate scan and collect its suggestions as data."""
    from find_fuzzy_duplicate_teams import run_fuzzy_duplicates

    os.environ.setdefault("SUPABASE_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
    out = []
    for gender in genders:
        for age in age_groups:
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    suggestions = run_fuzzy_duplicates(
                        age_group=age, gender=gender, state=None,
                        min_score=min_score, dry_run=True, auto_merge=False,
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"  {age} {gender}: scan failed ({str(exc)[:90]}) — cohort skipped", flush=True)
                continue
            print(f"  {age} {gender}: {len(suggestions)} candidates", flush=True)
            for s in suggestions:
                out.append({
                    "age_group": age, "gender": gender, "state": s["state"], "score": s["score"],
                    "merge_id": s["deprecated"]["team_id_master"], "merge_name": s["deprecated"]["team_name"],
                    "keep_id": s["canonical"]["team_id_master"], "keep_name": s["canonical"]["team_name"],
                    "club": s["canonical"].get("club_name"),
                })
    return out


def load_merge_map(sb) -> dict[str, str]:
    mapping, off = {}, 0
    while True:
        res = (sb.table("team_merge_map").select("deprecated_team_id,canonical_team_id")
               .range(off, off + 999).execute())
        rows = res.data or []
        for r in rows:
            mapping[r["deprecated_team_id"]] = r["canonical_team_id"]
        if len(rows) < 1000:
            break
        off += 1000
    return mapping


def gather_evidence(sb, candidates):
    """Games, aliases and original names for every team in the candidate set.

    Games are collected for each team AND for every team already merged into it, so an
    inherited history is visible rather than reading as an empty row.
    """
    merge_map = load_merge_map(sb)

    def canonical(tid):
        seen = set()
        while tid in merge_map and tid not in seen:
            seen.add(tid)
            tid = merge_map[tid]
        return tid

    absorbed = defaultdict(list)
    for dep, can in merge_map.items():
        absorbed[canonical(can)].append(dep)

    ids = sorted({c["merge_id"] for c in candidates} | {c["keep_id"] for c in candidates})
    expanded = {t: [t] + absorbed.get(canonical(t), []) for t in ids}
    every_id = sorted({i for v in expanded.values() for i in v})

    games = defaultdict(list)
    for i in range(0, len(every_id), 50):
        batch = every_id[i : i + 50]
        for side in ("home_team_master_id", "away_team_master_id"):
            off = 0
            while True:
                res = (sb.table("games")
                       .select("game_date,home_team_master_id,away_team_master_id")
                       .in_(side, batch).range(off, off + 999).execute())
                rows = res.data or []
                for g in rows:
                    other = g["away_team_master_id"] if side == "home_team_master_id" else g["home_team_master_id"]
                    games[g[side]].append((g["game_date"], canonical(other) if other else None))
                if len(rows) < 1000:
                    break
                off += 1000

    aliases = defaultdict(Counter)
    for i in range(0, len(ids), 100):
        res = (sb.table("team_alias_map").select("team_id_master,provider_id")
               .in_("team_id_master", ids[i : i + 100]).execute())
        for a in res.data or []:
            if a.get("provider_id"):
                aliases[a["team_id_master"]][a["provider_id"]] += 1

    teams = {}
    for i in range(0, len(ids), 100):
        res = (sb.table("teams")
               .select("team_id_master,team_name,team_name_original,gender,club_name,state_code,is_deprecated")
               .in_("team_id_master", ids[i : i + 100]).execute())
        for t in res.data or []:
            teams[t["team_id_master"]] = t

    return {"expanded": expanded, "canonical": canonical, "games": games, "aliases": aliases, "teams": teams}


_BAND = re.compile(r"(?<!\d)(?:20\d{2}|'?\d{2})\s*[/-]\s*'?\d{2}(?!\d)")

_WORD_BOYS = re.compile(r"(?<![a-z0-9])boys?(?![a-z0-9])", re.I)
_WORD_GIRLS = re.compile(r"(?<![a-z0-9])girls?(?![a-z0-9])", re.I)


def spelled_gender(name: str | None) -> str | None:
    """Gender a name states in words. A bare B/G is too weak to contradict a column."""
    n = name or ""
    boys, girls = bool(_WORD_BOYS.search(n)), bool(_WORD_GIRLS.search(n))
    if boys and not girls:
        return "Male"
    if girls and not boys:
        return "Female"
    return None


def basics_disagree(pair, ev) -> str | None:
    """Why the two rows fail the club/state/gender precondition, or None if they pass.

    The duplicate scan already compares only within one club, state and stored gender, so
    these normally hold. They are re-checked because a candidate list can arrive from
    anywhere, and because the stored gender is not trustworthy on its own: a batch import
    filed a set of girls rows as Male, and a merge across that error destroys a real squad.
    Where a name spells out "Boys" or "Girls", it outranks the column.
    """
    a = ev["teams"].get(pair["merge_id"], {})
    b = ev["teams"].get(pair["keep_id"], {})
    if not a or not b:
        return "a team row is missing"
    if a.get("is_deprecated") or b.get("is_deprecated"):
        return "a team row is already deprecated"

    club_a = (a.get("club_name") or "").strip().lower()
    club_b = (b.get("club_name") or "").strip().lower()
    if club_a != club_b:
        return f"clubs differ ({a.get('club_name')!r} vs {b.get('club_name')!r})"

    state_a = (a.get("state_code") or "").strip().upper()
    state_b = (b.get("state_code") or "").strip().upper()
    if state_a != state_b:
        return f"states differ ({state_a or 'none'} vs {state_b or 'none'})"

    if (a.get("gender") or "") != (b.get("gender") or ""):
        return f"stored genders differ ({a.get('gender')} vs {b.get('gender')})"

    said_a = spelled_gender(a.get("team_name_original") or a.get("team_name"))
    said_b = spelled_gender(b.get("team_name_original") or b.get("team_name"))
    if said_a and said_b and said_a != said_b:
        return f"the names state opposite genders ({said_a} vs {said_b})"
    for side, said, row in ((pair["merge_name"], said_a, a), (pair["keep_name"], said_b, b)):
        if said and row.get("gender") and said != row["gender"]:
            return f"{side!r} states {said} but is stored {row['gender']} — fix the gender first"
    return None


def decide(pair, ev):
    """Verdict plus the evidence behind it."""
    basics = basics_disagree(pair, ev)
    if basics:
        return {**pair, "verdict": "REFUSE", "why": basics,
                "merge_games": 0, "keep_games": 0, "merge_years": [], "keep_years": [],
                "how_merge": "not evaluated", "how_keep": "not evaluated",
                "merge_seasons": [], "keep_seasons": [], "shared_opponents": 0,
                "merge_name_original": "", "keep_name_original": ""}

    a, b = pair["merge_id"], pair["keep_id"]
    ga = [g for i in ev["expanded"].get(a, [a]) for g in ev["games"].get(i, [])]
    gb = [g for i in ev["expanded"].get(b, [b]) for g in ev["games"].get(i, [])]

    dates_a = {d for d, _ in ga}
    dates_b = {d for d, _ in gb}
    seasons_a = {season_of(d) for d in dates_a}
    seasons_b = {season_of(d) for d in dates_b}
    # Shared opponents are evidence of one split schedule only when both records met them in
    # the SAME season. Two squads that each faced the same clubs in different years share
    # opponents without ever sharing a schedule, and counting those clears the merge branch
    # below on nothing.
    both_seasons = seasons_a & seasons_b
    opponents_a = {o for d, o in ga if o and season_of(d) in both_seasons}
    opponents_b = {o for d, o in gb if o and season_of(d) in both_seasons}
    shared_opponents = opponents_a & opponents_b

    canon_a, canon_b = ev["canonical"](a), ev["canonical"](b)
    head_to_head = any(o == canon_b for _, o in ga) or any(o == canon_a for _, o in gb)

    years_a, how_a = cohort_of(pair["merge_name"], seasons_a)
    years_b, how_b = cohort_of(pair["keep_name"], seasons_b)

    team_a, team_b = ev["teams"].get(a, {}), ev["teams"].get(b, {})
    raw_a = team_a.get("team_name_original") or team_a.get("team_name") or ""
    raw_b = team_b.get("team_name_original") or team_b.get("team_name") or ""
    fused = max([*ev["aliases"].get(a, Counter()).values(), 0]) >= FUSED_REGISTRATION_THRESHOLD or \
        max([*ev["aliases"].get(b, Counter()).values(), 0]) >= FUSED_REGISTRATION_THRESHOLD

    if head_to_head:
        verdict, why = "REFUSE", "the two records played each other"
    elif dates_a & dates_b:
        verdict, why = "REFUSE", "both played a game on the same day"
    elif years_a and years_b and not (years_a & years_b):
        verdict, why = "REFUSE", "birth years disagree once labels are resolved"
    elif fused:
        verdict, why = "REVIEW", "a row already carries several concurrent registrations from one provider"
    elif bool(_BAND.search(raw_a)) != bool(_BAND.search(raw_b)):
        verdict, why = "REVIEW", "a two-year band on one side only, visible in the registered name"
    elif years_a and years_b and years_a != years_b:
        verdict, why = "REVIEW", "band vs single year"
    elif years_a and years_a == years_b:
        if not (seasons_a & seasons_b):
            verdict, why = "MERGE", "same birth year, schedules never overlap — a re-registration"
        elif len(shared_opponents) >= MIN_SHARED_OPPONENTS:
            verdict, why = "MERGE", f"same birth year, {len(shared_opponents)} shared opponents"
        else:
            verdict, why = "REVIEW", "same birth year and season, but no shared opponents"
    elif not ga and ev["aliases"].get(a) and ev["aliases"].get(b) and \
            not (set(ev["aliases"][a]) & set(ev["aliases"][b])):
        verdict, why = "MERGE", "empty shell registered with a different provider"
    else:
        verdict, why = "REVIEW", "cohort could not be determined from either name"

    return {
        **pair,
        "verdict": verdict, "why": why,
        "merge_games": len(ga), "keep_games": len(gb),
        "merge_years": sorted(years_a), "keep_years": sorted(years_b),
        "how_merge": how_a, "how_keep": how_b,
        "merge_seasons": sorted(seasons_a), "keep_seasons": sorted(seasons_b),
        "shared_opponents": len(shared_opponents),
        "merge_name_original": raw_a, "keep_name_original": raw_b,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all-cohorts", action="store_true", help="scan every age group and gender")
    ap.add_argument("--age-group", default=None)
    ap.add_argument("--gender", default=None, choices=["male", "female"])
    ap.add_argument("--candidates", default=None,
                    help="JSON array of pairs to judge instead of scanning (merge_id, keep_id, names)")
    ap.add_argument("--min-score", type=float, default=WORKFLOW_MIN_SCORE)
    ap.add_argument("--out", default="merge_decisions.json")
    args = ap.parse_args()

    sb = get_client()

    if args.candidates:
        candidates = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
        print(f"judging {len(candidates)} supplied candidates")
    else:
        ages = AGE_GROUPS if args.all_cohorts or not args.age_group else [args.age_group]
        genders = GENDERS if args.all_cohorts or not args.gender else [args.gender]
        print(f"scanning {len(ages) * len(genders)} cohorts at min-score {args.min_score}")
        candidates = generate_candidates(sb, ages, genders, args.min_score)
        print(f"candidates: {len(candidates)}")

    if not candidates:
        print("nothing to judge")
        return 0

    print("gathering game evidence (resolving merges)...")
    ev = gather_evidence(sb, candidates)
    decisions = [decide(c, ev) for c in candidates]

    counts = Counter(d["verdict"] for d in decisions)
    print("\n" + "=" * 60)
    for verdict in ("MERGE", "REFUSE", "REVIEW"):
        print(f"  {counts[verdict]:>5}  {verdict}")
    print("=" * 60)
    print("\n  by reason:")
    for (v, why), n in Counter((d["verdict"], d["why"]) for d in decisions).most_common():
        print(f"  {n:>5}  {v}: {why}")

    Path(args.out).write_text(json.dumps(decisions, indent=1), encoding="utf-8")
    merges = [d for d in decisions if d["verdict"] == "MERGE"]
    approved = Path(args.out).with_name(Path(args.out).stem + "_approved.json")
    approved.write_text(json.dumps(merges, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out} (all) and {approved} ({len(merges)} to merge)")
    print("Review the approved set before applying it — see the merging-duplicate-teams skill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
