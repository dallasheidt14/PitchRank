#!/usr/bin/env python3
"""Link or create one age group's EA teams in PitchRank. Dry run unless --execute.

Reads step 1's ``teams.csv`` and ``match_report.csv``: a confident team is linked to its
one candidate, a no-match team is created, and a review team is held until a pick for it
arrives through ``--decisions`` (``provider_team_id,your_pick`` with a team id, ``new`` or
``skip``). This is the only thing that writes ``modular11_ea`` aliases or creates EA
teams; the game import only follows the aliases written here.

Every run writes ``link_plan.csv`` and the hand-back spreadsheet (``handback.csv`` plus
``handback_legend.txt``). An executed run also logs each write to
``link_log_<UTC>.jsonl``, which ``--undo`` reverses.

Usage:
    python scripts/link_modular11_ea_teams.py --age u17
    python scripts/link_modular11_ea_teams.py --age u17 --execute
    python scripts/link_modular11_ea_teams.py --age u17 --undo data/modular11_ea/u17/link_log_<UTC>.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from postgrest.exceptions import APIError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.migrate_modular11_ea_season_keys import refuse_unmigrated  # noqa: E402
from src.models.modular11_ea_keys import club_state, ea_key  # noqa: E402
from src.models.modular11_ea_matcher import PROVIDER_CODE  # noqa: E402
from src.tournaments.alias_writer import upsert_team_alias  # noqa: E402
from src.utils.team_name_utils import resolve_distinction  # noqa: E402
from src.utils.us_states import STATE_CODE_TO_NAME  # noqa: E402
from supabase import create_client  # noqa: E402

ALIAS_CONFIDENCE = {"direct_id": 1.0, "fuzzy_auto": 0.95, "manual": 1.0}
WRITTEN = ("created", "updated")
HANDBACK_COLUMNS = [
    "provider_team_id",
    "ea_team_name",
    "club",
    "status",
    "pitchrank_team_id",
    "candidates",
    "your_pick",
]


@dataclass(frozen=True)
class LinkAction:
    provider_team_id: str
    key: str
    action: str
    team_id_master: str
    match_method: str
    display_name: str
    club_name: str
    age_group: str
    state_code: str
    reason: str


def plan_links(teams: list[dict], report: list[dict], decisions: dict[str, str]) -> list[LinkAction]:
    by_id = {r["provider_team_id"]: r for r in report}
    plan = []
    for team in teams:
        tid = team["provider_team_id"]
        row = by_id.get(tid, {"bucket": "no_match", "candidate_ids": ""})
        pick = (decisions.get(tid) or "").strip()
        base = {
            "provider_team_id": tid,
            "key": ea_key(tid, int(team["season"])),
            "display_name": team["display_name"],
            "club_name": team["club_name"],
            "age_group": team["age_group"],
            "state_code": club_state(team["club_name"]),
        }
        if pick.lower() == "skip":
            step = ("hold", "", "", "your pick: skip")
        elif pick.lower() == "new":
            step = ("create", "", "direct_id", "your pick: new")
        elif pick:
            step = ("link", pick, "manual", "your pick")
        elif row["bucket"] == "confident":
            step = ("link", row["candidate_ids"], "fuzzy_auto", "confident")
        elif row["bucket"] == "no_match":
            step = ("create", "", "direct_id", "no match")
        else:
            step = ("hold", "", "", "needs review")
        action, team_id_master, match_method, reason = step
        plan.append(
            LinkAction(**base, action=action, team_id_master=team_id_master, match_method=match_method, reason=reason)
        )
    return plan


def _existing_team(sb, provider_id: str, provider_team_id: str) -> str | None:
    try:
        row = (
            sb.table("teams")
            .select("team_id_master")
            .eq("provider_id", provider_id)
            .eq("provider_team_id", provider_team_id)
            .single()
            .execute()
        )
    except APIError as exc:
        if exc.code == "PGRST116":
            return None
        raise
    return row.data["team_id_master"]


def _create_team(sb, provider_id: str, action: LinkAction) -> str:
    team_id_master = str(uuid.uuid4())
    sb.table("teams").insert(
        {
            "team_id_master": team_id_master,
            "team_name": action.display_name,
            "club_name": action.club_name,
            "age_group": action.age_group,
            "gender": "Male",
            "state_code": action.state_code,
            "state": STATE_CODE_TO_NAME[action.state_code],
            "provider_id": provider_id,
            "provider_team_id": action.key,
            "distinction": resolve_distinction(action.display_name, action.club_name, None),
        }
    ).execute()
    return team_id_master


def _linked_team(sb, provider_id: str, provider_team_id: str) -> str | None:
    rows = (
        sb.table("team_alias_map")
        .select("team_id_master")
        .eq("provider_id", provider_id)
        .eq("provider_team_id", provider_team_id)
        .eq("review_status", "approved")
        .limit(1)
        .execute()
        .data
    )
    return rows[0]["team_id_master"] if rows else None


def _usable_target(sb, team_id_master: str, age_group: str) -> bool:
    """The game import rejects a link whose team is in another age or gender; refuse it here instead."""
    try:
        team = (
            sb.table("teams")
            .select("age_group, gender, is_deprecated")
            .eq("team_id_master", team_id_master)
            .single()
            .execute()
            .data
        )
    except APIError as exc:
        if exc.code == "PGRST116":
            return False
        raise
    return (
        (team.get("age_group") or "").lower() == age_group.lower()
        and team.get("gender") == "Male"
        and team.get("is_deprecated") is not True
    )


def apply_plan(sb, provider_id: str, plan: list[LinkAction], log_path: Path) -> tuple[dict[str, int], dict[str, str]]:
    """Returns the counts and ``{provider_team_id: team_id_master}`` for teams created this run.

    An EA team that already has an approved alias is never re-pointed here: a create reuses
    it silently, and a link to a different team is reported as needing a merge.
    """
    counts = {
        "teams_created": 0,
        "teams_reused": 0,
        "aliases_written": 0,
        "conflicts": 0,
        "held": 0,
        "already_linked": 0,
        "needs_merge": 0,
        "links_rejected": 0,
    }
    refuse_unmigrated(sb, provider_id)
    created: dict[str, str] = {}
    with log_path.open("a", encoding="utf-8") as log:
        for action in plan:
            if action.action == "hold":
                counts["held"] += 1
                continue
            linked = _linked_team(sb, provider_id, action.key)
            target = action.team_id_master
            if action.action == "link":
                if linked and linked != target:
                    counts["needs_merge"] += 1
                    print(f"EA team {action.provider_team_id} is already linked to {linked}; merge it into {target}")
                    continue
                if not _usable_target(sb, target, action.age_group):
                    counts["links_rejected"] += 1
                    print(f"EA team {action.provider_team_id}: {target} is missing, deprecated or another age/gender")
                    continue
            if action.action == "create":
                if linked:
                    counts["already_linked"] += 1
                    continue
                target = _existing_team(sb, provider_id, action.key)
                if target:
                    counts["teams_reused"] += 1
                else:
                    target = _create_team(sb, provider_id, action)
                    created[action.provider_team_id] = target
                    counts["teams_created"] += 1
                    log.write(json.dumps({"kind": "team", "team_id_master": target}) + "\n")
            confidence = ALIAS_CONFIDENCE[action.match_method]
            result = upsert_team_alias(
                sb,
                provider_uuid=provider_id,
                provider_team_id=action.key,
                team_id_master=target,
                provider_team_name=action.display_name,
                confidence=confidence,
                match_method=action.match_method,
                priority_score=confidence,
            )
            outcome = result.get("action")
            if outcome in WRITTEN:
                counts["aliases_written"] += 1
            else:
                counts["conflicts"] += 1
                print(f"Alias for EA team {action.provider_team_id} not written: {result}")
            log.write(
                json.dumps(
                    {
                        "kind": "alias",
                        "provider_team_id": action.key,
                        "team_id_master": target,
                        "result": outcome,
                    }
                )
                + "\n"
            )
    return counts, created


def _game_count(sb, team_id_master: str) -> int:
    total = 0
    for column in ("home_team_master_id", "away_team_master_id"):
        result = sb.table("games").select("id", count="exact").eq(column, team_id_master).limit(1).execute()
        total += result.count or 0
    return total


def undo(sb, provider_id: str, log_path: Path) -> dict[str, int]:
    """Removes the aliases a run created, then the teams it created that no game references."""
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    counts = {"aliases_removed": 0, "teams_removed": 0, "teams_refused": 0}
    for entry in entries:
        if entry["kind"] == "alias" and entry["result"] == "created":
            removed = (
                sb.table("team_alias_map")
                .delete()
                .eq("provider_id", provider_id)
                .eq("provider_team_id", entry["provider_team_id"])
                .eq("team_id_master", entry["team_id_master"])
                .execute()
            )
            counts["aliases_removed"] += len(removed.data or [])
    for entry in entries:
        if entry["kind"] != "team":
            continue
        if _game_count(sb, entry["team_id_master"]):
            counts["teams_refused"] += 1
            print(f"Kept team {entry['team_id_master']}: games already reference it")
            continue
        sb.table("teams").delete().eq("team_id_master", entry["team_id_master"]).execute()
        counts["teams_removed"] += 1
    return counts


def _candidates(row: dict) -> str:
    ids = [i for i in row.get("candidate_ids", "").split("|") if i]
    names = row.get("candidate_names", "").split("|")
    return " | ".join(f"{name} ({cid})" for name, cid in zip(names, ids))


def write_handback(
    path: Path, plan: list[LinkAction], report: list[dict], created: dict[str, str], dry_run: bool = False
) -> None:
    by_id = {r["provider_team_id"]: r for r in report}
    rows = []
    for action in plan:
        if action.action == "create":
            status = "would create" if dry_run else "created"
            rows.append(
                {
                    "provider_team_id": action.provider_team_id,
                    "ea_team_name": action.display_name,
                    "club": action.club_name,
                    "status": status,
                    "pitchrank_team_id": created.get(action.provider_team_id, ""),
                    "candidates": "",
                    "your_pick": "",
                }
            )
        elif action.action == "hold":
            rows.append(
                {
                    "provider_team_id": action.provider_team_id,
                    "ea_team_name": action.display_name,
                    "club": action.club_name,
                    "status": "needs review",
                    "pitchrank_team_id": "",
                    "candidates": _candidates(by_id.get(action.provider_team_id, {})),
                    "your_pick": "",
                }
            )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HANDBACK_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    examples = {}
    for row in rows:
        examples.setdefault(row["status"], row)
    lines = [
        "How to fill in handback.csv",
        "",
        "One row per EA team that was created (or would be) or still needs review.",
        "Fill in only the your_pick column, then send the file back. Leave it empty to decide later.",
        "",
        "Created rows (status 'created' or 'would create'):",
        "  These are new PitchRank teams. If one already exists in PitchRank under another name,",
        "  put that team's id in your_pick and the two will be merged by hand.",
        "",
        "Needs review rows (status 'needs review'): their games stay out until you pick.",
        "  - a PitchRank team id (from the candidates column or your own search): this EA team IS that team",
        "  - new: create it as its own new team",
        "  - skip: leave it out (it stays out until a run that uses your sheet)",
        "",
        "Example rows from this run:",
    ]
    for status, row in examples.items():
        lines.append(f"  [{status}] {row['ea_team_name']} ({row['club']}) candidates: {row['candidates'] or 'none'}")
    path.with_name("handback_legend.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _new_client():
    load_dotenv()
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("ERROR: missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def _provider_id(sb) -> str:
    try:
        return sb.table("providers").select("id").eq("code", PROVIDER_CODE).single().execute().data["id"]
    except APIError as exc:
        raise SystemExit(f"ERROR: provider {PROVIDER_CODE!r} is missing; apply migration 20261005120000 first") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--age", required=True)
    parser.add_argument("--in-dir", type=Path, default=Path("data/modular11_ea"))
    parser.add_argument("--decisions", type=Path, help="CSV with provider_team_id,your_pick")
    parser.add_argument("--execute", action="store_true", help="write links and new teams")
    parser.add_argument("--undo", type=Path, help="reverse the writes logged in this file")
    args = parser.parse_args(argv)
    age_dir = args.in_dir / args.age

    if args.undo:
        sb = _new_client()
        counts = undo(sb, _provider_id(sb), args.undo)
        print(" ".join(f"{k}={v}" for k, v in counts.items()))
        return 0

    report = _read_csv(age_dir / "match_report.csv")
    decisions = {}
    if args.decisions:
        decisions = {r["provider_team_id"]: r.get("your_pick", "") for r in _read_csv(args.decisions)}
    plan = plan_links(_read_csv(age_dir / "teams.csv"), report, decisions)
    with (age_dir / "link_plan.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(LinkAction.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(a) for a in plan)

    created: dict[str, str] = {}
    if args.execute:
        sb = _new_client()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path = age_dir / f"link_log_{stamp}.jsonl"
        counts, created = apply_plan(sb, _provider_id(sb), plan, log_path)
        print(" ".join(f"{k}={v}" for k, v in counts.items()))
        print(f"Undo with: --undo {log_path}")
    else:
        actions = [a.action for a in plan]
        print(f"link={actions.count('link')} create={actions.count('create')} hold={actions.count('hold')}")
        print("DRY RUN — nothing written")
    write_handback(age_dir / "handback.csv", plan, report, created, dry_run=not args.execute)
    return 0


if __name__ == "__main__":
    sys.exit(main())
