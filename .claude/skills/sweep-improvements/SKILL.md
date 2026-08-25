---
name: sweep-improvements
description: Periodic maintenance pass over PitchRank's improvement backlog - close finished entries, dedupe, re-anchor drifted file references, archive what is done. Use when asked to "sweep improvements", "review the backlog", "clean up improvements.md", "what's still open", "triage the improvement backlog", or before planning a work session from the backlog.
---

# Sweep Improvements

`.turbo/improvements.md` is append-only by construction. `/note-improvement` and
`/self-improve` are the only skills that write it and both only add; nothing on the PR
path closes an entry. So the file drifts in one direction: entries that shipped months
ago still read as open, `Where` anchors point at moved or deleted code, and the same
idea gets noted twice under different titles.

This skill is the counter-pressure. Run it periodically, or before planning work from
the backlog — an agent that picks a "next task" from an unswept backlog will sometimes
pick one that is already done.

## The schema

The live file's header is authoritative; read it first. In short: every entry is a
`###` heading carrying `ID`, `Status`, and the field its status obliges.

| Status | Meaning | Also required |
|--------|---------|---------------|
| `open` | Still wanted, nobody has done it | — |
| `done` | Shipped | `Refs` — the PR, branch or commit |
| `deferred` | Deliberately not now | `Trigger` — what would make it now |
| `dropped` | Will not do | `Refs` — why |

`done` and `dropped` live in `.turbo/improvements-archive.md`. IDs are stable and never
reused, so `IMP-042` resolves to one item forever, in whichever file it currently sits.

## Step 1: Run the mechanical pass

```bash
python scripts/sweep_improvements.py --dry-run
```

It reports what it would change and never writes on `--dry-run`. Read its output before
doing anything: it lists entries whose ID is missing, entries whose status obliges a
field they lack, duplicate IDs, and `Where` anchors naming untracked paths.

Its exit code is non-zero when it found a problem needing a decision. Anchor drift is
**not** such a problem — it is reported for you to read, because many of those paths are
files the entry proposes *creating*.

## Step 2: Decide the entries the script cannot

The script moves and renumbers; it never decides whether something is finished. For each
entry the report raises, and for any entry older than roughly 60 days:

1. **Is it already done?** Check the code, not the entry's own prose. An entry saying
   "awaiting merge" is the most common false open — verify with
   `gh pr view <N> --json state`. Set `Status: done` and write `Refs` naming what closed
   it.
2. **Is it a duplicate?** Search the live file for the same idea under another title.
   Keep the entry with the better evidence, set the other to `dropped`, and make its
   `Refs` name the survivor's ID so the trail is not lost.
3. **Is the premise still true?** An entry can be open and wrong at the same time. Two
   entries here once both named a repo secret the workflow had never read, so acting on
   either would have changed nothing. Correct the `Why` and say in it that you did.
4. **Did the anchor move or vanish?** Re-anchor to where the code lives now. If the code
   is gone entirely, the entry is usually `dropped` — say so in `Refs`.
5. **Is it deferred rather than open?** If nobody will do it until some condition holds,
   set `Status: deferred` and write the condition as `Trigger`. A deferred entry with no
   trigger is just an open one that has been quietly abandoned.

Never delete an entry. Closing it with a reason is what makes the record worth keeping;
deleting it means the same idea gets noted again in three months.

## Step 3: Apply

```bash
python scripts/sweep_improvements.py
```

This assigns IDs to entries that arrived without one and moves newly-closed entries into
the archive.

## Step 4: Verify

```bash
python -m pytest tests/unit/test_improvements_backlog.py -q
```

The test pins the closure vocabulary: it fails on a returning `**Resolved**:` or
`**Status (date)**:` label, a status outside the four, a closed entry with no `Refs`, a
deferred entry with no `Trigger`, a duplicate or malformed ID, a closed entry left in
the live file, an open one in the archive, and an entry written as `##`.

## Step 5: Report

Tell the user what changed: how many entries closed and why, how many were duplicates,
how many anchors were re-pointed, and what is left open. Name the entries you closed —
that list is the part worth reading.

## Rules

- Do not edit `.turbo/improvements.md` by hand to move or archive entries; run the script
  so the ID counter and the two files stay consistent.
- Judgment calls stay with the user. When an entry's status is genuinely unclear — the
  code half-changed, the decision never made — leave it `open` and say so in the report
  rather than guessing.
- Progress notes are `- **Update (YYYY-MM-DD)**:`, never a `Status` variant. The dated
  `Status` label is what fragmented this file the first time.
