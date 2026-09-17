#!/usr/bin/env python3
"""Keep an English youth league's teams out of the rankings.

An English league on GotSport reached PitchRank through opponent discovery. Its teams sit on US
state boards while playing only each other. This lists them in team_ranking_exclusions; the
rankings loader then drops every game they played.

Seeds are teams whose latest GotSport answer names an English association. A team joins the list
when all of these hold, repeated until nobody new joins:

  - GotSport has not confirmed it as a US team;
  - it played at least one team already listed;
  - at least half of its opponents are listed or registered with no association at all;
  - fewer than a fifth of its opponents are confirmed US teams.

Growing from the seeds is what keeps out the US teams that also have no association on file.

The dry run decides and writes the snapshot. A US team that met English touring sides can still
qualify, so read the snapshot and delete every row that is not an English team before applying
it. --execute replays that file and never recomputes.

Usage:
    python scripts/exclude_english_teams.py --snapshot english_teams.json              # dry run
    python scripts/exclude_english_teams.py --execute --snapshot english_teams.json --out log.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local", override=True)

from src.rankings.data_adapter import batch_fetch_rows  # noqa: E402
from src.utils.merge_resolver import MergeResolver  # noqa: E402
from src.utils.team_association_map import (  # noqa: E402
    MAPPED_OUTCOME,
    NO_ASSOCIATION_OUTCOME,
    UNMAPPED_OUTCOME_PREFIX,
    is_answer,
    is_english_association,
)
from supabase import create_client  # noqa: E402

ACTOR = "exclude_english_teams"
REASON = "English youth league team, not a US team"
ID_BATCH = 100
PAGE = 1000
SIDES = (("home_team_master_id", "away_team_master_id"), ("away_team_master_id", "home_team_master_id"))

# GotSport answers with this association when it holds none, and also when the association
# really is Alabama (scripts/assign_team_states.py UNSET_DEFAULT_ASSOCIATION). It therefore
# confirms nothing: an English team carrying the default must not be vetoed by it.
UNSET_DEFAULT_STATE = "AL"

# A national body names a country and no state, so to_state_code leaves it unmapped. It is
# still the provider saying "US team".
US_NATIONAL_ASSOCIATION = "USA"


def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(url, key)


def _paged(make_query) -> list[dict]:
    rows_out, off = [], 0
    while True:
        rows = make_query().range(off, off + PAGE - 1).execute().data or []
        rows_out.extend(rows)
        if len(rows) < PAGE:
            return rows_out
        off += PAGE


class _Identity:
    """Every team id this tool handles, in the ids the rankings loader compares.

    A probe filed against an id that later merged away describes the team that absorbed it, so
    the answer has to move with it — otherwise a provider-confirmed US team is judged under an
    id nothing else mentions, and nothing vetoes listing it.
    """

    def __init__(self, merge_resolver):
        # MergeResolver loads on first resolve(), so reading its map before that gives nothing.
        if merge_resolver is not None and not getattr(merge_resolver, "_loaded", False):
            merge_resolver.load_merge_map()
        merge_map = getattr(merge_resolver, "_merge_map", None) or {}
        self._canonical = dict(merge_map)
        self._aliases: dict[str, set[str]] = {}
        for deprecated, canonical in merge_map.items():
            self._aliases.setdefault(canonical, {canonical}).add(deprecated)

    def canonical(self, team_id):
        return self._canonical.get(team_id, team_id) if team_id else team_id

    def aliases(self, team_id) -> set[str]:
        return self._aliases.get(team_id, {team_id})


def latest_answers(probe_rows: list[dict]) -> dict[str, tuple[str, str | None]]:
    """Each team's newest answered probe, as (outcome, reported_state_code)."""
    answers: dict[str, tuple[str, str | None]] = {}
    for row in sorted(probe_rows, key=lambda r: r["probed_at"]):
        if is_answer(row["outcome"]):
            answers[row["team_id_master"]] = (row["outcome"], row.get("reported_state_code"))
    return answers


def classify(answers: dict[str, tuple[str, str | None]]) -> tuple[dict[str, str], set[str], set[str], Counter]:
    """Split the answers into (English seeds by association, no association, confirmed US, other unmapped).

    A team the provider cannot place lands only in the last: it neither seeds the list nor
    vetoes a team that played it.
    """
    seeds: dict[str, str] = {}
    no_association: set[str] = set()
    confirmed_us: set[str] = set()
    other_unmapped: Counter = Counter()
    for team_id, (outcome, reported_state) in answers.items():
        if outcome == MAPPED_OUTCOME:
            if reported_state != UNSET_DEFAULT_STATE:
                confirmed_us.add(team_id)
        elif outcome == NO_ASSOCIATION_OUTCOME:
            no_association.add(team_id)
        else:
            association = outcome.removeprefix(UNMAPPED_OUTCOME_PREFIX)
            if is_english_association(association):
                seeds[team_id] = association
            elif association.strip().upper() == US_NATIONAL_ASSOCIATION:
                confirmed_us.add(team_id)
            else:
                other_unmapped[association] += 1
    return seeds, no_association, confirmed_us, other_unmapped


def opponent_counts(opponents, listed, no_association: set[str], confirmed_us: set[str]) -> dict[str, int]:
    opponent_ids = set(opponents)
    return {
        "opponents": len(opponent_ids),
        "listed_opponents": sum(1 for o in opponent_ids if o in listed),
        "english_like_opponents": sum(1 for o in opponent_ids if o in listed or o in no_association),
        "confirmed_us_opponents": sum(1 for o in opponent_ids if o in confirmed_us),
    }


def qualifies(team_id: str, opponents, listed, no_association: set[str], confirmed_us: set[str]) -> bool:
    if team_id in confirmed_us:
        return False
    counts = opponent_counts(opponents, listed, no_association, confirmed_us)
    total = counts["opponents"]
    return (
        counts["listed_opponents"] >= 1
        and counts["english_like_opponents"] * 2 >= total
        and counts["confirmed_us_opponents"] * 5 < total
    )


def fetch_opponents(sb, team_ids, identity=None) -> dict[str, Counter]:
    """Games played against each opponent, for every team in team_ids, ignoring excluded games.

    `identity` resolves merges. Without it a team's games stored under an alias it absorbed are
    missed, and the same team counts as two opponents under its two ids.
    """
    identity = identity or _Identity(None)
    out: dict[str, Counter] = {t: Counter() for t in team_ids}
    ids = sorted({alias for t in team_ids for alias in identity.aliases(t)})
    for i in range(0, len(ids), ID_BATCH):
        batch = ids[i : i + ID_BATCH]
        for side, other in SIDES:
            games = _paged(
                lambda s=side, b=batch: sb.table("games")
                .select("id,home_team_master_id,away_team_master_id")
                .in_(s, b)
                .eq("is_excluded", False)
                .order("id", desc=False)
            )
            for g in games:
                team, opponent = identity.canonical(g[side]), identity.canonical(g[other])
                if opponent and opponent != team and team in out:
                    out[team][opponent] += 1
    return out


def grow(seeds: dict[str, str], load_opponents, no_association: set[str], confirmed_us: set[str]):
    """Return (evidence by listed team, games by opponent for every team whose games were read).

    Each round judges its candidates against the list as it stood when the round began, so the
    order teams are read in cannot change who joins.
    """
    listed: dict[str, dict] = {t: {"association": a} for t, a in seeds.items()}
    opponents: dict[str, Counter] = {}

    def load(team_ids):
        missing = [t for t in team_ids if t not in opponents]
        if missing:
            opponents.update(load_opponents(missing))

    load(seeds)
    frontier = set(seeds)
    round_no = 0
    while frontier:
        round_no += 1
        candidates = {o for t in listed for o in opponents.get(t, ())} - listed.keys()
        load(c for c in candidates if c not in confirmed_us)
        members = set(listed)
        joined = {c for c in candidates if qualifies(c, opponents.get(c, ()), members, no_association, confirmed_us)}
        for team_id in joined:
            listed[team_id] = {
                "round": round_no,
                **opponent_counts(opponents[team_id], members, no_association, confirmed_us),
            }
        frontier = joined
    return listed, opponents


def build_snapshot(sb, merge_resolver=None) -> dict:
    identity = _Identity(merge_resolver)
    probe_rows = _paged(
        lambda: sb.table("team_state_probe_log")
        .select("team_id_master,outcome,probed_at,reported_state_code")
        .order("id", desc=False)
    )
    for row in probe_rows:
        row["team_id_master"] = identity.canonical(row["team_id_master"])
    seeds, no_association, confirmed_us, other_unmapped = classify(latest_answers(probe_rows))
    listed, opponents = grow(
        seeds, lambda ids: fetch_opponents(sb, ids, identity), no_association, confirmed_us
    )

    ids = sorted(listed)
    teams = {
        t["team_id_master"]: t
        for t in batch_fetch_rows(
            sb, "teams", "team_id_master,team_name,club_name,state_code,is_deprecated", "team_id_master", ids
        )
    }
    ranked = {r["team_id"] for r in batch_fetch_rows(sb, "rankings_full", "team_id", "team_id", ids)}

    rows = []
    skipped = 0
    for team_id in ids:
        team = teams.get(team_id)
        if team is None or team.get("is_deprecated"):
            skipped += 1
            continue
        rows.append(
            {
                "team_id_master": team_id,
                "team_name": team.get("team_name"),
                "club_name": team.get("club_name"),
                "state_code": team.get("state_code"),
                "ranked": team_id in ranked,
                "games_against_unlisted_teams": sum(
                    n for opp, n in opponents.get(team_id, Counter()).items() if opp not in listed
                ),
                "evidence": listed[team_id],
            }
        )
    rows.sort(key=lambda r: (r["state_code"] or "", r["club_name"] or "", r["team_name"] or ""))
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "seeds": len(seeds),
        "skipped_deprecated_or_missing": skipped,
        "other_unmapped_associations": dict(other_unmapped.most_common()),
        "teams": rows,
    }


def print_summary(snapshot: dict) -> None:
    teams = snapshot["teams"]
    print(f"English league teams: {len(teams):,} ({sum(t['ranked'] for t in teams):,} ranked), "
          f"grown from {snapshot['seeds']:,} seeds; {snapshot['skipped_deprecated_or_missing']:,} "
          "deprecated or missing rows left off")
    by_state = Counter(t["state_code"] or "(none)" for t in teams)
    ranked_by_state = Counter(t["state_code"] or "(none)" for t in teams if t["ranked"])
    for state, n in by_state.most_common():
        print(f"   {state:<7} {n:>5,}  ranked {ranked_by_state[state]:>5,}")
    other = snapshot["other_unmapped_associations"]
    if other:
        print("Other associations GotSport reported, not treated as English: "
              + ", ".join(f"{a} ({n})" for a, n in other.items()))
    review = sorted((t for t in teams if t["games_against_unlisted_teams"]),
                    key=lambda t: -t["games_against_unlisted_teams"])
    print(f"Teams that also played unlisted teams — read these first: {len(review):,}")
    for t in review[:40]:
        print(f"   {t['games_against_unlisted_teams']:>3} games  {t['state_code'] or '--'}  "
              f"{t['club_name'] or ''} / {t['team_name']}")


def apply_snapshot(sb, snapshot_path: Path, out_path: Path) -> int:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    existing = {
        r["team_id_master"]
        for r in _paged(lambda: sb.table("team_ranking_exclusions").select("team_id_master").order("team_id_master"))
    }
    to_insert = [t for t in snapshot["teams"] if t["team_id_master"] not in existing]
    print(f"Snapshot teams: {len(snapshot['teams']):,}; already excluded: "
          f"{len(snapshot['teams']) - len(to_insert):,}; to exclude: {len(to_insert):,}")
    if not to_insert:
        return 0

    # ``team_ids`` is what this run wrote, so an undo cannot reach a row another run owns.
    # ``planned`` is what it set out to write, and the two differ when a run stops partway.
    log = {"applied": False, "planned": [t["team_id_master"] for t in to_insert], "team_ids": []}
    # Written before the first insert, not after the last. A failure mid-run otherwise leaves
    # teams excluded with no record of which were added by this run.
    out_path.write_text(json.dumps(log, indent=1), encoding="utf-8")

    try:
        for i in range(0, len(to_insert), ID_BATCH):
            batch = [
                {
                    "team_id_master": t["team_id_master"],
                    "reason": REASON,
                    "evidence": t["evidence"],
                    "excluded_by": ACTOR,
                }
                for t in to_insert[i : i + ID_BATCH]
            ]
            res = sb.table("team_ranking_exclusions").insert(batch).execute()
            log["team_ids"].extend(r["team_id_master"] for r in res.data or [])
    finally:
        log["applied"] = True
        out_path.write_text(json.dumps(log, indent=1), encoding="utf-8")

    print(f"\nExcluded {len(log['team_ids']):,} teams from rankings. Log: {out_path}")
    print("They leave the boards on the next ranking run. To undo: delete the team_ids in that log "
          "from team_ranking_exclusions.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", required=True,
                    help="the dry run writes its decisions here; --execute applies this file")
    ap.add_argument("--execute", action="store_true",
                    help="insert the snapshot's teams into team_ranking_exclusions (default is a dry run)")
    ap.add_argument("--out", default=None, help="where to write the rollback log")
    args = ap.parse_args()
    snapshot_path = Path(args.snapshot)

    if not args.execute:
        if snapshot_path.exists():
            raise SystemExit(f"{snapshot_path} already exists and may hold a reviewed list. Pass a new --snapshot.")
        sb = get_client()
        snapshot = build_snapshot(sb, MergeResolver(sb))
        snapshot_path.write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
        print_summary(snapshot)
        print(f"\nDRY RUN — nothing written to the database. Snapshot: {snapshot_path}")
        print("Delete every row that is not an English team, then re-run with --execute.")
        return 0

    if not snapshot_path.exists():
        raise SystemExit(f"{snapshot_path} does not exist. Run the dry run first and review its output.")
    out_path = Path(args.out) if args.out else Path(f"exclude_english_teams_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json")
    if out_path.exists():
        raise SystemExit(f"{out_path} already exists and is the only rollback record for that run. Pass a new --out.")
    return apply_snapshot(get_client(), snapshot_path, out_path)


if __name__ == "__main__":
    raise SystemExit(main())
