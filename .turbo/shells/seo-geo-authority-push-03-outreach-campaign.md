---
spec: C:/PitchRank/.turbo/specs/seo-geo-authority-push.md
depends_on: [seo-geo-authority-push-01-foundation-infra-measurement, seo-geo-authority-push-02-target-list-build, seo-geo-authority-push-04-keystone-report]
---

# Plan: Outreach Campaign — Templates, Sequences, Launch

## Context

This is the execution shell where the warmed domain, the verified list, and the keystone report converge into actual sending. It builds the tiered per-segment sequences (~150–250 verified sends/week, ~80% segment-templated + ~20% high-touch), authored in PitchRank brand voice, with the three offer angles. It enforces the link-scheme guardrail on the snippet/resource asks, ramps volume safely, runs the report's media pitch + Reddit seed, and defines the numeric pivot to community seeding if replies stay flat.

## Produces

- Tiered, per-segment email sequences (3–5 steps each, increasing gaps, breakup email, single interest-based CTA) with load-bearing token personalization, avoiding the banned-phrase list.
- The three offer assets in use: editorial data-story angles, a static data-snippet generator (copy-paste HTML / branded PNG with attribution link, reusing OG/infographic tooling), and a resource-page pitch.
- The link-scheme guardrail in practice: branded/varied anchors, editorial-link preference, identical-snippet links kept a minority of the mix.
- A configured ramp (≤20/day → ~150–250/wk batched target) and a defined pivot trigger (reply rate <~1–2% after ~3–4 weeks / ~600 verified sends → community seeding).
- The keystone report's distribution: media-segment pitch + neutral r/youthsoccer seed, logged in `outreach_targets`.

## Consumes

- Warmed sending domain + Instantly + deliverability guardrail — from Shell 1.
- `outreach_targets` tracking table — from Shell 1.
- Verified, segmented target list with personalization signals — from Shell 2.
- Published keystone report (the lead asset for media/blogger pitches) — from Shell 4.
- OG/infographic tooling for the static data snippet — from existing codebase.
- Organization author entity (`pitchrank-team`) that outreach asset bylines attribute to (R18) — from existing codebase (Shell 5 strengthens this entity but it pre-exists, so no hard dependency).

## Covers Spec Requirements

- R3
- R7
- R8
- R9
- R10
- R11
- R16

## Implementation Steps (High-Level)

1. **Author tiered per-segment sequences**
   - Write the 80%-templated segment sequences with real tokens + the ~20% high-touch tier, in brand voice, banned-phrase-clean, interest-based CTAs.
2. **Build the offer assets**
   - Editorial data-story angles; the static data-snippet generator (HTML + branded PNG with attribution link); the resource-page pitch.
3. **Apply the link-scheme guardrail**
   - Branded/varied anchors, prefer editorial links, cap identical-snippet share.
4. **Configure ramp + pivot**
   - Set the ≤20/day → batched ramp and the numeric pivot checkpoint (~600 sends / ~3–4 weeks).
5. **Distribute the report**
   - Run the media-segment pitch and the r/youthsoccer seed; log all transitions in `outreach_targets`.

## Open Questions

- Whether sequence authoring/sending lives entirely in Instantly vs. partly scripted — resolve at expansion.
- Exact per-segment token set and high-touch selection criteria — resolve at expansion using Shell 2's stored signals.
- Reuse path for the static data-snippet generator against existing OG/infographic routes — resolve via survey at expansion.

## Expansion Deferred

The following are filled in when `/expand-shell` runs:

- Pattern survey against the codebase state at implementation time
- Concrete `file_path` references with named functions or symbols for each Implementation Step
- Verification section with specific test commands and smoke checks
- Context Files section with the files to read in full before editing
