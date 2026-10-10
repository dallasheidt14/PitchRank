"""Turn the owner's review-page choices into a merge list for apply_vetted_team_merges.py, and
record the pairs the owner kept separate.

Takes the manifest build_review_page.py wrote and the page's saved choices, read back from its
`decisions-<run>` collection with the ArtifactData tool: the folder `out_dir` saved them to (or
the `decisions-<run>` folder inside it), or a JSON list of `{"id": ..., "data": {...}}`
documents. Team ids come only from the manifest; a saved choice contributes its decision, its
swap, and a note that is printed and, on a Keep separate, recorded. The run fails outright, rather
than guessing, on a choice naming a pair the page never showed, on a duplicate or mislabelled
document, on a decision, swap or note of the wrong kind, on merges that disagree about which team
survives or that would join two teams the page keeps separate, and on finding no choices at all.
Keep separate choices are recorded before the merges are checked, so they land even when the
merges are refused.

Each merge carries both teams' age group, gender, state and club as the manifest recorded them,
so the applier refuses one whose teams have changed since; a merge whose manifest records none
is refused by the applier.

It writes the merge list and prints the pairs behind every other decision, with the notes. With
--execute it also records every Keep separate as a keep_separate decision in
team_cleanup_decisions, which the duplicate scans and the applier read, leaving any pair that
already holds an active decision as it stands. Without --execute it never touches the database.

    python .claude/skills/merging-duplicate-teams/scripts/collect_review_decisions.py \
        --manifest review.html.manifest.json --decisions <out_dir> --out vetted.json
    python .claude/skills/merging-duplicate-teams/scripts/collect_review_decisions.py \
        --manifest review.html.manifest.json --decisions <out_dir> --out vetted.json --execute
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import active_subjects, get_client  # noqa: E402
from scripts.team_cleanup.decisions import (  # noqa: E402
    DECISIONS_TABLE,
    DecisionsUnavailable,
    keep_separate_row,
    page_built_at,
    resolve_execute,
)
from scripts.team_cleanup.vetted import KEEP_AS_VETTED, MERGE_AS_VETTED, records_teams  # noqa: E402

DECISIONS = ("merge", "separate", "unsure")
SWAPPED = {
    "merge_id": "keep_id",
    "keep_id": "merge_id",
    "merge_name": "keep_name",
    "keep_name": "merge_name",
    MERGE_AS_VETTED: KEEP_AS_VETTED,
    KEEP_AS_VETTED: MERGE_AS_VETTED,
}


def _fields(doc_id: str, content: dict) -> dict:
    if "data" in content:
        if content.get("id", doc_id) != doc_id:
            raise SystemExit(f"document {doc_id} claims to be {content['id']}")
        content = content["data"]
    return {k: v for k, v in content.items() if k != "id"}


def load_choices(path: Path, run: str) -> dict[str, dict]:
    """In a folder the filename is a document's id, and nothing inside the file can change it;
    in a listing an id may appear once."""
    if path.is_dir():
        folder = path / f"decisions-{run}" if (path / f"decisions-{run}").is_dir() else path
        files = sorted(folder.glob("*.json"))
        return {f.stem: _fields(f.stem, json.loads(f.read_text(encoding="utf-8"))) for f in files}
    choices = {}
    for doc in json.loads(path.read_text(encoding="utf-8")):
        if doc["id"] in choices:
            raise SystemExit(f"document {doc['id']} is listed twice")
        choices[doc["id"]] = _fields(doc["id"], doc)
    return choices


def collect(manifest: dict, choices: dict[str, dict], *, check: bool = True) -> dict:
    if manifest["pairs"] and not choices:
        raise SystemExit("no saved choices were found: check the folder or file passed as --decisions")
    unknown = sorted(set(choices) - set(manifest["pairs"]))
    if unknown:
        raise SystemExit(f"{len(unknown)} saved choice(s) name no pair on this page: {', '.join(unknown)}")
    for pair_id, choice in choices.items():
        note = choice.get("note")
        if (
            choice.get("decision") not in (*DECISIONS, None)
            or not isinstance(choice.get("swap", False), bool)
            or not isinstance(note, (str, type(None)))
            or "\x00" in (note or "")
        ):
            raise SystemExit(f"saved choice {pair_id} holds a decision, swap or note the page never writes: {choice}")

    merges, by_decision, notes = [], {d: [] for d in (*DECISIONS, "undecided")}, {}
    for pair_id, pair in manifest["pairs"].items():
        choice = choices.get(pair_id, {})
        decision = choice.get("decision") or "undecided"
        by_decision[decision].append(pair_id)
        if choice.get("note"):
            notes[pair_id] = choice["note"]
        if decision != "merge":
            continue
        if choice.get("swap"):
            pair = {SWAPPED.get(key, key): value for key, value in pair.items()}
        merges.append(dict(pair))
    result = {"merges": merges, "by_decision": by_decision, "notes": notes}
    if check:
        check_merges(manifest, result)
    return result


def check_merges(manifest: dict, result: dict) -> None:
    refuse_conflicts(result["merges"])
    refuse_kept_apart_joins(manifest, result)


def refuse_conflicts(merges: list[dict]) -> None:
    """A team merged into two survivors, or merged away while also a survivor, makes the applier
    drop or chain those merges, so the owner's cluster decision would not land as chosen."""
    retired = Counter(m["merge_id"] for m in merges)
    clash = [m for m in merges if retired[m["merge_id"]] > 1 or m["keep_id"] in retired]
    if clash:
        lines = "\n".join(f"  {m['merge_name']} -> {m['keep_name']}" for m in clash)
        raise SystemExit(f"these merges disagree about which team survives; settle the cluster on the page:\n{lines}")


def refuse_kept_apart_joins(manifest: dict, result: dict) -> None:
    """Two merges into one survivor can join a pair the same page keeps separate, and the applier
    cannot refuse that until the page's Keep separate choices are recorded."""
    group: dict[str, str] = {}

    def root(team_id: str) -> str:
        while group.get(team_id, team_id) != team_id:
            team_id = group[team_id]
        return team_id

    for m in result["merges"]:
        group[root(m["merge_id"])] = root(m["keep_id"])
    joined = [
        manifest["pairs"][pair_id]
        for pair_id in result["by_decision"]["separate"]
        if root(manifest["pairs"][pair_id]["merge_id"]) == root(manifest["pairs"][pair_id]["keep_id"])
    ]
    if joined:
        lines = "\n".join(f"  {p['merge_name']} / {p['keep_name']}" for p in joined)
        raise SystemExit(f"these merges would join teams the page keeps separate; settle them on the page:\n{lines}")


def keep_separate_rows(manifest: dict, result: dict) -> list[dict]:
    """A page's documents carry no trustworthy time of their own, so a decision is dated by the
    page's build."""
    decided_at, source = page_built_at(manifest), f"page:{manifest['run']}"
    rows = []
    for pair_id in result["by_decision"]["separate"]:
        pair, note = manifest["pairs"][pair_id], (result["notes"].get(pair_id) or "").strip()
        rows.append(keep_separate_row(pair["merge_id"], pair["keep_id"], note, decided_at, source))
    return rows


def record_keep_separate(rows: list[dict], execute: bool) -> None:
    if not rows:
        return
    if not execute:
        print(f"\nDRY RUN -- {len(rows)} Keep separate choice(s) not recorded. Re-run with --execute to record them.")
        return
    if not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit("--execute needs SUPABASE_SERVICE_ROLE_KEY: the table refuses every other role.")
    sb = get_client()
    try:
        existing = active_subjects(sb, [r["subject_key"] for r in rows])
    except DecisionsUnavailable as exc:
        hint = "\nApply the team_cleanup_decisions migration before --execute." if exc.table_missing else ""
        raise SystemExit(f"{exc}{hint}") from exc
    to_write = [r for r in rows if r["subject_key"] not in existing]
    if to_write:
        sb.table(DECISIONS_TABLE).insert(to_write).execute()
    print(f"\nrecorded {len(to_write)} Keep separate decision(s); {len(rows) - len(to_write)} pair(s) already held one")
    print(
        f"Undo: UPDATE {DECISIONS_TABLE} SET superseded_at = now() "
        f"WHERE source = '{rows[0]['source']}' AND superseded_at IS NULL;"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, help="the .manifest.json build_review_page.py wrote")
    ap.add_argument("--decisions", required=True, help="the out_dir folder, or a JSON list of documents")
    ap.add_argument("--out", required=True, help="where to write the merge list")
    ap.add_argument("--execute", action="store_true", help="record the Keep separate choices (default is a dry run)")
    ap.add_argument("--dry-run", action="store_true", help="force a dry run; wins over --execute")
    args = ap.parse_args()
    execute = resolve_execute(args.execute, args.dry_run)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    result = collect(manifest, load_choices(Path(args.decisions), manifest["run"]), check=False)
    print(f"run {manifest['run']}:")
    pairs = manifest["pairs"]

    def names(pair_id):
        return f"{pairs[pair_id]['merge_name']} -> {pairs[pair_id]['keep_name']}"

    for decision, ids in result["by_decision"].items():
        print(f"  {decision:<10} {len(ids)}")
        if decision != "merge":
            for pair_id in ids:
                print(f"      {names(pair_id)}")
    for pair_id, note in result["notes"].items():
        print(f"  note on {names(pair_id)}: {note!r}")
    record_keep_separate(keep_separate_rows(manifest, result), execute)

    check_merges(manifest, result)
    Path(args.out).write_text(json.dumps(result["merges"], indent=1), encoding="utf-8")
    print(f"wrote {len(result['merges'])} merges to {args.out}")
    unrecorded = sum(1 for m in result["merges"] if not records_teams(m))
    if unrecorded:
        print(f"  {unrecorded} merge(s) carry no record of the teams as the page showed them, so the applier "
              "will refuse them; rebuild the page to merge them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
