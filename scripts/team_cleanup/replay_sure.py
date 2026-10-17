#!/usr/bin/env python3
"""Replay sure.py's rules over the cards of finished weekly runs, against how the owner decided them.

For each run and stage it reads the cards the page showed and the owner's collected choices, sorts
every card into sure or not, and prints how the owner decided each kind. It exits 1, naming the
cards, if a card the owner turned down or was unsure about would have been sure: a rule that would
have applied a change the owner did not want is not one to apply unattended. A replay that reads
nothing checks nothing, so it refuses a run it cannot read, a run that built no page, and a page
that was never collected.

The evidence is read as it stands today, so a team renamed or re-probed since reads differently.
Read-only: it never writes to the database.

    python scripts/team_cleanup/replay_sure.py --runs 2026-10-15-nv,2026-10-15-az,2026-10-15-ca
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import get_client, load_merge_map, resolver  # noqa: E402
from scripts.team_cleanup.collect import DECISIONS_FILE  # noqa: E402
from scripts.team_cleanup.decisions import APPLY, DONT_APPLY, UNSURE, DecisionsUnavailable  # noqa: E402
from scripts.team_cleanup.propose_week import (  # noqa: E402
    AGE_REVIEW_FILE,
    AGES,
    PROPOSED_STAGES,
    STATES,
    _read_csv,
    with_age_evidence,
)
from scripts.team_cleanup.run_store import MANIFEST_FILE, read_run, stage_dir, store_dir  # noqa: E402
from scripts.team_cleanup.sure import Signals, held_fills, reverted_changes, state_evidence, sure_because  # noqa: E402
from src.tournaments.storage._io import read_json  # noqa: E402

UNDECIDED = "undecided"
COLUMNS = (APPLY, DONT_APPLY, UNSURE, UNDECIDED)


def stage_cards(store: Path, run_id: str, stage: str) -> list[tuple[dict, str]] | None:
    """Each card the stage's page showed, as its proposal and the owner's decision, or None for a
    stage that built no page."""
    folder = stage_dir(store, run_id, stage)
    if not (folder / MANIFEST_FILE).exists():
        return None
    if not (folder / DECISIONS_FILE).exists():
        raise ValueError(f"{run_id}'s {stage} page was never collected, so every card would read as undecided")
    proposals = list(read_json(folder / MANIFEST_FILE)["cards"].values())
    if stage == AGES:
        proposals = with_age_evidence(proposals, _read_csv(folder / AGE_REVIEW_FILE))
    decided = {(d["team_id_master"], d["new_value"]): d["decision"] for d in read_json(folder / DECISIONS_FILE)}
    return [(p, decided.get((p["team_id_master"], p["new_value"]), UNDECIDED)) for p in proposals]


def replay(sb, store: Path, run_ids: list[str]) -> tuple[dict[str, Counter], list[str]]:
    """Per stage, (sure or not, the owner's decision) -> cards; and the sure cards the owner did not
    want. Each card is judged as its team stands today, so a team merged since its run is read under
    its surviving id, as the undo ledger and the live teams are."""
    canonical = resolver(load_merge_map(sb))
    tables, unwanted, paged = {}, [], set()
    for stage in PROPOSED_STAGES:
        runs = {run_id: cards for run_id in run_ids if (cards := stage_cards(store, run_id, stage)) is not None}
        paged |= set(runs)
        evidence = state_evidence(sb, stage, [p for cards in runs.values() for p, _ in cards])
        reverted = reverted_changes(sb, stage, canonical)
        table = Counter()
        for run_id, cards in runs.items():
            held = held_fills(sb, stage_dir(store, run_id, stage), [p for p, _ in cards]) if stage == STATES else set()
            signals = Signals(reverted, {canonical(team) for team in held}, evidence)
            for p, decision in cards:
                why = sure_because(stage, {**p, "team_id_master": canonical(p["team_id_master"])}, signals)
                table["sure" if why else "conflict", decision] += 1
                if why and decision in (DONT_APPLY, UNSURE):
                    change = f"{p['team_name']!r} {p['old_value']} -> {p['new_value']}"
                    unwanted.append(f"{run_id} {stage}: {change} ({decision})")
        tables[stage] = table
    if unpaged := [run_id for run_id in run_ids if run_id not in paged]:
        raise ValueError(f"{', '.join(unpaged)} built no page to replay")
    return tables, unwanted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", required=True, help="Comma-separated run ids, e.g. 2026-10-15-nv,2026-10-15-az")
    ap.add_argument(
        "--store",
        type=Path,
        help="The run store, absolute (default: PITCHRANK_CLEANUP_DIR, else ~/pitchrank-cleanup-runs)",
    )
    args = ap.parse_args()
    run_ids = [r.strip() for r in args.runs.split(",") if r.strip()]
    if not run_ids:
        raise SystemExit("Name at least one run to replay.")
    try:
        store = store_dir(args.store)
        for run_id in run_ids:
            read_run(store, run_id)
        tables, unwanted = replay(get_client(), store, run_ids)
    except DecisionsUnavailable as exc:
        raise SystemExit(f"Cannot replay {args.runs}: {exc}") from exc
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Cannot replay {args.runs}: {exc}") from None
    for stage, table in tables.items():
        print(f"\n{stage}")
        for kind in ("sure", "conflict"):
            print(f"  {kind}: " + "  ".join(f"{column}={table[kind, column]}" for column in COLUMNS))
    if unwanted:
        print("\nSure, though the owner turned it down or was unsure:")
        print("\n".join(f"  {line}" for line in unwanted))
        return 1
    print("\nNo card the owner turned down or was unsure about is sure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
