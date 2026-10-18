#!/usr/bin/env python3
"""Turn the owner's choices on a stage's review page into that stage's applier input.

Takes the stage's page.manifest.json, which pages.py wrote, and the page's saved choices, read back
from its `decisions-<run>` collection with the ArtifactData tool: the folder `out_dir` saved them to
(or the `decisions-<run>` folder inside it), or a JSON list of documents. Ids come only from the
manifest; a saved choice contributes its decision and a note. It refuses, rather than guessing, a
choice naming a card the page never showed, a duplicate or mislabelled document, a decision or
note of the wrong kind, finding no choices at all, and a stage whose files changed after the page
was built. A card saved with no decision (a note typed before choosing, or a choice cleared) is
undecided.

Into the stage folder it writes:

  vetted.csv / vetted.json   the applier's own input, holding only the changes the owner chose
                             Apply, and absent when there are none:
             clubs   the scoped swap snapshot's rows for them, approved
             states  the scoped snapshot cut to their decisions, keeping its rules stamp and each
                     decision's action: one the rules were unsure of stays `queue`, so the apply
                     step settles it through its review row instead of replaying it, as the
                     dashboard's State Review Queue does
             ages    the plan's rows for them
  decisions.json             every decided card's choice and note, for the apply step to record
                             before it writes anything
  collected.json             the collection: the page run, the counts and the files' hashes

With --from-db it reads the choices from the page's published cards in team_cleanup_cards instead,
the website's, taking a decision, a note and the time it was saved from each owner card. It refuses
a later build published without its files, a card of the build with no row, a row under the build's
page run that it never made, a row in the other lane, and a decision and its time not set together;
with every row there, no decision at all is a page left undecided.
That read is its only database access. Collecting again, while the run is in review and the stage is
not applied, replaces all three files; while an apply holds the run on this machine, it refuses.

With --lane auto it collects the stage's automatic lane instead, into auto/: every change the
manifest's `auto` lists, decided Apply with no choice to read, under the same three files.

    python scripts/team_cleanup/collect.py --run 2026-10-14-nv --stage states --decisions <out_dir>
    python scripts/team_cleanup/collect.py --run 2026-10-14-nv --stage states --from-db
    python scripts/team_cleanup/collect.py --run 2026-10-14-nv --stage states --lane auto
"""

from __future__ import annotations

import argparse
import shlex
import sys
from collections import Counter
from pathlib import Path

import httpx
from postgrest.exceptions import APIError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import get_client, page  # noqa: E402
from scripts.repair_swapped_club_names import write_log  # noqa: E402
from scripts.team_cleanup.decisions import APPLY, CARD_COLS, CARDS_TABLE, TEAM_DECISIONS, page_built_at  # noqa: E402
from scripts.team_cleanup.propose_week import (  # noqa: E402
    AGES,
    APPLIER_INPUTS,
    CLUBS,
    PROPOSED_STAGES,
    STATES,
    _read_csv,
)
from scripts.team_cleanup.review_page import load_choices  # noqa: E402
from scripts.team_cleanup.run_store import (  # noqa: E402
    AUTO,
    COLLECTED_MARKER,
    LANE_CARDS,
    LANES,
    MANIFEST_FILE,
    OWNER,
    PAGE_MARKER,
    ApplyLockError,
    Busy,
    RunBusy,
    file_hash,
    hold_apply_file,
    inputs_dir,
    lane_name,
    read_run,
    refused,
    reporting_busy,
    stage_due,
    store_dir,
)
from src.tournaments.storage._io import read_json, utc_now_iso, write_json  # noqa: E402

DECISIONS_FILE = "decisions.json"
VETTED = {CLUBS: "vetted.csv", STATES: "vetted.json", AGES: "vetted.csv"}
# How each lane's decisions name where they came from.
LANE_SOURCES = {OWNER: "page", AUTO: AUTO}


def check_unchanged(folder: Path) -> None:
    """Every file the page's build hashed, its manifest among them, still matches."""
    marker = read_json(folder / PAGE_MARKER)
    changed = [name for name, digest in marker["hashes"].items() if file_hash(folder / name) != digest]
    if changed:
        raise SystemExit(f"changed since the page was built: {', '.join(changed)}; rebuild the page and decide again")


def check_choices(manifest: dict, choices: dict[str, dict]) -> None:
    unknown = sorted(set(choices) - set(manifest["cards"]))
    if unknown:
        raise SystemExit(f"{len(unknown)} saved choice(s) name no card on this page: {', '.join(unknown)}")
    for card_id, choice in choices.items():
        note = choice.get("note")
        if (
            choice.get("decision") not in (*TEAM_DECISIONS, None)
            or not isinstance(note, (str, type(None)))
            or "\x00" in (note or "")
        ):
            raise SystemExit(f"saved choice {card_id} holds a decision or note the page never writes: {choice}")


def fetch_cards(sb, **match) -> list[dict]:
    """The published cards whose columns equal ``match``, ordered by card_id."""

    def query():
        built = sb.table(CARDS_TABLE).select(CARD_COLS)
        for column, value in match.items():
            built = built.eq(column, value)
        return built

    return page(query, "card_id")


def db_choices(sb, manifest: dict) -> tuple[dict[str, dict], dict[str, str]]:
    """The owner's choices on the page's published cards, and when the database saved each one. A later
    build of the page published without its files on disk is refused: the website is to show the newest
    build, so the owner may have decided that one instead."""
    run, built = manifest["run"], page_built_at(manifest)
    rows = fetch_cards(sb, run_id=manifest["cleanup_run"], stage=manifest["stage"])
    newer = sorted({row["page_run"] for row in rows if page_built_at({"run": row["page_run"]}) > built})
    if newer:
        raise SystemExit(
            f"page run {newer[-1]} of this page is published, but the page on disk is the earlier {run}: the later "
            "build's files were lost. Build and publish the page again if none of its cards is decided; decided "
            f"ones stay in {CARDS_TABLE} and need recovering by hand"
        )
    lanes = {card_id: lane for lane in LANES for card_id in manifest[LANE_CARDS[lane]]}
    found = {row["card_id"]: row for row in rows if row["page_run"] == run}
    missing, unknown = sorted(set(lanes) - set(found)), sorted(set(found) - set(lanes))
    if missing:
        raise SystemExit(
            f"{len(missing)} card(s) of page run {run} are not in {CARDS_TABLE}: {', '.join(missing[:10])}; "
            "build and publish the page again"
        )
    if unknown:
        raise SystemExit(f"{CARDS_TABLE} holds card(s) page run {run} never made: {', '.join(unknown)}")
    choices, decided = {}, {}
    for card_id, row in found.items():
        if row["lane"] != lanes[card_id]:
            raise SystemExit(
                f"card {card_id} is in the {row['lane']} lane; page run {run} built it in {lanes[card_id]}"
            )
        if (row["decision"] is None) != (row["decided_at"] is None):
            raise SystemExit(f"card {card_id} holds a decision without the time it was saved, or a time without one")
        if lanes[card_id] == OWNER and row["decision"] is not None:
            choices[card_id] = {"decision": row["decision"], "note": row["note"]}
            decided[card_id] = row["decided_at"]
    return choices, decided


def decision_rows(manifest: dict, choices: dict[str, dict], lane: str = OWNER, decided=None) -> list[dict]:
    """Every decided card, dated when ``decided`` says the database saved it, else by the page's build: a
    page's own documents carry no trustworthy time."""
    built_at, source = page_built_at(manifest), f"{LANE_SOURCES[lane]}:{manifest['run']}"
    rows = []
    for card_id, proposal in manifest[LANE_CARDS[lane]].items():
        choice = choices.get(card_id, {})
        if choice.get("decision"):
            note = (choice.get("note") or "").strip() or None
            decided_at = (decided or {}).get(card_id) or built_at
            rows.append(
                {**proposal, "decision": choice["decision"], "note": note, "decided_at": decided_at, "source": source}
            )
    return rows


def write_vetted(folder: Path, stage: str, approved: set[str]) -> Path | None:
    """The stage file's rows for the approved teams, copied as it holds them, so the applier reads
    its own escaping back. A stage proposes one change per team, so a team id names one row."""
    path, inputs = folder / VETTED[stage], inputs_dir(folder)
    path.unlink(missing_ok=True)
    if not approved:
        return None
    if stage == STATES:
        snapshot = read_json(inputs / APPLIER_INPUTS[STATES])
        decisions = [d for d in snapshot["decisions"] if d["team_id"] in approved]
        write_json(path, {**snapshot, "decisions": decisions}, indent=1)
        return path
    rows = [row for row in _read_csv(inputs / APPLIER_INPUTS[stage]) if row["team_id_master"] in approved]
    write_log([{**row, "approved": "true"} for row in rows] if stage == CLUBS else rows, path)
    return path


def collected(stage: str, lane: str) -> str:
    return lane_name(stage, AUTO) if lane == AUTO else f"the {stage} choices"


def collect(store: Path, run_id: str, stage: str, decisions: Path | None, lane: str = OWNER, sb=None) -> dict:
    """Held under the apply lock's file half, so no apply or page build on this machine acts on files a collect
    is replacing. With ``sb`` the owner's choices are read from the page's published cards."""
    try:
        with hold_apply_file(store, run_id):
            return _collect(store, run_id, stage, decisions, lane, sb)
    except RunBusy as exc:
        raise Busy(f"Cannot collect {collected(stage, lane)} for {run_id}: {exc}") from None
    except ApplyLockError as exc:
        raise SystemExit(f"Cannot collect {collected(stage, lane)} for {run_id}: {exc}") from None


def _collect(store: Path, run_id: str, stage: str, decisions: Path | None, lane: str, sb) -> dict:
    folder = stage_due(store, read_run(store, run_id), stage, ("collect", "apply"), lane)
    check_unchanged(inputs_dir(folder))
    manifest = read_json(inputs_dir(folder) / MANIFEST_FILE)
    cards, decided = manifest[LANE_CARDS[lane]], None
    if lane == AUTO:
        choices = {card_id: {"decision": APPLY} for card_id in cards}
    elif sb is not None:
        choices, decided = db_choices(sb, manifest)
        check_choices(manifest, choices)
    else:
        choices = load_choices(decisions, manifest["run"]) if cards else {}
        if cards and not choices:
            raise SystemExit("no saved choices were found: check the folder or file passed as --decisions")
        check_choices(manifest, choices)

    rows = decision_rows(manifest, choices, lane, decided)
    approved = {row["team_id_master"] for row in rows if row["decision"] == APPLY}
    folder.mkdir(exist_ok=True)
    vetted = write_vetted(folder, stage, approved)
    write_json(folder / DECISIONS_FILE, rows, indent=1)
    counts = Counter(row["decision"] for row in rows)
    marker = {
        "run": manifest["run"],
        "collected_at": utc_now_iso(),
        "counts": {**{d: counts[d] for d in TEAM_DECISIONS}, "undecided": len(cards) - len(rows)},
        "vetted": vetted.name if vetted else None,
        "hashes": {path.name: file_hash(path) for path in (vetted, folder / DECISIONS_FILE) if path},
    }
    write_json(folder / COLLECTED_MARKER, marker, indent=1)
    return {"folder": folder, "marker": marker, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="The run id, e.g. 2026-10-14-nv")
    ap.add_argument("--stage", required=True, choices=PROPOSED_STAGES)
    ap.add_argument("--lane", choices=LANES, default=OWNER, help="The owner's choices, or the automatic lane")
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--decisions", type=Path, help="The out_dir folder, or a JSON list of documents")
    source.add_argument("--from-db", action="store_true", help=f"Read the choices from {CARDS_TABLE} instead")
    ap.add_argument(
        "--store",
        type=Path,
        help="The run store, absolute (default: PITCHRANK_CLEANUP_DIR, else ~/pitchrank-cleanup-runs)",
    )
    args = ap.parse_args()
    if (args.lane == OWNER) != (args.decisions is not None or args.from_db):
        ap.error("the owner's lane takes --decisions or --from-db, and the automatic lane neither")
    what = f"Cannot collect {collected(args.stage, args.lane)} for {args.run}"
    with reporting_busy():
        try:
            sb = get_client() if args.from_db else None
            result = collect(store_dir(args.store), args.run, args.stage, args.decisions, args.lane, sb)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"{what}: {exc}") from None
        except (APIError, httpx.HTTPError) as exc:
            raise SystemExit(refused(what, exc, shlex.join(["python", *sys.argv]))) from None
    folder, marker = result["folder"], result["marker"]
    print(f"page run {marker['run']}:")
    for decision, count in marker["counts"].items():
        print(f"  {decision:<10} {count}")
    for row in result["rows"]:
        if row["decision"] != APPLY or row["note"]:
            note = f"  note: {row['note']!r}" if row["note"] else ""
            print(f"    {row['decision']:<10} {row['team_name']!r}: {row['old_value']!r} -> {row['new_value']!r}{note}")
    print(f"wrote {folder / marker['vetted']}" if marker["vetted"] else "nothing to apply")
    print(f"wrote {folder / DECISIONS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
