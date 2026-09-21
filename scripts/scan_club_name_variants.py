#!/usr/bin/env python3
"""List the club-name variant groups a state still has once the weekly cleanup has run.

`scripts/full_club_analysis.py` already merges two spellings of one club when its
`CLUB_CANONICAL_OVERRIDES` name them or when `normalize_for_grouping` folds them
together. This lists what that leaves behind, so a state pass reads a short list of
decisions instead of the whole club roster.

It is a detector, not a rule. Its fold is deliberately looser than the shipped one --
organisation words anywhere in a trailing run, a redundant acronym tag, word order, case,
punctuation, accents and plurals all collapse -- because a group it fails to raise is a
club nobody looks at again, while a group it raises wrongly costs one line of reading. A
group listed here is a question for the owner, never a fix.

Four folds exist because the scan that was rebuilt by hand each round missed them, and
the owner caught each by eye:

- a one-letter-per-word acronym, which cannot see `(CUSC)` repeating `Chesapeake United SC`
- `Assoc` beside `Assn` and `Association`
- `Youth` as an organisation word, which split `X Youth Soccer` from `X Youth Soccer Assn`
- `ysa`/`ysl` as trailing organisation tokens

Each variant is printed with sample team names, because the acronym a club writes into its
own team names is what decides the ambiguous groups -- `NC Rush` turned out to be Triad
because its teams read `NCRT`.

Read-only: it fetches teams and prints. Nothing here writes to the database.

Usage:
    python scripts/scan_club_name_variants.py --state TX
    python scripts/scan_club_name_variants.py --state TX --samples 5
    python scripts/scan_club_name_variants.py --state TX --json out.json
    python scripts/scan_club_name_variants.py            # every state
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402

from scripts.full_club_analysis import (  # noqa: E402
    analyze_state,
    club_acronym,
    fetch_all_teams,
    get_supabase,
    learn_vocabulary,
    looks_like_acronym,
    overlay_fixes,
    trailing_tag,
)

console = Console()

# Words naming what kind of body a club is, rather than which club it is. A trailing run
# of these is dropped, so "Inwood SC", "Inwood Soccer Club" and "Inwood Youth Soccer
# Association" reach one identity. Tier words ("Premier", "Elite", "Select", "United")
# are deliberately absent -- they distinguish clubs.
ORG_TOKENS = frozenset(
    {
        "ac",
        "academy",
        "academia",
        "academies",
        "alliance",
        "assn",
        "assns",
        "asso",
        "assoc",
        "assocs",
        "association",
        "associations",
        "athletic",
        "athletics",
        "cd",
        "cf",
        "club",
        "clube",
        "clubs",
        "co",
        "company",
        "fa",
        "fc",
        "football",
        "futbol",
        "inc",
        "incorporated",
        "jsc",
        "junior",
        "juniors",
        "league",
        "leagues",
        "llc",
        "ltd",
        "organization",
        "sa",
        "sc",
        "sl",
        "soccer",
        "sport",
        "sports",
        "yfc",
        "ysa",
        "ysc",
        "ysl",
        "yso",
        "youth",
    }
)

_TOKEN = re.compile(r"[a-z0-9]+", re.ASCII)
_NON_ALNUM = re.compile(r"[^a-z0-9]+", re.ASCII)


def _ascii_fold(name: str) -> str:
    """Lowercase `name` with accents dropped, so "Barça" and "Barca" read alike."""
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _tokens(name: str) -> list[str]:
    folded = _ascii_fold(name).replace("&", " and ")
    return _TOKEN.findall(folded)


def _singular(token: str) -> str:
    return token[:-1] if len(token) >= 5 and token.endswith("s") else token


def _strip_redundant_tag(club: str) -> str:
    """Drop a trailing "(TAG)" that only repeats the name's own acronym."""
    tag = trailing_tag(club)
    if tag and club_acronym(tag[0]) == _NON_ALNUM.sub("", _ascii_fold(tag[1])):
        return tag[0]
    return club


def _core_key(club: str) -> str:
    """The club's identity with a trailing run of organisation words dropped."""
    tokens = [_singular(t) for t in _tokens(club)]
    core = list(tokens)
    while core and core[-1] in ORG_TOKENS:
        core.pop()
    return "|".join(core or tokens)


def _sorted_key(club: str) -> str:
    """Every token, order discarded, so "FC Dallas" and "Dallas FC" meet.

    Organisation words are kept here, so "Dallas SC" stays apart from "FC Dallas".
    """
    return "|".join(sorted(_singular(t) for t in _tokens(club)))


def scan_keys(club: str) -> set[str]:
    """The keys `club` joins a group on. Two clubs sharing any key are one group.

    A trailing "(TAG)" is dropped whatever it holds, rather than only when it repeats the
    name's own acronym: a scan that tested the tag for redundancy is what let `(CUSC)`
    through, and a tag naming something else is a group the owner rejects in one line.
    """
    keys = set()
    tag = trailing_tag(club)
    for form in {club, tag[0] if tag else club}:
        core = _core_key(form)
        if core:
            keys.add("core:" + core)
            keys.add("sorted:" + _sorted_key(form))
    return keys


def _acronym_form(club: str) -> str:
    """The acronym `club` is, when its whole name is one -- "CVYSA" -- else an empty string."""
    tokens = _tokens(_strip_redundant_tag(club))
    if len(tokens) != 1:
        return ""
    token = tokens[0]
    return token if 2 <= len(token) <= 8 and token.isalpha() and looks_like_acronym(token) else ""


class _Union:
    """Union-find over club names."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def group_clubs(clubs) -> list[list[str]]:
    """Group club names that look like spellings of one club. Groups of one are dropped."""
    clubs = list(clubs)
    union = _Union()
    by_key: dict[str, str] = {}
    for club in clubs:
        union.find(club)
        for key in scan_keys(club):
            if key in by_key:
                union.union(club, by_key[key])
            else:
                by_key[key] = club

    # A club whose whole name is an acronym joins the club that acronym spells out.
    by_acronym: dict[str, str] = {}
    for club in clubs:
        by_acronym.setdefault(club_acronym(_strip_redundant_tag(club)), club)
    for club in clubs:
        form = _acronym_form(club)
        if form and form in by_acronym and by_acronym[form] != club:
            union.union(club, by_acronym[form])

    grouped: dict[str, list[str]] = defaultdict(list)
    for club in clubs:
        grouped[union.find(club)].append(club)
    return [sorted(members) for members in grouped.values() if len(members) > 1]


def unresolved_groups(teams, state_code, vocabulary, samples=3):
    """Variant groups a state still holds after `analyze_state`'s fixes land.

    Running the shipped analysis first is what keeps a group that already has a rule, or
    that the automatic pass already folds, off the list.
    """
    fixes, _, _ = analyze_state(teams, state_code, vocabulary)
    resolved = overlay_fixes(teams, fixes)

    counts: dict[str, int] = defaultdict(int)
    team_names: dict[str, list[str]] = defaultdict(list)
    for team in resolved:
        club = team.get("club_name")
        if not club:
            continue
        counts[club] += 1
        if len(team_names[club]) < samples:
            team_names[club].append(team.get("team_name") or "")

    groups = []
    for members in group_clubs(counts):
        members = sorted(members, key=lambda c: (-counts[c], c))
        groups.append(
            {
                "state": state_code,
                "teams": sum(counts[c] for c in members),
                "variants": [
                    {"club": club, "teams": counts[club], "sample_team_names": team_names[club]} for club in members
                ],
            }
        )
    return sorted(groups, key=lambda g: (-g["teams"], g["variants"][0]["club"]))


def fetch_club_names(client):
    """Every live team's club name, nationally, for the vocabulary the caps pass reads."""
    names = []
    offset, page_size = 0, 10000
    while True:
        result = (
            client.table("teams")
            .select("club_name")
            .eq("is_deprecated", False)
            .order("team_id_master")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        if not result.data:
            break
        names.extend(row.get("club_name") for row in result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    return names


def fetch_states(client):
    states = set()
    offset, page_size = 0, 10000
    while True:
        result = (
            client.table("teams")
            .select("state_code")
            .eq("is_deprecated", False)
            .order("team_id_master")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        if not result.data:
            break
        states.update(row["state_code"] for row in result.data if row.get("state_code"))
        if len(result.data) < page_size:
            break
        offset += page_size
    return sorted(states)


def print_groups(groups, min_teams):
    for group in groups:
        if group["teams"] < min_teams:
            continue
        console.print(f"\n[bold cyan]{group['state']}[/bold cyan]  ({group['teams']} teams)")
        for variant in group["variants"]:
            console.print(f"  [bold]{variant['club']}[/bold]  [dim]{variant['teams']} teams[/dim]")
            for name in variant["sample_team_names"]:
                console.print(f"      [dim]{name}[/dim]")


def main():
    parser = argparse.ArgumentParser(description="List unresolved club-name variant groups")
    parser.add_argument("--state", action="append", help="State code to scan (repeatable; default: every state)")
    parser.add_argument("--samples", type=int, default=3, help="Sample team names shown per variant (default: 3)")
    parser.add_argument("--min-teams", type=int, default=1, help="Hide groups smaller than this (default: 1)")
    parser.add_argument("--json", help="Also write the groups to this path as JSON")
    args = parser.parse_args()

    load_dotenv()
    client = get_supabase()

    console.print("Learning club-name vocabulary...")
    vocabulary = learn_vocabulary(fetch_club_names(client))

    states = [s.upper() for s in args.state] if args.state else fetch_states(client)

    all_groups = []
    for state in states:
        teams = fetch_all_teams(client, state)
        groups = unresolved_groups(teams, state, vocabulary, samples=args.samples)
        shown = [g for g in groups if g["teams"] >= args.min_teams]
        all_groups.extend(shown)
        console.print(f"{state}: {len(teams)} teams, {len(shown)} unresolved variant groups")

    print_groups(all_groups, args.min_teams)
    console.print(f"\n[bold]{len(all_groups)} groups[/bold] across {len(states)} state(s)")

    if args.json:
        Path(args.json).write_text(json.dumps(all_groups, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"Wrote {args.json}")


if __name__ == "__main__":
    main()
