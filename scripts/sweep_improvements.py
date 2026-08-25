#!/usr/bin/env python3
"""Mechanical maintenance pass over the improvement backlog.

`.turbo/improvements.md` is append-only by construction: `/note-improvement` and
`/self-improve` only ever add to it, and nothing on the PR path closes an entry.
Left alone it grows until reading it costs more than it returns — 118 entries and
~25K tokens, over half of them 60+ days old, when this script was written.

This handles the parts that need no judgment:

* assign an `ID` to any entry that arrived without one (`/note-improvement` is a
  global skill and does not know about this file's schema)
* move `done` and `dropped` entries into `.turbo/improvements-archive.md`
* report entries missing a field their `Status` requires
* report `Where` anchors naming paths that no longer exist

The judgment — is this actually done, is it a duplicate, is the anchor merely moved
— belongs to the `sweep-improvements` skill, which runs this first and acts on the
report.

Usage:
    python scripts/sweep_improvements.py --dry-run   # report only
    python scripts/sweep_improvements.py             # report and rewrite both files
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE = PROJECT_ROOT / ".turbo" / "improvements.md"
ARCHIVE = PROJECT_ROOT / ".turbo" / "improvements-archive.md"

LIVE_STATUSES = ("open", "deferred")
CLOSED_STATUSES = ("done", "dropped")
ALL_STATUSES = LIVE_STATUSES + CLOSED_STATUSES

# What each status obliges the entry to also carry.
REQUIRED_WITH = {"done": "Refs", "dropped": "Refs", "deferred": "Trigger"}

FIELD_ORDER = ["ID", "Status", "Type", "Category", "Where", "Why", "Noted", "Refs", "Trigger"]

ENTRY_RE = re.compile(r"^### (.+)$")
FIELD_RE = re.compile(r"^- \*\*([^*]+)\*\*\s*:\s*(.*)$")
ID_RE = re.compile(r"^IMP-(\d{3,})$")
BACKTICKED = re.compile(r"`([^`\n]+)`")

# Mirrors tests/unit/test_agent_doc_references.py: anchors into generated or
# gitignored trees can never resolve against the tracked-file index.
SKIP_PREFIXES = ("data/", "reports/", "logs/", "venv/", "node_modules/", ".turbo/", "models/")
CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".sql", ".yml", ".yaml", ".json", ".sh", ".md")


@dataclass
class Entry:
    title: str
    fields: dict[str, str] = field(default_factory=dict)
    extras: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return self.fields.get("Status", "open")

    @property
    def ident(self) -> str:
        return self.fields.get("ID", "(no ID)")

    def render(self) -> str:
        out = [f"### {self.title}", ""]
        out += [f"- **{k}**: {self.fields[k]}" for k in FIELD_ORDER if k in self.fields]
        out += [f"- **{k}**: {v}" for k, v in self.fields.items() if k not in FIELD_ORDER]
        out += self.extras
        return "\n".join(out)


def split_header(text: str) -> tuple[str, list[str]]:
    """Return the file header and the raw entry chunks after it."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ENTRY_RE.match(ln)]
    if not starts:
        return text.rstrip() + "\n", []
    header = "\n".join(lines[: starts[0]]).rstrip() + "\n"
    chunks = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(lines)
        chunks.append("\n".join(lines[s:e]))
    return header, chunks


def parse_entry(chunk: str) -> Entry:
    lines = chunk.splitlines()
    entry = Entry(title=ENTRY_RE.match(lines[0]).group(1).strip())
    for ln in lines[1:]:
        m = FIELD_RE.match(ln)
        if m:
            entry.fields.setdefault(m.group(1).strip(), m.group(2).strip())
        elif ln.strip():
            entry.extras.append(ln)
    return entry


def tracked_files() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return {ln.strip() for ln in out.splitlines() if ln.strip()}


def anchor_resolves(token: str, tracked: set[str]) -> bool:
    cleaned = token.removeprefix("./").rstrip("/")
    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[0]
    if "::" in cleaned:
        cleaned = cleaned.split("::", 1)[0]
    if not cleaned or cleaned.startswith(SKIP_PREFIXES) or cleaned.startswith("/"):
        return True  # gitignored tree, or a URL route rather than a repo path
    if "/" not in cleaned and not cleaned.endswith(CODE_SUFFIXES):
        return True  # a bare symbol or prose, not a path
    if cleaned in tracked:
        return True
    if any(t.startswith(cleaned + "/") for t in tracked):
        return True
    return any(t.endswith("/" + cleaned) for t in tracked)


def drifted_anchors(entry: Entry, tracked: set[str]) -> list[str]:
    where = entry.fields.get("Where", "")
    bad = []
    for token in BACKTICKED.findall(where):
        token = token.strip()
        if " " in token or not token or any(c in token for c in "<>{}*[]"):
            continue
        if not anchor_resolves(token, tracked):
            bad.append(token)
    return bad


def next_free_id(entries: list[Entry]) -> int:
    used = []
    for e in entries:
        m = ID_RE.match(e.fields.get("ID", ""))
        if m:
            used.append(int(m.group(1)))
    return (max(used) + 1) if used else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report without rewriting either file")
    args = parser.parse_args()

    live_header, live_chunks = split_header(LIVE.read_text(encoding="utf-8"))
    archive_text = ARCHIVE.read_text(encoding="utf-8") if ARCHIVE.is_file() else ""
    archive_header, archive_chunks = split_header(archive_text)

    live = [parse_entry(c) for c in live_chunks]
    archived = [parse_entry(c) for c in archive_chunks]

    print(f"live:    {len(live)} entries")
    print(f"archive: {len(archived)} entries")

    # --- backfill the schema fields an appended entry arrives without -------- #
    # /note-improvement is a global skill and writes only Type/Category/Where/
    # Why/Noted. Both fields have to be filled: an entry with an ID but no Status
    # is still invisible to the Status grep this schema exists for.
    everything = live + archived
    counter = next_free_id(everything)
    assigned: list[tuple[str, str]] = []
    statused: list[tuple[str, str]] = []
    for entry in live:
        if "ID" not in entry.fields:
            entry.fields["ID"] = f"IMP-{counter:03d}"
            assigned.append((entry.fields["ID"], entry.title))
            counter += 1
        if "Status" not in entry.fields:
            # A newly noted entry is open by definition — nobody has done it yet.
            entry.fields["Status"] = "open"
            statused.append((entry.fields["ID"], entry.title))
    if assigned:
        print(f"\nassigned {len(assigned)} new ID(s):")
        for ident, title in assigned:
            print(f"  {ident}  {title[:70]}")
    if statused:
        print(f"\nbackfilled Status: open on {len(statused)} entr(y/ies):")
        for ident, title in statused:
            print(f"  {ident}  {title[:70]}")

    # --- move closed entries to the archive ---------------------------------- #
    to_archive = [e for e in live if e.status in CLOSED_STATUSES]
    still_live = [e for e in live if e.status not in CLOSED_STATUSES]
    if to_archive:
        print(f"\narchiving {len(to_archive)} closed entr(y/ies):")
        for entry in to_archive:
            print(f"  {entry.ident}  [{entry.status}]  {entry.title[:64]}")

    # --- report problems that need a human ----------------------------------- #
    problems: list[str] = []
    seen_ids: dict[str, str] = {}
    for entry in still_live + to_archive + archived:
        ident = entry.ident
        if entry.status not in ALL_STATUSES:
            problems.append(f"{ident}: Status {entry.status!r} is not one of {ALL_STATUSES}")
        needed = REQUIRED_WITH.get(entry.status)
        if needed and needed not in entry.fields:
            problems.append(f"{ident}: Status {entry.status!r} requires a {needed} line — {entry.title[:50]}")
        if ident in seen_ids:
            problems.append(f"{ident}: duplicate ID, also on {seen_ids[ident][:50]!r}")
        seen_ids[ident] = entry.title

    tracked = tracked_files()
    drift = [(e.ident, e.title, bad) for e in still_live if (bad := drifted_anchors(e, tracked))]
    if drift:
        print(
            f"\n{len(drift)} live entr(y/ies) name an untracked path. Some are files the entry "
            f"proposes creating\nrather than anchors that drifted, so this is a report to read, "
            f"not a defect list:"
        )
        for ident, title, bad in drift:
            print(f"  {ident}  {title[:52]}")
            print(f"        {', '.join(bad[:4])}")

    if problems:
        print(f"\n{len(problems)} problem(s) needing a decision:")
        for p in problems:
            print(f"  {p}")

    counts = Counter(e.status for e in still_live)
    print("\nlive after sweep: " + ", ".join(f"{s} {counts.get(s, 0)}" for s in LIVE_STATUSES))

    if args.dry_run:
        print("\n[dry-run] no files written")
        return 1 if problems else 0

    if to_archive or assigned or statused:
        LIVE.write_text(
            live_header + "\n" + "\n\n".join(e.render() for e in still_live) + "\n", encoding="utf-8"
        )
        ARCHIVE.write_text(
            (archive_header or "# Improvements — archive\n")
            + "\n"
            + "\n\n".join(e.render() for e in archived + to_archive)
            + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {LIVE.relative_to(PROJECT_ROOT)} and {ARCHIVE.relative_to(PROJECT_ROOT)}")
    else:
        print("\nnothing to move; files unchanged")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
