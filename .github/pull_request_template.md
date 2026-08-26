<!--
Before merging:

- `python scripts/pr_wait.py` waits out the Codex review window (about 10 minutes
  from open), prints whatever it found, then merges. It exists because `gh pr checks`
  reports run status only, and the findings live on the review.
- `claude-review` is red on every PR and is not a required check. The seven `ci.yml`
  checks are the gate.
- If this finishes a `.turbo/improvements.md` entry, close it here: set
  `- **Status**: done` and add a `- **Refs**:` line naming this PR.
-->

## What changed

<!-- What it does and why. Prose beats a bullet list for anything non-obvious. -->

## Verification

<!-- What you ran and what it said. A green gate is not verification of a doc change:
     doc claims need checking against the code they describe. -->

## Notes for review

<!-- Anything a reviewer would otherwise have to reconstruct: an alternative you
     rejected, a line you drew around scope, a follow-up you left open. -->
