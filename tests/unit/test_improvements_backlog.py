"""The improvement backlog says "done" exactly one way.

`.turbo/improvements.md` is written by two global skills (`/note-improvement`,
`/self-improve`) that only ever append, and read by humans and agents deciding what
to work on next. Before this test it recorded closure five different ways --
`**Status**: deferred`, `**Status (2026-05-07 audit)**:`, `**Resolved**: <date> by
<branch>`, `**Resolved (2026-08-19)**:`, and free prose inside `Why` -- so no single
grep could answer "is this open?", and six finished items still read as open.

Three entries had also been written with `##` instead of `###`, which made them
invisible to every heading-based tool including the count in this file's own header.

The checks below pin the vocabulary rather than the schema in full: an entry that
`/note-improvement` just appended carries no `ID` or `Status` yet, and failing CI for
that would punish the wrong person. `scripts/sweep_improvements.py` backfills those.
What must never come back is a second way of spelling closure.

Each check carries a companion test proving its parser matched real input, because a
regex that silently matches nothing passes forever while proving nothing.
"""

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIVE = PROJECT_ROOT / ".turbo" / "improvements.md"
ARCHIVE = PROJECT_ROOT / ".turbo" / "improvements-archive.md"

LIVE_STATUSES = {"open", "deferred"}
CLOSED_STATUSES = {"done", "dropped"}
ALL_STATUSES = LIVE_STATUSES | CLOSED_STATUSES

# What a status obliges the entry to also carry. A deferred entry has no closing
# reference -- it has a resumption condition -- so it carries Trigger, not Refs.
REQUIRED_WITH = {"done": "Refs", "dropped": "Refs", "deferred": "Trigger"}

ENTRY_RE = re.compile(r"^### (.+)$")
FIELD_RE = re.compile(r"^- \*\*([^*]+)\*\*\s*:\s*(.*)$")
ID_RE = re.compile(r"^IMP-\d{3,}$")

# The four spellings this file used to carry, plus any new dated variant of them.
BANNED_MARKER = re.compile(r"^- \*\*(Resolved|Status\s*\()")

BACKLOG_FILES = [p for p in (LIVE, ARCHIVE) if p.is_file()]
BACKLOG_IDS = [str(p.relative_to(PROJECT_ROOT)).replace("\\", "/") for p in BACKLOG_FILES]


def _entries(path: Path) -> list[tuple[int, str, dict[str, str]]]:
    """(line number, title, fields) per entry."""
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [i for i, ln in enumerate(lines) if ENTRY_RE.match(ln)]
    out = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(lines)
        fields: dict[str, str] = {}
        for ln in lines[s + 1 : e]:
            m = FIELD_RE.match(ln)
            if m:
                fields.setdefault(m.group(1).strip(), m.group(2).strip())
        out.append((s + 1, ENTRY_RE.match(lines[s]).group(1).strip(), fields))
    return out


def test_backlog_files_exist() -> None:
    assert LIVE.is_file(), f"{LIVE} is missing; the backlog is referenced from CLAUDE.md"
    assert ARCHIVE.is_file(), f"{ARCHIVE} is missing; closed entries have nowhere to go"


# --------------------------------------------------------------------------- #
# Check 1: one vocabulary for closure
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", BACKLOG_FILES, ids=BACKLOG_IDS)
def test_no_ad_hoc_lifecycle_markers(path: Path) -> None:
    """`Resolved` and dated `Status (...)` labels are what fragmented this file."""
    offenders = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if BANNED_MARKER.match(line.strip()):
            offenders.append(
                f"{path.relative_to(PROJECT_ROOT)}:{lineno}: {line.strip()[:70]!r} -- use "
                f"`- **Status**: <{'|'.join(sorted(ALL_STATUSES))}>` plus Refs/Trigger. A dated "
                f"progress note is `- **Update (YYYY-MM-DD)**:`, which is not a lifecycle value."
            )
    assert not offenders, "\n".join(offenders)


@pytest.mark.parametrize("path", BACKLOG_FILES, ids=BACKLOG_IDS)
def test_status_values_are_in_the_vocabulary(path: Path) -> None:
    bad = []
    for lineno, title, fields in _entries(path):
        status = fields.get("Status")
        if status is not None and status not in ALL_STATUSES:
            bad.append(
                f"{path.relative_to(PROJECT_ROOT)}:{lineno}: Status {status!r} on {title[:48]!r}; "
                f"expected one of {sorted(ALL_STATUSES)}"
            )
    assert not bad, "\n".join(bad)


def test_status_parser_sees_real_entries() -> None:
    entries = _entries(LIVE)
    assert len(entries) > 50, f"entry parser found only {len(entries)} entries in the live backlog"
    statuses = {f.get("Status") for _, _, f in entries}
    assert statuses & LIVE_STATUSES, f"no live status values parsed; saw {statuses}"
    assert not BANNED_MARKER.match("- **Status**: open")
    assert BANNED_MARKER.match("- **Resolved**: 2026-08-24 by some-branch")
    assert BANNED_MARKER.match("- **Status (2026-05-07 audit)**: still valid")


# --------------------------------------------------------------------------- #
# Check 2: a closed entry says what closed it
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", BACKLOG_FILES, ids=BACKLOG_IDS)
def test_non_open_entries_carry_their_companion_field(path: Path) -> None:
    missing = []
    for lineno, title, fields in _entries(path):
        needed = REQUIRED_WITH.get(fields.get("Status", "open"))
        if needed and needed not in fields:
            missing.append(
                f"{path.relative_to(PROJECT_ROOT)}:{lineno}: {fields.get('ID', '(no ID)')} is "
                f"{fields.get('Status')!r} but has no {needed} line -- {title[:44]!r}"
            )
    assert not missing, "\n".join(missing)


# --------------------------------------------------------------------------- #
# Check 3: IDs are stable and never mean two things
# --------------------------------------------------------------------------- #


def test_ids_are_well_formed_and_unique_across_both_files() -> None:
    seen: dict[str, str] = {}
    problems = []
    for path in BACKLOG_FILES:
        for lineno, title, fields in _entries(path):
            ident = fields.get("ID")
            if ident is None:
                continue  # freshly appended by /note-improvement; the sweep assigns it
            rel = path.relative_to(PROJECT_ROOT)
            if not ID_RE.match(ident):
                problems.append(f"{rel}:{lineno}: ID {ident!r} is not IMP-NNN")
            elif ident in seen:
                problems.append(f"{rel}:{lineno}: ID {ident} already used by {seen[ident][:44]!r}")
            else:
                seen[ident] = title
    assert not problems, "\n".join(problems)
    assert len(seen) > 50, f"only {len(seen)} IDs parsed; the ID scan is not seeing the files"


# --------------------------------------------------------------------------- #
# Check 4: the two files do not overlap in meaning
# --------------------------------------------------------------------------- #


def test_live_file_holds_no_closed_entries() -> None:
    stranded = [
        f"{lineno}: {fields.get('ID', '(no ID)')} is {fields['Status']!r} -- {title[:44]!r}"
        for lineno, title, fields in _entries(LIVE)
        if fields.get("Status") in CLOSED_STATUSES
    ]
    assert not stranded, (
        "closed entries are still in the live backlog; run "
        "`python scripts/sweep_improvements.py` to archive them:\n" + "\n".join(stranded)
    )


def test_archive_holds_no_open_entries() -> None:
    if not ARCHIVE.is_file():
        pytest.skip("no archive file yet")
    wrong = [
        f"{lineno}: {fields.get('ID', '(no ID)')} is {fields.get('Status')!r} -- {title[:44]!r}"
        for lineno, title, fields in _entries(ARCHIVE)
        if fields.get("Status") not in CLOSED_STATUSES
    ]
    assert not wrong, "the archive is for closed entries only:\n" + "\n".join(wrong)


# --------------------------------------------------------------------------- #
# Check 5: every entry is a `###`, or heading-based tools cannot see it
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", BACKLOG_FILES, ids=BACKLOG_IDS)
def test_entries_use_h3_headings(path: Path) -> None:
    """Three entries were `##` and every `###` tool, including the sweep, skipped them."""
    stray = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if lineno == 1:
            continue  # the file title
        if line.startswith("## ") and not line.startswith("### "):
            stray.append(
                f"{path.relative_to(PROJECT_ROOT)}:{lineno}: {line.strip()[:60]!r} is an `##` "
                f"heading. Entries must be `###` or heading-based tools skip them silently."
            )
    assert not stray, "\n".join(stray)
