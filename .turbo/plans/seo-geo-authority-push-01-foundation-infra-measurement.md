---
status: done
spec: C:/PitchRank/.turbo/specs/seo-geo-authority-push.md
---

# Plan: Foundation — Sending Infrastructure + Measurement

## Context

The authority push is gated on two foundations that everything else consumes: a safe way to send batched outreach without burning the primary domain, and a measurement baseline captured *before* any sending so the September 1 scorecard has a valid delta. This shell stands both up. The sending domain's warmup is a 2–3 week long-pole, so kicking it off here lets it run in the background while the list, report, and entity shells proceed. The `outreach_targets` table is the shared store every later shell writes to.

## Pattern Survey

### Analogous Features
- `supabase/migrations/20251113150557_add_scrape_requests.sql` (origin/main) — **strongest mirror for `outreach_targets`**: a status-workflow tracking table with `id UUID DEFAULT gen_random_uuid() PRIMARY KEY`, `status TEXT DEFAULT 'pending'` (bare TEXT, no CHECK/ENUM), lifecycle `*_at TIMESTAMPTZ` columns, a partial index `... (status) WHERE status='pending'`, and RLS (anon-insert + service-role-update + read-all).
- `supabase/migrations/20260329000000_create_report_card_leads.sql` (origin/main) — contact/segment capture analog: `source TEXT DEFAULT '...'` (segment-like), `created_at`, `idx_rcl_email`, RLS anon-insert.
- `supabase/migrations/20260414000000_create_model_training_runs.sql` (origin/main) — the `updated_at` convention: `update_<table>_updated_at()` plpgsql fn + `BEFORE UPDATE` trigger, `COMMENT ON TABLE`.
- `.turbo/geo/run_baseline.py` + `.turbo/geo/_recheck_geo.py` (repo `.turbo`, local) — **the GEO panel re-measurement tool**: `_recheck_geo.py` re-runs OpenAI+Gemini live and writes dated `recheck-YYYY-MM-DD.md` + `responses-YYYY-MM-DD/` JSON. Re-invoke for the week-0 baseline; do not rebuild.

### Reusable Utilities
- `.turbo/geo/run_baseline.py` — `analyze(text, brand_terms, competitors)` and per-engine callers `call_openai`/`call_gemini` returning `(text, citation_urls, model)`; inline `.env` loader from `C:/PitchRank/.env`; `responses/` disk-cache so re-runs only hit newly-configured engines.
- `.turbo/geo/_recheck_geo.py:11-18` — network prologue: `socket.getaddrinfo` → IPv4-only + `truststore.inject_into_ssl()`. **Load-bearing on this machine** (Norton MITM breaks Python HTTPS — memory `env_norton_tls_interception`). Any new baseline script must include it.
- `~/.claude/skills/google-search-console/scripts/gsc_client.py:80` — `SearchConsoleClient.query(...)` wraps `searchanalytics().query()` + `list_sitemaps()` only (scope `webmasters.readonly`). Used for search-analytics totals/context.
- `~/.claude/skills/google-search-console/scripts/_pull_roadmap.py` — working GSC pull wrapper on this machine (IPv4+truststore applied).

### Convention Anchors
- **Migration naming:** `supabase/migrations/<14-digit-timestamp>_<snake_case>.sql`.
- **Table DDL:** `CREATE TABLE IF NOT EXISTS <table>` (surveyed migrations do NOT prefix `public.`), `id UUID DEFAULT gen_random_uuid() PRIMARY KEY`, `TIMESTAMPTZ DEFAULT NOW()`, `COMMENT ON TABLE`.
- **Status columns = bare `TEXT DEFAULT '...'`; NO Postgres ENUMs anywhere** (`CREATE TYPE … AS ENUM` = zero hits across 134 migrations). High-churn workflow tables (`scrape_requests`) deliberately omit CHECK to avoid migration friction. → **Decision (confirmed): `status TEXT DEFAULT 'queued'`, no CHECK.**
- **Index naming:** `idx_<table>_<col>`; partial index for the hot status filter.
- **RLS:** `ENABLE ROW LEVEL SECURITY` + explicit policies (service-role UPDATE).
- **Apply path:** Supabase MCP `apply_migration` (cleaner here) or `supabase db push`.
- **Snapshot artifacts:** dated markdown under `.turbo/geo/` and `.turbo/seo/` (`# Title — YYYY-MM-DD` + tables, sibling `responses-YYYY-MM-DD/` JSON). Sept-1 scorecard already specced in `.turbo/geo-playbook-2026-04-29.md` (Week 20, ~lines 246-266): save at `.turbo/geo/scorecard-2026-09.md`, measure **delta from baseline**.

### Load-Bearing Absences / Risks
- **GSC Links (backlinks) report has NO API.** `gsc_client.py` does search-analytics + sitemaps only; the Links report (referring domains, top linking sites) is UI-export-only. → **Decision (confirmed): source the backlink baseline + Sept-1 referring-domain count from a manual GSC Links UI export + Ahrefs Webmaster Tools (free tier); `outreach_targets` is the source of truth for outreach-*attributable* links.** The plan must not assume API backlink access.
- **All outreach/Instantly/sending-domain/warmup infra is greenfield** (no in-repo prior art; the only email code is the transactional Resend layer, not reusable for cold sequences).
- **Sending-domain name unresolved:** `getpitchrank.com` is out — `pitchrank.com`/`.com` is unavailable/not ours (brand is **pitchrank.io**). Choose a pitchrank.io-aligned secondary domain (e.g. `getpitchrank.io`, `pitchrankhq.com`, `trypitchrank.com`) at provisioning; referenced below as `<sending-domain>`.
- **Baseline branch:** the working tree is on feature branch `fix/modular11-events-division-mapping`; create the migration on a branch off `origin/main`.

## Implementation Steps

1. **Provision the dedicated sending domain + start warmup** (external ops; document settings, no repo code)
   - Register `<sending-domain>` (a pitchrank.io-aligned secondary domain — NOT `pitchrank.com`, which is unavailable). Configure SPF, DKIM, DMARC on it. Leave `pitchrank.io` MX/mail untouched.
   - Connect `<sending-domain>` to **Instantly**, create the mailbox(es), and start auto-warmup (2–3 weeks). Record the final domain name + plan tier in this plan's runbook section when chosen.
2. **Configure the deliverability guardrail** (Instantly config; document thresholds)
   - Set auto-pause when bounce >~3% or spam-complaint >~0.1%; enable a periodic seed-list inbox-placement check. This is the observed-health stop that bounds R3's ramp.
3. **Create the `outreach_targets` tracking table** (new migration)
   - Add `supabase/migrations/<timestamp>_create_outreach_targets.sql`, mirroring `20251113150557_add_scrape_requests.sql` for shape/RLS and `20260414000000_create_model_training_runs.sql` for the `updated_at` trigger.
   - Columns: `id UUID DEFAULT gen_random_uuid() PRIMARY KEY`; `segment TEXT NOT NULL`; `org TEXT`; `contact TEXT`; `verification_status TEXT DEFAULT 'unverified'`; `status TEXT DEFAULT 'queued'` (no CHECK — lifecycle queued→verified→sent→replied→linked/declined); `link_url TEXT`; `notes TEXT`; `created_at TIMESTAMPTZ DEFAULT NOW()`; `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`.
   - Indexes: `idx_outreach_targets_status` (partial `WHERE status='queued'`), `idx_outreach_targets_segment`. Add `update_outreach_targets_updated_at()` fn + `BEFORE UPDATE` trigger. `ENABLE ROW LEVEL SECURITY` + service-role policies. `COMMENT ON TABLE`.
   - Apply via Supabase MCP `apply_migration`.
4. **Capture the week-0 baseline** (before any sending)
   - GEO: re-invoke `.turbo/geo/_recheck_geo.py` (keep the IPv4+truststore prologue + `.env` loader). **Note: the script hardcodes the date** — `RESP = ROOT / "responses-2026-06-02"` and `OUT = ROOT / "recheck-2026-06-02.md"` (lines 24-25), plus the title/baseline-comparison strings. Before running, edit those date constants to the week-0 capture date so it writes a fresh `recheck-<week0-date>.md` + `responses-<week0-date>/` instead of overwriting the June-2 artifacts in place. It measures OpenAI + Gemini only (`ENGINES`, line 29). Treat that dated panel as the week-0 GEO baseline and reference it as such in the scorecard (Step 5). Record OpenAI/Gemini brand-mention + citation rates.
   - Backlinks: pull a manual GSC Links UI export + Ahrefs Webmaster Tools (free) referring-domain count; record both in `.turbo/seo/backlink-baseline-2026-06.md`.
   - Context totals: run `~/.claude/skills/google-search-console/scripts/_pull_roadmap.py` for the search-analytics snapshot.
5. **Define the Sept-1 scorecard**
   - Create `.turbo/geo/scorecard-2026-09.md` from the GEO-playbook Week-20 template (delta-from-baseline; do not promise absolute citation counts). **Scope note:** the playbook template is a 4-engine matrix (ChatGPT/Claude/Perplexity/Gemini + cross-engine ≥3-of-4), but this foundation measures the 2 engines the recheck panel covers (OpenAI + Gemini), matching the R20/R21 targets; the Claude/Perplexity columns and the ≥3-of-4 cross-engine cut are out of scope here. Record targets: +15–25 net-new referring domains, indexation ≥60%, OpenAI ≥75% & Gemini ≥75%. Document the attributable-vs-organic method: cross-reference referring domains against `outreach_targets.link_url` (attributable) vs the rest (organic).

## Verification

- **Migration:** after `apply_migration`, `outreach_targets` appears in `list_tables`; `execute_sql` an INSERT then an UPDATE and confirm `status`/`verification_status` defaults and that `updated_at` advances on UPDATE (trigger works); confirm `idx_outreach_targets_status`/`_segment` exist and RLS is enabled.
- **GEO baseline:** the dated `.turbo/geo/recheck-YYYY-MM-DD.md` + `responses-YYYY-MM-DD/` exist; `_recheck_geo.py` completes OpenAI+Gemini with no TLS/`WinError 10060` failures (IPv4+truststore prologue present); brand-mention/citation numbers recorded and tagged as the week-0 baseline.
- **Backlink baseline:** `.turbo/seo/backlink-baseline-2026-06.md` exists with a referring-domain count from GSC export + Ahrefs free.
- **Scorecard:** `.turbo/geo/scorecard-2026-09.md` exists with the targets + attribution method.
- **Sending infra (manual checks):** SPF/DKIM/DMARC validate on `<sending-domain>` (e.g. an MXToolbox/DMARC check); Instantly warmup is running; `pitchrank.io` mail flow unchanged.
- Edge cases: confirm the migration is created on a branch off `origin/main` (not the stale feature branch); confirm no `public.`-prefixed table name (repo convention).
- **Unrecoverable manual step:** the backlink baseline (GSC Links UI export + Ahrefs free) is the one Step-4 sub-task with no scriptable capture or re-run — its numbers can't be reconstructed later. A missed week-0 backlink count breaks the Sept-1 referring-domain delta, so capture it before any sending begins and double-check the file is written.

## Context Files

- `supabase/migrations/20251113150557_add_scrape_requests.sql` — the table shape/RLS/partial-index pattern to mirror for `outreach_targets`.
- `supabase/migrations/20260414000000_create_model_training_runs.sql` — the `updated_at` trigger-function convention.
- `.turbo/geo/_recheck_geo.py` and `.turbo/geo/run_baseline.py` — the GEO baseline tool + the load-bearing IPv4/truststore network prologue and engine callers.
- `~/.claude/skills/google-search-console/scripts/gsc_client.py` — confirms GSC client is search-analytics only (no Links endpoint), grounding the manual-backlink decision.
- `.turbo/geo-playbook-2026-04-29.md` (Week 20, ~lines 246-266) — the Sept-1 scorecard template + delta-from-baseline guidance.
- `.turbo/specs/seo-geo-authority-push.md` — source spec; this plan covers R1, R2, R4, R19, R20, R21.
