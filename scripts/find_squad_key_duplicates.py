#!/usr/bin/env python3
"""Propose merges for one squad whose rows spell the same squad in different words.

Doorway D of .claude/skills/merging-duplicate-teams. A club's squad reaches the database once
per provider, and once per event registration within a provider, and every copy writes the
cohort and the club its own way: `ESC- 2015 Purple` and `EDGE Purple 15B`, `U12B Grey` and
`Skyline 15B Grey`, `Arsenal Colorado 14/15B Gold` and `Arsenal Colorado Pre-ECNL B2014/15
Gold`. The skill's other doorways cannot pair these spellings.

Each name is read once, in passes by kind: a leading birth year, then game formats (`11v11`,
dropped), U-ages and U-age ranges, two-year bands and single birth years, each recording the
ages it states. The squad key is the words left over, after folding spelling variants, less the
club's words and initials, the row's own state code, club-type, gender and filler words
(NOISE_WORDS) and league words. Nothing the reader did not take as a cohort leaves the key, so
`Rush 14 Blue` keeps its 14: a number mid-name is a squad number until an affix, an apostrophe,
a Boys/Girls beside it or a leading position makes it a year. A `pre` stays in the key unless
it introduces ECNL or MLS, so `Pre-NPL Gold` never shares a key with `NPL Gold`. Two rows pair
when:
  - they share club (compared with punctuation and case stripped), age_group, gender and
    state_code, a NULL club borrowing the cohort's longest club the team name starts with
  - their squad keys are equal and not empty
  - the cohorts their names state can be one cohort: a band names one age, a U-age one age
    or a range of two, a bare birth year either of two, two bare years must be the same year,
    and a name whose
    own age tokens contradict each other pairs with nothing
  - their names do not state different leagues, Pre-ECNL moving up to ECNL excepted
  - neither name carries an AD, HD or EA division marker, or any MLS mention (MLS NEXT,
    MLS Academy, Pre-MLS)
A live row that already resolves to another through team_merge_map is left out: it is merged
in effect, and pairing it would propose merges into a row that is going away.

Screens, each decisive: opposite genders in the registered names, a head-to-head game, a
shared game date, a self-play row. A row pairing cleanly with more than one other row is held
rather than guessed at, and so is a pair neither of whose names fits the stored age group.
The survivor is the row whose name states a band or a current U-age,
then a bare birth year, then no age, and last a label stale for the stored cohort; ties go to
more games, then the latest game.

Every provider but modular11 is scanned, the per-event ones included, because a squad
re-registered for each event is the shape it exists to find.

Blind spots it ships with. A squad named only by its league on one provider (`BU12 Pre MLS
Next`) and by a squad word on the other (`BU12 Academy`) has no shared key. A club that
rebranded, or that files a branch as the club on one provider and inside the team name on the
other, never shares a group. And stripping club initials also strips a branch code that
happens to be one (`CR` for a Castle Rock branch of Colorado Rapids).

Read-only: writes a CSV of every pair it considered and a JSON of the proposals, and never
touches the database. The proposals are candidates, not a safe list: the skill's refusal
review, adversarial review and apply steps still apply, and the vetted JSON goes straight to
scripts/apply_vetted_team_merges.py.

Usage:
    python scripts/find_squad_key_duplicates.py --state CO --out-dir data/exports
    python scripts/find_squad_key_duplicates.py --state CO --age-group u12
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import (  # noqa: E402
    build_evidence,
    fetch_games,
    fetch_teams,
    get_client,
    load_merge_map,
    merged_into,
    normalize,
    registered_name,
    resolver,
    stated_gender,
)
from scripts.find_queue_matches import has_protected_division  # noqa: E402
from scripts.fix_band_cohorts import csv_safe  # noqa: E402
from src.utils.team_name_utils import _FORMAT_TOKEN, _UAGE_TOKEN, NOISE_WORDS  # noqa: E402
from src.utils.team_utils import CURRENT_YEAR  # noqa: E402

OUT_OF_SCOPE_PROVIDERS = frozenset({"modular11"})

LEAGUE_WORDS = frozenset(
    {"ecnl", "ecrl", "rl", "mls", "next", "npl", "dpl", "dplo", "ga", "preecnl", "premls"}
)
# `pre` names a league only in front of these; in front of anything else it marks a tier
# (Pre-NPL, Pre-Academy) and stays in the key.
PRE_LEAGUES = frozenset({"ecnl", "mls"})

# Checked in order, so an RL or Pre-ECNL name is never read as plain ECNL.
LEAGUE_PATTERNS = (
    ("ecnl rl", re.compile(r"\becnl[\s-]*rl\b|\becrl\b|\brl\b")),
    ("pre-ecnl", re.compile(r"\bpre[\s-]*ecnl\b")),
    ("ecnl", re.compile(r"\becnl\b")),
    ("mls next", re.compile(r"\bmls[\s-]*next\b")),
    ("npl", re.compile(r"\bnpl\b")),
    ("dpl", re.compile(r"\bdplo?\b")),
    ("ga", re.compile(r"\bga\b")),
)
# A Pre-ECNL squad becomes the club's ECNL squad when its cohort reaches the ECNL ages, and
# the older registration keeps the old word.
COMPATIBLE_LEAGUES = frozenset({frozenset({"pre-ecnl", "ecnl"})})
# Any MLS mention, not only "MLS NEXT": `MLS Academy` and `Pre-MLS` name the same programme.
_MLS = re.compile(r"(?<![a-z])(?:pre[\s-]*)?mls", re.I)

# Spelling variants seen in provider registrations, folded before keys are compared.
SPELLING = {"untied": "united", "grey": "gray"}

U_AGE_BOUNDS = range(5, 24)
BIRTH_YEAR_BOUNDS = range(2005, 2021)

_EDGE = r"(?<![a-z0-9])"
_END = r"(?![a-z0-9])"
_YY = r"((?:19|20)?\d\d)"
_BAND_SPAN = re.compile(rf"{_EDGE}[bg]?'?{_YY}[bg]?\s*[/-]\s*[bg]?'?{_YY}[bg]?{_END}")
_YEAR_SPAN = re.compile(
    rf"{_EDGE}(?:[bg]?((?:19|20)\d\d)[bg]?|[bg](\d\d)|(\d\d)[bg]|'(\d\d)){_END}"
    rf"|{_EDGE}(\d\d)(?=\s+(?:boys|girls)\b)|(?:(?<=\bboys )|(?<=\bgirls ))(\d\d){_END}"
)
_LEADING_YEAR = re.compile(r"^\s*(\d\d)(?=[\s(])")
# A U-age range `_UAGE_TOKEN` splits in two: `U17/U18`, `18U-19U`, and `13/14U`, whose first
# half it does not read at all.
_U_AGE = r"[bg]?(?:u-?(\d{1,2})|(\d{1,2})u)[bg]?"
_U_RANGE = re.compile(rf"{_EDGE}(?:{_U_AGE}\s*[/-]\s*{_U_AGE}|(\d{{1,2}})\s*/\s*(\d{{1,2}})u[bg]?){_END}")
_WORD_SPLIT = re.compile(r"[^a-z0-9]+")
_DIGITS = re.compile(r"\d{1,2}")

PROPOSED, HELD, REJECTED = "proposed", "held", "rejected"

RECORD_FIELDS = (
    "status", "reason", "club", "age_group", "gender", "state", "squad_key",
    "name_a", "name_b", "name_original_a", "name_original_b", "provider_a", "provider_b",
    "games_a", "games_b", "merge_id", "keep_id", "merge_name", "keep_name",
)
PROVIDER_TEXT_FIELDS = frozenset(
    {"club", "name_a", "name_b", "name_original_a", "name_original_b", "merge_name", "keep_name", "squad_key"}
)


def four_digit(year: str) -> int:
    return int(year) if len(year) == 4 else 2000 + int(year)


def age_of(younger_year: int) -> int:
    return CURRENT_YEAR - younger_year + 1


@dataclass
class Reading:
    """What one read of a team name found: the ages each cohort token allows, the bare birth
    years among them, whether a band or U-age was read (`exact`), and the words left once cohort
    tokens and game formats are removed."""

    allowed: list = field(default_factory=list)
    bare: set = field(default_factory=set)
    exact: bool = False
    words: list = field(default_factory=list)

    @property
    def ages(self) -> set[int] | None:
        """None when the name states no cohort; empty when its own tokens contradict."""
        return set.intersection(*self.allowed) if self.allowed else None


def read_name(team_name: str | None) -> Reading:
    reading = Reading()
    text = (team_name or "").lower().replace("–", "-").replace("—", "-")

    def u_age(m):
        ages = {int(d) for d in _DIGITS.findall(m.group(0))} & set(U_AGE_BOUNDS)
        if not ages:
            return m.group(0)
        reading.allowed.append(ages)
        reading.exact = True
        return " "

    def band(m):
        years = {four_digit(g) for g in m.groups()}
        if len(years) != 2 or max(years) - min(years) != 1 or age_of(max(years)) not in U_AGE_BOUNDS:
            return m.group(0)
        reading.allowed.append({age_of(max(years))})
        reading.exact = True
        return " "

    def year(m):
        stated = four_digit(next(g for g in m.groups() if g))
        if stated not in BIRTH_YEAR_BOUNDS:
            return m.group(0)
        reading.allowed.append({age_of(stated), age_of(stated) - 1})
        reading.bare.add(stated)
        return " "

    # Leading position is judged on the name as written, before any token is removed.
    text = _FORMAT_TOKEN.sub(" ", _LEADING_YEAR.sub(year, text))
    text = _UAGE_TOKEN.sub(u_age, _U_RANGE.sub(u_age, text))
    text = _YEAR_SPAN.sub(year, _BAND_SPAN.sub(band, text))
    reading.words = [w for w in _WORD_SPLIT.split(text) if w]
    return reading


def is_club_initials(token: str, club_words: list[str]) -> bool:
    """Two to five letters matching, in order, the first letters of the club's words followed
    by "soccer club", which club_name often leaves off: `ESC` for club `Colorado Edge`."""
    if not 2 <= len(token) <= 5 or not token.isalpha():
        return False
    initials = iter(w[0] for w in [*club_words, "soccer", "club"])
    return all(any(ch == i for i in initials) for ch in token)


def squad_key(team_name: str | None, club: str | None, state_code: str | None = None) -> frozenset:
    club_words = read_name(club).words
    removable = set(club_words) | NOISE_WORDS | LEAGUE_WORDS | {(state_code or "").lower()}
    tokens = [SPELLING.get(w, w) for w in read_name(team_name).words]
    kept = []
    for word, following in zip(tokens, [*tokens[1:], None]):
        if word == "pre" and following in PRE_LEAGUES:
            continue
        if word in removable or is_club_initials(word, club_words):
            continue
        kept.append(word)
    return frozenset(kept)


def stated_cohort(team_name: str | None) -> tuple[set[int] | None, set[int]]:
    """(ages, bare): the ages a name allows, and a one-element set holding its bare birth year
    when it states exactly one, else an empty set.

    A bare birth year is the younger year of one band and the older year of the next, so it
    allows both ages. Ages are unfolded: the U18 and U19 squads that share the u19 board are
    different teams.
    """
    reading = read_name(team_name)
    return reading.ages, reading.bare if len(reading.bare) == 1 else set()


def cohorts_compatible(name_a: str | None, name_b: str | None) -> bool:
    (ages_a, bare_a), (ages_b, bare_b) = stated_cohort(name_a), stated_cohort(name_b)
    if ages_a == set() or ages_b == set():
        return False
    if bare_a and bare_b and bare_a != bare_b:
        return False
    if ages_a is None or ages_b is None:
        return True
    return bool(ages_a & ages_b)


def stated_league(team_name: str | None) -> str | None:
    lowered = (team_name or "").lower()
    for league, pattern in LEAGUE_PATTERNS:
        if pattern.search(lowered):
            return league
    return None


def leagues_conflict(name_a: str | None, name_b: str | None) -> bool:
    a, b = stated_league(name_a), stated_league(name_b)
    return bool(a and b and a != b and frozenset({a, b}) not in COMPATIBLE_LEAGUES)


def is_protected_division(team_name: str | None) -> bool:
    return has_protected_division(team_name) or bool(_MLS.search(team_name or ""))


def ages_contradict(ages: set[int] | None, age_group: str) -> bool:
    if ages is None:
        return False
    stored = int(age_group.lstrip("u"))
    return not (stored in ages or (stored == 19 and bool(ages & {18, 19})))


def contradicts_stored_cohort(team_name: str | None, age_group: str) -> bool:
    return ages_contradict(read_name(team_name).ages, age_group)


def name_rank(team_name: str | None, age_group: str) -> int:
    """2 for a band or U-age that fits the stored cohort, 1 for a bare birth year, 0 for no
    stated age, -1 for a label stale for, or contradicting, the stored cohort."""
    reading = read_name(team_name)
    if ages_contradict(reading.ages, age_group):
        return -1
    if reading.exact:
        return 2
    return 1 if reading.bare else 0


def effective_clubs(teams) -> dict[str, str | None]:
    """Each row's club, a NULL one borrowing the longest club of its cohort that the team
    name starts with."""
    by_cohort = defaultdict(dict)
    for t in teams:
        if t["club_name"] and normalize(t["club_name"]):
            by_cohort[(t["age_group"], t["gender"], t["state_code"])][t["club_name"]] = normalize(t["club_name"])
    clubs = {}
    for t in teams:
        club = t["club_name"]
        if not club:
            name = normalize(t["team_name"])
            cohort = by_cohort[(t["age_group"], t["gender"], t["state_code"])]
            starts = [c for c, norm in cohort.items() if name.startswith(norm)]
            club = max(starts, key=lambda c: len(cohort[c])) if starts else None
        clubs[t["team_id_master"]] = club
    return clubs


def build_pairs(teams, provider_code) -> tuple[list[dict], list[dict]]:
    """Pairs sharing a squad key, split into those the names admit and those they refuse."""
    teams = [
        t
        for t in teams
        if provider_code.get(t["provider_id"]) not in OUT_OF_SCOPE_PROVIDERS and t["age_group"] and t["gender"]
    ]
    clubs = effective_clubs(teams)
    groups = defaultdict(list)
    for t in teams:
        club = clubs[t["team_id_master"]]
        key = squad_key(t["team_name"], club, t["state_code"])
        if club and key:
            groups[(normalize(club), t["age_group"], t["gender"], t["state_code"] or "", key)].append(t)

    admitted, refused = [], []
    for group, members in groups.items():
        for a, b in combinations(members, 2):
            pair = {"a": a, "b": b, "key": group[-1], "club": clubs[a["team_id_master"]]}
            reason = name_refusal(a, b)
            (refused if reason else admitted).append({**pair, "reason": reason})
    return admitted, refused


def name_refusal(a, b) -> str | None:
    if is_protected_division(a["team_name"]) or is_protected_division(b["team_name"]):
        return "an AD, HD, EA or MLS division name"
    if not cohorts_compatible(a["team_name"], b["team_name"]):
        return "the names state different birth cohorts"
    if leagues_conflict(a["team_name"], b["team_name"]):
        return "the names state different leagues"
    said_a, said_b = stated_gender(registered_name(a)), stated_gender(registered_name(b))
    if said_a and said_b and said_a != said_b:
        return f"the registered names state opposite genders ({said_a} vs {said_b})"
    return None


def evidence_refusal(pair, ev) -> str | None:
    ida, idb = pair["a"]["team_id_master"], pair["b"]["team_id_master"]
    if idb in ev.opponents[ida]:
        return "the two records played each other"
    if ev.dates[ida] & ev.dates[idb]:
        return "both played a game on the same day"
    if ida in ev.self_play or idb in ev.self_play:
        return "a row carries a self-play game and is already two squads"
    return None


def hold_reason(pair, partners: Counter) -> str | None:
    a, b = pair["a"], pair["b"]
    if partners[a["team_id_master"]] > 1 or partners[b["team_id_master"]] > 1:
        return "a row pairs with more than one row of its club"
    age = a["age_group"]
    if contradicts_stored_cohort(a["team_name"], age) and contradicts_stored_cohort(b["team_name"], age):
        return "neither name fits the stored age group"
    return None


def direction(pair, ev) -> tuple[dict, dict]:
    """(keep, merge), in the survivor order the module docstring states."""

    def rank(row):
        tid = row["team_id_master"]
        return (name_rank(row["team_name"], row["age_group"]), ev.games[tid], max(ev.dates[tid], default=""))

    a, b = pair["a"], pair["b"]
    return (a, b) if rank(a) >= rank(b) else (b, a)


def to_record(pair, keep, merge, provider_code, status, reason="", games=(None, None)) -> dict:
    a, b = pair["a"], pair["b"]
    return {
        "status": status,
        "reason": reason,
        "club": pair["club"],
        "age_group": a["age_group"],
        "gender": a["gender"],
        "state": a["state_code"],
        "squad_key": " ".join(sorted(pair["key"])),
        "name_a": a["team_name"],
        "name_b": b["team_name"],
        "name_original_a": a["team_name_original"] or "",
        "name_original_b": b["team_name_original"] or "",
        "provider_a": provider_code.get(a["provider_id"]),
        "provider_b": provider_code.get(b["provider_id"]),
        "games_a": games[0],
        "games_b": games[1],
        "merge_id": merge["team_id_master"],
        "keep_id": keep["team_id_master"],
        "merge_name": merge["team_name"],
        "keep_name": keep["team_name"],
    }


def write_csv(path, records) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(RECORD_FIELDS))
        writer.writeheader()
        for record in records:
            writer.writerow({k: csv_safe(v) if k in PROVIDER_TEXT_FIELDS else v for k, v in record.items()})


def scan(sb, args):
    providers = {p["id"]: p["code"] for p in sb.table("providers").select("id,code").execute().data}

    print("teams...", flush=True)
    teams = fetch_teams(sb, state=args.state, age_group=args.age_group)
    print(f"  {len(teams):,} live teams")

    print("merge map...", flush=True)
    merge_map = load_merge_map(sb)
    canonical = resolver(merge_map)
    already_merged = [t for t in teams if canonical(t["team_id_master"]) != t["team_id_master"]]
    teams = [t for t in teams if canonical(t["team_id_master"]) == t["team_id_master"]]
    print(f"  {len(already_merged):,} live rows left out because they already resolve to another")

    admitted, refused = build_pairs(teams, providers)
    print(f"  {len(admitted):,} pairs the names admit, {len(refused):,} they refuse")
    records = [to_record(p, p["a"], p["b"], providers, REJECTED, p["reason"]) for p in refused]
    if not admitted:
        return records

    print("games...", flush=True)
    candidates = {row["team_id_master"] for p in admitted for row in (p["a"], p["b"])}
    game_rows = fetch_games(sb, sorted(merged_into(candidates, merge_map, canonical)))
    ev = build_evidence(game_rows, [], canonical, candidates)

    clean = []
    for pair in admitted:
        keep, merge = direction(pair, ev)
        games = tuple(ev.games[pair[s]["team_id_master"]] for s in ("a", "b"))
        reason = evidence_refusal(pair, ev)
        if reason:
            records.append(to_record(pair, keep, merge, providers, REJECTED, reason, games))
        else:
            clean.append((pair, keep, merge, games))
    partners = Counter(row["team_id_master"] for pair, *_ in clean for row in (pair["a"], pair["b"]))
    for pair, keep, merge, games in clean:
        held = hold_reason(pair, partners)
        records.append(to_record(pair, keep, merge, providers, HELD if held else PROPOSED, held or "", games))
    records.sort(key=lambda r: (r["status"], r["age_group"], r["gender"], r["club"] or ""))
    return records


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default="data/exports", help="where to write the CSV and JSON")
    ap.add_argument("--state", required=True, help="the state_code to scan, e.g. CO")
    ap.add_argument("--age-group", help="restrict to one age group, e.g. u12")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    records = scan(get_client(), args)

    proposed = [r for r in records if r["status"] == PROPOSED]
    stem = f"squad_key_duplicates_{args.state.lower()}"
    if args.age_group:
        stem += f"_{args.age_group.lower()}"
    csv_path, json_path = out_dir / f"{stem}.csv", out_dir / f"{stem}.json"
    write_csv(csv_path, records)
    json_path.write_text(json.dumps(proposed, indent=1), encoding="utf-8")

    print("\n=== Funnel ===")
    for (status, reason), n in sorted(Counter((r["status"], r["reason"]) for r in records).items()):
        print(f"  {status:<9} {reason:<58} {n:,}")
    print(f"\nwrote {csv_path}  (every pair considered)")
    print(f"wrote {json_path}  (proposals only)")
    print("These are proposals. Steps 4-6 of merging-duplicate-teams still apply before any merge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
