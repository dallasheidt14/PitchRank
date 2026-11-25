# Black Friday 2026 sale — design

Status: draft for owner approval, 2026-11-24.

## Intent

Run a four-day sale on PitchRank Premium annual to bring in **new paying annual subscribers and cash
up front**, not free trials. Success is net new paying annual subscribers over the four days. The
build must be reusable: the next sale should be a new settings entry, not a new feature.

## The offer (owner-decided)

- **Window:** Friday 2026-11-27 12:00 AM through Monday 2026-11-30 11:59:59 PM, Arizona time
  (America/Phoenix, UTC-7 all year). In UTC: `2026-11-27T07:00:00Z` up to, not including,
  `2026-12-01T07:00:00Z`.
- **Price:** first year of the existing annual plan for **$47.88** (shown as **$3.99/mo**), charged
  immediately, **no free trial**. It renews at the standard **$69.99/year**. Regular price $69.99,
  32% off.
- **Who can buy:** anyone not currently paying PitchRank monthly or annually. "I don't care who they
  are" — there are no history checks: past trials, people whose cancelled plan has run out, and
  brand-new visitors are all eligible.
- **Still counted as current subscribers (owner, 2026-11-24):** accounts whose card is failing
  (`past_due`, Stripe still retrying) and accounts that cancelled but still have paid time left. No
  sale for them, and nothing about their subscription changes. The checkout refuses them, the banner
  and prompts are hidden from them, and a signed-out purchase by one is refunded under webhook rule
  (c).
- **Existing paying subscribers:** out of scope. They see no sale messaging, and nothing about their
  subscription changes.
- **Customers type no coupon code.** The discount is applied by the server.

## Owner decisions

- Sale settings live in code (one settings file), plus an expiry date on the Stripe coupon as a
  second, independent stop (approach 1 below).
- New customers only (as defined above), Friday through end of Monday.

## Calls made in the conversation (stated to the owner, not objected to)

1. **People in a free trial right now are eligible** (they aren't paying yet). Buying the sale ends
   their trial and starts the paid year, so they end up with one subscription, never two. If the sale
   checkout fails or is abandoned, the trial is untouched. They also *see* the sale: banner and
   prompt visibility goes by subscription status (hidden only for people on a paid plan), not by
   `plan`. Every existing check counts a trialing account as premium, so a plan-based check would
   hide the offer from exactly these people. The trial is ended even when it sits under a different
   Stripe customer with the same email, which is what a signed-out purchase produces. Otherwise it
   would convert on day 7 and double-bill.
2. **A currently paying subscriber who buys while signed out** (so we only learn who they are inside
   Stripe's checkout page) has the new purchase cancelled and refunded automatically, and gets an
   email saying so. This mirrors how the webhook already handles duplicate anonymous trials today.
3. **The copy changes from one day to four.** "ONE DAY / 24 HOURS ONLY" becomes Black Friday through
   Cyber Monday wording. The countdown runs to Monday midnight Arizona time.
4. **Customer-facing pieces ship first,** because they must be live by Thursday night. The admin
   campaign summary ships after the sale starts. It reads after-the-fact data, so nothing is lost.

## Calls made in writing this up (owner to check)

5. **The sale is a third option; the two standard plans stay exactly as they are (owner,
   2026-11-24).** Monthly $6.99 and Annual $69.99, each with its 7-day trial, are unchanged on the
   page and in Stripe. The Black Friday annual card is added beside them and is the visually dominant
   one.
6. **Checkout pages near midnight.** A Stripe checkout page must stay open at least 30 minutes, so
   sale checkouts are set to close at the end of the sale, or 30 minutes after they open, whichever is
   later. Anyone who opens checkout before 11:30 PM Monday has it close exactly at midnight. Someone
   who clicks in the last 30 minutes gets up to 30 minutes to finish. They clicked in time, so we
   honour them. This needs no midnight job; the repo has no Vercel cron, and the GitHub scheduler has
   skipped runs before. The close time is also capped at Stripe's 24-hour maximum. The coupon's
   `redeem_by` is set to **30 minutes after the sale end**. Stripe's docs don't say whether it is
   re-checked when payment happens, and it can't be changed once the coupon exists, so the late
   clickers must not depend on that. The server clock refuses new sale checkouts at exactly midnight.
   The coupon is the backstop beyond that.
7. **Campaign links before and after the sale.** Before Friday, `/upgrade?campaign=black-friday-2026`
   shows the normal upgrade page (no teaser). After Monday it shows a short "The Black Friday sale has
   ended" note above the normal page.
8. **Admin preview** is a query flag honoured only for admin accounts. It shows the banner, the sale
   card and the paywall copy before Friday. It cannot buy: the checkout route decides by the server's
   clock alone and ignores the flag.

## Testing (owner, 2026-11-24: "Test buy on a preview copy")

- **Automated tests** cover every money path with Stripe doubles. They follow the repo's double
  rules: the double records at the terminal call and refuses what Stripe refuses, for example
  `discounts` together with `allow_promotion_codes`.
- **One practice purchase before Friday** on a Vercel preview deployment of the branch, with:
  - Stripe test-mode keys and test price ids
  - a test-mode copy of the coupon
  - a preview-only setting that moves the sale window to "now"
  - Resend, Beehiiv, Telegram and the GA Measurement Protocol keys left blank on that preview
- **Owner setup, about 15 minutes:**
  - test-mode keys and price ids on the preview's environment
  - a test-mode webhook endpoint pointing at the preview URL
  - a way past Vercel's preview protection
- **The preview still reads and writes production Supabase.** The practice purchase therefore uses
  one throwaway email, and that account and profile are deleted afterwards. Choosing this option is
  the owner's OK for that one account.
- **Cases to run:**
  - a signed-out new buyer, in full
  - if time allows, a signed-in trial user switching, to prove they keep Premium after the trial is
    ended

## Approaches considered

1. **Settings in code + Stripe coupon expiry (chosen).** One settings module holds each sale: id,
   start, end, coupon id, display prices, copy. The server checks the clock. The coupon's own
   `redeem_by` (end + 30 minutes) stops it being applied after that, even if our code slips.
   Emergency off: one environment setting, live after a redeploy (a few minutes). Deleting the coupon
   in Stripe stops *new* sale checkouts instantly. Fastest to build. A future sale is a new entry.
2. **Settings in a database table.** Dates are editable and the sale can be killed instantly with no
   redeploy. Costs a migration plus an editing screen, about half a day the Thursday deadline doesn't
   have. Rejected for now. The settings shape should not block moving to it later.
3. **A separate discounted Stripe price.** Rejected: it would renew at the discounted amount unless
   carefully scheduled, which the brief explicitly forbids.

## How it works today (what the change touches)

- **Checkout:** `frontend/app/api/stripe/checkout/route.ts`. It validates the price id against the
  monthly and yearly env prices and sets `allow_promotion_codes: true` on every session. Signed-in
  buyers are refused if they hold an active or trialing subscription, and get a 7-day trial only if
  they never had a subscription. Anonymous buyers always get a 7-day trial, because the email is not
  known until Stripe collects it.
- **Webhook:** `frontend/app/api/stripe/webhook/route.ts`. Anonymous checkout links to or creates a
  Supabase account by email. If that email already had a subscription and the new one is *trialing*,
  it cancels the new one and emails the buyer. **A paid (non-trialing) anonymous checkout from
  someone already paying is not caught; it links the new subscription and double-bills.** That gap is
  why call 2 needs building.
- **Hazard for call 1:** `handleSubscriptionDeleted` sets the profile to `plan: 'free'` by
  **customer id**, whichever subscription was deleted, then routes Beehiiv into the trial-cancel
  automation. Cancelling the old trial after the paid sale subscription starts would therefore
  downgrade the new buyer and send them a "your trial was cancelled" email. The deletion handler must
  act only when the deleted subscription is the one stored on the profile (or when the customer has no
  other live subscription). Check `scripts/reconcile_stripe_subscriptions.py` (runs every 6 hours) and
  `/api/stripe/sync` the same way, for how they pick a subscription when a customer briefly has two.
- **Paywalls:** `middleware.ts` sends every non-premium visitor to `/upgrade` (with `next=`) for
  `/teams`, `/compare` and `/watchlist`. So non-paying visitors never see those pages, and **the
  upgrade page is the main paywall**. Its existing "You were looking at <team>" header and
  `return_to` destination already work. The in-page prompts are `ClutchFactorCard`,
  `TeamInsightsCard` (both `?source=` links with impression and click tracking) and the watchlist
  link.
- **Banner placement:** the root layout (`frontend/app/layout.tsx`) renders `Navigation` for every
  page. Pages are static/ISR, so a server-rendered banner would go stale. Rankings, home, blog and
  state pages are where a non-paying visitor sees it.
- **Analytics:** browser events in `frontend/lib/events.ts` (GA4 via gtag). Purchases are counted
  server-side by the webhook through the Measurement Protocol (`frontend/lib/analyticsServer.ts`,
  `subscription_completed`). The internal analytics dashboard is `frontend/app/(internal)/analytics/`
  (tiles such as `UpgradeFunnelTile`), and the Stripe dashboard is `/mission-control/subscriptions`.

## The design

**Sale settings.** One module (e.g. `frontend/lib/promotions.ts`) exports the list of sales and one
server-side function, "which sale is live at time T", used by every surface. It also has a helper for
the browser that takes a server-supplied "now". The Black Friday entry carries:
- id `black-friday-2026`
- start and end as UTC instants
- the Stripe coupon id (from an env var, so test and live differ)
- display prices ($47.88, $3.99/mo, $69.99, 32%)
- banner and card copy
- the plan it applies to (yearly)

A kill-switch env var forces "no sale live".

**Stripe (owner approves before any live write).** One coupon:
- `amount_off: 2211` USD, `duration: 'once'` (first invoice only)
- `applies_to` the Premium product
- `redeem_by` = the sale end + 30 minutes (call 6)
- name "Black Friday 2026"

Create the same coupon in test mode for the preview. No changes to existing products, prices,
subscriptions or customers.

**Checkout route.** The sale card sends the yearly price plus the sale id. The standard cards send no
sale id and keep today's behaviour, trial included, even during the sale. When the sale id is sent
and that sale is live by the server clock:
- create the session with `discounts: [{ coupon }]` in place of `allow_promotion_codes`. Stripe
  allows one or the other, which also blocks stacking.
- no `trial_period_days`
- `expires_at` per call 6
- metadata `promotion: black-friday-2026` on the session and the subscription, plus campaign and UTM
  values next to the existing `ga_client_id`

Signed-in buyers holding a **trialing** subscription are allowed through (call 1). Active payers are
still refused. A sale id sent outside the window, or with the kill switch on, is refused with an
"offer has ended" message; the route behaves exactly as today for everything else. The client never
sends the coupon.

**Webhook.**
- (a) Sale checkout completed for a customer who also has a trialing subscription: cancel the old
  trial after the new subscription is stored.
- (b) Guard `handleSubscriptionDeleted` (and any Beehiiv routing) so deleting a non-current
  subscription changes nothing.
- (c) Anonymous sale checkout whose email belongs to someone already paying: refund the sale invoice,
  cancel the new subscription, email the buyer, and notify the owner. The existing Telegram notice
  pattern is next to the duplicate-trial code.
- (d) Fire the purchase analytics event once per subscription, keyed on Stripe's event or
  subscription id so retries don't double-count.

**Banner.**
- A client component above `Navigation`, shown only while a sale is live.
- Hidden for premium and admin accounts. Admins see it in preview.
- Decided from the shipped sale settings and a server "now" (a tiny cached endpoint or the response
  `Date` header), so a wrong browser clock can't show it outside the window. Checkout still decides
  on its own.
- Desktop copy: "BLACK FRIDAY: Get a full year of PitchRank Premium for just $3.99/mo. — Claim Offer".
  Mobile copy: "Black Friday: Premium for $3.99/mo."
- Live countdown to the end instant, so it is the same in every time zone.
- Dismissible for the session.
- Not in the server HTML, so crawlers and SEO see nothing; keep layout shift minimal.
- Brand: Forest Green `#0B5345` with the site's existing accent, Oswald display type. The brief's
  "lime green" maps to the existing accent token rather than a new colour.

**Upgrade page.**
- During the sale a third card, the Black Friday card, is added and is visually dominant. The
  existing Monthly and Annual cards are unchanged. The sale card has:
  - "Black Friday Exclusive" label and countdown
  - $3.99/mo effective, "$47.88 billed today for your first year", $69.99 struck through, "32% OFF"
  - the existing feature list, "Premium access starts immediately"
  - the renewal line "Renews at $69.99/year. Cancel anytime."
  - CTA "Unlock Premium"
- The paywall header line changes from "Start your free trial…" to Black Friday wording.
- `?campaign=` handling per call 7.
- Feature copy uses the page's existing `FEATURES` descriptions. Nothing new is claimed.

**Paywall prompts.** `ClutchFactorCard`, `TeamInsightsCard` and the watchlist link swap their
upgrade line for "Unlock this and a full year of Premium for $3.99/mo — Black Friday only" while the
sale is live. Links keep their `source` and team parameters.

**Analytics events** (GA4, names as the brief gives them):
- browser: `black_friday_banner_view`, `black_friday_banner_click`, `black_friday_offer_view`,
  `black_friday_checkout_started`
- server, from verified Stripe events: `black_friday_purchase_completed` and
  `black_friday_checkout_expired`

Event names derive from the sale id, so the next sale gets its own names with no code change.
Properties: source and page, campaign and UTM, segment (new / trial switch), price, transaction id,
revenue. `black_friday_monthly_upgrade` is dropped, because monthly subscribers are out of scope.

**Admin summary (after launch).** A Black Friday tile or section showing:
- checkout starts and completed purchases from Stripe (sale metadata)
- new paid subscribers and trial switches
- gross revenue and revenue by channel (UTM)
- banner views and clicks from GA4

## Goals / non-goals / anti-goals

- **Goals:** automatic start and stop with no deploy; exact $47.88 first invoice; $69.99 renewal;
  one subscription per buyer; reusable settings.
- **Non-goals:**
  - changing existing subscribers
  - monthly-to-annual switching
  - marketing emails
  - a database-backed promotion editor
  - changes to ranking, entitlement or free-user permissions
- **Anti-goals (failure even if it "works"):**
  - anyone double-billed
  - anyone losing Premium because of a sale checkout
  - a renewal at $47.88
  - the sale showing or selling outside the window
  - a cheap-looking pop-up

## Constraints

- **Deadline:** customer-facing pieces live and verified by Thursday 2026-11-26, 11:59 PM Arizona.
- **Stripe API version:** pinned in `frontend/lib/stripe/server.ts`. Verify fields against the
  installed typings.
- **Live Stripe access** from this machine is the MCP connector, live mode only. Test-mode keys must
  be set on a preview deployment by the owner.
- **Owner approval required** before creating the live coupon, merging, or deploying.
- **Public repo:** no business figures or live Stripe ids in committed files.

## Left to the builder

- exact file and component names
- how the server "now" reaches the banner
- banner dismiss storage
- test structure (mirror the existing route tests and `frontend/test/fixtures.ts`)
- the email template for the signed-out refund, modelled on `sendDuplicateSubscriptionEmail`
