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
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from find_queue_matches import (
    get_supabase,
    normalize_team_name,
    extract_team_variant,
    has_protected_division,
)
from difflib import SequenceMatcher

# ─────────────────────────────────────────────────────────────────────
# STRUCTURED DISTINCTION EXTRACTION
#
# Each team name is decomposed into features:
#   color, direction, program/league, team_number, location_code,
#   squad_name (mascot), secondary_numbers, age_tokens
#
# Two teams from the same club are duplicates ONLY when every
# extracted distinction matches.  The fuzzy score applies to the
# remaining "base" portion (club abbreviation, word order, etc.).
# ─────────────────────────────────────────────────────────────────────

# ── Colors ──────────────────────────────────────────────────────────
TEAM_COLORS = frozenset({
    "red", "blue", "white", "black", "gold", "grey", "gray", "green",
    "orange", "purple", "yellow", "navy", "maroon", "silver", "pink",
    "sky", "royal", "crimson",
})

# ── Directions (full words + abbreviations → canonical) ─────────────
DIRECTION_CANONICAL = {
    "north": "north", "south": "south", "east": "east", "west": "west",
    "central": "central",
    "n": "north", "s": "south", "e": "east", "w": "west",
    "nw": "northwest", "ne": "northeast", "sw": "southwest", "se": "southeast",
    "nth": "north", "sth": "south",
}

# ── Programs / leagues ──────────────────────────────────────────────
PROGRAM_WORDS = frozenset({
    "academy", "premier", "select", "elite", "ecnl", "ecrl", "npl",
    "ga", "rl", "comp", "recreational", "tal", "stxcl", "dpl", "scdsl",
    "next", "copa", "nal", "reserve", "classic", "division", "fdl",
})

# ── Location / region codes (sub-club branches) ────────────────────
LOCATION_CODES = frozenset({
    # Texas sub-regions
    "ctx", "ntx", "stx", "etx", "wtx",
    # AZ sub-regions
    "phx", "sev", "wv", "ev",
    # CA sub-regions
    "sm", "av", "mv", "le", "hb", "nb", "lb", "oc", "ie", "sfv",
    # General location codes (within-club branches)
    "cp", "wc", "up", "rc", "go", "sl", "tw", "tt",
    "cy",
})

# ── Noise words (never differentiate teams) ─────────────────────────
NOISE_WORDS = frozenset({
    "fc", "sc", "sa", "ac", "cf", "fcs", "ysa",
    "soccer", "club", "futbol", "football", "youth",
    "boys", "girls", "the", "of", "and",
    "b", "g", "m", "f",
})

# US state codes — not differentiating (just the team's state)
US_STATES = frozenset({
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
})

# Age/year patterns
AGE_PATTERN = re.compile(r"\b(20\d{2})\b|'(\d{2})(?:/(\d{2}))?|\b[Uu]-?(\d{1,2})\b")


def _tokenize(name: str) -> list[str]:
    """Split name into lowercase tokens, splitting on spaces, hyphens, underscores, and dots."""
    if not name:
        return []
    # Replace hyphens, underscores, dots, slashes with spaces first so "TFA-OC" → "TFA OC"
    normalized = re.sub(r"[-_./]", " ", name.lower())
    return [w.strip("()[]'*") for w in normalized.split() if w.strip("()[]'*")]


def extract_distinctions(name: str) -> dict:
    """
    Extract every distinguishing feature from a team name.

    Returns dict with:
        colors       : frozenset of color words
        directions   : frozenset of canonical direction words
        programs     : frozenset of program/league words
        team_number  : str or None  (1, 2, i, ii, …)
        location_codes: frozenset of short location/region codes
        squad_words  : frozenset of remaining differentiating words (mascots, etc.)
        age_tokens   : tuple of raw age/year strings found
        secondary_nums: tuple of numbers appearing AFTER the first age token
    """
    empty = {
        "colors": frozenset(), "directions": frozenset(), "programs": frozenset(),
        "team_number": None, "location_codes": frozenset(), "state_codes": frozenset(),
        "squad_words": frozenset(), "age_tokens": (), "secondary_nums": (),
    }
    if not name:
        return empty

    tokens = _tokenize(name)

    colors = set()
    directions = set()
    programs = set()
    location_codes = set()
    state_codes = set()
    team_number = None
    classified = set()  # indices of tokens already assigned a role

    # ── Pass 1: classify known token types ──
    for idx, tok in enumerate(tokens):
        if tok in TEAM_COLORS:
            colors.add(tok)
            classified.add(idx)
        elif tok in DIRECTION_CANONICAL:
            directions.add(DIRECTION_CANONICAL[tok])
            classified.add(idx)
        elif tok in PROGRAM_WORDS:
            programs.add(tok)
            classified.add(idx)
        elif tok in LOCATION_CODES:
            location_codes.add(tok)
            classified.add(idx)
        elif tok in NOISE_WORDS:
            classified.add(idx)
        elif tok in US_STATES:
            state_codes.add(tok)
            classified.add(idx)
        elif re.fullmatch(r"(i{1,3}|iv|v|vi{0,3})", tok):
            team_number = tok
            classified.add(idx)
        elif re.fullmatch(r"[1-9]|10", tok):
            team_number = tok
            classified.add(idx)

    # ── Pass 2: extract age tokens and secondary numbers ──
    age_tokens = []
    for m in AGE_PATTERN.finditer(name):
        age_tokens.append(m.group(0).lower().strip("'"))

    secondary_nums = []
    first_age = AGE_PATTERN.search(name)
    if first_age:
        after = name[first_age.end():]
        secondary_nums = re.findall(r"\d+", after)

    # ── Pass 3: classify age-token indices ──
    for idx, tok in enumerate(tokens):
        if idx in classified:
            continue
        # Age+gender combo (15m, 16m, b06, b08, b2010, u16b) — extract age part
        age_gender_match = re.fullmatch(
            r"(\d{1,4})u?[bgmf]|[bgmf](\d{1,4})u?|u(\d{1,2})[bgmf]", tok
        )
        if age_gender_match:
            age_num = (
                age_gender_match.group(1)
                or age_gender_match.group(2)
                or age_gender_match.group(3)
            )
            if age_num:
                age_tokens.append(age_num)
            classified.add(idx)
        elif re.fullmatch(r"20\d{2}", tok) or re.fullmatch(r"\d{2}/\d{2}", tok):
            classified.add(idx)
        elif re.fullmatch(r"u-?\d{1,2}", tok):
            classified.add(idx)
        elif re.fullmatch(r"\d+m?", tok):
            classified.add(idx)

    # ── Pass 4: remaining unclassified tokens → squad words or location codes ──
    squad_words = set()
    for idx, tok in enumerate(tokens):
        if idx in classified:
            continue
        if not tok:
            continue
        # Age+gender combos already handled in Pass 3
        # Alphanumeric tokens like KHP1, KHA1 — treat as differentiators
        if not tok.isalpha() and not tok.isdigit() and len(tok) >= 2:
            squad_words.add(tok)
            continue
        if not tok.isalpha():
            continue
        if len(tok) == 1:
            # Single letter differentiator (B vs Y in "Force B" vs "Force Y")
            squad_words.add(tok)
        elif 2 <= len(tok) <= 3:
            location_codes.add(tok)
        elif len(tok) >= 4:
            squad_words.add(tok)

    # ── Normalize program equivalences ──
    # "RL" alone = "ECNL RL" (Regional League = ECNL Regional League)
    if "rl" in programs:
        programs.add("ecnl")  # RL always implies ECNL RL

    return {
        "colors": frozenset(colors),
        "directions": frozenset(directions),
        "programs": frozenset(programs),
        "team_number": team_number,
        "location_codes": frozenset(location_codes),
        "state_codes": frozenset(state_codes),
        "squad_words": frozenset(squad_words),
        "age_tokens": tuple(sorted(age_tokens)),
        "secondary_nums": tuple(secondary_nums),
    }


def _should_skip_pair(name_a: str, name_b: str) -> bool:
    """
    Compare extracted distinctions. Skip (return True) if ANY feature
    differs — these are different teams within the same club.
    """
    da = extract_distinctions(name_a)
    db = extract_distinctions(name_b)

    # Colors must match (Red vs Blue = different team)
    if da["colors"] != db["colors"]:
        return True

    # Directions must match (North vs South, SW vs W = different)
    if da["directions"] != db["directions"]:
        return True

    # Programs/leagues must match (Academy vs Premier, ECNL vs ECRL, NPL vs none)
    if da["programs"] != db["programs"]:
        return True

    # Team numbers must match (1 vs 2, I vs II)
    if da["team_number"] != db["team_number"]:
        return True

    # Location codes must match (SM vs AV, HB vs NB, CP vs WC)
    if da["location_codes"] != db["location_codes"]:
        return True

    # Squad/mascot words must match (Brave vs none, Bolts vs Clash, Gazelle vs Samba)
    if da["squad_words"] != db["squad_words"]:
        return True

    # Age tokens must be compatible ('10/11 vs '10 = different)
    if da["age_tokens"] != db["age_tokens"]:
        return True

    # Secondary numbers must match (Union 2010 FC 2009 vs 2008)
    if da["secondary_nums"] != db["secondary_nums"]:
        return True

    # State codes: if BOTH names contain state codes but they differ → different branches
    # (e.g. Union KC "KS" vs "MO", Nebo United "DC" vs "NC")
    # If only one name has a state code, it's just metadata noise — don't skip
    if da["state_codes"] and db["state_codes"] and da["state_codes"] != db["state_codes"]:
        return True

    return False


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
    var_a = extract_team_variant(name_a)
    var_b = extract_team_variant(name_b)
    if var_a != var_b:
        return None

    score = SequenceMatcher(None, norm_a, norm_b).ratio()

    club_a = (team_a.get("club_name") or "").strip().lower()
    club_b = (team_b.get("club_name") or "").strip().lower()
    if club_a and club_b and club_a == club_b:
        score = min(1.0, score + 0.15)

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
        name = (t.get("team_name") or "")
        club = (t.get("club_name") or "")
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


def fetch_teams(supabase, age_group: str, gender: str, state: str | None = None):
    """Fetch non-deprecated teams for cohort (paginated). age_group: u16/U16, gender: male/female/Male/Female."""
    age = age_group.strip().upper()
    if not age.startswith("U"):
        age = f"U{age}"
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
            .or_(f"age_group.eq.{age},age_group.eq.{age.lower()},age_group.eq.{age.upper()}")
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
                score = score_team_pair(ta, tb)
                if score is None or score < min_score:
                    continue
                # Only suggest merge if same club (avoid merging "2010 White" from different clubs)
                club_a = (ta.get("club_name") or "").strip().lower()
                club_b = (tb.get("club_name") or "").strip().lower()
                if club_a != club_b:
                    continue
                # Red 1 vs Red 2, Academy vs Premier, or one generic name without age — skip
                if _should_skip_pair(ta["team_name"], tb["team_name"]):
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


if __name__ == "__main__":
    main()
