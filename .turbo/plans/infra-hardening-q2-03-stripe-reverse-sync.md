---
type: shell
status: draft
spec: .turbo/specs/infra-hardening-q2.md
depends_on: []
---

# Plan: Stripe Reverse-Sync

## Context

When PitchRank's `checkout.session.completed` webhook fails after Stripe creates a customer but before the DB profile is updated, an orphan is created — the customer pays but has no `stripe_customer_id` in `user_profiles`. The existing reconciliation script only queries users with non-null `stripe_customer_id`, so these orphans are invisible. Orphans can be created after just 1-2 webhook attempts due to `isPermanentError()` returning HTTP 200 for "already exists" errors.

This shell adds a reverse-sync script that queries Stripe for all active subscriptions and checks for missing DB links, auto-linking by email where possible and alerting on remaining orphans.

## Produces

- New script `scripts/reverse_sync_stripe.py` with cursor-based Stripe pagination, batch Supabase queries, auto-link by email, orphan alerting via Resend, and `--dry-run` flag
- New GitHub Actions workflow `.github/workflows/reconcile-stripe-reverse-sync.yml` running daily
- Alert fallback: GH Actions step fails (exit code 1) if Resend email delivery fails

## Consumes

- Existing forward-sync script — from existing codebase (`scripts/reconcile_stripe_subscriptions.py`) for pattern reference
- Existing GH Actions workflow — from existing codebase (`.github/workflows/reconcile-stripe-daily.yml`) for workflow pattern reference
- Resend email configuration — from existing codebase (`RESEND_API_KEY`, `ALERT_EMAIL` env vars, same email patterns as forward-sync)
- Stripe SDK — from existing codebase (`stripe` Python package in `requirements.txt`)
- Supabase SDK — from existing codebase (`supabase` Python package in `requirements.txt`)

## Covers Spec Requirements

- Spec §3: Stripe Reverse-Sync — Problem (invisible orphans)
- Spec §3: Stripe Reverse-Sync — Failure Scenarios (isPermanentError fast-orphan path)
- Spec §3: Stripe Reverse-Sync — Solution (reverse-sync logic with pagination, auto-link, alerting)
- Spec §3: Stripe Reverse-Sync — Integration (new script + GH Actions workflow)
- Spec §3: Stripe Reverse-Sync — Alert Fallback (fail GH step + stdout logging)
- Spec §3: Stripe Reverse-Sync — Pagination Mechanics (Stripe starting_after + Supabase .range())
- Spec §3: Stripe Reverse-Sync — Verification
- Spec §3: Stripe Reverse-Sync — Known Limitations (race condition, email-only alerting)

## Implementation Steps (High-Level)

1. **Create reverse_sync_stripe.py script**
   - Fetch all active Stripe subscriptions with cursor-based pagination (starting_after, 100/page)
   - Extract customer IDs and emails from subscriptions
   - Batch-query user_profiles for matching stripe_customer_id values (.range() for batches of 1000)
   - Identify orphans: Stripe customers whose ID appears in no user_profiles row
   - Auto-link: if user_profiles row exists with matching email but null stripe_customer_id, update it
   - Collect remaining unlinked orphans for alerting

2. **Add alerting via Resend**
   - Send email to ALERT_EMAIL with orphan details (customer ID, email, subscription status)
   - If Resend fails, log orphans to stdout and exit with code 1

3. **Add --dry-run flag**
   - When set, output orphans and auto-link candidates without making DB changes or sending email

4. **Create GitHub Actions workflow**
   - Schedule: daily cron (e.g., `0 8 * * *`)
   - Manual trigger: workflow_dispatch with dry_run input
   - Pass required secrets: SUPABASE_URL, SUPABASE_SERVICE_KEY, STRIPE_SECRET_KEY, RESEND_API_KEY
   - Mirror structure of existing reconcile-stripe-daily.yml

5. **Verify reverse-sync behavior**
   - Run with --dry-run against production data
   - Verify pagination handles multiple pages correctly
   - Verify auto-link logic matches by email correctly
   - Verify alert email sends

## Open Questions

None

## Expansion Deferred

The following are filled in when `/expand-plan-shell` runs:

- Pattern survey against the codebase state at implementation time
- Concrete `file_path:line_number` references for each Implementation Step
- Verification section with specific test commands and smoke checks
- Context Files section with the files to read in full before editing
