# Trial funnel drought — Aug 13–17, 2026

**Verdict: the funnel is not broken.** Re-verified end to end on live production on Aug 17,
including the Stripe-hosted card form. The drought is real and now the 2nd-longest on record,
but every mechanical layer is healthy and the behavioural break sits *upstream* of payments.

Updated 2026-08-17 after the Aug 16 investigation's tripwire came due.

---

## Current state (Aug 17, ~21:00 UTC)

- **Last trial: Aug 13, 05:05 UTC.** Gap is now **4.7 days**.
- Ranks **#2 of 99** gaps over 76 days. Record is 4.90 d (Jun 16 → Jun 21), which self-resolved.
- Signups (auth.users): Aug 13 = 1, then **0 on Aug 14, 15, 16, 17**.
- Today produced 4 genuine checkout sessions, 0 completions.

## What was verified working on Aug 17

| Layer | Evidence |
|---|---|
| `/upgrade` | Renders fully — pricing, "7-day free trial", working CTAs, 0 console errors |
| Stripe card form | Walked the real path. Shows "7 days free", "Then $6.99 per month starting August 24, 2026", card + Apple Pay + Link + Cash App + Klarna, live "Start trial" button |
| Checkout API | **2 × HTTP 429 and 9 × HTTP 500 in 24h** across the whole site. The IP rate limiter is not blocking anyone |
| Rankings job | Ran Aug 17 13:13 UTC, success. `ranking_history` updated 15:26 UTC. Rankings are fresh |
| Stripe billing | Renewals charging normally; an Aug 8 trial converted to paid Aug 15 on day 7 |

## The actual signal: drop-off is at first touch, not at payment

Adding `email_entered` (did the visitor type an email into Stripe's form) to the session ledger
is what cracked this. Across 135 sessions, Jul 17 → Aug 16:

- **35%** of sessions have an email entered
- **32%** complete
- → once someone types their email, **~91% convert**

During the drought: **13 genuine sessions, 1 email entered, 0 completions.**

The collapse is at the *first interaction on Stripe's page*, before anything Radar, 3-D Secure,
or card processing could touch. That is not a payments failure. It means the traffic arriving at
checkout is not buyer traffic.

P(≤1 email entry in 13 sessions | p=0.35) ≈ **3%, about 1 in 34**. Notable, not extreme.

### Close precedent

**Jul 29–31: 9 sessions, 1 email entered, 0 completions** — structurally identical to Aug 14–17.
It resolved on its own on Aug 1 with 4 completions and no code change.

## Ruled out

- Any Aug 12–13 commit (#954 GA4, #955 signup page, #957 webhook). #957 merged *after* the last trial and only touches post-checkout provisioning.
- 3-D Secure change — `request_three_d_secure: automatic` is present on pre-cutoff sessions too; it is the default. `payment_method_options: {}` just reflects a payment method being engaged.
- Checkout session config drift — completed and abandoned sessions are field-for-field identical (`amount_total: 0`, same mode, same payment method types).
- Rate limiting / API errors — see table above.
- Stale rankings / failed Monday job — ran clean.
- Supabase auth — health 200, `disable_signup: false`, live 422 validation.

## The structural problem worth fixing regardless

**69,029 HTTP 307 redirects in 24h.** Every logged-out visitor to any `/teams/*` page is bounced
to `/upgrade`. That produced **72,226 requests to `/upgrade` in 24h → 4 checkout sessions**
(0.006%). Bot volume is *growing* — it was ~58k when first measured a day earlier.

Two consequences:
1. Every funnel metric is poisoned; conversion rates computed off `/upgrade` traffic are meaningless.
2. If any of that is real search traffic landing on team pages, those people hit a paywall with
   zero context and bounce. Bad for conversion and bad for SEO.

## The blocking gap

**Human traffic cannot be measured.** Vercel Web Analytics is off, runtime logs retain ~24h, and
`GSC_CREDENTIALS_FILE` is not configured. Every in-DB proxy is too sparse to trend
(newsletter_subscribers: 4 rows ever; user-clicked scrape requests: 5 in 25 days; watchlist adds: ~1/week).

Without it, "did buyers stop arriving?" is unanswerable from this side.

## Next actions

| Action | Who | Why |
|---|---|---|
| **Turn on Vercel Web Analytics** | you, 1 click | Forward-looking traffic. This investigation cost 15+ agents largely because it's off |
| **Check GA4 Aug 10–17** (sessions/users, landing pages) | you — creds are Vercel-only | The one backward-looking read on whether humans stopped arriving |
| Stripe Dashboard → Radar → Blocked, Aug 13–17 | you | Now *low* priority — blocks happen after email entry, and people aren't getting that far |
| Fix `/teams/*` → `/upgrade` 307 for logged-out visitors | eng | 69k/day, poisons metrics, likely costs real conversions and SEO |

**Tripwire, revised:** the Jul 29–31 precedent recovered after 3 days. This one is at 4.7 and
counting. If Tue Aug 18 also closes at zero, the variance explanation is exhausted — treat it as
a demand/traffic problem and go straight to GA4 and Search Console, not to the payment stack.

## Investigation side effects

Probe agents created ~14 live Stripe checkout sessions on Aug 16 and 1 on Aug 17 (all `open`,
unpaid, no card details). They auto-expire in 24h. **Exclude them from Aug 16 metrics** — the raw
Aug 16 count of 16 sessions is ~14 agents and ~2 genuine.
