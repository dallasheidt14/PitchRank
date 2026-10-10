#!/usr/bin/env python3
"""Carry the owner's Keep-separate choices from the old merge review pages into team_cleanup_decisions.

Each review page kept the owner's choices in its own store, which no scan reads, so a pair the
owner marked "Keep separate" was proposed again by the next scan of its state. This reads a
folder holding:

  index.tsv               one line per page: slug, title, page URL (tab-separated)
  <slug>.manifest.json    the page builder's manifest: {run, title, pairs: {doc id: ...}}, or a
                          saved copy naming the page's `decisions-<run>` collection instead of run
  <slug>.decisions.json   the page's documents as read back: [{id, data: {decision, swap, note}}],
                          an empty list for a page nobody decided

and writes one keep_separate decision for each pair whose newest choice is "separate".

Newest means the most recently built page: the saved documents carry no time of their own, and
the owner reversed earlier choices by deciding the same pair again on a later page. A page's build
time is its run id; a page built before builds were stamped needs its time given with --built-at,
and is refused without it. Times compare in UTC. Two choices on one pair from pages built in the
same second, disagreeing, refuse the whole run rather than pick one.

Team ids come only from the manifest, never from a document. A document the manifest does not
know, one listed twice, a decision outside the page's three, or a listed page with no
<slug>.decisions.json refuses the whole run.

Dry run by default. --execute inserts, skipping any pair that already holds an active decision,
so an answer given since is never overwritten by an older page.

Usage:
    python scripts/team_cleanup/carry_forward.py --pages-dir <folder>
    python scripts/team_cleanup/carry_forward.py --pages-dir <folder> --execute
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import batched, get_client, page  # noqa: E402
from scripts.team_cleanup.decisions import (  # noqa: E402
    DECISIONS_TABLE,
    KEEP_SEPARATE,
    MERGES,
    DecisionsUnavailable,
    pair_subject,
)

SEPARATE, MERGE, UNSURE = "separate", "merge", "unsure"
PAGE_DECISIONS = frozenset({SEPARATE, MERGE, UNSURE})
INSERT_BATCH = 500
# A pair key is two ids long, so a lookup holds half as many as an id batch to stay inside the
# same URL length.
SUBJECT_BATCH = 50

_RUN = re.compile(r"^(?:decisions-)?(\d{8}T\d{6}Z)-")


@dataclass(frozen=True)
class Choice:
    merge_id: str
    keep_id: str
    decision: str
    note: str
    decided_at: str
    page_id: str
    page_title: str

    @property
    def subject(self) -> str:
        return pair_subject(self.merge_id, self.keep_id)


def resolve_execute(execute_flag: bool, dry_run_flag: bool) -> bool:
    """Fail safe: asking for both means the caller wants the preview."""
    return execute_flag and not dry_run_flag


def page_built_at(manifest: dict) -> str:
    stamp = manifest.get("run") or manifest.get("collection")
    match = _RUN.match(stamp or "")
    if not match:
        raise ValueError(f"the manifest carries no build time (run or collection {stamp!r})")
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()


def read_index(pages_dir: Path) -> list[tuple[str, str, str]]:
    """(slug, title, page id) for every page the folder lists."""
    entries = []
    for line in (pages_dir / "index.tsv").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        slug, title, url = line.split("\t")[:3]
        entries.append((slug, title, url.rstrip("/").rsplit("/", 1)[-1]))
    return entries


def page_choices(
    manifest: dict, documents: list, page_id: str, title: str, built_at: str | None = None
) -> tuple[list[Choice], list[str]]:
    """The choices one page holds, and every reason to distrust them."""
    try:
        built_at = built_at or page_built_at(manifest)
    except ValueError as exc:
        return [], [f"{title}: {exc}; give it with --built-at"]
    pairs = manifest["pairs"]
    choices, problems, seen = [], [], set()
    for document in documents:
        pair = pairs.get(document.get("id"))
        if pair is None:
            problems.append(f"{title}: document {document.get('id')!r} is not on the page's manifest")
            continue
        if document["id"] in seen:
            problems.append(f"{title}: document {document['id']!r} is listed twice")
            continue
        seen.add(document["id"])
        decision = (document.get("data") or {}).get("decision")
        if decision is None:
            continue
        if decision not in PAGE_DECISIONS:
            problems.append(f"{title}: document {document['id']!r} holds decision {decision!r}")
            continue
        note = (document["data"].get("note") or "").strip()
        choices.append(Choice(pair["merge_id"], pair["keep_id"], decision, note, built_at, page_id, title))
    return choices, problems


def newest_choices(choices: list[Choice]) -> tuple[dict[str, Choice], list[str]]:
    """The newest choice per pair, and every pair two same-second pages disagree on."""
    newest, problems = {}, []
    for choice in sorted(choices, key=lambda c: c.decided_at):
        earlier = newest.get(choice.subject)
        if earlier and earlier.decided_at == choice.decided_at and earlier.decision != choice.decision:
            problems.append(
                f"{choice.subject}: {earlier.page_title} and {choice.page_title} were built in the same "
                f"second and disagree ({earlier.decision} vs {choice.decision})"
            )
        newest[choice.subject] = choice
    return newest, problems


def keep_separate_rows(newest: dict[str, Choice]) -> list[dict]:
    return [
        {
            "stage": MERGES,
            "subject_key": choice.subject,
            "team_id_master": choice.merge_id,
            "other_team_id": choice.keep_id,
            "decision": KEEP_SEPARATE,
            "note": choice.note or None,
            "decided_at": choice.decided_at,
            "source": f"carried:{choice.page_id}",
        }
        for choice in sorted(newest.values(), key=lambda c: c.subject)
        if choice.decision == SEPARATE
    ]


def active_subjects(sb, subjects: list[str]) -> set[str]:
    """The merge subjects that already hold an active decision of any kind."""
    found = set()
    try:
        for batch in batched(subjects, SUBJECT_BATCH):
            rows = page(
                lambda b=batch: sb.table(DECISIONS_TABLE)
                .select("id,subject_key,superseded_at")
                .eq("stage", MERGES)
                .in_("subject_key", b),
                "id",
            )
            found |= {r["subject_key"] for r in rows if r["superseded_at"] is None}
    except Exception as exc:
        raise DecisionsUnavailable(f"could not read {DECISIONS_TABLE}: {exc}") from exc
    return found


def parse_built_at(values: list[str]) -> dict[str, str]:
    """`--built-at slug=ISO-time` pairs, each time checked to parse and to name its zone."""
    built = {}
    for value in values:
        slug, _, when = value.partition("=")
        parsed = datetime.fromisoformat(when)
        if parsed.tzinfo is None:
            raise ValueError(f"--built-at {value!r} needs a time zone, e.g. 2026-09-24T00:00:00+00:00")
        built[slug] = parsed.astimezone(timezone.utc).isoformat()
    return built


def load_pages(pages_dir: Path, built_at: dict[str, str]) -> tuple[list[Choice], list[str], int]:
    choices, problems = [], []
    entries = read_index(pages_dir)
    for slug, title, page_id in entries:
        manifest = json.loads((pages_dir / f"{slug}.manifest.json").read_text(encoding="utf-8"))
        decisions_path = pages_dir / f"{slug}.decisions.json"
        if not decisions_path.exists():
            problems.append(f"{title}: no {decisions_path.name}; save the page's documents first")
            continue
        documents = json.loads(decisions_path.read_text(encoding="utf-8"))
        found, wrong = page_choices(manifest, documents, page_id, title, built_at.get(slug))
        choices += found
        problems += wrong
    return choices, problems, len(entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pages-dir", type=Path, required=True, help="Folder of saved review pages")
    parser.add_argument("--execute", action="store_true", help="Write the decisions (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Force a dry run; wins over --execute")
    parser.add_argument("--out", type=Path, help="Write the planned rows to this JSON file")
    parser.add_argument(
        "--built-at",
        action="append",
        default=[],
        metavar="SLUG=TIME",
        help="Build time of a page, used instead of its manifest's; needed where the manifest carries "
        "none, e.g. co_orig=2026-09-24T00:00:00+00:00",
    )
    args = parser.parse_args()
    execute = resolve_execute(args.execute, args.dry_run)
    try:
        built_at = parse_built_at(args.built_at)
    except ValueError as exc:
        parser.error(str(exc))

    choices, problems, pages_read = load_pages(args.pages_dir, built_at)
    newest, conflicts = newest_choices(choices)
    problems += conflicts
    if problems:
        print("Refusing: the saved pages hold choices this script cannot trust.")
        for problem in problems:
            print(f"  {problem}")
        return 1

    rows = keep_separate_rows(newest)
    by_decision = Counter(c.decision for c in newest.values())
    decided = defaultdict(set)
    for choice in choices:
        decided[choice.subject].add(choice.decision)
    reversed_pairs = sum(1 for seen in decided.values() if len(seen) > 1)
    print(f"pages read            {pages_read:,}")
    print(f"choices read          {len(choices):,}")
    print(f"pairs decided         {len(newest):,}  (newest choice: {dict(sorted(by_decision.items()))})")
    print(f"pairs decided twice, differently  {reversed_pairs:,}  (the newer page wins)")
    print(f"keep_separate rows    {len(rows):,}")

    if args.out:
        args.out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(f"planned rows written to {args.out}")

    if execute and not os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        raise SystemExit("--execute needs SUPABASE_SERVICE_ROLE_KEY: the table refuses every other role.")
    try:
        sb = get_client()
        existing = active_subjects(sb, [r["subject_key"] for r in rows])
    except DecisionsUnavailable as exc:
        if not exc.table_missing:
            print(f"\n{exc}")
            return 1
        if execute:
            raise SystemExit(f"{exc}\nApply the team_cleanup_decisions migration before --execute.") from exc
        print(f"\n{exc}\nDRY RUN -- the table does not exist yet, so every row above would be new.")
        return 0

    to_write = [r for r in rows if r["subject_key"] not in existing]
    print(f"already decided       {len(rows) - len(to_write):,}  (left as they stand)")
    print(f"to write              {len(to_write):,}")
    if not execute:
        print("\nDRY RUN -- nothing written. Re-run with --execute to write the rows above.")
        return 0

    for batch in batched(to_write, INSERT_BATCH):
        sb.table(DECISIONS_TABLE).insert(batch).execute()
    print(f"\nwrote {len(to_write):,} keep_separate decisions to {DECISIONS_TABLE}")
    print(
        f"Undo, every carried decision at once: UPDATE {DECISIONS_TABLE} SET superseded_at = now() "
        "WHERE source LIKE 'carried:%' AND superseded_at IS NULL;"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
