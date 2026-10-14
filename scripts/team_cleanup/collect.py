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

It never touches the database. Collecting again, while the run is in review and the stage is not
applied, replaces all three; while an apply holds the run on this machine, it refuses.

    python scripts/team_cleanup/collect.py --run 2026-10-14-nv --stage states --decisions <out_dir>
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.repair_swapped_club_names import write_log  # noqa: E402
from scripts.team_cleanup.decisions import APPLY, TEAM_DECISIONS, page_built_at  # noqa: E402
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
    COLLECTED_MARKER,
    MANIFEST_FILE,
    PAGE_MARKER,
    ApplyLockError,
    file_hash,
    hold_apply_file,
    read_run,
    stage_due,
    store_dir,
)
from src.tournaments.storage._io import read_json, utc_now_iso, write_json  # noqa: E402

DECISIONS_FILE = "decisions.json"
VETTED = {CLUBS: "vetted.csv", STATES: "vetted.json", AGES: "vetted.csv"}


def check_unchanged(folder: Path) -> None:
    """Every file the page's build hashed, its manifest among them, still matches."""
    marker = read_json(folder / PAGE_MARKER)
    changed = [name for name, digest in marker["hashes"].items() if file_hash(folder / name) != digest]
    if changed:
        raise SystemExit(f"changed since the page was built: {', '.join(changed)}; rebuild the page and decide again")


def check_choices(manifest: dict, choices: dict[str, dict]) -> None:
    if manifest["cards"] and not choices:
        raise SystemExit("no saved choices were found: check the folder or file passed as --decisions")
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


def decision_rows(manifest: dict, choices: dict[str, dict]) -> list[dict]:
    """Every decided card, dated by the page's build: a page's documents carry no trustworthy time
    of their own."""
    decided_at, source = page_built_at(manifest), f"page:{manifest['run']}"
    rows = []
    for card_id, proposal in manifest["cards"].items():
        choice = choices.get(card_id, {})
        if choice.get("decision"):
            note = (choice.get("note") or "").strip() or None
            rows.append(
                {**proposal, "decision": choice["decision"], "note": note, "decided_at": decided_at, "source": source}
            )
    return rows


def write_vetted(folder: Path, stage: str, approved: set[str]) -> Path | None:
    """The stage file's rows for the approved teams, copied as it holds them, so the applier reads
    its own escaping back. A stage proposes one change per team, so a team id names one row."""
    path = folder / VETTED[stage]
    path.unlink(missing_ok=True)
    if not approved:
        return None
    if stage == STATES:
        snapshot = read_json(folder / APPLIER_INPUTS[STATES])
        decisions = [d for d in snapshot["decisions"] if d["team_id"] in approved]
        write_json(path, {**snapshot, "decisions": decisions}, indent=1)
        return path
    rows = [row for row in _read_csv(folder / APPLIER_INPUTS[stage]) if row["team_id_master"] in approved]
    write_log([{**row, "approved": "true"} for row in rows] if stage == CLUBS else rows, path)
    return path


def collect(store: Path, run_id: str, stage: str, decisions: Path) -> dict:
    """Held under the apply lock's file half, so no apply on this machine acts on files a collect is replacing."""
    try:
        with hold_apply_file(store, run_id):
            return _collect(store, run_id, stage, decisions)
    except ApplyLockError as exc:
        raise SystemExit(f"Cannot collect the {stage} choices for {run_id}: {exc}") from None


def _collect(store: Path, run_id: str, stage: str, decisions: Path) -> dict:
    folder = stage_due(store, read_run(store, run_id), stage, ("collect", "apply"))
    check_unchanged(folder)
    manifest = read_json(folder / MANIFEST_FILE)
    choices = load_choices(decisions, manifest["run"]) if manifest["cards"] else {}
    check_choices(manifest, choices)

    rows = decision_rows(manifest, choices)
    approved = {row["team_id_master"] for row in rows if row["decision"] == APPLY}
    vetted = write_vetted(folder, stage, approved)
    write_json(folder / DECISIONS_FILE, rows, indent=1)
    counts = Counter(row["decision"] for row in rows)
    marker = {
        "run": manifest["run"],
        "collected_at": utc_now_iso(),
        "counts": {**{d: counts[d] for d in TEAM_DECISIONS}, "undecided": len(manifest["cards"]) - len(rows)},
        "vetted": vetted.name if vetted else None,
        "hashes": {path.name: file_hash(path) for path in (vetted, folder / DECISIONS_FILE) if path},
    }
    write_json(folder / COLLECTED_MARKER, marker, indent=1)
    return {"folder": folder, "marker": marker, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="The run id, e.g. 2026-10-14-nv")
    ap.add_argument("--stage", required=True, choices=PROPOSED_STAGES)
    ap.add_argument("--decisions", required=True, type=Path, help="The out_dir folder, or a JSON list of documents")
    ap.add_argument(
        "--store",
        type=Path,
        help="The run store, absolute (default: PITCHRANK_CLEANUP_DIR, else ~/pitchrank-cleanup-runs)",
    )
    args = ap.parse_args()
    try:
        result = collect(store_dir(args.store), args.run, args.stage, args.decisions)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Cannot collect the {args.stage} choices for {args.run}: {exc}") from None
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
