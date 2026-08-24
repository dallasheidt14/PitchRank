# LLM Council Transcript — Iter-3 Refine-Spec Escalation

**Date:** 2026-04-29
**Subject spec:** `.turbo/specs/tournament-ingest-silent-drops.md`
**Question:** Apply 9 iter-3 findings, or break out of the refine-spec loop?

## Framed Question

Should we apply 9 iteration-3 findings to the spec, or has the refine-spec
loop hit diminishing returns where moving to plan-shells is more valuable?
Pattern: each iteration's "fixes" introduced new flawed assumptions caught
by the next iteration.

Options: (a) apply iter-3, (b) apply only the 3 critical, skip High/Medium,
(c) accept spec as-is and move to plan-shells, (d) different recommendation.

## Advisor Responses

**The Outsider:** Document is the wrong shape for a forensic problem. Stop
refining. Spend 2 hours adding logging/counters and re-run Puri Cup. Reality
of why 441→0 will reorganize the spec more honestly than 9 more findings.
Recommendation: **(d) modified — instrument, then thin spec.**

**The Executor:** Apply 3 criticals only, ship through plan-shells, harden
in PR 2. Acceptance gate measures broken system; write-site table wrong;
trace cardinality conflated — those break the fix itself. High/Medium are
hardening. Recommendation: **(b) with hard stop.**

**The Contrarian:** Spec is at the wrong altitude. Prose keeps disagreeing
with code because no one is executing anything. Reject all three options.
Spike riskiest empirical claims in code: grep writes, run tracer on Puri
Cup, confirm signature change scope. 90 minutes of code beats more prose.
Recommendation: **Reject the framing; spike the claims.**

**The Expansionist:** Pattern is a learning machine, not diminishing returns.
Harvest into a `/refine-ingest-spec` template; codify "min 3 iterations on
production-pathway specs." Apply iter-3 then do a fourth pass to extract
generalizable questions. Recommendation: **(a) plus extraction pass.**

**The First Principles Thinker:** Wrong question. Verification is happening
in code, not spec. The spec is a lossy mirror. Iter-3 didn't find leftover
iter-1 bugs; it found bugs you wrote in iter-2. Cheapest path to truth is
failing payload + logging. Recommendation: **(d) — 50-line instrumentation
patch, let trace dictate the spec, criticals as instrumentation guardrails.**

## Peer Review Highlights

**4 of 5 reviewers** picked First Principles as strongest. Contrarian was
close second. Both share the diagnosis: spec at wrong altitude, code is
ground truth.

**5 of 5 reviewers** picked Expansionist as biggest blind spot — process
romance while production is dark; codifying the pathology rather than
escaping it.

**4 of 5 reviewers** raised a critical point no advisor caught:
**existing memory artifacts already document the failure class.**

- `gotcha_import_games_enhanced_dedup.md` — IMPORT_RESULT silent 5th-drop
  bucket; symmetric `game_uid` causes H+A perspective collisions.
- `gotcha_alias_write_silent_swallow.md` — `_create_alias` bare-except
  swallows DB failures.
- `gotcha_gotsport_per_event_captcha.md` — per-event reCAPTCHA could
  explain extreme rejection rates.

**Reviewer 1** added: 441-record Puri Cup payload should be checked in as
a golden fixture so all phases measure against the same artifact.

**Reviewer 3** added: criticality labels themselves are suspect by induction.
If iter-2 produced 4 SELECTs miscategorized as writes, why trust iter-3's
severity judgments?

**Reviewer 5** added: extreme 441/0 rejection could be schema mismatch or
upstream data issue, not necessarily a matcher bug.

## Chairman's Verdict

### Where the Council Agrees

Refinement loop is producing flawed artifacts faster than it corrects them.
Iter-3 surfaced iter-2 bugs, not iter-1 leftovers. Three of four "stop
refining" advisors converged on instrument-then-spec. Expansionist's
codify-the-pattern dissent was unanimously flagged as wrong.

### Where the Council Clashes

Executor (apply 3 criticals + ship) vs the rest (don't ship spec yet —
instrument first). Substantive: are the criticality labels themselves
trustworthy? Reviewer 3 says no — by induction.

### Blind Spots Caught Only by Peer Review

1. **Existing memory artifacts already document the failure class.** Three
   iterations of fresh prose may be re-deriving knowledge already on disk.
2. **441-record payload as checked-in golden fixture.**
3. **Rank-order findings by trace, not by labels.**
4. **Whether this is even a code fix vs upstream data issue.**

### Final Recommendation: (d), modified — in a specific order

1. **Check memory first, not code.** Open `gotcha_import_games_enhanced_dedup.md`,
   `gotcha_alias_write_silent_swallow.md`, `gotcha_gotsport_per_event_captcha.md`.
   If one already names the silhouette, three iterations were unnecessary
   and a fourth would be too.
2. **Then check IMPORT_RESULT buckets and `team_match_review_queue` for the
   Puri Cup batch.** One SQL query. Tells you whether records were
   matched-then-dropped, never-matched, deduped-out, or never-arrived.
   Collapses 6 of the 9 iter-3 findings to "moot."
3. **Only then instrument** — scoped to the layer the bucket data implicates.
   50-line tracer against the 441-record fixture.
4. **Apply the 3 criticals as guardrails for instrumentation, not as a
   shipping checklist.** Skip High/Medium until the trace says they matter.
5. **Don't move to plan-shells yet.** Empirical claims in the spec
   (write-site table, alias_cache scope, RPC coverage) haven't been
   verified against the running code.

### The One Thing to Do First

Open `gotcha_import_games_enhanced_dedup.md` and run one query against
`team_match_review_queue` + IMPORT_RESULT bucket counts filtered to the
Puri Cup batch. If the bucket distribution names the failure, you're done
with refinement entirely.

## Anonymization Mapping (held during peer review)

- Response A → The Outsider
- Response B → The Executor
- Response C → The Contrarian
- Response D → The Expansionist
- Response E → The First Principles Thinker
