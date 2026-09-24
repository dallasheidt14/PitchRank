"""Turn the owner's review-page choices into a merge list for apply_vetted_team_merges.py.

Takes the manifest build_review_page.py wrote and the page's saved choices, read back from its
`decisions-<run>` collection with the ArtifactData tool: the folder `out_dir` saved them to (or
the `decisions-<run>` folder inside it), or a JSON list of `{"id": ..., "data": {...}}`
documents. Team ids come only from the manifest; a saved choice contributes its decision, its
swap, and a note that is only printed. The run fails outright, rather than guessing, on a choice naming a pair
the page never showed, on a duplicate or mislabelled document, on a decision or swap of the
wrong kind, on merges that disagree about which team survives, and on finding no choices at all.

Never touches the database: it writes the merge list and prints the pairs behind every other
decision, with the notes.

    python .claude/skills/merging-duplicate-teams/scripts/collect_review_decisions.py \
        --manifest review.html.manifest.json --decisions <out_dir> --out vetted.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

DECISIONS = ("merge", "separate", "unsure")


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


def collect(manifest: dict, choices: dict[str, dict]) -> dict:
    if manifest["pairs"] and not choices:
        raise SystemExit("no saved choices were found: check the folder or file passed as --decisions")
    unknown = sorted(set(choices) - set(manifest["pairs"]))
    if unknown:
        raise SystemExit(f"{len(unknown)} saved choice(s) name no pair on this page: {', '.join(unknown)}")
    for pair_id, choice in choices.items():
        if choice.get("decision") not in (*DECISIONS, None) or not isinstance(choice.get("swap", False), bool):
            raise SystemExit(f"saved choice {pair_id} holds a decision or swap the page never writes: {choice}")

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
            pair = {"merge_id": pair["keep_id"], "keep_id": pair["merge_id"],
                    "merge_name": pair["keep_name"], "keep_name": pair["merge_name"]}
        merges.append(dict(pair))
    refuse_conflicts(merges)
    return {"merges": merges, "by_decision": by_decision, "notes": notes}


def refuse_conflicts(merges: list[dict]) -> None:
    """A team merged into two survivors, or merged away while also a survivor, makes the applier
    drop or chain those merges, so the owner's cluster decision would not land as chosen."""
    retired = Counter(m["merge_id"] for m in merges)
    clash = [m for m in merges if retired[m["merge_id"]] > 1 or m["keep_id"] in retired]
    if clash:
        lines = "\n".join(f"  {m['merge_name']} -> {m['keep_name']}" for m in clash)
        raise SystemExit(f"these merges disagree about which team survives; settle the cluster on the page:\n{lines}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, help="the .manifest.json build_review_page.py wrote")
    ap.add_argument("--decisions", required=True, help="the out_dir folder, or a JSON list of documents")
    ap.add_argument("--out", required=True, help="where to write the merge list")
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    result = collect(manifest, load_choices(Path(args.decisions), manifest["run"]))
    Path(args.out).write_text(json.dumps(result["merges"], indent=1), encoding="utf-8")
    print(f"run {manifest['run']}: wrote {len(result['merges'])} merges to {args.out}")
    pairs = manifest["pairs"]

    def names(pair_id):
        return f"{pairs[pair_id]['merge_name']} -> {pairs[pair_id]['keep_name']}"

    for decision, ids in result["by_decision"].items():
        print(f"  {decision:<10} {len(ids)}")
        if decision != "merge":
            for pair_id in ids:
                print(f"      {names(pair_id)}")
    for pair_id, note in result["notes"].items():
        print(f"  note on {names(pair_id)}: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
