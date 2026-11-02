#!/usr/bin/env python3
"""Undo one card's change from a cleanup run: the one team, or the one merge, an applied lane changed for it.

It finds the card in its stage's page.manifest.json, the owner's cards or the automatic lane's, and the
change the lane's decisions.json applied for it, which team_cleanup_changes must hold unreverted. It then puts
that change back the way the lane's own revert would, for that one team:

  clubs, ages  the applier's own --revert of a copy of the batch's log holding only the team's rows
  merges       the exclusion's own --revert of a copy of each log it wrote over the batch, holding only the
               games naming the retired row and the copies the trigger hid with them, then the merge applier's
               --revert of a copy of the batch's merge log holding only this merge
  states       revert_team_states over each of the lane's windows holding the team's own writes, read from
               just before the team's id with a page of one, after a dry run of the same call names this team

The copies are written under <lane>/undo/<card>/, never beside the applier's own logs in the exports folder,
which the lane's revert reads. It then checks the database holds the old value again, stamps reverted_at on
the change in team_cleanup_changes, and with --decline records Don't apply (Keep separate for a pair) under
source undo:<card>, so the change is not proposed again, before the stamp, so a retry can still find the change
and record it. Each undo is added to the lane's REVERT.md. While the run is open and the lane has not finished
applying, a change it has not applied yet waits (exit 75) rather than being refused.

Like the lane's revert it refuses what that revert would refuse, holds the run's apply lease (a closed run's
file lock alone), and runs --execute only inside the apply window unless --outside-window. A dry run, the
default, says what it would do and writes nothing.

    python scripts/team_cleanup/undo_card.py --run 2026-11-04-all --card <card id>
    python scripts/team_cleanup/undo_card.py --run 2026-11-04-all --card <card id> --decline --execute
"""

from __future__ import annotations

import argparse
import csv
import io
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
from postgrest.exceptions import APIError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.apply_vetted_team_merges import read_log as read_merge_log  # noqa: E402
from scripts.exclude_none_opponent_games import cascade_key  # noqa: E402
from scripts.find_cross_provider_duplicates import get_client  # noqa: E402
from scripts.team_cleanup.apply_stage import (  # noqa: E402
    REVERT_FILE,
    NotYet,
    _same,
    actor_for,
    check_other_writers,
    check_window,
    exclude_revert_command,
    keep_lease,
    own_log,
    plan_decisions,
    record_decisions,
    revert_command,
    revert_refusal,
    stamp_reverted,
    state_audit,
    state_owner,
    state_windows,
)
from scripts.team_cleanup.collect import DECISIONS_FILE  # noqa: E402
from scripts.team_cleanup.decisions import (  # noqa: E402
    APPLY,
    CHANGES_TABLE,
    DONT_APPLY,
    MERGES,
    UNDO_SOURCE,
    resolve_execute,
)
from scripts.team_cleanup.pairs import as_chosen  # noqa: E402
from scripts.team_cleanup.propose_week import FIELDS, LOGS, PROPOSED_STAGES, STATES, run_step  # noqa: E402
from scripts.team_cleanup.review_page import fetch_teams  # noqa: E402
from scripts.team_cleanup.run_store import (  # noqa: E402
    APPLY_MARKER,
    LANE_CARDS,
    LANES,
    MANIFEST_FILE,
    OPEN_STATUSES,
    ApplyLockError,
    Busy,
    RunBusy,
    acquire_apply_lock,
    hold_apply_file,
    lane_dir,
    lane_name,
    read_progress,
    read_run,
    refused,
    reporting_busy,
    stage_dir,
    store_dir,
)
from src.tournaments.storage._io import read_json, utc_now_iso, write_json  # noqa: E402

UNDO_SCRIPT = "scripts/team_cleanup/undo_card.py"
UNDO_DIR = "undo"
UNDONE_NOTE = "undone from the review page"


@dataclass(frozen=True)
class Change:
    """A card's applied change: the team it changed (for a merge, the retired row) and, for a merge, the kept
    one; the decisions.json row that applied it; and its unreverted team_cleanup_changes row."""

    stage: str
    lane: str
    card_id: str
    team: str
    kept: str | None
    decision: dict
    ledger: dict


def find_card(store: Path, run_id: str, card_id: str) -> tuple[str, str, dict]:
    """(stage, lane, proposal) of a card on one of the run's pages."""
    for stage in PROPOSED_STAGES:
        path = stage_dir(store, run_id, stage) / MANIFEST_FILE
        if not path.exists():
            continue
        manifest = read_json(path)
        for lane in LANES:
            proposal = manifest[LANE_CARDS[lane]].get(card_id)
            if proposal is not None:
                return stage, lane, proposal
    raise ValueError(f"card {card_id} is on none of run {run_id}'s pages")


def card_change(sb, store: Path, run_id: str, card_id: str) -> Change:
    """The card's applied change, refused when its lane changed nothing for it or the change is undone. While the
    run is open and the lane has not finished applying, a change not applied yet waits for it (Busy)."""
    stage, lane, proposal = find_card(store, run_id, card_id)
    folder = lane_dir(store, run_id, stage, lane)
    waits = read_run(store, run_id)["status"] in OPEN_STATUSES and not (folder / APPLY_MARKER).exists()

    def not_yet(why: str) -> Exception:
        return (
            Busy(f"card {card_id} waits until {lane_name(stage, lane)} has applied it: {why}")
            if waits
            else ValueError(why)
        )

    if not (folder / DECISIONS_FILE).exists():
        raise not_yet(f"{lane_name(stage, lane)} has collected no choices, so card {card_id} changed nothing yet")
    if stage == MERGES:
        key = (proposal["merge_id"], proposal["keep_id"])
        rows = [r for r in read_json(folder / DECISIONS_FILE) if (r["merge_id"], r["keep_id"]) == key]
    else:
        key = (proposal["team_id_master"], proposal["new_value"])
        rows = [r for r in read_json(folder / DECISIONS_FILE) if (r["team_id_master"], r["new_value"]) == key]
    if not rows or rows[0]["decision"] != APPLY:
        decided = rows[0]["decision"] if rows else "undecided"
        raise ValueError(f"card {card_id} was decided {decided}, so its lane changed nothing for it")
    row = rows[0]
    if stage == MERGES:
        chosen = as_chosen(row)
        team, kept, new_value = chosen["merge_id"], chosen["keep_id"], chosen["keep_id"]
    else:
        team, kept, new_value = row["team_id_master"], None, row["new_value"]
    ledger = (
        sb.table(CHANGES_TABLE)
        .select("id,team_id_master,field,old_value,new_value,log_file")
        .eq("run_id", run_id)
        .eq("stage", stage)
        .eq("team_id_master", team)
        .eq("new_value", new_value)
        .is_("reverted_at", "null")
        .execute()
        .data
    )
    if not ledger:
        raise not_yet(
            f"team_cleanup_changes holds no change of card {card_id} still in place: none was applied, or it is undone"
        )
    return Change(stage, lane, card_id, team, kept, row, ledger[0])


# --- the copies the appliers' own reverts replay --------------------------------------------------------


def team_rows_csv(log: Path, team: str) -> tuple[str, int]:
    """The batch log with only the team's rows, as text in the log's own encoding, and how many it holds."""
    raw = log.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
    column = rows[0].index("team_id_master")
    kept = [rows[0], *(row for row in rows[1:] if row and row[column] == team)]
    out = io.StringIO()
    csv.writer(out).writerows(kept)
    return ("﻿" if bom else "") + out.getvalue(), len(kept) - 1


def pair_exclusions(logged: dict, retired: str) -> dict:
    """An exclusion log cut to the games naming the retired row that its run reached, with the later copies
    the trigger hid along with them, as its own --revert reads it."""
    sent = logged.get("sent", logged.get("confirmed")) or 0
    rows = logged["rows"]
    reached = [row for row in rows[:sent] if retired in (row["home_team_master_id"], row["away_team_master_id"])]
    keys = {_cascade(row) for row in reached} - {None}
    twins = [row for row in rows[sent:] if _cascade(row) in keys]
    trimmed = {key: value for key, value in logged.items() if key != "reverted_at"}
    return {**trimmed, "rows": reached + twins, "sent": len(reached), "confirmed": len(reached)}


def _cascade(row: dict):
    home, away = (int(score) for score in row["score"].split("-"))
    return cascade_key({**row, "home_score": home, "away_score": away})


def replays(change: Change, store: Path, run_id: str, progress: dict, execute: bool) -> list[tuple]:
    """(what, command, its output log) of each applier's own revert the undo runs, in order, writing the copies
    they replay under <lane>/undo/<card>/ when ``execute``."""
    folder = lane_dir(store, run_id, change.stage, change.lane)
    undo = folder / UNDO_DIR / change.card_id
    if execute:
        undo.mkdir(parents=True, exist_ok=True)
    steps = []
    for batch in reversed(progress["batches"]):
        log = own_log(change.stage, batch, run_id)
        if not log:
            continue
        if change.stage == MERGES:
            entries = [e for e in read_merge_log(Path(log)) if e["merge_id"] == change.team]
            if not entries:
                continue
            for step in reversed(batch.get("excludes", [])):
                if not Path(step["log"]).exists():
                    continue
                cut = pair_exclusions(read_json(Path(step["log"])), change.team)
                if not cut["rows"]:
                    continue
                copy = undo / Path(step["log"]).name
                if execute:
                    write_json(copy, cut, indent=1)
                steps.append(("the games it hid", exclude_revert_command(str(copy), execute), copy))
            copy = undo / Path(log).name
            if execute:
                write_json(copy, entries, indent=1)
            steps.append(("the merge", revert_command(MERGES, str(copy), execute), copy))
        else:
            text, count = team_rows_csv(Path(log), change.team)
            if not count:
                continue
            copy = undo / Path(log).name
            if execute:
                copy.write_text(text, encoding="utf-8", newline="")
            steps.append((f"the {batch['batch']} batch", revert_command(change.stage, str(copy), execute), copy))
    if not steps:
        raise ValueError(f"no batch log of {lane_name(change.stage, change.lane)} holds card {change.card_id}'s team")
    return [(what, command, undo / LOGS / f"{Path(copy).stem}.log") for what, command, copy in steps]


# --- states ---------------------------------------------------------------------------------------------


def _before(team: str) -> str:
    """The uuid just short of ``team``'s, from which revert_team_states' keyset page of one starts at the team."""
    return str(uuid.UUID(int=uuid.UUID(team).int - 1))


def state_windows_of(sb, run_id: str, progress: dict, team: str) -> list[tuple[str, tuple[str, str], str]]:
    """The lane's state windows holding the team's own writes, newest first. The lane's revert refusal has
    already refused windows holding another writer's write."""
    own = state_owner(progress)
    return [
        (actor, window, label)
        for actor, window, label in reversed(state_windows(run_id, progress))
        if any(row["team_id_master"] == team and own(row) for row in state_audit(sb, actor, window))
    ]


def revert_state(sb, run_id: str, team: str, actor: str, window: tuple[str, str], label: str) -> int:
    """revert_team_states over one window for the one team: a dry run first, refused unless it names the team."""
    params = {
        "p_applied_by": actor,
        "p_applied_after": window[0],
        "p_applied_before": window[1],
        "p_reverted_by": f"{actor_for(run_id)}:revert",
        "p_after": _before(team),
        "p_batch_size": 1,
        "p_revert_reason": f"undo {actor_for(run_id)} states, one card, {label}",
    }
    preview = (sb.rpc("revert_team_states", {**params, "p_dry_run": True}).execute().data or [{}])[0]
    if preview.get("last_team_id") != team:
        raise ValueError(
            f"revert_team_states over the {label} window would put back {preview.get('last_team_id')}, not {team}"
        )
    found = (sb.rpc("revert_team_states", {**params, "p_dry_run": False}).execute().data or [{}])[0]
    return found.get("rows_changed") or 0


# --- the undo -------------------------------------------------------------------------------------------


def back(sb, change: Change) -> bool:
    team = fetch_teams(sb, [change.team]).get(change.team)
    if team is None:
        return False
    if change.stage == MERGES:
        return not team["is_deprecated"]
    return _same(FIELDS[change.stage], team[FIELDS[change.stage]], change.ledger["old_value"])


def declined_decision(sb, change: Change) -> list:
    """Don't apply (Keep separate for a pair) on the change, so it is not proposed again, planned against the
    active decisions: refused when a later decision is already recorded."""
    row = {**change.decision, "decision": DONT_APPLY, "note": UNDONE_NOTE}
    row.update({"decided_at": utc_now_iso(), "source": f"{UNDO_SOURCE}{change.card_id}"})
    return plan_decisions(sb, change.stage, [row])


def declined_name(stage: str) -> str:
    return "Keep separate" if stage == MERGES else "Don't apply"


def undo_card(sb, store: Path, run_id: str, card_id: str, declined: bool, outside_window: bool, retry: str) -> None:
    change = card_change(sb, store, run_id, card_id)
    folder = lane_dir(store, run_id, change.stage, change.lane)
    progress = read_progress(folder)
    open_run = read_run(store, run_id)["status"] in OPEN_STATUSES
    hold = acquire_apply_lock(sb, store, run_id) if open_run else hold_apply_file(store, run_id)
    planned = declined_decision(sb, change) if declined else []
    with hold as holder:
        check_other_writers()
        lines = [f"## Undo of card {card_id} ({change.team}), {utc_now_iso()}", ""]

        def before(step: int, what: str) -> None:
            if step:
                check_window(outside_window)
                check_other_writers()
            keep_lease(sb, run_id, holder, f"the undo of {what} was not run", retry)

        try:
            refusal = revert_refusal(sb, store, folder, run_id, change.stage, progress)
            if refusal:
                lines.append(f"Refused. {refusal}")
                raise Busy(refusal) if isinstance(refusal, NotYet) else SystemExit(refusal)
            if change.stage == STATES:
                for step, (actor, window, label) in enumerate(state_windows_of(sb, run_id, progress, change.team)):
                    before(step, label)
                    count = revert_state(sb, run_id, change.team, actor, window, label)
                    lines.append(f"- {label}: revert_team_states put back {count}")
                    print(lines[-1][2:])
            else:
                for step, (what, command, output) in enumerate(replays(change, store, run_id, progress, True)):
                    before(step, what)
                    code = run_step(command, output)
                    lines.append(f"- {what}: {command[0]} --revert {command[2]} exited {code}; see {output}")
                    print(lines[-1][2:])
                    if code != 0:
                        raise SystemExit(f"Stopped: the undo of {what} exited {code}; see {output}")
            if not back(sb, change):
                lines.append("Stopped: the database does not hold the old value again.")
                raise SystemExit(
                    f"Stopped: card {card_id}'s team does not hold its old value again; something changed it since"
                )
            # The stamp comes last: a retry finds the change by its unstamped row, so a lost decline is recorded then.
            if declined:
                record_decisions(sb, planned, retry)
                lines.append(f"Recorded {declined_name(change.stage)} under {UNDO_SOURCE}{card_id}.")
                print(lines[-1])
            stamped, _ = stamp_reverted(sb, run_id, change.stage, {change.team})
            lines.append(f"Stamped reverted_at on {stamped} ledger row(s).")
            print(lines[-1])
        except (APIError, httpx.HTTPError) as exc:
            lines.append(f"Stopped: {exc}")
            raise SystemExit(refused(f"Could not finish undoing card {card_id}", exc, retry)) from None
        finally:
            with (folder / REVERT_FILE).open("a", encoding="utf-8") as record:
                record.write("\n".join(lines) + "\n\n")


def dry_run(sb, store: Path, run_id: str, card_id: str, declined: bool) -> None:
    change = card_change(sb, store, run_id, card_id)
    folder = lane_dir(store, run_id, change.stage, change.lane)
    progress = read_progress(folder)
    print(f"DRY RUN -- would undo card {card_id} of {lane_name(change.stage, change.lane)}, team {change.team}:")
    if change.stage == STATES:
        for _, window, label in state_windows_of(sb, run_id, progress, change.team):
            print(f"  {label}: revert_team_states over {window[0]} to {window[1]}, for this team alone")
    else:
        for what, command, _ in replays(change, store, run_id, progress, False):
            print(f"  {what}: python {subprocess.list2cmdline(command)}")
    refusal = revert_refusal(sb, store, folder, run_id, change.stage, progress)
    if refusal:
        print(f"It would refuse. {refusal}")
        return
    if declined:
        declined_decision(sb, change)
        print(f"Then it records {declined_name(change.stage)} and stamps reverted_at on the change.")
    else:
        print("Then it stamps reverted_at on the change.")
    print("Re-run with --execute to undo it.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True, help="The run id, e.g. 2026-11-04-all")
    parser.add_argument("--card", required=True, help="The card id, as team_cleanup_cards holds it")
    parser.add_argument("--decline", action="store_true", help="Also record the change as not to propose again")
    parser.add_argument("--execute", action="store_true", help="Write to the database (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Force a dry run; wins over --execute")
    parser.add_argument("--outside-window", action="store_true", help="Run --execute outside the apply window")
    parser.add_argument(
        "--store",
        type=Path,
        help="The run store, absolute (default: PITCHRANK_CLEANUP_DIR, else ~/pitchrank-cleanup-runs)",
    )
    args = parser.parse_args()
    with reporting_busy():
        return run_command(args)


def run_command(args: argparse.Namespace) -> int:
    execute = resolve_execute(args.execute, args.dry_run)
    what = f"undo card {args.card} of {args.run}"
    command = [UNDO_SCRIPT, "--run", args.run, "--card", args.card, *(["--decline"] if args.decline else [])]
    retry = f"python {subprocess.list2cmdline([*command, *(['--execute'] if execute else [])])}"
    try:
        store = store_dir(args.store)
        if execute:
            check_window(args.outside_window)
        sb = get_client()
        if execute:
            undo_card(sb, store, args.run, args.card, args.decline, args.outside_window, retry)
        else:
            dry_run(sb, store, args.run, args.card, args.decline)
    except RunBusy as exc:
        raise Busy(f"Cannot {what}: {exc}") from None
    except ApplyLockError as exc:
        raise SystemExit(f"Cannot {what}: {exc}") from None
    except (APIError, httpx.HTTPError) as exc:
        raise SystemExit(refused(f"Cannot {what}", exc, retry)) from None
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Cannot {what}: {exc}") from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
