#!/usr/bin/env python3
"""
Dry-run validation for the distinction-column proposal.

Goals:
  1. Resolve a single `distinction` value for every team using the priority rule
     (coach → numeral → color → direction → squad_word → NULL).
  2. Report coverage (non-null %) overall and by cohort.
  3. Verify (club_name, age_group, league, gender, state_code, distinction) is
     a unique team key — surface duplicates to inspect.
  4. Show before/after samples for a quick sanity sniff.

Reads only. Makes no DB writes.
"""

from __future__ import annotations

import collections
import os
import random
import sys
from typing import Optional

import truststore
from dotenv import load_dotenv

from supabase import create_client

truststore.inject_into_ssl()

# Load env
load_dotenv("C:/PitchRank/.env.local")
load_dotenv("C:/PitchRank/.env")

# Importable from the repo
sys.path.insert(0, "C:/PitchRank")
from src.utils.team_name_utils import extract_distinctions, resolve_distinction  # noqa: E402

_CLUB_NOISE = {
    "fc", "sc", "sa", "ac", "cf", "cd", "fcs", "ysa",
    "soccer", "club", "futbol", "football", "youth", "academy",
    "the", "of", "and", "association",
}

# NOTE: `_LEAGUE_TOKENS` is the diagnostic's own token set used by
# classify_distinction_problems to flag league-redundant distinctions.
# League-equivalent tokens that are redundant with the `league` column.
# Deliberately EXCLUDES "ad"/"hd" — those are load-bearing for Modular11
# (MLS NEXT) display and must never be flagged. See the cleanup design spec.
_LEAGUE_TOKENS = {
    "ecnl", "ecnl-rl", "ecrl", "rl", "ga", "npl", "dpl", "dplo",
    "scdsl", "nal", "mlsnext", "mls-next", "next", "ea", "ea2",
    "pre-ecnl", "mls", "nl",
}


def _club_tokens(club_name: Optional[str]) -> set:
    """Lowercase tokens of the club name, minus generic noise.

    Used to strip club-name leakage from distinction emissions
    (e.g. 'Cheshire SA → Cheshire 2009 DPL' should not emit 'cheshire').
    """
    if not club_name:
        return set()
    import re as _re
    toks = _re.split(r"[\s\-_./]+", club_name.lower())
    out = set()
    for t in toks:
        t = t.strip("()[]'*.,")
        if not t or t in _CLUB_NOISE or len(t) < 2:
            continue
        out.add(t)
    return out


def _club_acronym(club_name: Optional[str]) -> str:
    """First-letter acronym of all words in the club name (>=3 words required).

    'California Odyssey Soccer Club' -> 'cosc'. Returns '' when the club has
    fewer than 3 words (acronyms shorter than that are too collision-prone to
    flag).
    """
    if not club_name:
        return ""
    import re as _re
    raw_tokens = [
        t.strip("()[]'*.,")
        for t in _re.split(r"[\s\-_./]+", club_name.lower())
    ]
    words = [t for t in raw_tokens if t]
    if len(words) < 3:
        return ""
    return "".join(t[0] for t in words)


def classify_distinction_problems(distinction: Optional[str], club_name: Optional[str]) -> set:
    """Return the set of problem buckets a resolved distinction falls into.

    Buckets: 'unknown', 'league_token', 'club_acronym', 'multi_token',
    'single_char'. Empty set means the distinction looks clean. Pure function.
    """
    problems = set()
    if not distinction:
        return problems
    tokens = [t for t in distinction.split("|") if t]
    if len(tokens) >= 2:
        problems.add("multi_token")
    acronym = _club_acronym(club_name)
    for t in tokens:
        tl = t.lower()
        if tl == "unknown":
            problems.add("unknown")
        if tl in _LEAGUE_TOKENS:
            problems.add("league_token")
        if len(tl) == 1:
            problems.add("single_char")
        if acronym and tl == acronym:
            problems.add("club_acronym")
    return problems


def main():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not (url and key):
        print("Missing Supabase creds")
        sys.exit(1)

    c = create_client(url, key)

    # Pull all teams (paged) with the fields we need
    teams = []
    page = 0
    while True:
        r = (
            c.table("teams")
            .select("id,team_name,team_name_original,club_name,age_group,gender,state_code,league,is_deprecated")
            .range(page * 1000, page * 1000 + 999)
            .execute()
        )
        if not r.data:
            break
        teams.extend(r.data)
        page += 1
        if page > 200:
            break

    total = len(teams)
    print(f"Scanned {total:,} teams")

    # 1. Resolve distinctions
    resolved = 0
    null_count = 0
    by_source = collections.Counter()
    samples_resolved = []
    samples_null = []
    problem_buckets = collections.Counter()
    problem_samples = collections.defaultdict(list)

    for t in teams:
        name = t.get("team_name") or ""
        club = t.get("club_name") or ""
        d = extract_distinctions(name)
        dist = resolve_distinction(name, club, t.get("state_code"))

        # Track which categories contributed (composite — count all that fired)
        contributed = False
        if d.get("coach_name"):
            by_source["coach"] += 1
            contributed = True
        if d.get("team_number"):
            by_source["number"] += 1
            contributed = True
        if d.get("colors"):
            by_source["color"] += 1
            contributed = True
        if d.get("directions"):
            by_source["direction"] += 1
            contributed = True
        # squad_words: only count if any survives club-token strip
        sw_set = set(d.get("squad_words") or [])
        sw_kept = sw_set - _club_tokens(club)
        if sw_kept:
            by_source["squad_word"] += 1
            contributed = True
        if not contributed:
            by_source["NULL"] += 1

        if dist is not None:
            resolved += 1
            if len(samples_resolved) < 25 and not t.get("is_deprecated"):
                samples_resolved.append((t.get("club_name"), name, dist))
        else:
            null_count += 1
            if len(samples_null) < 25 and not t.get("is_deprecated"):
                samples_null.append((t.get("club_name"), name))

        t["_distinction"] = dist
        for bucket in classify_distinction_problems(dist, club):
            problem_buckets[bucket] += 1
            if len(problem_samples[bucket]) < 10 and not t.get("is_deprecated"):
                problem_samples[bucket].append((club, name, dist))

    # 2. Coverage
    print("\n=== COVERAGE ===")
    print(f"  resolved : {resolved:,}  ({100*resolved/total:.1f}%)")
    print(f"  null     : {null_count:,}  ({100*null_count/total:.1f}%)")
    print("\n=== SOURCE WINNER ===")
    for src, n in by_source.most_common():
        print(f"  {src:12} {n:>7,}  ({100*n/total:.1f}%)")

    # 3. Unique-key check
    print("\n=== UNIQUENESS CHECK ===")
    # Restrict to non-deprecated teams (the live identity surface)
    live = [t for t in teams if not t.get("is_deprecated")]
    print(f"Live teams: {len(live):,}")
    keys = collections.defaultdict(list)
    for t in live:
        if not (t.get("club_name") and t.get("age_group") and t.get("gender")):
            continue
        k = (
            (t["club_name"] or "").strip().lower(),
            t["age_group"],
            t.get("league") or "",
            t["gender"],
            t.get("state_code") or "",
            t.get("_distinction") or "",
        )
        keys[k].append(t)

    dup_keys = {k: v for k, v in keys.items() if len(v) > 1}
    print(f"Unique keys: {len(keys):,}")
    print(f"Collision keys (>=2 teams sharing identity): {len(dup_keys):,}")
    print(f"Collision team count: {sum(len(v) for v in dup_keys.values()):,}")

    # 4. Show sample collisions
    if dup_keys:
        print("\n--- Sample collisions (first 15) ---")
        for k, v in list(dup_keys.items())[:15]:
            club, age, league, gender, st, dist = k
            print(
                f"\nKEY: club={club!r}  age={age}  league={league!r}  "
                f"gender={gender}  state={st}  distinction={dist!r}"
            )
            for t in v[:5]:
                print(f"  - id={t['id'][:8]} team_name={t['team_name']!r}  orig={t.get('team_name_original')!r}")

    # 5. Show resolved samples
    print("\n=== RESOLVED SAMPLES (random 15 of 25) ===")
    random.seed(42)
    for club, name, dist in random.sample(samples_resolved, min(15, len(samples_resolved))):
        print(f"  club={club!r:35.35} name={name!r:55.55} → distinction={dist!r}")

    print("\n=== PROBLEM BUCKETS (resolved distinctions only) ===")
    print(f"  {'bucket':16} {'count':>8}  {'% of resolved':>14}")
    for bucket, n in problem_buckets.most_common():
        pct = (100 * n / resolved) if resolved else 0.0
        print(f"  {bucket:16} {n:>8,}  {pct:>13.1f}%")
    for bucket, _ in problem_buckets.most_common():
        print(f"\n--- sample: {bucket} ---")
        for club, name, dist in problem_samples[bucket][:10]:
            print(f"  club={club!r:30.30} name={name!r:45.45} dist={dist!r}")

    # 6. Show NULL samples — sanity check NULL is right (or whether we're missing distinguishers)
    print("\n=== NULL SAMPLES (random 15 of 25) ===")
    for club, name in random.sample(samples_null, min(15, len(samples_null))):
        print(f"  club={club!r:35.35} name={name!r}")

    # 7. Sanity check: for cohorts that DO collide on the proposed key, are they
    #    actually different teams (different team_name) or genuine dupes the
    #    fuzzy-merge step missed?
    print("\n=== COLLISION ANALYSIS ===")
    same_name = 0
    diff_name = 0
    null_dist_collisions = []
    for k, v in dup_keys.items():
        names = {(t["team_name"] or "").lower() for t in v}
        if len(names) == 1:
            same_name += 1
        else:
            diff_name += 1
        # Bucket 4: cohorts where the distinction is NULL/empty for ALL teams
        # — distinguisher is missing from team_name in every row → likely merge candidates
        dist = k[5]
        if not dist:
            null_dist_collisions.append((k, v))
    print(f"  Collisions where all teams share team_name (likely already-known dupes): {same_name}")
    print(f"  Collisions where team_names differ (priority rule may be lossy): {diff_name}")
    print(f"  Collisions where distinction is NULL for the whole group (Bucket 4): {len(null_dist_collisions)}")

    # Export Bucket 4 list to CSV for review
    import csv
    out_path = "C:/PitchRank/logs/distinction_bucket4_likely_merges.csv"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    total_teams_b4 = 0
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "club_name", "age_group", "league", "gender", "state_code",
            "team_count", "team_id", "team_name", "team_name_original",
        ])
        # Sort: largest groups first
        null_dist_collisions.sort(key=lambda kv: -len(kv[1]))
        for k, teams_in_group in null_dist_collisions:
            club, age, league, gender, st, _ = k
            for t in teams_in_group:
                w.writerow([
                    club, age, league, gender, st,
                    len(teams_in_group), t["id"], t["team_name"],
                    t.get("team_name_original") or "",
                ])
                total_teams_b4 += 1
    print(
        f"  → Bucket 4 CSV written: {out_path}  "
        f"({total_teams_b4:,} teams across {len(null_dist_collisions):,} groups)"
    )

    # Also show top 25 largest Bucket 4 groups inline
    print("\n--- Bucket 4 (top 25 groups by size) ---")
    for k, teams_in_group in null_dist_collisions[:25]:
        club, age, league, gender, st, _ = k
        print(f"\n[{len(teams_in_group)}] club={club!r}  age={age}  league={league!r}  gender={gender}  state={st}")
        for t in teams_in_group[:6]:
            print(f"    id={t['id'][:8]}  team_name={t['team_name']!r}  orig={t.get('team_name_original')!r}")
        if len(teams_in_group) > 6:
            print(f"    … +{len(teams_in_group)-6} more")


if __name__ == "__main__":
    main()
