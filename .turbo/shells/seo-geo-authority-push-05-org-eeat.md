---
spec: C:/PitchRank/.turbo/specs/seo-geo-authority-push.md
depends_on: []
---

# Plan: Organization E-E-A-T Enrichment

## Context

The smallest workstream: strengthen the existing `pitchrank-team` Organization entity's trust signals so the brand reads as a credible, established source to both Google's quality model and AI engines. Per the operator's privacy choice, this stays Organization-only — no personal Person entity and no contributor byline (the GEO author-veto ceiling is an accepted MVP limitation). Independent of all other shells; can be done anytime.

## Produces

- Enriched homepage/author `Organization` JSON-LD: `foundingDate`, `knowsAbout`/methodology linkage, scale proof points, and `sameAs` (Wikidata Q139785143 + social profiles).
- The Organization established as the canonical author/byline entity (author reference in structured data) plus the byline convention that the report (Shell 4) and outreach assets (Shell 3) follow when they attribute to PitchRank — consistent with the no-fabrication rule. (Shell 5 defines the entity and convention; the asset-creating shells apply it as part of their own work.)

## Consumes

- Existing `pitchrank-team` Organization entity / `AuthorEntitySchema` + homepage structured-data components — from existing codebase.
- Wikidata entity Q139785143 — from existing codebase (already linked via `sameAs`).

## Covers Spec Requirements

- R17
- R18

## Implementation Steps (High-Level)

1. **Enrich the Organization JSON-LD**
   - Add `foundingDate`, `knowsAbout`/methodology link, scale proof points, and confirm `sameAs` includes Wikidata + socials. No Person node.
2. **Wire Organization byline**
   - Ensure report + outreach assets attribute to the Organization, no fabricated persona.

## Open Questions

- Exact component file(s) holding the Organization JSON-LD and whether enrichment belongs there vs. a shared constant — resolve via survey at expansion.
- Which scale proof points to surface (and keep them in sync with `product-marketing.md`) — resolve at expansion.

## Expansion Deferred

The following are filled in when `/expand-shell` runs:

- Pattern survey against the codebase state at implementation time
- Concrete `file_path` references with named functions or symbols for each Implementation Step
- Verification section with specific test commands and smoke checks
- Context Files section with the files to read in full before editing
