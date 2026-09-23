#!/usr/bin/env python3
"""Propose merges for a squad registered once with GotSport and once with another provider.

Doorway C of .claude/skills/merging-duplicate-teams: one squad holding two team rows because
two providers each registered it. Both rows publish on the rankings boards with half a record
each, which is the duplicate a customer notices. Neither other doorway reaches this class --
Doorway A (scripts/find_fuzzy_duplicate_teams.py) requires club_name to match on strip and
lower alone, which a second provider's spelling rarely survives, and Doorway B matches fixture
fingerprints, which never match here because the opponents are duplicated too.

Candidate rule, all required:
  - different team-level provider_id: GotSport on one side, a --provider code on the other.
    modular11 is out of scope by operator decision; soccereventsgroup, athletes2events and
    playmetrics_tournament are operator-run per event and are not scanned.
  - same age_group, gender and state_code
  - club_name equal once punctuation and case are stripped
  - team_name identical once punctuation and case are stripped, and at least --min-name-len

Screens, each decisive:
  - the two registered names state opposite genders, reading a B/G affix as well as the word
  - the rows played each other, shared a game date, or either carries a self-play row
  - opponent Jaccard above --jaccard-max, opponents resolved through team_merge_map

Club equality decides who may pair; `are_same_club` decides only who competes, at a threshold
deliberately lower than the matchers' gates because a false competitor costs a review where a
hidden one costs a merge.

Tiers 6 and 7 carry a flag a person has to settle: a competing partner inside the club cohort,
and a row already holding several registrations from one provider. None of the seven is a safe
list -- Steps 4 to 6 of the skill still apply, and a tier is not a decision.

Blind spots it ships with. It pairs only against GotSport, so a TGS row duplicated on
SincSports is invisible. It requires identical names, so the containment classes the skill
tabulates are out of reach, as are clubs spelled two ways across providers. Its direction rule
keeps the GotSport row unless that row is empty and the other side is not, which is right for
the tiers below but is not a judgement about which row holds the better record.

Read-only: writes a CSV and a JSON, never touches the database. The CSV carries the refused
pairs too, because Step 4 of the skill is to review every refusal rather than a sample; the
JSON carries only the proposals. Vet the JSON, then feed the surviving pairs to
scripts/apply_vetted_team_merges.py, which is where the writes happen.

Usage:
    python scripts/find_cross_provider_duplicates.py --out-dir data/exports
    python scripts/find_cross_provider_duplicates.py --provider sincsports --state WA
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

from scripts.decide_team_merges import FUSED_REGISTRATION_THRESHOLD  # noqa: E402
from scripts.fix_band_cohorts import csv_safe  # noqa: E402
from scripts.fix_gender_from_registered_name import (  # noqa: E402
    AFFIX_B,
    AFFIX_G,
    WORD_B,
    WORD_G,
    spelled_gender,
)
from src.utils.club_normalizer import are_same_club  # noqa: E402
from src.utils.provider_ids import is_blank_provider_id  # noqa: E402
from supabase import create_client  # noqa: E402

PRIMARY_PROVIDER = "gotsport"
SECONDARY_PROVIDERS = ("tgs", "sincsports", "playmetrics", "affinity_wa", "affinity_or")

TEAM_COLS = (
    "team_id_master,team_name,team_name_original,club_name,age_group,gender,"
    "state_code,provider_id,provider_team_id"
)
GAME_COLS = "id,home_team_master_id,away_team_master_id,game_date,is_excluded"

# Refused pairs stay in the CSV because Step 4 of the skill is to review every refusal, not a
# sample of them -- a shared date that is really one fixture imported twice presents here
# exactly as it does in Doorway A. They are kept out of the JSON, which feeds
# apply_vetted_team_merges.py.
REJECTED_TIER = "0_rejected"
FLIP_TIER = "4_flip_direction"

# Only approved aliases are matched, so only approved ones may justify a merge: an alias a
# reviewer rejected would otherwise become the evidence for the one tier that skips every
# review flag.
APPROVED_ALIAS = "approved"

# The CSV's column order, declared rather than read off the first record.
RECORD_FIELDS = (
    "tier", "rejected_reason", "provider", "club", "age_group", "gender", "state",
    "gs_name", "ot_name", "gs_name_original", "ot_name_original", "gs_games", "ot_games",
    "gs_excluded_games", "ot_excluded_games",
    "opponent_jaccard", "competing_partners", "competing_partner_ids", "max_registrations",
    "alias_already_points_at_gotsport", "direction", "survivor_holds_fewer_games",
    "merge_id", "keep_id", "merge_name", "keep_name",
)

# Free text a club typed into a provider's registration form, so a spreadsheet must be kept
# from reading it as a formula.
PROVIDER_TEXT_FIELDS = frozenset(
    {"club", "gs_name", "ot_name", "gs_name_original", "ot_name_original", "merge_name", "keep_name"}
)

_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]")


def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(url, key)


def page(build, order_col, size=10000):
    """Drain a PostgREST query, ordered so pages neither skip nor repeat rows.

    Advances by what came back rather than by `size`, because the server's row cap differs by
    deployment and treating a capped page as the final one truncates the scan silently.
    """
    rows, off = [], 0
    while True:
        chunk = build().order(order_col).range(off, off + size - 1).execute().data or []
        if not chunk:
            return rows
        rows.extend(chunk)
        off += len(chunk)


def batched(seq, n=100):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def normalize(value: str | None) -> str:
    return _NON_ALNUM.sub("", value or "").lower()


def registered_name(row) -> str:
    """The name the club registered, which outranks the row's current one.

    team_name_original is stashed only on a row's first rewrite, so it is NULL on most rows
    and the current name is all there is.
    """
    return row.get("team_name_original") or row.get("team_name") or ""


def stated_gender(name: str | None) -> str | None:
    """The gender a name states, or None when the name contradicts itself.

    `any_gender` exists to read opponents, where a guess beats nothing, so it lets a `12B`
    affix win over the word "Girls". Here a single name is the whole witness and the verdict
    refuses a merge, so a name saying both says neither -- while `12G` against `12B`, which
    the word-only reading cannot see at all, is exactly what this screen is for.
    """
    n = name or ""
    word = spelled_gender(n)
    if word:
        return word
    if WORD_B.search(n) or WORD_G.search(n):
        return None
    boy, girl = bool(AFFIX_B.search(n)), bool(AFFIX_G.search(n))
    if boy and not girl:
        return "Male"
    if girl and not boy:
        return "Female"
    return None


def resolver(raw: dict[str, str]):
    """Follow merge chains to the surviving row. A single hop leaves A->B->C reading B."""

    def canonical(team_id):
        seen = set()
        while team_id in raw and team_id not in seen:
            seen.add(team_id)
            team_id = raw[team_id]
        return team_id

    return canonical


def load_merge_map(sb) -> dict[str, str]:
    return {
        m["deprecated_team_id"]: m["canonical_team_id"]
        for m in page(lambda: sb.table("team_merge_map").select("deprecated_team_id,canonical_team_id"), "id")
    }


def merged_into(team_ids, merge_map, canonical) -> set:
    """Every row a candidate's evidence is read under, plus the candidates themselves.

    A merge leaves `games` naming the deprecated row, so reading raw ids alone makes a
    survivor that absorbed a full season look empty -- and "empty" is what tiers 1, 3, 4
    and 5 turn on. The candidate's own survivor has to be in here too: a row can be live
    and still carry a `team_merge_map` entry, and evidence is keyed on the resolved id, so
    fetching only the raw one reads that candidate as having no schedule at all.
    """
    wanted = set(team_ids) | {canonical(t) for t in team_ids}
    return wanted | {d for d in merge_map if canonical(d) in wanted}


@dataclass
class Evidence:
    """Per-team game and registration facts, keyed by the surviving row."""

    games: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    excluded: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    dates: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    opponents: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    self_play: set = field(default_factory=set)
    aliases: dict[str, set] = field(default_factory=lambda: defaultdict(set))

    def registrations(self, team_id) -> Counter:
        """Registrations per provider, derived so it cannot drift from `aliases`.

        `team_alias_map` is UNIQUE on (provider_id, provider_team_id), so the alias set is
        already one row per registration. Nothing here separates a club's sequential
        season-by-season re-registrations from concurrent ones, which the threshold is about.
        """
        return Counter(provider for provider, _ in self.aliases[team_id])


def build_evidence(game_rows, alias_rows, canonical, team_ids) -> Evidence:
    ev = Evidence()
    tracked = {canonical(t) for t in team_ids}
    for g in game_rows:
        home, away = canonical(g["home_team_master_id"]), canonical(g["away_team_master_id"])
        if home and home == away:
            # Resolved, because the commonest fused row is one that absorbed a team it had
            # played. A fused row is not a ranking input, so an excluded row still counts.
            ev.self_play.add(home)
            continue
        if g.get("is_excluded"):
            # Counted but not rated. An excluded game is no part of a live schedule, so it
            # must not decide direction -- but a merge moves the row anyway, so a reviewer
            # deciding whether the thin survivor is really the thin row has to see it.
            for mine in (home, away):
                if mine and mine in tracked:
                    ev.excluded[mine] += 1
            continue
        for mine, them in ((home, away), (away, home)):
            if not mine or mine not in tracked:
                continue
            ev.games[mine] += 1
            if g.get("game_date"):
                ev.dates[mine].add(g["game_date"])
            if them:
                ev.opponents[mine].add(them)
    for a in alias_rows:
        ev.aliases[canonical(a["team_id_master"])].add((a["provider_id"], a["provider_team_id"]))
    return ev


def build_pairs(teams, provider_code, *, secondary_codes, competing_similarity, min_name_len):
    """Every GotSport / secondary-provider pair of rows the candidate rule admits.

    The group key omits the club on purpose. Keying on it -- which is what comparing clubs
    byte-for-byte amounts to -- hides a competing partner filed under the club's other
    spelling, and an ambiguous cluster then reads as a clean pair of two.
    """
    groups = defaultdict(list)
    for t in teams:
        code = provider_code.get(t["provider_id"])
        if code != PRIMARY_PROVIDER and code not in SECONDARY_PROVIDERS:
            continue
        name, club = normalize(t["team_name"]), normalize(t["club_name"])
        if not club or len(name) < min_name_len or not t["age_group"] or not t["gender"]:
            continue
        groups[(name, t["age_group"], t["gender"], t["state_code"] or "")].append(t)

    pairs = []
    for members in groups.values():
        clubs = {m["team_id_master"]: normalize(m["club_name"]) for m in members}
        primaries = [m for m in members if provider_code[m["provider_id"]] == PRIMARY_PROVIDER]
        secondaries = [m for m in members if provider_code[m["provider_id"]] in secondary_codes]
        for gs in primaries:
            gs_club = gs["club_name"]
            rivals = [
                m
                for m in members
                if m["team_id_master"] != gs["team_id_master"]
                and are_same_club(m["club_name"] or "", gs_club or "", threshold=competing_similarity)
            ]
            for ot in secondaries:
                if clubs[gs["team_id_master"]] != clubs[ot["team_id_master"]]:
                    continue
                pairs.append(
                    {
                        "gs": gs,
                        "ot": ot,
                        "provider_code": provider_code[ot["provider_id"]],
                        "competing": [r for r in rivals if r["team_id_master"] != ot["team_id_master"]],
                    }
                )
    return pairs


def screen(pair, ev, canonical, *, jaccard_max) -> tuple[str | None, float]:
    """Why this pair is not a duplicate, plus the opponent Jaccard the screen measured."""
    gs, ot = pair["gs"], pair["ot"]
    gid, oid = canonical(gs["team_id_master"]), canonical(ot["team_id_master"])

    # Measured before the refusals so a refused row carries its real overlap into the CSV.
    # Step 4 asks the reviewer whether a shared date's differing opponents are themselves
    # duplicates, and a hardcoded 0.0 answers "no" on rows that were never measured.
    union = ev.opponents[gid] | ev.opponents[oid]
    jaccard = len(ev.opponents[gid] & ev.opponents[oid]) / len(union) if union else 0.0

    said_gs, said_ot = stated_gender(registered_name(gs)), stated_gender(registered_name(ot))
    if said_gs and said_ot and said_gs != said_ot:
        return f"the registered names state opposite genders ({said_gs} vs {said_ot})", jaccard
    if oid in ev.opponents[gid] or gid in ev.opponents[oid]:
        return "the two records played each other", jaccard
    if ev.dates[gid] & ev.dates[oid]:
        return "both played a game on the same day", jaccard
    if gid in ev.self_play or oid in ev.self_play:
        return "a row carries a self-play game and is already two squads", jaccard
    if jaccard > jaccard_max:
        return f"opponent overlap above {jaccard_max}", jaccard
    return None, jaccard


def max_registrations(pair, ev, canonical) -> int:
    counts = [
        n
        for row in (pair["gs"], pair["ot"])
        for n in ev.registrations(canonical(row["team_id_master"])).values()
    ]
    return max(counts, default=0)


def flips_direction(pair, ev, canonical) -> bool:
    """Whether the secondary row, not GotSport, holds the live schedule.

    Read from the game counts rather than from the tier, because a review flag can take the
    tier away from `4_flip_direction` while leaving the GotSport row just as empty -- and the
    direction is what decides which row a merge deprecates.
    """
    gs_games = ev.games[canonical(pair["gs"]["team_id_master"])]
    ot_games = ev.games[canonical(pair["ot"]["team_id_master"])]
    return gs_games == 0 and ot_games > 0


def alias_points_at_primary(pair, ev, canonical) -> bool:
    """Whether the secondary row's registration already resolves to the GotSport master.

    `''`, `'None'` and `'null'` are live values in `team_alias_map.provider_team_id`, and two
    of them matching identifies no team -- which is not the warrant `1_provably_safe` claims.
    """
    ot = pair["ot"]
    if is_blank_provider_id(ot["provider_team_id"]):
        return False
    return (ot["provider_id"], ot["provider_team_id"]) in ev.aliases[canonical(pair["gs"]["team_id_master"])]


def tier_for(pair, ev, canonical) -> str:
    """Which shape this pair is: provably-safe wins outright, the review flags then demote,
    and otherwise the shape follows the game counts.

    A provably-safe pair keeps its tier through those flags: its alias already points at the
    survivor, so the merge moves no attribution whatever else sits in the cluster.
    """
    gs, ot = pair["gs"], pair["ot"]
    gid, oid = canonical(gs["team_id_master"]), canonical(ot["team_id_master"])
    gs_games, ot_games = ev.games[gid], ev.games[oid]

    if alias_points_at_primary(pair, ev, canonical) and ot_games == 0:
        return "1_provably_safe"
    if pair["competing"]:
        return "6_review_competing_partner"
    if max_registrations(pair, ev, canonical) >= FUSED_REGISTRATION_THRESHOLD:
        return "7_review_fused_registration"
    if flips_direction(pair, ev, canonical):
        return FLIP_TIER
    if gs_games == 0 and ot_games == 0:
        return "5_both_empty"
    if ot_games == 0:
        return "3_other_side_empty"
    return "2_both_have_games"


def to_record(pair, ev, canonical, tier, jaccard, rejected_reason="") -> dict:
    gs, ot = pair["gs"], pair["ot"]
    gid, oid = canonical(gs["team_id_master"]), canonical(ot["team_id_master"])
    gs_games, ot_games = ev.games[gid], ev.games[oid]
    flip = flips_direction(pair, ev, canonical)
    keep, merge = (ot, gs) if flip else (gs, ot)
    keep_games, merge_games = (ev.games[canonical(keep["team_id_master"])],
                               ev.games[canonical(merge["team_id_master"])])
    return {
        "tier": tier,
        "rejected_reason": rejected_reason,
        "provider": pair["provider_code"],
        "club": gs["club_name"],
        "age_group": gs["age_group"],
        "gender": gs["gender"],
        "state": gs["state_code"],
        "gs_name": gs["team_name"],
        "ot_name": ot["team_name"],
        "gs_name_original": gs["team_name_original"] or "",
        "ot_name_original": ot["team_name_original"] or "",
        "gs_games": gs_games,
        "ot_games": ot_games,
        "gs_excluded_games": ev.excluded[gid],
        "ot_excluded_games": ev.excluded[oid],
        "opponent_jaccard": round(jaccard, 3),
        "competing_partners": len(pair["competing"]),
        "competing_partner_ids": " ".join(c["team_id_master"] for c in pair["competing"]),
        "max_registrations": max_registrations(pair, ev, canonical),
        "alias_already_points_at_gotsport": alias_points_at_primary(pair, ev, canonical),
        "direction": "flipped" if flip else "gotsport_survives",
        "survivor_holds_fewer_games": keep_games < merge_games,
        "merge_id": merge["team_id_master"],
        "keep_id": keep["team_id_master"],
        "merge_name": merge["team_name"],
        "keep_name": keep["team_name"],
    }


def write_csv(path, records) -> None:
    """The review sheet, defanged and always rewritten.

    Escaping happens on this path rather than in `to_record`, so the JSON the applier reads
    keeps the registered text. The header is written even for an empty scan, so this file and
    the JSON beside it always describe the same run instead of the CSV surviving from an
    earlier, wider one.
    """
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(RECORD_FIELDS))
        writer.writeheader()
        for record in records:
            writer.writerow({k: csv_safe(v) if k in PROVIDER_TEXT_FIELDS else v for k, v in record.items()})


def fetch_teams(sb, *, state=None, age_group=None):
    def build():
        q = sb.table("teams").select(TEAM_COLS).eq("is_deprecated", False)
        if state:
            q = q.eq("state_code", state.upper())
        if age_group:
            q = q.eq("age_group", age_group.lower())
        return q

    return page(build, "team_id_master")


def fetch_games(sb, team_ids):
    rows, seen = [], set()
    for side in ("home_team_master_id", "away_team_master_id"):
        for batch in batched(team_ids):
            for g in page(lambda b=batch, s=side: sb.table("games").select(GAME_COLS).in_(s, b), "id"):
                if g["id"] not in seen:
                    seen.add(g["id"])
                    rows.append(g)
    return rows


def fetch_aliases(sb, team_ids):
    rows = []
    for batch in batched(team_ids):
        rows += page(
            lambda b=batch: sb.table("team_alias_map")
            .select("team_id_master,provider_id,provider_team_id")
            .eq("review_status", APPROVED_ALIAS)
            .in_("team_id_master", b),
            "id",
        )
    return rows


def scan(sb, args):
    providers = {p["id"]: p["code"] for p in sb.table("providers").select("id,code").execute().data}
    secondary_codes = {args.provider} if args.provider else set(SECONDARY_PROVIDERS)

    print("teams...", flush=True)
    teams = fetch_teams(sb, state=args.state, age_group=args.age_group)
    print(f"  {len(teams):,} live teams")

    pairs = build_pairs(
        teams,
        providers,
        secondary_codes=secondary_codes,
        competing_similarity=args.competing_similarity,
        min_name_len=args.min_name_len,
    )
    print(f"  {len(pairs):,} raw candidate pairs")
    if not pairs:
        return [], Counter()

    print("merge map...", flush=True)
    merge_map = load_merge_map(sb)
    canonical = resolver(merge_map)
    candidates = {row["team_id_master"] for p in pairs for row in (p["gs"], p["ot"])}
    cluster = merged_into(candidates, merge_map, canonical)
    print(f"  {len(candidates):,} candidate rows, {len(cluster):,} with their merged predecessors")

    print("games and aliases...", flush=True)
    game_rows = fetch_games(sb, sorted(cluster))
    alias_rows = fetch_aliases(sb, sorted(cluster))
    print(f"  {len(game_rows):,} games, {len(alias_rows):,} alias rows")
    ev = build_evidence(game_rows, alias_rows, canonical, candidates)

    records, rejected = [], Counter()
    for pair in pairs:
        reason, jaccard = screen(pair, ev, canonical, jaccard_max=args.jaccard_max)
        if reason:
            rejected[reason] += 1
            records.append(to_record(pair, ev, canonical, REJECTED_TIER, jaccard, reason))
            continue
        records.append(to_record(pair, ev, canonical, tier_for(pair, ev, canonical), jaccard))
    records.sort(key=lambda r: (r["tier"], r["provider"], -r["gs_games"] - r["ot_games"], r["club"] or ""))
    return records, rejected


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default="data/exports", help="where to write the CSV and JSON")
    ap.add_argument("--provider", choices=SECONDARY_PROVIDERS, help="restrict the non-GotSport side")
    ap.add_argument("--state", help="restrict to one state_code")
    ap.add_argument("--age-group", help="restrict to one age group, e.g. u14")
    ap.add_argument("--jaccard-max", type=float, default=0.20, help="reject above this opponent overlap")
    ap.add_argument(
        "--competing-similarity",
        type=float,
        default=0.60,
        help="club similarity at which a third row of the cohort counts as a competing partner",
    )
    ap.add_argument("--min-name-len", type=int, default=8, help="min normalised team-name length")
    args = ap.parse_args()

    for flag, value in (("--jaccard-max", args.jaccard_max), ("--competing-similarity", args.competing_similarity)):
        # NaN fails this range test, which is the point: it compares false against everything,
        # so it would switch a screen off rather than loosen it.
        if not 0.0 <= value <= 1.0:
            ap.error(f"{flag} must be a ratio between 0 and 1, got {value!r}")

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    records, rejected = scan(get_client(), args)

    proposed = [r for r in records if r["tier"] != REJECTED_TIER]
    csv_path = out_dir / "cross_provider_duplicates.csv"
    json_path = out_dir / "cross_provider_duplicates.json"
    write_csv(csv_path, records)
    json_path.write_text(json.dumps(proposed, indent=1), encoding="utf-8")

    print("\n=== Funnel ===")
    print(f"  rows written {'':<55} {len(records):,}")
    for reason, n in sorted(rejected.items()):
        print(f"  rejected  {reason:<56} {n:,}")
    print(f"  proposed  {'':<56} {len(proposed):,}")

    by_tier = Counter(r["tier"] for r in proposed)
    print("\n=== Tiers ===")
    for tier in sorted(by_tier):
        print(f"  {tier:<30} {by_tier[tier]:,}")
    print(f"\nwrote {csv_path}  (proposals and refusals)")
    print(f"wrote {json_path}  (proposals only)")
    print("These are proposals. Steps 4-6 of merging-duplicate-teams still apply: review every")
    print(f"{REJECTED_TIER} row as well, and tiers 6 and 7 carry a flag a person has to settle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
