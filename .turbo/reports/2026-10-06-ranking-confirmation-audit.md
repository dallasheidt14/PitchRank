# Confirmation-month audit — October 6, 2026

## Decision

Use **November 1–30, 2026** for independent confirmation, training through **October 31**, with the decision in early December. October independence could not be established. This is the owner's approved conservative fallback, not a finding that October definitely contaminated this package.

The owner selected “Not sure—verify first.” November has not started, so its outcomes cannot have informed today's frozen design. Keep the code, comparisons and rules fixed. The completed September evidence remains screening only.

## Evidence inspected without opening October outcomes

- Saved plan revisions supplied by the owner, especially `Untitled (3).md` (October 4). Its later sections fix the combination and order the combination-versus-incumbent comparison before the ceiling candidate. Earlier “October unseen” statements are claims, not a complete audit of every development activity.
- Original run provenance and freeze manifests. All formal September candidate runs `board-LG-*` use the August 31 cutoff. Earlier development runs `board-G0-main`, `board-G1-goalclip`, `board-G2-final` and `board-G3-rounds500` use a snapshot dated October 1. The date alone does not prove which October games it contains or what informed the final package.
- Metadata-only inspection of the original development transcript: relevant tool-call dates, script names and evaluation date arguments; no game outcomes or result payloads were displayed. The explicitly dated scoring commands found target September 1–30. October 1 appears in earlier freeze commands. This targeted history is not proof about every other chat or design decision.
- Completed September reproduction, source receipts and release history through `a50dbfb29`. Original, C1 and release sources still match the measured hashes. A separate incumbent worktree at `8338d25a7` was prepared and matches all nine archived engine-file hashes.

No October game file or October scorecard was opened during this audit. The October-containing original snapshot remains untouched. File hashes and source references are recorded in the [design record](../plans/ranking-confirmation-lock.json); transcripts and raw datasets are not committed.

## Recovered comparison family

The original September screen compared `scf`, `gender` and `young` with three-way Holm adjustment. The later October 3 owner decision fixes one combination, and the revised October 4 plan explicitly lists combination versus incumbent, then the ceiling candidate versus combination. The archived combination-versus-incumbent report names `scfgender` alone.

The independent first stage therefore preserves the later fixed family `scfgender` and the existing Holm calculation (one hypothesis in that family). This does not change any September verdict or reopen the dropped changes. The original three-way screen is preserved as historical evidence. The full package is a separate, prerequisite-gated second stage; C1 alone is diagnostic, not another confirmation hypothesis.

## What is locked, and what is not

The release source, three comparison roles, C1 diagnostic source, configurations, runtime, scorer, capture tooling, rules, month and five-run inventory are frozen now. No ranking source was edited and no ranking run started.

The executable evaluation lock deliberately has `locked=false`, `outcomes_unseen_at_lock=false`, `locked_at=null` and no training-manifest hash. October 31 inputs do not yet exist as a complete training window. Bind them and validate the recorded runs before creating a new final lock, and before accessing November outcomes. Never mark the current template ready just to satisfy the scorer.
