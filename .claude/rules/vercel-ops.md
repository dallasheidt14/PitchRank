# Vercel & Deployment Operations

## Check env vars FIRST when debugging Vercel failures
Before investigating code logic, API versions, or data issues — compare Vercel env var names against code references character-by-character. An entire debugging session was wasted chasing Stripe API mismatches when the root cause was `SUPABASE_SERVICE_KEY` vs `SUPABASE_SERVICE_ROLE_KEY`.

## GITHUB_TOKEN pushes don't trigger webhooks
Pushes made with the default `GITHUB_TOKEN` in GitHub Actions do NOT trigger Vercel or third-party webhooks. If a workflow needs to trigger a Vercel deploy, use a Personal Access Token instead.

## Check CI health first for payment/webhook issues
When investigating Stripe webhook or payment failures, check GitHub Actions reconciliation workflow health first. The problem is often upstream (failed sync, stale data) rather than in the webhook handler itself.
