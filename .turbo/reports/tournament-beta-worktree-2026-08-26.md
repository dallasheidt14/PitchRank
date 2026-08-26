# Retired worktree: `C:/PitchRank_tournament_beta` — 2026-08-26

Removed on 2026-08-26 as part of item 8 of the agent-readiness plan. This is the record of
what was on that disk and where each piece went.

## The branch was never at risk

The worktree had `shell/gotsport-tier-section-parser-02` checked out at `0818f99d6`, and
`origin` holds that same branch at that same commit. Its **33 unmerged commits are on the
remote** and were untouched by the removal. Verified immediately before removing:

```
origin: 0818f99d6bff23f3f88fc04cc9f65f2aa3e9f489
wtree : 0818f99d6bff23f3f88fc04cc9f65f2aa3e9f489
```

What was unique to that disk was 12 modified/deleted tracked files and 8 untracked paths.

## What was kept

| File | What it is |
|---|---|
| `tournament-beta-src-2026-08-26.patch` | The uncommitted `src/` changes — 5 files, net −90 lines. Apply with `git apply` from the repo root against `shell/gotsport-tier-section-parser-02`. |
| `tournament-beta-run_intake.ps1` | The only hand-written untracked file. |

The `src/` patch reads as a **half-finished backout of a `cohort_champions` feature**:
`schema.py` drops the field from `EventReportCard` and both its serializers, and
`event_compute.py` and the two report templates drop the code that populated and rendered it.
It was archived rather than committed precisely because it looks mid-thought — committing it
would have recorded an unfinished revert as branch history.

## What was not kept

Generated output and build artifacts, ~47 MB in total:

- `models/point_in_time_tournament_margin_postsnapshot_poisson_draw_gate_v1/` — 37 MB
- `reports/gotsport__42433__unknown/scenarios/` — 10 MB
- `reports/gotsport__{42433,42434,44692,49371}__*/` intake and report output — ~1.6 MB
- `.pytest_cache/`, `.ruff_cache/`, empty `data/` directories

The tracked half of that generated output (report JSON/JSONL under `reports/`) is in the full
1.4 MB patch left at `.turbo/archive/tournament-beta-tracked-2026-08-26.patch` on the machine
that ran the removal. That path is gitignored, so it is **local to that machine only** and is
not a durable record. Only the two files above travel with the repo.

## Rebuilding it

```bash
git worktree add C:/PitchRank_tournament_beta shell/gotsport-tier-section-parser-02
```

The worktree will lack `node_modules` and `.env.local`, per the worktree notes in `CLAUDE.md`.
