---
status: done
---

# Plan: Black Friday 2026 sale

## As built (2026-11-24; review fixes and owner changes 2026-11-25)

Every step below shipped. These details differ from the text that follows:

- **The sale starts Wed 2026-11-25 00:00 Arizona, not Friday (owner, 2026-11-25, before merge):**
  "I want to turn it on now. And still have it run through until dec 1 1am like we already have
  planned."
  - `startsAt` is `2026-11-25T07:00:00Z`, already past at merge, so the sale goes live when the merge
    deploys. The end is unchanged: new sale checkouts stop at 00:00 Tue 2026-12-01 Arizona
    (`2026-12-01T07:00:00Z`), an open one can still finish within its 31 minutes, and the coupon's
    `redeem_by` stays an hour after the end, the owner's "1am".
  - Below, "four days" means six and "Friday" means the new start. The "Before Friday" checks that
    need a sale still upcoming (`upcoming`, two cards, admin preview, the refused sale checkout)
    cannot run; the other "Before Friday" checks and the "At 00:00 Friday" checks run once, right
    after the merge deploys.
  - The sale copy stays as written, including the paywall line's "Black Friday through Cyber Monday
    only" (owner, 2026-11-25, when asked).
- **No practice purchase on the preview (owner, 2026-11-25),** so Owner step 1's test-mode setup and
  Verification's practice purchase were not done. In their place, one unpaid sale checkout was
  opened on this branch's preview against live Stripe, with the live coupon and a four-hour
  preview-only window: Stripe showed $47.88 today, then $69.99 per year, a "Black Friday 2026" line
  of -$22.11, no trial and no code box. Nothing has yet run the webhook against real Stripe events;
  watching the first real purchases and the daily sweep cover that. The owner created the live
  coupon by hand (the Stripe connector refuses writes). Its id lives only in Vercel settings, for
  production and for this branch's preview, whose window was then closed; never in the repo.
- **Upgrade grid:** three columns from `lg` (1024px) up, not `md`. At 768px three columns clipped the
  existing Yearly button ("Start Free Trial — Best Va…"). On tablets the sale card takes its own row
  above Monthly and Yearly, which keep their two-column row; phones are as planned (sale first).
- **Banner reaches the top edge (owner, 2026-11-24, after the screenshots).** The banner carries the
  header's safe-area padding while it shows (`html.promo-banner-visible header.safe-top` drops the
  header's). The header's total height, and so `--site-header-height`, is unchanged from the plan.
- **The client hook is one module-level store** (`useSyncExternalStore`) shared by the banner and the
  upgrade page, not per-component state over a shared promise. It runs one refresh timer and one
  1-second ticker. It returns `state`, `promotion`, `preview`, `isLive` and `remainingMs`; nothing
  read `offsetMs`, so it stays internal, and the plan's `loading` was dropped. `promo_preview=1` is
  read once, when the store starts, so preview needs a full page load with the flag.
  - The banner stays subscribed for the whole campaign period, so "the next mount retries" a failed
    first request never happens. Instead, until it has an answer, the store retries every 30 seconds
    at most (every 5 seconds in the 90 seconds after the start and after the end, and at the start
    itself when that comes sooner). Only an answer corrects the browser's clock, so until then neither
    the start nor the end by that clock delays the retries past 30 seconds or stops them.
  - A page load that began outside a campaign period checks the bundled sales again whenever a
    component subscribes, first or not, so a tab kept open into a campaign period starts asking at its
    next subscribe (opening /upgrade, or a re-render that mounts the banner), without a reload.
  - Each request is abandoned after 10 seconds, through a timer set by hand: `AbortSignal.timeout` is
    missing from Safari before 16 and Chrome before 103, which the site's browser targets include.
  - One request runs at a time; the one in flight schedules the next.
- **A customer created in the same request** skips the open-session expiry and the post-expiry
  re-check: it can hold no sessions or subscriptions yet.
- **Both branches refuse on filtered lists, at all times (supersedes step 4's "Standard requests keep
  their order" and its `status: 'all', limit: 10` history).** A first page of `status: 'all'` can hide
  a live subscription behind ten cancelled ones. A standard checkout reads `trialing` then `active` (a
  sale adds `past_due`), in the order a subscription moves, so one that changes status mid-check is
  still in a later list. A one-row `status: 'all'` list read after them decides the trial (standard)
  or the segment (sale); its newest subscription is refused on too, so one started during the check
  is caught. Both re-check the same statuses after the expiry, so a sale paid in that instant gets no
  second subscription, while past_due can still re-subscribe. `lib/plan.ts` holds
  `STANDARD_REFUSED_STATUSES`/`isStandardRefusedStatus` and `LIVE_SUBSCRIPTION_STATUSES`; the webhook
  uses `isStandardRefusedStatus` to choose which email a blocked signed-out trial gets.
- **The checkout route writes a new Stripe customer only onto a profile that still has none.** A
  signed-out purchase that linked the account meanwhile, or a checkout opened at the same instant in
  another tab, keeps the customer it wrote; this request answers 409 "Your account changed while
  checkout was starting. Please try again." (owner, 2026-11-25, from the review). An unconditional
  write could split an account from the purchase just linked to it.
- **Signed-out profile writes are conditional on the Stripe customer and subscription the handler
  read** (`.is(null)` or `.eq(prior)` for each). Two concurrent purchases for one existing account do
  not both link, and neither does a guest sale racing a signed-in checkout on the account's own
  customer: the later one matches no row, Stripe retries it, and the retry meets the linked account,
  so it is classified as a duplicate. The one exception is the delivery that created a brand-new
  login: when a twin delivery of the same checkout found that empty profile by email and linked it
  first, the creator still goes on to send the set-password email and write the sign-in marker,
  which only it sends, and then stops: the twin has already sent the signup notice, the newsletter
  steps and the purchase event.
- **A delivery whose email-matched profile already holds its own subscription returns at once**: a
  concurrent delivery of the same checkout linked it between the two lookups. Without it, a standard
  trial delivered twice at once could cancel itself as a "second trial".
- **A cancelled sale subscription is still checked, and refused on a hit, with no alert and no email
  (supersedes Decisions' "suppresses only the alert" and step 5's check 0).** Linking it would demote
  the account it duplicated. With no hit, the email path still links it only to a never-billed free
  account, where it records the cancelled status.
- **A standard signed-out trial under a comped account's email is cancelled, not linked (owner,
  2026-11-25, from the review).**
  - "Comped" means premium or admin with no Stripe ids at all.
  - It takes the same path as a paying subscriber's second trial: cancelled with no charge, the
    "already subscribed" email, and a Telegram notice.
  - A re-delivery of the cancelled trial is ignored. Linking it would let anyone typing such an email
    into a signed-out checkout overwrite the account.
- **A refused `createUser` whose re-read finds the profile not yet linked throws**, so Stripe retries
  rather than raising a false `account_exists_unlinked` while a concurrent delivery is still linking.
  The branch keys on GoTrue's `email_exists` code. The installed client sends API version
  2024-01-01, and GoTrue's source builds its duplicate-email error with that code; the hosted
  service's answer was not observed.
- **The duplicate alert** reads "whether a profile points at it" from the matched profile, with no
  separate lookup. It lists up to 100 subscriptions per live status, and labels `amount_total` as the
  checkout total. The buyer's refund email is sent first, so the alert can say whether it went out.
  The blocked-trial notice says the same about its own email.
- **The sale's source is resolved one way** (`saleAttribution` in `app/upgrade/page.tsx`): the URL's
  attribution, then the session's first touch, then the page's own source. The Stripe metadata (and
  so `purchase_completed`) and the `source` of `offer_view` and `checkout_started` use it, each
  resolved when it fires. A banner claim on /upgrade after the view rewrites the stored source, so,
  when the page URL carries no `source`, that checkout is credited to the banner while its view was
  not.
- **Test doubles:**
  - `filteringClientMock.failOn` also takes `skip` and `times`.
  - `filteringClientMock` runs every query against the table as it stands when the query is awaited,
    `.single()` and `.maybeSingle()` included, so two guarded writes built before either is awaited
    see each other, as PostgreSQL would. As PostgREST does, it filters, then sorts by every `order`
    key in the order given, then pages; `.in()` keeps the values it was given. `.eq(col, null)`
    matches no row, as PostgREST's `eq.null` does.
  - The server-import check (`test/server-imports.test.ts`) scans every route handler under `app/`
    (`route.ts/.tsx/.js/.jsx`) rather than step 10's six named files, and follows `.js`/`.jsx` modules.
  - `route.test.ts` keeps its hand-built Supabase double, extended to chain the guarded write. Its
    signed-out cases are re-tested against the filtering double in `route.promotion.test.ts`, for
    sale and standard sessions.
- **`useInCampaignPeriod`** reads the clock in a `useSyncExternalStore` snapshot rather than step 6's
  post-mount effect: the repo's purity lint refuses `Date.now()` during render.
- **Upgrade page:** the feature list and the "Processing..." spinner became small local components
  shared by all three cards; the Monthly and Yearly markup is otherwise unchanged.
- **The daily duplicate sweep** remains a by-hand read-only procedure (Verification), not code.

Verified locally:
- **CI gate:** the frontend half is green; 2,000+ vitest tests pass.
- **Mutation runs:** every guard mutation from the build and its four review rounds was killed by a
  named new test, on the full suite in an isolated worktree; guards a mutation first survived gained
  the test that kills them.
- **Production build** with the preview window override and a local fake Stripe, checked at 375,
  768, 1024 and 1280, and in WebKit at 375:
  - the banner and menu stay pinned
  - phone search and the rankings filter bar sit below the header, with and without the banner
  - dismissing the banner shrinks the header by 40px
  - a signed-out and a signed-in free sale checkout each reached Stripe with the coupon, no trial and
    no promotion codes; the signed-in one used a throwaway login, deleted afterwards
  - after the window, the campaign link shows the ended notice and checkout refuses the sale

## Context

The owner wants a four-day sale on PitchRank Premium annual, to bring in new paying annual subscribers
and cash up front rather than free trials. The approved design is
`docs/superpowers/specs/2026-11-24-black-friday-sale-design.md`. It is the source of truth for every
product decision; read it first.

In short:
- **Window:** Fri 2026-11-27 00:00 through Mon 2026-11-30 23:59:59 America/Phoenix. In UTC that is
  `2026-11-27T07:00:00Z` up to `2026-12-01T07:00:00Z`, end not included.
- **Offer:** the first year of the existing $69.99 annual price for $47.88, through a one-time
  $22.11 coupon. No trial, charged today, renews at $69.99.
- **Upgrade page:** a third, visually dominant "Black Friday" card beside the **unchanged** Monthly
  $6.99 and Annual $69.99 cards.
- **Banner:** site-wide, in a top bar above the menu (owner's pick), with a countdown.
- **Paywall:** Black Friday wording where non-paying visitors actually meet the paywall: the
  `/upgrade` page that middleware sends them to, including its "you were looking at" team header.
  The in-page overlays are unreachable for them and stay unchanged (step 8).
- **Links and tracking:** campaign and UTM links, and GA4 funnel events.
- **Preview:** an admin-only look before the start.
- **Eligibility:** anyone without a live subscription. Current payers, people in a free trial
  (owner, 2026-11-24, after the plan review), failing-card (`past_due`) accounts and
  cancelled-but-paid-up accounts all count as current subscribers: no sale. Because of that, no
  account ever holds two live subscriptions on purpose.
- **Duplicate purchases** (a current subscriber buying while signed out, or one person paying
  twice) are not undone by code. The webhook leaves the account alone, alerts the owner on
  Telegram, and emails the buyer that a refund is coming. The owner refunds and cancels it in
  Stripe by hand (owner, 2026-11-24).
- **This supersedes the design's calls 1 and 2** (trial users eligible; automatic refund) and
  several details after them. **Where the design and this plan differ, this plan wins.** Step 11
  updates the design doc to match.

**Deadline.** This must be merged and deployed, with the live coupon in place, before Thu 2026-11-26
11:59 PM Arizona. Deploying early is safe, because every surface is gated by the server-side window.

**Owner approval** is needed before each of these: the live coupon is created, the PR is merged, or
production is deployed.

The admin campaign summary is **out of this plan**. It ships after launch, under its own plan, with
counting rules designed against the real purchase data.

## Branch and local-state setup

- **Build only in the worktree `C:\pitchrank-black-friday`,** branch `feat/black-friday-sale`, off
  `origin/main` `908e90c85`. The branch already carries the design commit `31de4781a`.
- **Never edit `C:\PitchRank`.** That shared checkout sits on an unrelated branch with someone
  else's staged work, and is weeks behind `origin/main`.
- **Before the first edit:**
  1. Run `git -C C:/pitchrank-black-friday status -sb`. Expect a clean tree, ahead of `origin/main`
     by the design commit and this plan.
  2. Run `git -C C:/pitchrank-black-friday diff origin/main --stat -- frontend/`. Expect it empty.
  3. If either shows foreign changes, stop and ask.
- **The worktree has no `frontend/node_modules`.** Junction it from `C:\PitchRank\frontend\node_modules`
  as the `fresh-worktree-setup-on-pitchrank` memory describes, then run vitest and tsc in the
  worktree. Remove the junction through `scripts/clean_merged_worktrees.py`, never with a bare
  `git worktree remove`.
- **Review with `/review-code` against `git -C C:/pitchrank-black-friday diff`.** `/code-review`
  reviews the session's start checkout, not this worktree.
- **The repo is public.** No live Stripe ids (coupon, price, customer, subscription) and no business
  figures in any committed file, test fixture or PR text. Use env-var names and obvious fakes.

## Pattern Survey

Survey run 2026-11-24 against the worktree (HEAD = `origin/main` 908e90c85 + design commit). Paths are
relative to `C:\pitchrank-black-friday`. Stripe typings were read from
`C:\PitchRank\frontend\node_modules\stripe`, which is 21.0.1, the same version as the worktree's
`package-lock.json:11620-11622`.

### Analogous Features

**Checkout route**
- `frontend/app/api/stripe/checkout/route.ts:12-21`: `baseSessionParams(priceId, returnTo)` builds
  the shared params. `allow_promotion_codes: true` is hard-set at :18 on every session, so a sale
  branch has to remove it, not add `discounts` next to it.
- `checkout/route.ts:34-55`: the body is `{ priceId, next }` and nothing else. The price is checked
  against `getStripePriceIds()` plus both `NEXT_PUBLIC_STRIPE_PRICE_*` env values.
- `checkout/route.ts:57-62`: `sessionMetadata` (`ga_client_id`, `return_to`) goes on the session
  only. Subscription metadata is just `supabase_user_id` (:134) or `anonymous_checkout` (:153), and
  the tests pin "never onto the subscription".
- `checkout/route.ts:79-84` and `:114-122`: two refusal gates.
  - The profile is refused when `plan==='premium'` and status is `active|trialing`.
  - Then `stripe.subscriptions.list({status:'all', limit:10})` refuses on any `active|trialing`
    subscription.
  - `past_due` passes both gates today. That is deliberate (webhook `route.ts:319-324`).
  - "Cancelled with time left" is an `active` subscription with `cancel_at`/`cancel_at_period_end`
    set, so the `active` check already refuses it.
- `checkout/route.ts:125,133`: a trial is given only when `allSubs.data.length === 0`. The anonymous
  branch always gives a trial (:151-154) and sets the `checkout_browser` cookie (:147, :157-158).
- `checkout/route.ts:160-166`: any throw becomes a generic 500. Business refusals are `{ error }`
  JSON with status 400.

**Webhook**
- `frontend/app/api/stripe/webhook/route.ts:244-503`, `handleCheckoutCompleted`:
  - Skips unsettled sessions (:255-260), re-fetches the subscription (:263) and builds
    `baseUpdates` (:265-271).
  - Looks up the profile by customer id (:276-281). A signed-in checkout writes through
    `updateUserProfile` (:285-290).
- Signed-out checkout, linked by email (`webhook/route.ts:304-371`):
  - The duplicate-trial cancel runs only when the new subscription is `trialing` and the account has
    billing history (:317-351).
  - It calls `stripe.subscriptions.cancel` (:328), then sends `sendDuplicateSubscriptionEmail` or
    `sendReturningSubscriberEmail` depending on `alreadySubscribed` (:325-336; an email failure is
    non-fatal). It then sends a Telegram `notifyAdmin` (:341-349) and returns without touching the
    profile.
  - **Double-bill gap:** a paid (`active`) signed-out checkout from someone already paying falls
    through to :362-371. That overwrites the profile's `stripe_customer_id`/`stripe_subscription_id`
    with the new customer, and the old subscription keeps billing.
- `webhook/route.ts:355-358`: a re-delivered blocked duplicate reads `canceled` and is ignored. A
  refunded sale purchase that is re-delivered is covered by the same guard.
- `webhook/route.ts:456-458`: `sendSubscriptionCompleted(session.metadata?.ga_client_id)` fires on
  every delivery where `plan==='premium'`. There is no dedupe;
  `.claude/skills/stripe-billing-data/SKILL.md:186-189` confirms a re-delivery counts twice.
- `webhook/route.ts:485-502`: Beehiiv tag and lifecycle are upserted every time. Enrollment is
  skipped when the stored prior status equals the new one (:494-498). The same prior-status check is
  used at :567-570 and :641-644; it is the only idempotency mechanism in the webhook.
- `webhook/route.ts:512-544`, `handleSubscriptionUpdated`: it re-fetches the subscription, then writes
  `stripe_subscription_id: current.id` (:526), status and plan by **customer id**, for whichever
  subscription the event names. A late `customer.subscription.updated` for an old trial would
  re-point the profile, just as the delete handler would.
- `webhook/route.ts:549-585`, `handleSubscriptionDeleted`:
  - Writes `plan:'free'`, `stripe_subscription_id:null` by customer id with no check that the
    deleted subscription is the stored one (:553-559).
  - Routes Beehiiv to `trial_canceled` when the prior status was `trialing` (:578).
  - If no profile holds the old trial's customer any more (re-pointed at :362-365),
    `updateUserProfile` throws "No user profile found". `isPermanentError` (:36-43) turns that into a
    200, and Beehiiv is skipped.
- `webhook/route.ts:590-627` (`handleInvoicePaid`) and `:632-672` (`handleInvoicePaymentFailed`) also
  write by customer id with no current-subscription check.
- `webhook/route.ts:689-703`, `handleChargeRefunded`: a full refund calls
  `syncLifecycle(customerId,'paid_canceled')`. That resolves the email from the Stripe customer
  (:66-74, :114-123) and enrolls it in the win-back automation. **Refunding a signed-out sale
  purchase by a current payer** (separate customer, same email) would therefore put that payer's
  Beehiiv lifecycle into `paid_canceled`.
- `frontend/lib/stripe/server.ts:55-65`: `WEBHOOK_EVENTS` has no `checkout.session.expired`. A new
  event type needs an entry here, a case in the switch (webhook `route.ts:154-219`), and adding to the
  Stripe endpoint's event list.

**Sync and reconcile (picking a subscription when a customer has two)**
- `frontend/app/api/stripe/sync/route.ts:57-72` always uses the session's own subscription. It writes
  subscription id, status and plan, not `cancel_at_period_end`.
  - Signed in (:75-125): refuses when the profile's customer differs (:94-95, :109-110).
  - Signed out (:129-154): updates by customer id, or returns 202.
  - Nothing checks that the session's subscription is the profile's current one. Re-syncing an older
    completed session (such as the original trial checkout) would write `canceled`, which means
    `plan: free`.
- `scripts/reconcile_stripe_subscriptions.py:75-93` calls
  `stripe.Subscription.list(customer=..., limit=1)` with no `status`. That relies on Stripe's default
  of non-cancelled subscriptions, newest first (Stripe behaviour, not repo code).
  - While a trial and a sale overlap on one customer, it picks the newer sale subscription, so it
    does not downgrade. Once the trial is cancelled it drops out.
  - It reads only the profile's `stripe_customer_id` (:59-72), so it never sees a separate refunded
    sale customer.
  - It writes plan, status and subscription id (:166-180), and deliberately not
    `cancel_at_period_end` (:171-173).
  - `dashboard.py:1394,1473` uses the same `limit=1` pattern, for display only.

**Upgrade page**
- `frontend/app/upgrade/page.tsx`:
  - :21-24: `PRICE_IDS` come from `NEXT_PUBLIC_*` env vars.
  - :26-36: `FEATURES` has five entries `{icon,title,text}`.
  - :50-55: state is `loadingPlan` (`'monthly'|'yearly'|null`), `selectedPlan` (default yearly) and
    `yearlyFirstOnPhones`.
  - :76: `source` is `next || source || 'direct'`. Campaign and UTM params are not read anywhere.
  - :79-103: the tapped-team header uses `safeTeamPath` and `api.getPaywallTeamPreview`; its copy
    "Start your free trial…" is at :192.
  - :117-145, `handleUpgrade`: waits for `userLoading`, calls
    `trackPlanSelected`/`trackCheckoutInitiated` with hard-coded 6.99/69.99, calls
    `startCheckout(priceId, tappedTeamPath)`, and shows errors in the banner (:222-229, scrolled into
    view at :113-115).
  - :265: the cards sit in a `md:grid-cols-2` grid. Monthly is :267-323 and Yearly :326-396
    (`order-first md:order-0` on phones, :331). Trial copy is in each card footer and the final CTA
    (:507-533).
  - The page never checks subscription status.
- `frontend/app/upgrade/page.test.tsx`:
  - The `next/navigation` mock builds params from `state.next` only (:17-19).
  - The `useUser` mock returns `{user,isLoading}` with no `profile` (:20).
  - The `@/lib/events` mock exports exactly three functions (:21-25).
  - `planCard()` finds `[data-slot="card"]` by text (:47-52).
  - Tests pin two cards in one `md:grid-cols-2` grid, Monthly before Yearly (:141-149), and
    `startCheckout(priceId, next)` (:196-227).
- `frontend/lib/stripe/client.ts:7-29`: `startCheckout(priceId, next)` posts `{priceId, next}`,
  throws the server's `error` text, and redirects.

**Paywall prompts**
- `frontend/components/ClutchFactorCard.tsx:54-59,89-97,115-158` and
  `TeamInsightsCard.tsx:43-48,79-87,115-178` share one shape:
  - A `hasPremiumAccess(profile)` gate, and an impression event on mount when not premium.
  - An overlay line ("Unlock clutch-game splits" :137, "Unlock AI-powered team analysis" :158).
  - A link to `/upgrade?source=<feature>&team=<id>` that calls `trackPaywallUpgradeClicked`
    (:139-151, :159-171).
- `frontend/app/watchlist/page.tsx:268-291`: the non-premium block links to bare `/upgrade` (:281),
  with no source and no tracking.
- `frontend/components/paywall-upgrade-link.test.tsx:11-18,44-60`: mocks `useUser`/`hasPremiumAccess`
  and events, and pins the exact href and a single link.
- `frontend/middleware.ts:5,102-141` gates `/teams`, `/compare` and `/watchlist` by plan
  (`premium|admin`).
  - Signed-out visitors go to `/upgrade?next=<path>` (:105-110).
  - Signed-in non-premium users go to `/upgrade` **with no `next`** (:132, :138).
  - So the in-page prompts render only when the browser's profile disagrees with middleware. One such
    case: `useUser`'s profile fetch fails and `profile` becomes null (`hooks/useUser.ts:107-112`),
    which shows prompts to a paying user. In practice the upgrade page is the paywall.

**Site-wide banner, countdown, server time**
- No site-wide banner or announcement component exists. `frontend/app/api/announcements/route.ts:14-36`
  is a database-backed public GET, used only by `app/infographics/page.tsx`.
- Countdown precedent: `frontend/components/MissingGamesForm.tsx:126-140` uses `useEffect` with
  `setInterval(update, 1000)`, recomputes from `Date.now()`, and clears on unmount.
- Relative-time helpers are local copies: `app/mission-control/leads/page.tsx:45-56` and
  `app/mission-control/subscriptions/page.tsx:61`.
- No code passes a server "now" to client components. Nothing reads the `Date` header and there is
  no time endpoint.

### Reusable Utilities
- `frontend/lib/stripe/server.ts:29-39`: `stripe`, a lazy Proxy. The API version is pinned to
  `'2026-03-25.dahlia'` (:18), which matches the installed `types/apiVersion.d.ts:3`.
- `server.ts:45-50`: `getStripePriceIds()` returns `{MONTHLY, YEARLY}` from `STRIPE_PRICE_*`, falling
  back to `NEXT_PUBLIC_*`. YEARLY is the price the sale reuses.
- `server.ts`, other helpers:
  - `isSessionPaymentSettled` (:72-74).
  - `extractPeriodEnd` (:80-86).
  - `mapStatusToPlan` (:92-94): `trialing` and `past_due` map to premium.
  - `isCancellationScheduled` (:106-109): reads `cancel_at` or `cancel_at_period_end`. This is the
    existing "cancelled with time left" test.
  - `updateUserProfile` (:118-140): writes by customer id and throws "No user profile found…", which
    the webhook treats as permanent.
- `webhook/route.ts:50-60` `getPriorState`, `:66-74` `getCustomerEmail`, `:98-123`
  `enrollInLifecycleAutomation`/`syncLifecycle`, `:30` `escapeHtml`: all private to the module, so
  reusing them means editing in place.
- `frontend/lib/notifications/admin.ts:14-45`: `notifyAdmin(html)` sends to Telegram, best-effort,
  never throws.
- `frontend/lib/email/duplicate-subscription.ts`: an HTML template function plus
  `sendDuplicateSubscriptionEmail(email): Promise<boolean>`.
  - It returns early when `resend` is null (`lib/email/resend.ts:4`), never throws, and sends from
    `'PitchRank <noreply@mail.pitchrank.io>'`.
  - `returning-subscriber.ts:49` has the same shape. There are no unit tests for either module; the
    webhook mocks each one.
- `frontend/lib/analyticsServer.ts`:
  - `gaClientIdFromCookie` (:8-10).
  - `sendSubscriptionCompleted(clientId)` (:24-52): a Measurement Protocol POST with a 3s timeout that
    never throws and is skipped in dev or when secrets are missing. The event name is hard-coded
    (:44) and it sends no params. Tests are in `lib/analyticsServer.test.ts`, which stubs `fetch` and
    env.
- `frontend/lib/analytics.ts:39-55`: `gtagEvent(name, params)` drops null/undefined, does nothing in
  dev, and queues through a shim (:18-30).
- `frontend/lib/events.ts:243-297`: typed funnel wrappers, one `trackX` per event. Payload types are
  in `frontend/types/events.ts:94-107` (`plan?: 'monthly'|'yearly'`).
- `frontend/hooks/useUser.ts`:
  - `UserProfile` (:8-20) includes `subscription_status` and `cancel_at_period_end`, but no UI
    component reads either; only API routes use `subscription_status`.
  - `hasPremiumAccess` (:25-28) is plan-based (`premium|admin`), so it is true for trialing accounts.
  - `hasAdminAccess` (:33-36).
  - The hook exposes `error` when the profile fetch failed (:107-112).
- Admin checks: `frontend/lib/supabase/admin.ts:14` `requireAdmin()` on the server. On the client,
  `hasAdminAccess` is used in `components/TeamHeader.tsx:86` and `components/GameHistoryTable.tsx:159`.
- `frontend/lib/api/optionalAuth.ts:13-34` `optionalAuth()`, and `lib/api/rateLimit.ts`
  `checkRateLimit`/`getClientIp`.
- `safeTeamPath` (`lib/auth/emailTokens`): the shared `next` sanitiser, used in checkout :58, webhook
  :444 and the upgrade page :80.
- `frontend/lib/admin/timezone.ts:19` `BUSINESS_TIMEZONE = 'America/Phoenix'`, plus `wallClockDate`
  (:21-51). The file starts with `import 'server-only'` (:1), so a client banner cannot import it.
- `frontend/lib/reports/report-card.ts:19-21` `reportCardUpgradeUrl`: the only existing UTM-tagged
  `/upgrade` link builder.
- `frontend/lib/stripe/checkoutBrowser.ts:13-28` `newCheckoutBrowserKey`: the cookie for signed-out
  checkouts. Its 24h maxAge matches Stripe's session lifetime.
- `frontend/lib/constants.ts:205-207` `SECRET_QUERY_PARAMS`/`SECRET_QUERY_PATHS`: no tag loads on
  `/upgrade/success`, which is why the purchase event is sent from the server.
- Test doubles:
  - `frontend/test/fixtures.ts:195` `makeStripeSubscription` has no `metadata`, `discounts` or
    `latest_invoice`.
  - `:271` `makeStripeInvoice` has `discounts`, `billing_reason` and `parent.subscription_details`.
  - Both are used only by the admin tests and `lib/stripe/__tests__/server.test.ts`, not by the
    Stripe route tests.
  - There is no Checkout Session fixture; `app/api/stripe/sync/__tests__/route.test.ts:69-77` has a
    local `makeSession`.
  - `frontend/test/supabase-mock.ts`: `queryBuilder` (:15-42), `serviceClientMock` (:52-72), and
    `filteringClientMock` (:124), which actually applies filters.
- Stripe typings (`types/Checkout/SessionsResource.d.ts`):
  - `allow_promotion_codes?: boolean` (:20).
  - `discounts?: Array<{coupon?, promotion_code?}>` (:119, :742-752), "only up to one may be
    specified".
  - `expires_at?: number` (:136), "30 minutes to 24 hours after Checkout Session creation".
  - `subscription_data.trial_period_days` (:3341) and `subscription_data.metadata` are present.
- **`discounts` + `allow_promotion_codes` exclusivity is not documented in the installed typings,**
  and the Stripe docs search did not return a page stating it. A double that refuses the pair models
  Stripe's server-side refusal, not anything in the types.
- Refund path on dahlia: no refund code exists in the repo yet. The fields are:
  - `Subscription.latest_invoice` (`Subscriptions.d.ts:147`).
  - `Invoice.payments?: ApiList<InvoicePayment>` (`Invoices.d.ts:343`); there is no top-level
    `payment_intent` or `charge`.
  - `InvoicePayment.payment.payment_intent` (`InvoicePayments.d.ts:81`).
  - `RefundCreateParams` takes `charge` or `payment_intent` (`RefundsResource.d.ts:11,46`).

### Convention Anchors
- **Route test shape:** `__tests__/route.test.ts` beside the route.
  - `vi.hoisted` refs plus `vi.mock('@/lib/stripe/server', …)` with a hand-built `stripe` object.
  - `@/lib/supabase/server` is mocked so `optionalAuth` runs for real (checkout test :32-39); the rate
    limiter is mocked (:27-30).
  - Assertions read `mockCheckoutSessionsCreate.mock.calls[0][0]`.
  - Checkout's `subscriptions.list` is an inline `vi.fn` returning `[]` (:52-54). No test covers
    `trial_period_days`, `allow_promotion_codes` or the active-subscription refusal.
- **Webhook test double:** it mocks `@supabase/supabase-js` `createClient` (test :115-139) with a
  `queueMaybeSingle` queue (:89-95) that separates the customer-id lookup from the email lookup.
  - `updateUserProfile` is a mocked export, so writes through it are asserted by call.
  - The direct `.update(...).eq('id', …)` writes on the signed-out path (route :362-365, :389-392)
    resolve to an inert object and are never recorded. That double is more permissive than
    production, which the repo's double rules warn against.
  - Each describe block has its own `fireEvent(type, object)` helper (:516-523, :996-1003). The real
    `isCancellationScheduled` comes in through `importOriginal` (:10-11).
- **Webhook error policy:** permanent errors return 200, everything else 500 so Stripe retries (route
  :36-43, :222-236). Email, Telegram, Beehiiv and GA side-effects are wrapped and non-fatal.
- **Idempotency:** the only mechanism is comparing the stored `subscription_status` before writing.
  There is no event-id store in `supabase/migrations` and no `idempotencyKey` in any Stripe call.
- **`user_profiles.cancel_at_period_end`** is written only by the webhook handlers that route Beehiiv
  (`server.ts:102-105`; reconcile :171-173).
- **Client-only after hydration:** the precedent reads storage in a post-mount `useEffect`
  (`components/RecentMovers.tsx:34-42`).
- **Root layout constraints:**
  - The root layout has no React Query provider: `app/providers.tsx:6-27` is Tooltip only, and
    `DataProviders` is mounted per section (`frontend/CLAUDE.md:205-212`).
  - `useUser` is per-component, not shared (pitfall 22, `frontend/CLAUDE.md:516-518`), and Navigation
    already calls it (`components/Navigation.tsx:17`).
- **Banner mount point:**
  - `app/layout.tsx:160-170` renders `SiteProviders`, then `WebVitalsReporter`, `Navigation` (:162),
    `main#main`, `Footer`, `Toaster`.
  - Navigation is `sticky top-0 z-50 … safe-top` (`components/Navigation.tsx:40-43`).
  - `--site-header-height` (`app/globals.css:99-103`, with `safe-top` at :183-185) assumes Navigation
    is the only thing at the top, for the sticky elements under it.
- **Brand tokens:** `--primary` is forest green and `--accent` electric yellow
  (`app/globals.css:59-73`); Oswald is `font-display`.
- **Env flags:** a string compare inside a function, e.g. `process.env.X === 'true'`
  (`lib/matchPredictionShadow.ts:15-17`). There is no date-window config module anywhere in
  `frontend/lib`.
- **Event naming:** snake_case, one `trackX` per event (`lib/events.ts:5-9`). The internal GA funnel
  hard-codes its step names (`lib/internal-analytics/queries/ga4-upgrade-funnel.ts:24-27`,
  `ga4-upgrade-sources.ts:51-52`).
- **Cross-file guards:** they scan every non-test `.tsx` under `app/` and `components/`
  (`test/component-sources.ts:4-14`; `centred-containers`, `single-main-landmark`,
  `no-nested-link-button`), so a new banner is checked automatically.
- **Time in tests:** `vi.useFakeTimers({ toFake: ['Date'] })` plus `vi.setSystemTime`
  (`app/api/reports/team-card/__tests__/route.test.ts:98-99`,
  `app/api/watchlist/__tests__/route.test.ts:70`).
- **Downstream readers keyed per subscription:** trial conversion uses `paidSubIds.has(sub.id)`
  (`lib/admin/month-projection.ts:209-219`), so a trial ended by a sale purchase counts as not
  converted. `isActivatingPayment` (:151-153) counts the $47.88 invoice as cash.

### Proposed Alignment
Follow the shapes that already exist. Extend `baseSessionParams` and the body parsing in the checkout
route and keep `{ error }` JSON refusals. Put new Stripe helpers next to `isCancellationScheduled` in
`lib/stripe/server.ts`, model the refund email on `duplicate-subscription.ts`, and add the event
helpers next to `sendSubscriptionCompleted` and `lib/events.ts`.

Some of this has no precedent and has to be built new: the sale settings module, the source of
server time for the client, and the banner. The "is this the profile's current subscription" guard
is also wider than the spec says. It has to cover every handler that writes by customer id
(subscription updated and deleted, invoice paid and failed) and `handleChargeRefunded`, not only
`handleSubscriptionDeleted`.

> **Superseded after the survey (owner rulings, 2026-11-24):** do **not** add that guard. Trial users
> can't buy the sale and one checkout per customer is open at a time, so no account holds two live
> subscriptions on purpose. The only webhook changes are the ones in step 5. The survey above is
> kept verbatim as a record of the code.

Two test doubles need tightening before new tests can lean on them. The webhook's Supabase double
doesn't record direct profile updates. The checkout double has no per-test `subscriptions.list` and no
checkout-session fixture.

## Decisions made while planning

- **Banner placement (owner, 2026-11-24): top bar above the menu,** on every page including
  `/upgrade`, except `/upgrade/success`. There, a buyer who has just paid while signed out would
  otherwise be invited to buy again.
  - **Pinned with the menu (owner, 2026-11-24).** It renders as the first row *inside*
    `Navigation`'s sticky header (`components/Navigation.tsx:40-43`, `sticky top-0 z-50 … safe-top`),
    above the menu row. It sits below the safe-area padding and scrolls with nothing: header and
    banner stay pinned together until the visitor taps ×.
  - **One line, fixed height `h-10` (2.5rem) at every width** (`truncate` for overflow), so the
    header grows by a known amount.
  - **While the banner shows, `<html>` carries the class `promo-banner-visible`**, and
    `app/globals.css` adds
    `html.promo-banner-visible { --site-header-height: calc(4rem + 2.5rem + max(1rem, env(safe-area-inset-top, 0px))); }`.
    Every reader of the variable moves down with it, and `--rankings-sticky-top` derives from it
    already. The readers are the phone search panel (`components/GlobalSearch.tsx:223`, `fixed`), the
    rankings filter bar (`components/RankingsStickyFilters.tsx:32`, `fixed`) and the rankings
    scroll margin (`components/RankingsPageContent.tsx:62`).
  - The banner removes the class when it hides or is dismissed.
  - It appears after the server's answer arrives, so the page shifts down once, shortly after load.
    That is accepted for the four days.
  - On `/upgrade` its link scrolls to the sale card (`#sale`) instead of navigating.
- **Trial users count as current subscribers (owner, 2026-11-24).** They see no sale and checkout
  refuses them, exactly like payers. No sale code path ends a trial or cancels a subscription. No
  "current subscription" guard is added to the subscription and invoice webhook handlers.
  - *Prototype note (2026-11-24):* the existing `/api/stripe/sync` signed-in branch does re-point
    `stripe_subscription_id` to whatever session the success page names (`sync/route.ts:57-72`),
    before the webhook runs. So in the same-customer race below, the profile may already point at
    either subscription. That is why the alert lists both subscriptions rather than naming one.
- **Duplicates are refunded by the owner by hand (owner, 2026-11-24).** The owner judges every
  duplicate, and the code's job is to make sure each one reaches them with enough detail to decide.
  - **Scope: sale sessions only** (sessions whose metadata carries `promotion`), exactly as
    prototyped. Standard checkouts keep today's handling. A wider scope was tried on paper and
    dropped: the scoped review found it would redden about 15 existing webhook tests and stop a
    never-billed cancelled checkout from linking (`webhook/route.ts:353-369`; `route.test.ts:1104`).
  - **Invariant for sale sessions.** Every exit from `handleCheckoutCompleted` for a settled sale
    session does one of two things:
    - (a) links the subscription to a profile, or
    - (b) writes a `console.error('[webhook] PAID_CHECKOUT_NOT_LINKED', { reason, subscriptionId, customerId })`
      line **and** sends `notifyAdmin` with what the owner needs to decide.
    
    A sale always takes money: $47.88, no trial, no promotion codes. The exits measured on sale
    sessions:

    | Exit | Today | Now |
    |---|---|---|
    | the buyer already holds Premium (checks below) | unhandled (new path) | (b), reason `duplicate`, buyer emailed |
    | Stripe customer has no email (`webhook/route.ts:297-300`) | `console.error`, 200, no alert | (b), reason `no_email` |
    | `createUser` refuses "already been registered" and a re-read of the profile by email does not show it already holding this subscription | permanent → 200, buyer not premium, no alert | (b), reason `account_exists_unlinked` |
    | … and the re-read *does* show this subscription linked (a same-session replay won the race) | — | 200, no alert |
    | payment unsettled (`payment_status: 'unpaid'`) | info, 200 | unchanged: `async_payment_succeeded` fulfils it later |
    
    Missing customer or subscription ids (`:244-263`) cannot occur for a subscription-mode session.
    A sale subscription already `canceled` when its event is handled suppresses only the alert; the
    existing link/ignore logic still runs (check 0 below).
  - **What counts as already holding Premium:**
    - an `active`, `trialing` or `past_due` subscription on the same Stripe customer, other than
      this one
    - a profile matched by email whose `plan` is `premium` or `admin` (comped friends, and the
      owner's own admin account if they buy while signed out, which must never be overwritten to
      `premium`), unless its `stripe_customer_id` is this session's customer
    - a profile matched by email whose *different* customer holds an `active`, `trialing` or
      `past_due` subscription
  - **On a duplicate the webhook:**
    - writes nothing to the profile
    - logs and alerts per (b)
    - emails the buyer that they already have Premium and the duplicate purchase will be refunded
      within one business day
    - sends no purchase event
    - returns 200
  - **What the alert carries:** every live subscription involved, for each its id, its customer, when
    it was created, its amount and whether a profile points at it. The owner picks which to refund.
    It does not assert which one is "the" duplicate: in the same-customer race either may be the one
    the profile now points at.
  - **Same-customer duplicates are prevented, not handled.**
    - While a promotion is live, and for 24 hours after its `endsAt` (which also covers a kill
      switch, since a disabled sale's `endsAt` is still ahead), creating *any* checkout session for
      a signed-in customer (sale or standard) first expires **all** of that customer's other open
      sessions, paged to the end.
    - The prototype confirmed every order this blocks:
      - standard then sale
      - sale then standard
      - a late sale session plus a standard one 5 minutes after `endsAt`
      - with the kill switch on
    - What remains is two creation requests from one user in the same instant. That is out of
      bound: the button disables while loading and the route is rate-limited to 5 a minute. The
      same-customer check stays as a safety net.
    - If it fires, a by-hand cancel there runs `handleSubscriptionDeleted` (`plan: free` by customer
      id, untag, lifecycle `paid_canceled`, win-back enrolment), and the refund runs
      `syncLifecycle('paid_canceled')` for that linked customer. Reconcile restores the plan within 6
      hours but not Beehiiv, so the alert says: "after refunding, set this subscriber's newsletter
      lifecycle back to paid, re-add the premium tag and remove them from the win-back automation".
  - **Known gap, left to the sweep (W10, measured):**
    1. A returning profile's old customer has an open signed-in **standard** checkout.
    2. The buyer completes a guest sale, which links the profile to the new customer.
    3. The old standard checkout is then paid. That completion carries no `promotion`, finds no
       profile by its customer, falls to the email branch, and re-links the profile to the
       full-price subscription, at info level only.
    
    The sale subscription is left unlinked and billing. The daily sweep surfaces its customer as a
    candidate, with the email's profile and its current subscription listed beside it, and the owner
    decides. Fixing it in code would mean running detection on standard checkouts, the scope
    dropped above.
- **A failed alert is caught by a daily sweep, not by machinery.** `notifyAdmin` is best-effort and
  never throws, so every (b) exit also writes its `PAID_CHECKOUT_NOT_LINKED` error line.
  - Each morning of the sale, and after it, a read-only check lists **candidates for the owner to
    review**:
    - live subscriptions created since the campaign start whose Stripe customer no `user_profiles`
      row holds
    - customers holding two live subscriptions
  - It skips anything created in the last hour, because a legitimate new guest's customer is
    unlinked until fulfilment completes and sync answers 202 in that interval
    (`sync/route.ts:127-147`).
  - For each candidate it shows:
    - all of that customer's live subscriptions, including any created before the campaign
    - the profile, if any, that the customer's email matches, and that profile's current
      subscription
    - the session's payment status
  - It never says "refund this one"; the owner decides (see Verification).
- **Server time and the kill switch reach the browser through one small endpoint,**
  `GET /api/promotion`.
  - It is cached `public, s-maxage=30` with no stale-while-revalidate. The client adds the
    response's `Age` header (seconds, when present) to `serverNow`, so a cached copy doesn't run the
    clock late.
  - The sale appears within about 30 seconds of 00:00. A tab left open during the sale refetches
    every 5 minutes, so an emergency off reaches it within about 6 minutes of the redeploy.
  - The kill switch is a server-only env var, so the browser never decides on its own. The exception
    is admin preview, which renders from the bundled settings and can never buy.
  - Outside a campaign period the browser does not call the endpoint at all. The hook first checks
    the bundled `PROMOTIONS`; with no entry starting within 7 days or ended within 30 days, it
    returns "none" without a request.
- **Purchase events have no dedupe gate.** The sale purchase event is sent as the **last** action of
  a successful sale fulfillment, after every write. A throw earlier in the handler causes a Stripe
  retry before anything was sent. `sendServerEvent` never throws, so the handler returns 200 right
  after sending. A duplicate event therefore needs Stripe to re-deliver a delivery we already
  answered with 200, which is rare. Each event carries `transaction_id` (the subscription id), so
  counts can be made distinct.
  
  The rejected alternative was the "profile did not already hold this subscription id" rule. It
  is suppressed whenever `/api/stripe/sync` (called first by `/upgrade/success`,
  `sync/route.ts:57-72`) writes the id before the webhook runs. Stripe stays the source of truth
  for purchase counts.
- **`black_friday_monthly_upgrade` is dropped,** because monthly subscribers are out of scope.
  `black_friday_checkout_expired` needs `checkout.session.expired` added to the Stripe webhook
  endpoint's event list. That is an owner step, for test and live.
- **Deferred, not in this plan:**
  - the admin campaign summary (its own plan, after launch)
  - a database-backed promotion editor
  - the success page shown to a signed-out duplicate buyer: it still says "check your email to set
    your password"; the refund email is what tells them the truth
  - Trial → Paid cards are unaffected now that trials can't buy the sale, so nothing to note
  - **in-page paywall overlays get no sale copy:**
    - `ClutchFactorCard`, `TeamInsightsCard` and the watchlist block sit on routes that
      `middleware.ts:5,102-141` gates by plan, so signed-out and free visitors are redirected to
      `/upgrade` before they render
    - the overlays are reached only by a Premium viewer whose profile fetch failed, who is outside
      the sale audience
    - the paywall the sale audience actually meets is `/upgrade` (step 7), including its tapped-team
      header
  - **UTMs on a link to a premium page** (`/teams`, `/compare`, `/watchlist`) are dropped by the
    middleware redirect (`middleware.ts:105-110`). Campaign links point at `/upgrade`, and the only
    UTM links the repo builds (`lib/reports/report-card.ts:20`) land on `/upgrade` too, so middleware
    is unchanged.

## Prototype record (2026-11-24)

A throwaway build of steps 4–5 ran in a scratch worktree, since removed, to settle the
duplicate-handling sections by running them. It used a stateful Stripe double and
`filteringClientMock` with per-terminal failure injection. Its diff, tests and doubles were kept in
the session scratchpad (`…/scratchpad/bf-proto/`), which may be cleared; they are a reference, not
code to copy blind.

**How it was scoped:**
- Duplicate checks 0–3 were gated on sale sessions (`if (promotionId …)` in its webhook diff).
- The email lowercase, the two lookup throws and the verified `.select('id')` writes ran for
  **every** session.
- With that split, the unchanged existing webhook suite gave 74 of 75; the one failure is named in
  step 10. The unchanged checkout suite gave 14 of 14 on today's clock.

**Exercised and passing (41 new tests):**
- Checkout:
  - open-session expiry in each two-tab order, across midnight, with the kill switch, and across
    two pages with another customer's session left alone
  - no extra calls outside the period
  - every eligibility refusal
- Webhook:
  - the same-customer duplicate (and that `limit: 1` misses it)
  - comped, admin and stale-free email matches
  - a mixed-case email link
  - the customer-id lookup error
  - the already-resolved re-delivery
  - both verified-write failures
  - the refund-lifecycle skip and its positive control
  - the relink orphan (W10)

**What it found:**
- W10 re-links to the full-price subscription. It is left to the sweep: see Decisions, "Known
  gap".
- three silent unlinked-paid exits, now (b) exits for sale sessions:
  - no email
  - an existing auth user with no profile carrying the email
  - two concurrent guest deliveries (which only `Promise.all` interleaving reached; run back to back
    they are a `duplicate`)
- the retry gap after a failed new-account write
- the refusal and coupon ordering
- the error-versus-zero-rows test limit
- the clock-dependent existing checkout tests
- the one existing webhook test that needs a linked profile

**Not exercised:**
- the (b) exits `no_email` and `account_exists_unlinked` as the plan now words them (the prototype
  observed the silent paths but did not implement the alerts)
- the profile re-read after a `createUser` refusal
- real Stripe or GoTrue: mid-payment expiry, real paging, whether GoTrue lowercases emails
- real concurrency (microtask interleaving only)
- the sync route itself (its effect was seeded)
- every client surface: the hook, banner, upgrade page, attribution and client helper
- `/api/promotion` and `PROMOTION_WINDOW_OVERRIDE`
- `checkout.session.expired`
- the Measurement Protocol body
- `notifyAdmin` escaping, the import scan, the rate limit, and the daily sweep

## Implementation Steps

1. **Sale settings module (client-safe) and server resolver**
   - **New `frontend/lib/plan.ts` first.** It has no directive, so client and server code can both
     use it, and exports `hasPremiumPlan(plan)` (`plan === 'premium' || plan === 'admin'`).
     - `hasPremiumAccess` in `frontend/hooks/useUser.ts:25-28` stays where it is for existing callers
       and becomes `profile ? hasPremiumPlan(profile.plan) : false`.
     - **Server code never imports from `hooks/useUser.ts`.** Its line 1 is `'use client'`, and route
       handlers compile in Next's RSC layer, where every export of a client module is a stub that
       throws. A reviewer reproduced this on next@16.2.6: a route calling it returned "Attempted to
       call hasPremiumAccess() from the server". In the checkout route that throw would land in the
       generic 500, so every signed-in sale checkout would fail.
     - `lib/promotions.ts`, `lib/promotions.server.ts`, the checkout route and the webhook import
       `lib/plan.ts` only.
   - New `frontend/lib/promotions.ts`, pure and importable by client and server code (no directive,
     no import from `hooks/`). It exports:
     - a `Promotion` type:
       - `id`, `startsAt` and `endsAt` as ISO UTC strings, `planInterval: 'year'`
       - `campaign` (`black-friday-2026`) and `analyticsPrefix` (`black_friday`)
       - a display block: list price, first-year price, monthly-equivalent price, percent off, and
         `amountCents` (4788)
       - a copy block: `bannerDesktop`, `bannerMobile`, `cardLabel`, `cta`, `endedNotice`,
         `upgradeHeaderLine`
     - `PROMOTIONS: readonly Promotion[]` with the Black Friday 2026 entry:
       - `startsAt` `2026-11-27T07:00:00Z`, `endsAt` `2026-12-01T07:00:00Z`
       - display: list $69.99, first year $47.88, monthly $3.99, 32% off
       - copy: Black Friday through Cyber Monday wording, per the design's call 3
     - `promotionStateAt(promo, nowMs)` returning `'upcoming' | 'live' | 'ended'`: start
       inclusive, end exclusive
     - `findPromotionById(id)` and `findRelevantPromotion(nowMs)`: the live entry, else the next
       upcoming within 7 days, else the most recent ended within 30 days, else `null`
     - `formatCountdown(msRemaining)`: clamps at zero; days, hours and minutes, switching to
       hh:mm:ss under 24 hours
     - `isInSaleAudience({ user, profile, isLoading, error, preview })`:
       - `false` while loading
       - `true` for no user
       - `false` for a user with no resolved profile (null or fetch error)
       - `false` when `hasPremiumPlan(profile.plan)`. This covers `premium` (paying, trialing,
         `past_due` and cancel-scheduled all map to premium through `mapStatusToPlan`), comped
         premium, and `admin`.
       - `true` otherwise
       - `preview` overrides to `true` only for admins
     - nothing campaign-specific outside the `PROMOTIONS` entry; every surface reads copy, prices,
       campaign and prefix from the resolved promotion
   - Use no `America/Phoenix` arithmetic anywhere. The instants are UTC constants, so the countdown is
     the same in every time zone.
   - New `frontend/lib/promotions.server.ts` (`import 'server-only'`):
     - `getPromotionStatus(nowMs = Date.now())` returns `{ promotion, state }` for
       `findRelevantPromotion`.
     - When `PROMOTIONS_DISABLED === 'true'`, a `live` state is reported as `'ended'`, so every
       surface treats it as over.
     - When `VERCEL_ENV === 'preview'` and `PROMOTION_WINDOW_OVERRIDE` is set (`<startISO>/<endISO>`),
       the override replaces the entry's window everywhere it is read, client payload included.
     - `getLivePromotion(id, nowMs)` returns the promotion only when `id` matches and the state is
       `live`. The route reads refusal copy from `findPromotionById(id)`, which ignores state, never
       from this result.
     - `getPromotionCouponId(promo)` reads `STRIPE_COUPON_` + the id upper-snake-cased
       (`STRIPE_COUPON_BLACK_FRIDAY_2026`) and throws a configuration error when it is missing.
   - Add the new env names, with comments and no values, to `frontend/.env.example`:
     `PROMOTIONS_DISABLED`, `PROMOTION_WINDOW_OVERRIDE`, `STRIPE_COUPON_BLACK_FRIDAY_2026`.

2. **`GET /api/promotion` endpoint**
   - New `frontend/app/api/promotion/route.ts`. It returns
     `{ state: 'live'|'upcoming'|'ended'|'none', promotion: <client-safe fields incl. effective startsAt/endsAt> | null, serverNow: <ms> }`
     with `Cache-Control: public, s-maxage=30`.
   - It never returns the coupon id. No auth is needed: the content is public marketing.
   - Add it to the public-route inventory in `frontend/CLAUDE.md`, beside `GET /api/announcements`.

3. **Shared client hook**
   - New `frontend/hooks/useLivePromotion.ts` returns
     `{ state, promotion, offsetMs, preview, loading }`.
   - **When it fetches:**
     - only when the bundled `findRelevantPromotion(Date.now())` is non-null
     - once per page load through a module-level promise, shared by the banner and the upgrade page
     - a failed **first** fetch on a page load is not cached (the next mount retries) and resolves to
       `state: 'none'`
     - a failed **refetch** keeps the last good `state`, `promotion` and `offsetMs` and retries on
       its own schedule. That is 5 seconds near a boundary, else 5 minutes while the bundled entry's
       window is current, whatever the last answer said. So one dropped request (a phone tab
       resuming) never hides a live sale or stops the refresh loop.
   - `offsetMs = serverNow + (Number(response.headers.get('age')) || 0) * 1000 - Date.now()` at
     response.
   - **Boundaries and refresh without a reload:**
     - A timer fires at the next transition, `startsAt` or `endsAt` minus `offsetMs`.
     - At `startsAt` it discards the cached promise and refetches. If the answer is still `upcoming`
       (a cached copy), it retries every 5 seconds for up to 90 seconds, then falls back to the
       5-minute refresh.
     - At `endsAt` it flips `state` to `'ended'` locally and then refetches.
     - While `state === 'live'` it refetches every 5 minutes, so an emergency off reaches open tabs.
     - The hook exposes one derived boolean, re-evaluated each second, and every consumer reads it:
       `isLive = preview || (state === 'live' && promotionStateAt(promotion, Date.now() + offsetMs) === 'live')`.
   - **Admin preview:**
     - The hook reads `promo_preview=1` from `window.location.search` in a post-mount effect,
       following `components/RecentMovers.tsx:34-42`. Never `useSearchParams`: in the root-layout
       banner it fails `next build` with "Missing Suspense boundary".
     - When that flag is set and the caller says the viewer is an admin (`profile.plan === 'admin'`),
       the hook returns the bundled relevant entry with `preview: true`, which makes `isLive` true
       before the real start. The countdown in preview runs to the bundled `endsAt`.
   - **`profile` comes from the caller,** which already calls `useUser`. The hook never calls
     `useUser` itself (frontend pitfall 22: a second session and profile fetch per page).
   - **Landing attribution:**
     - On first mount in a browser session, the hook stores any `campaign` and `utm_*` query values
       in `sessionStorage` as first-touch for the session, through a small new
       `frontend/lib/attribution.ts` (`captureLandingAttribution()`, `readAttribution()`).
     - It caps values at 100 characters with control characters stripped, and keeps only those six
       keys.
     - `mergeAttribution(pageParams, stored)` merges **per key**: a key present in the current URL
       wins, and the stored first-touch value fills each key the URL lacks. So a banner click
       (`campaign`, `source=banner`) keeps a landing `utm_source`.

4. **Checkout route: sale session**
   - **Body:** `frontend/app/api/stripe/checkout/route.ts` gains an optional `promotion` (sale id) and
     an optional `attribution` object:
     - keys: `campaign`, `source`, `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`
     - each a string, server-side re-capped at 100 characters with control characters stripped
     - unknown keys dropped
   - **When `promotion` is present:**
     - Resolve the entry with `findPromotionById(promotion)`. An unknown id returns 400
       `{ error: "This offer isn't available." }`.
     - Then `getLivePromotion(promotion)`. When it is not live (upcoming, ended or disabled), return
       400 `{ error: entry.copy.endedNotice }`. Neither refusal may reach the generic 500.
     - **Price:**
       - The posted `priceId` must pass the existing `price_` prefix check.
       - It must equal exactly the yearly id the upgrade page posts:
         `process.env.NEXT_PUBLIC_STRIPE_PRICE_YEARLY`, or `STRIPE_PRICE_YEARLY` only when the public
         one is unset. Otherwise 400 "Invalid price ID", with no fallback.
       - The sale charges that id, the same price a standard annual checkout from the page charges.
         So the pre-launch standard-checkout check proves the sale's base price, and no second,
         unverified id is accepted.
     - **Session params:**
       - from `baseSessionParams` with `allow_promotion_codes` **removed**
       - `discounts: [{ coupon: getPromotionCouponId(promo) }]`
       - no `trial_period_days` on either branch
       - `expires_at = Math.floor(clamp(endsAt, now + 31 min, now + 23 h) / 1000)`: well inside
         Stripe's 30-minute to 24-hour range, measured on Stripe's clock
     - **Metadata:**
       - `promotion`, `segment` and the attribution keys go on the session **and** on
         `subscription_data.metadata`, so the after-launch summary can read them from the
         subscription
       - `segment` is one of:
         - `new`: no prior subscriptions
         - `returning`: had some, none live
         - `signed_out`: anonymous checkout
       - Signed-in history comes from the existing `status: 'all', limit: 10` list
         (`allSubs.data.length > 0` → `returning`), which the route already makes. It is kept for
         segmenting only; eligibility uses the filtered lists below.
       - `ga_client_id` and `return_to` stay session-only, as today
     - **Order of operations for a sale request,** confirmed by the prototype. Each refusal happens
       before anything has side effects. The rate limit and `optionalAuth` stay first, as today
       (`checkout/route.ts:23-38`).
       1. Parse and sanitise the body.
       2. Resolve the promotion (unknown → 400, not live → 400).
       3. Check the price (→ 400).
       4. Resolve `getPromotionCouponId(promo)`. A missing env throws here, giving a 500 before any
          Stripe call. The prototype found that resolving it inside `create`, after the expiry,
          expired the buyer's open checkouts and *then* failed.
       5. Signed in: load the profile and refuse on `hasPremiumPlan`.
       6. If the profile already has a `stripe_customer_id`, run the three filtered refusals scoped
          with `customer`. With no customer, skip them: it has no subscriptions. **Never call a list
          without `customer`,** which would read other buyers' subscriptions.
       7. Create the Stripe customer if the profile has none, through the existing admin-client write.
       8. Expire open sessions.
       9. Re-run the three filtered refusals after the expiry. An earlier session that completed in
          the meantime shows up here as a live subscription, and is refused.
       10. Create the session.
       
       A refused buyer therefore gets no new Stripe customer and keeps their other open checkouts.
       - **Standard requests keep their order.** The expiry, when it applies, runs after the existing
         `status: 'all'` refusal and trial decision pass (`:113-125`), immediately before `create`.
       - **Expiring a session that is no longer open:** Stripe expires only `open` sessions. On an
         expire error, retrieve that session. If its status is no longer `open`, carry on and let
         step 9 decide; otherwise rethrow.
     - **Signed-in eligibility:**
       - refuse with "You already have an active subscription" when `hasPremiumPlan(profile.plan)`
         (from `lib/plan.ts`), before any Stripe call
       - also refuse when a Stripe list with `status` `active`, `trialing` or `past_due` (three
         filtered `limit: 1` calls; a hit on any is enough here, because no sale subscription exists
         yet) returns anything. Not the existing `status: 'all', limit: 10` list, which any live
         subscription behind ten cancelled rows can escape.
     - **One open checkout per signed-in customer around a promotion.** Before creating **any**
       session for a signed-in customer, list the customer's `status: 'open'` Checkout sessions and
       `checkout.sessions.expire` every one, awaiting each before creating.
       - It applies to the sale branch always, and to the standard branch while
         `getPromotionStatus()` reports `live`, or `ended` with `now < endsAt + 24 h` (covering the
         31-minute tail of late sale sessions and a kill switch).
       - **Paged to the end, then expired:** the list defaults to 10 per page. Collect every open
         session id first with a `starting_after` loop until `has_more` is false, then expire each.
         Expiring during the walk changes the filtered set under the cursor. The prototype's double
         skipped rows that way; real Stripe's behaviour is unverified, so collect first regardless.
       - **Always scoped** with `customer`.
       - This blocks both two-tab orders (standard then sale, sale then standard), including across
         midnight.
       - Outside that period the standard branch makes no extra calls, so it stays as it is today.
     - **Signed-out:** same sale params; keep the `checkout_browser` cookie and the
       `anonymous_checkout` metadata as today.
   - **Without `promotion`, behaviour is as today,** except for the open-session expiry above while
     a promotion is live. Preserve:
     - the rate limit
     - price validation against both env sets
     - `ga_client_id` / `return_to` metadata
     - customer creation and the admin-client write
     - trial eligibility, `customer_update`, the browser cookie
     - the generic 500
   - **Client helper:** `frontend/lib/stripe/client.ts` `startCheckout(priceId, next, options?)` gains
     an optional `{ promotion, attribution }` posted in the body. Existing callers are unchanged.

5. **Webhook: the sale-session invariant, duplicate alert, email match, refund lifecycle, events**
   - `frontend/app/api/stripe/webhook/route.ts`. Implement the sale-session invariant in Decisions.
     - **Scope, exactly as prototyped:**
       - **Every** checkout session: the email lowercase, the two lookup throws and the verified
         `.select('id')` writes.
       - **Sale sessions only** (metadata carries `promotion`): duplicate checks 0–3, the (b) exits
         and the purchase event.
       - Standard sessions otherwise keep today's handling, including the existing duplicate-trial
         cancel, the never-billed link of an ended subscription and the billed-account ignore
         (`:317-369`).
     - Add one private helper,
       `alertUnlinkedPaidCheckout({ reason, session, subscriptions, matchedProfile })`. It writes the
       `PAID_CHECKOUT_NOT_LINKED` error line, then `notifyAdmin` with escaped HTML listing, for every
       live subscription involved: id, customer, created time, amount, and whether a profile points
       at it. For `duplicate` it adds the reason and the same-customer Beehiiv instruction when that
       applies. It names no single subscription to refund.
     - **Email match (pre-existing defect, now money-bearing).** In the signed-out path (:293-308),
       lowercase and trim the Stripe customer's email before the `user_profiles` lookup and before
       `createUser`.
       - Measured read-only on 2026-11-24: no stored profile email had uppercase letters, while
         Stripe keeps the case the buyer typed and some recent live customers' emails are
         mixed-case. Counts are deliberately left out of this public file.
       - A case miss today reaches `createUser` → "already been registered" → `isPermanentError` →
         200, leaving a paid buyer unlinked.
       - Throw on the lookup's `error` (→ 500 → Stripe retries) instead of discarding it.
       - Do the same for the customer-id lookup at `webhook/route.ts:276-280`, which also discards
         its error today. Otherwise a transient failure there sends a retry down the signed-out path,
         where the buyer's own (already linked, now premium) row would look like a duplicate.
     - **Duplicate detection, sale sessions only,** run before any profile write, in whichever branch
       the session takes: signed-in (a profile holds the customer) or the email branch (`:291`).
       0. **Cancelled suppresses only the alert.** If the subscription the handler retrieved
          (`webhook/route.ts:263`) is `canceled` (typically a re-delivery after the owner resolved a
          duplicate), checks 1–3 send no alert and no email. The existing link/ignore logic then
          runs unchanged: never-billed account → link, billed account → ignore (`:353-369`).
       1. **Same customer:** list the session's customer's `active`, `trialing` and `past_due`
          subscriptions with `limit: 10` per status, never `limit: 1`, and exclude the session's own
          subscription after listing. The prototype showed `limit: 1` returns only the sale itself:
          the duplicate is missed, the profile is re-pointed and a purchase event is sent.
       2. **Signed out, plan:** the email lookup selects `plan` as well as its current columns. A
          matched profile whose `plan` is `premium` or `admin` is a duplicate (comped and admin
          accounts included, live Stripe subscription or not), unless its `stripe_customer_id` is
          this session's customer.
       3. **Signed out, other customer:** when the email matches a profile with a
          `stripe_customer_id` other than this one, list that customer's subscriptions in the same
          three statuses.
       
       If any of checks 1–3 finds one:
       - write nothing to the profile
       - `alertUnlinkedPaidCheckout({ reason: 'duplicate', … })`. The alert lists every live
         subscription involved, as Decisions describes, and the owner picks which to refund. For the
         same-customer case it adds: "after refunding, set this subscriber's newsletter lifecycle
         back to paid, re-add the premium tag and remove them from the win-back automation; reconcile
         restores premium within 6 hours".
       - send the new `sendDuplicatePurchaseEmail(email)`
       - send no purchase event, and return 200
     - **The other (b) exits, sale sessions only** (see the Decisions table):
       - **No email:** the existing "Stripe customer has no email" return (:297-300) → reason
         `no_email`.
       - **Account already registered:** a `createUser` failure whose message includes "already been
         registered".
         - First re-read `user_profiles` by the lowercased email. If that profile now holds this
           session's subscription (a concurrent replay of the same session won), return 200 with no
           alert.
         - Otherwise → reason `account_exists_unlinked`.
       - Each alerting exit calls `alertUnlinkedPaidCheckout` and returns 200. The subscription is
         not cancelled; the owner links or refunds it by hand.
       - Standard sessions keep today's behaviour on both paths.
     - **Verified signed-out profile writes.** Otherwise the existing paths run (link by email, or
       create the account), with the profile writes at `webhook/route.ts:362-365` and `:389-392`
       verified. Both currently discard the update's result.
       - Each `.update(...).eq('id', …)` gains `.select('id')`.
       - A returned `error` throws `Error('profile write failed: ' + error.message)`.
       - Zero rows throws `Error('profile write matched no row')`, so the handler answers 500 and
         Stripe retries. This mirrors `updateUserProfile`'s verified write
         (`frontend/lib/stripe/server.ts:118-139`).
       - The two messages differ on purpose. The prototype found that an errored supabase-js update
         also returns `data: null`, so the zero-row check alone would catch both, and only the
         message tells which check fired.
       - **Known residue, accepted:** if `createUser` succeeds and this write then fails, Stripe's
         retry finds the trigger-created free profile by email and takes the link path. The buyer
         ends up premium, but gets no set-password email or `checkout_session_id` sign-in marker.
         The backstop is `scripts/check_stuck_signups.py`, run every 6 hours by
         `check-stuck-signups.yml`. Read in that script, it reminds a non-admin profile only when all
         of these hold:
         - its status is `active`, `trialing` or `past_due` (:61-64), which holds once the retry has
           linked it
         - its auth user carries `anonymous_checkout` and has never signed in (:130-145, :241-248)
         - it is past the 24 h or 72 h threshold, with fewer than the allowed reminders sent
         
         So the reminder arrives within roughly 24–30 hours of the link, and only once the link has
         recovered.
     - **`handleChargeRefunded` (:689-703):** skip `syncLifecycle` when no `user_profiles` row has
       `stripe_customer_id = charge.customer`. That is the owner's by-hand refund of a duplicate,
       whose customer is never stored. Without this, the buyer's email would be enrolled in the
       paid win-back automation while they are still a paying subscriber.
       - The by-hand cancel of an unlinked duplicate needs no change. `handleSubscriptionDeleted`
         reads `getPriorState` → `null` and skips Beehiiv, and `updateUserProfile` throws
         "No user profile found", which `isPermanentError` answers with 200.
     - **Purchase event.** As the last action of a sale fulfillment that wrote the profile, send
       `<prefix>_purchase_completed` with:
       - `transaction_id` = subscription id
       - `value` = `session.amount_total / 100` and `currency` = `session.currency.toUpperCase()`,
         both only when non-null. Dahlia types them `number | null` and `string | null`. When either
         is null, omit both rather than send a zero.
       - `promotion_id`, `segment` and the attribution keys from metadata
       
       The existing `subscription_completed` call stays as it is.
     - **Expired event.** Add `CHECKOUT_SESSION_EXPIRED: 'checkout.session.expired'` to
       `WEBHOOK_EVENTS` (`frontend/lib/stripe/server.ts:55`) and a switch case. When the session
       metadata carries `promotion`, send `<prefix>_checkout_expired` with the session's
       `ga_client_id`, `promotion_id` and `segment`. Otherwise do nothing. Sessions the route expires
       under "one open checkout per signed-in customer" also fire this. That is accepted: they are
       abandoned checkouts.
   - **`frontend/lib/analyticsServer.ts`:** add `sendServerEvent(clientId, name, params)`, extracted
     from the body of `sendSubscriptionCompleted`, with the same timeout and never-throw rules.
     Re-express `sendSubscriptionCompleted` as a call to it, so there is one Measurement Protocol code
     path.
   - **New `frontend/lib/email/duplicate-purchase.ts`,** modelled on `duplicate-subscription.ts`
     (template plus `sendDuplicatePurchaseEmail(email): Promise<boolean>`, early return without
     Resend, never throws). It says they already have PitchRank Premium, so this purchase will be
     refunded within one business day and nothing else changes. The wording is not sale-specific,
     because a paid standard duplicate uses it too. Import it directly in the webhook,
     as the webhook imports `@/lib/email/duplicate-subscription`; that sibling is not re-exported from
     `frontend/lib/email/index.ts`.

6. **Banner**
   - **Mounting:**
     - New `frontend/components/PromotionBanner.tsx` (`'use client'`), rendered by
       `frontend/components/Navigation.tsx` as the first child of its sticky `<header>` (:39-42),
       above the `h-16` menu row. So it is pinned with the menu, per Decisions.
     - `frontend/app/layout.tsx` is unchanged.
     - Navigation already calls `useUser()` (:17). Widen that destructuring to
       `{ user, profile, isLoading, error, signOut }` and pass
       `user`/`profile`/`isLoading`/`error` to the banner as props.
     - The banner never calls `useUser` itself, so it adds no session or profile fetch on any page
       at any time.
   - **The banner calls nothing that fetches outside a campaign period:** it renders its inner part
     (which calls `useLivePromotion`) only when, in a post-mount effect, the bundled
     `findRelevantPromotion(Date.now())` is non-null.
   - **When it renders nothing:**
     - on the server
     - while loading
     - unless `isLive`
     - when `isInSaleAudience` is false
     - on `/upgrade/success` (`usePathname`)
     - once dismissed this session (`sessionStorage`)
   - **Header height:** while it renders, an effect adds `promo-banner-visible` to
     `document.documentElement`, and the effect's cleanup removes it. Add the matching rule to
     `frontend/app/globals.css` beside `--site-header-height` (:100), per Decisions.
   - Content:
     - desktop: `copy.bannerDesktop`, a countdown from
       `formatCountdown(endsAt - (Date.now() + offsetMs))` ticking each second (the
       `MissingGamesForm.tsx:126-140` pattern), and a "Claim Offer" link
     - phones: `copy.bannerMobile` and the link
     - both: a dismiss button with an accessible name
   - The link goes to `/upgrade?campaign=<promotion.campaign>&source=banner`, plus `promo_preview=1`
     when previewing.
   - On `/upgrade` itself the link scrolls to `#sale`. Its click handler first writes `campaign` and
     `source: 'banner'` into the session attribution through `lib/attribution.ts`
     (`recordClickAttribution`), overwriting just those two keys, so the checkout still records the
     banner as the source.
   - Styling: Tailwind with `bg-primary` and `text-accent` emphasis, Oswald `font-display` for the
     headline. Exactly one line, fixed `h-10`, at every width, `truncate`, so it matches the 2.5rem
     added to `--site-header-height`. No animation beyond the ticking digits. `role="region"` with an
     `aria-label`. The countdown is not `aria-live`.
   - Events: `<prefix>_banner_view` once per page load when shown, `<prefix>_banner_click` on the
     link.

7. **Upgrade page: third card, campaign handling, copy**
   - **When the sale card shows** (`frontend/app/upgrade/page.tsx`): read `useLivePromotion()`, with
     `profile` from the page's own `useUser()` call, and `isInSaleAudience`.
     - The page already binds `error` to the checkout error (`upgrade/page.tsx:48-52`), so
       destructure the hook's as `const { user, profile, isLoading: userLoading, error: profileError } = useUser()`.
     - Pass `profileError` to the audience check, never the page's checkout `error`. When `isLive` and the
     viewer is in audience, render a third `Card`, `id="sale"`, using the existing
     `variant="primary"` treatment plus a ring or scale to make it dominant. Its content comes from
     `promotion.display` and `promotion.copy`:
     - the card label and countdown
     - monthly equivalent, "<first-year price> billed today for your first year"
     - list price struck through, percent off, "Premium access starts immediately"
     - the existing `FEATURES` list
     - "Renews at <list price>/year. Cancel anytime."
     - CTA `copy.cta`
   - **Layout:** the grid becomes `md:grid-cols-3` (container widened from `max-w-4xl` to fit) only
     while the sale card renders. On computers the sale card sits in the middle; on phones it comes
     first. Monthly and Annual cards keep their content, buttons, trial copy and tracking exactly.
     Preserve the `selectedPlan`/`yearlyFirstOnPhones` behaviour for those two. See the
     `hidden`/`flex` tailwind-merge trap in the `hidden-class-drops-flex-through-tailwind-merge`
     memory before touching card classes.
   - **Buying:** `handleUpgrade` gains a `'promotion'` plan. It calls
     `startCheckout(PRICE_IDS.YEARLY, tappedTeamPath, { promotion: promotion.id, attribution })`,
     where `attribution = mergeAttribution(<the page's own campaign, source and utm_* params>, readAttribution())`.
     - It fires the existing `trackPlanSelected` and `trackCheckoutInitiated` with
       `plan: 'yearly'` and `price: display.amountCents / 100`, so the internal funnel's
       plan-selected → checkout-started → subscribed steps stay consistent during the sale
       (`lib/internal-analytics/queries/ga4-upgrade-funnel.ts:22-27`).
     - It also fires `<prefix>_checkout_started` at the same price.
     - `loadingPlan` widens to include `'promotion'`; the tracking payload's `plan` stays
       `'yearly'`, so `types/events.ts` is unchanged there.
   - **Ended notice:** when `campaign` matches the relevant promotion's `campaign` and the state is
     `ended`, show `copy.endedNotice` above the normal page. That covers both the kill switch and
     the end of the window. Upcoming or `none` shows the normal page.
   - Track `<prefix>_offer_view` once when the sale card renders.
   - The tapped-team header line (:192) uses `copy.upgradeHeaderLine` while the sale card shows.
   - A viewer not in audience (paying, trialing, admin without preview) sees no sale card. Today's
     page and refusal are unchanged for them.

8. **Paywall overlays: no change**
   - `ClutchFactorCard`, `TeamInsightsCard` and the watchlist block are left exactly as they are.
     They are reached only by a Premium viewer whose profile fetch failed. Middleware sends every
     signed-out and free visitor to `/upgrade` first (`middleware.ts:5,102-141`; see the Pattern
     Survey). Sale copy there would reach paying subscribers only.
   - The sale's paywall message is the `/upgrade` tapped-team header and sale card in step 7.
   - `copy.paywallLine` is dropped from the `Promotion` copy block.

9. **Browser event helpers**
   - `frontend/lib/events.ts`: add
     `trackPromotionEvent(promo, step: 'banner_view'|'banner_click'|'offer_view'|'checkout_started', params)`.
     It emits `${promo.analyticsPrefix}_${step}` through `gtagEvent`, with `promotion_id`, `campaign`,
     `source`, `page_path`, `price` and the session attribution.
   - Add the payload type beside the others in `frontend/types/events.ts`.

10. **Tests (written alongside each step)**
    - **Tighten the doubles first:**
      - Webhook test: move the Supabase double onto `filteringClientMock` (`test/supabase-mock.ts`),
        so lookups honour their filters and writes land on stored rows. Seed both the payer's and
        the duplicate's customers, and assert on final rows.
      - **New webhook tests go in their own file**,
        `frontend/app/api/stripe/webhook/__tests__/route.promotion.test.ts`. There the real
        `updateUserProfile` (`lib/stripe/server.ts:118-139`) runs against the filtering double, so a
        write through it changes a seeded row and a missing row throws "No user profile found…" for
        real. A "profile untouched" assertion then fails if the duplicate branch takes any write
        path.
        - The existing `route.test.ts` keeps its mocked `updateUserProfile`. It relies on
          `mockRejectedValueOnce` and `invocationCallOrder` for the Dunning-order guards (:250, :277,
          :1182-1203).
        - Add only the cases that touch changed lines: the lookup-error throws and the verified
          signed-out writes. Make its `createUser` double insert the trigger-created `user_profiles`
          row, as `supabase/migrations/20251209100000_create_user_profiles.sql:37-52` does.
      - **Failure injection at the write under test,** not by table. Give the filtering double a
        per-call hook (for example `failOn({ table, op: 'update' })`) that fails only that terminal
        after the lookups succeed. Assert in the test that the update was reached.
        - Separately, a successful update that returns zero rows.
        - Removing either result check must fail its own named test.
        - For the lookup-error tests, extend `failing[table]` to `.maybeSingle()` (today it skips
          `.single()`/`.maybeSingle()`, `test/supabase-mock.ts:118-122`), with a case in
          `test/supabase-mock.test.ts`.
      - **Unchanged-row assertions compare against literal expected values**, written in the test.
        Never compare against the seeded object: `filteringClientMock` mutates seeded rows in place
        (`test/supabase-mock.ts:157-161`).
      - Webhook test: the Stripe double's `subscriptions.list` honours `customer` and `status`,
        returns newest first, and applies `limit`. Then a `limit: 1` same-customer check would
        return only the sale itself and fail the test.
      - Checkout test: let each test set `subscriptions.list` results by status, and add
        `checkout.sessions.list` (honouring `customer` and `status`, paginating at 10 with
        `has_more`) and `expire`.
      - Add a checkout-session fixture to `frontend/test/fixtures.ts`, beside
        `makeStripeSubscription`.
      - Make the checkout double **refuse** a create call carrying both `discounts` and
        `allow_promotion_codes`, and an `expires_at` outside 30 minutes to 24 hours of its own
        clock, the way Stripe's server does.
    - **`lib/promotions` tests:**
      - state edges under fake timers: `2026-11-27T06:59:59Z` upcoming, `07:00:00Z` live,
        `2026-12-01T06:59:59Z` live, `07:00:00Z` ended
      - kill switch reports ended
      - override honoured only with `VERCEL_ENV=preview`
      - missing coupon env throws
      - `formatCountdown` at 3 days, 1 hour, 59 seconds and a negative value (→ zero)
      - `isInSaleAudience` for signed-out, loading, signed-in with a null profile, signed-in with an
        error, free, premium, admin, and admin with preview
      - `lib/plan.ts` `hasPremiumPlan` for each plan value
      - `mergeAttribution`: a URL key wins, a stored key fills a missing one, and the banner's
        `campaign` + `source` keep a stored `utm_source`
      - a second synthetic promotion with different copy, price, campaign and prefix: every helper
        and the endpoint payload follow it with no code change
    - **Client helper test** (new `frontend/lib/stripe/__tests__/client.test.ts`): the real
      `startCheckout` with a stubbed `fetch` posts `promotion` and `attribution` in the body. Removing
      either from the serialisation must fail it. The route test then feeds that exact body.
    - **Checkout route tests:**
      - sale session params: the literal coupon env value, no trial, no `allow_promotion_codes`,
        `promotion`/`segment`/attribution on both session and `subscription_data.metadata`
      - price, with the two yearly env ids set to different values:
        - the posted `NEXT_PUBLIC_` id is charged as posted
        - the server-only id is refused
        - with `NEXT_PUBLIC_STRIPE_PRICE_YEARLY` unset, `STRIPE_PRICE_YEARLY` is accepted
        - a monthly id, an unknown id and a blank are each refused with 400 and no fallback
      - `segment` values exactly: `new` for a customer with no subscriptions, `returning` for one
        with only a cancelled one, `signed_out` for anonymous, asserted on both metadata objects
      - an unknown promotion id → 400 "This offer isn't available."; upcoming, ended and disabled →
        400 with that entry's `endedNotice`; none of them a 500
      - **Import scan** (new `frontend/test/server-imports.test.ts`, modelled on
        `test/component-sources.ts`):
        - It reads `app/api/stripe/checkout/route.ts`, `app/api/stripe/webhook/route.ts`,
          `app/api/promotion/route.ts`, `lib/promotions.ts`, `lib/promotions.server.ts` and
          `lib/plan.ts`, and follows their relative and `@/` imports transitively.
        - It asserts that none of them imports `hooks/useUser` or any module whose first statement
          is `'use client'`.
        - The build smoke covers the runtime side.
      - `expires_at` exactly, under fake time:
        - created 48 h before the end → now + 23 h
        - 10 h before → `endsAt`
        - 20 min before → now + 31 min
        - at `endsAt` → refused with the ended notice
      - refusal for a premium profile, before any Stripe call
      - refusal for an `active`, a `trialing` and a `past_due` subscription, **each sitting behind
        ten newer cancelled ones**, on a profile seeded `plan: 'free'` so the plan check cannot
        refuse first.
        - The existing `status: 'all', limit: 10` check already refuses an `active` or `trialing`
          subscription that is among the newest ten.
        - Only the behind-ten, free-plan fixtures make deleting a filtered list fail its own test, as
          the prototype showed (its fixtures defaulted to `plan: 'free'`).
      - **order:**
        - a comped-premium profile with `stripe_customer_id: null` is refused with no
          `customers.create` call
        - a free profile with an existing customer and an open session, refused by a filtered list,
          keeps its open session (no `expire` call)
        - with the coupon env unset, the 500 comes before any expiry
        - a customerless free profile makes no `subscriptions.list` call at all, and never an
          unscoped one
      - **expiry races:**
        - an earlier session that completed between the eligibility check and the listing is refused
          by the post-expiry re-check
        - an `expire` that Stripe refuses because the session already completed is tolerated, and
          the re-check then refuses
        - any other `expire` error → 500
      - **clock-pinned existing suite:** `checkout/__tests__/route.test.ts` uses the real clock. The
        prototype ran it unchanged at 2026-11-28 and two signed-in tests failed
        (`checkout.sessions.list is not a function`), while "returns 500 with generic error" passed
        for the wrong reason. Every PR's CI would go red during the sale.
        - Pin that file's clock outside the window (`vi.useFakeTimers({ toFake: ['Date'] })` +
          `vi.setSystemTime`, the repo's pattern), and add `checkout.sessions.list` / `expire` to
          its Stripe mock.
        - Tighten "returns 500 with generic error" (`:275-299`) to assert that
          `checkout.sessions.create` was reached and that the body is exactly
          `{ error: 'Failed to create checkout session' }`.
      - **Open-session expiry:**
        - An open earlier session for the same customer, sale or standard, is expired before a new
          sale session is created. Seed 12 open sessions across two pages, plus one open session
          for a **different** customer. All 12 are expired before `create` is called, and the other
          customer's stays open.
        - An open sale session is expired before a standard session while the sale is live.
        - The same holds for a standard session created 5 minutes after `endsAt` while a late sale
          session is still open, and after a kill switch.
        - No expiry calls are made for a standard session 25 hours after `endsAt`.
      - attribution re-capped and unknown keys dropped
      - standard monthly and yearly sessions identical to today outside the sale, and during it
        except for the expiry calls
    - **Webhook tests,** one fixture per conjunct:
      - **Same-customer duplicate:** the customer holds an older `active` subscription plus the sale.
        Expect the profile untouched, `notifyAdmin` called, email sent, no purchase event. This
        fails under a `limit: 1` list.
      - **Signed-out duplicates, one fixture per predicate.** The guest sale's customer is unlinked in
        Supabase every time, so the email branch really runs.
        - *plan check (check 2):* the email matches a comped `premium` profile with no Stripe
          customer, and separately an `admin` profile
        - *other-customer check (check 3):* the email matches a **stale `free`** profile whose
          different customer has a live subscription (`active`, then `trialing`, then `past_due`).
          The plan check cannot pass these, so removing the Stripe lookup fails them.
        - Each case expects no link, no write (stored row equal to literal expected values; `plan`
          still `admin` for the admin), the `PAID_CHECKOUT_NOT_LINKED` line with reason
          `duplicate`, the alert and the email.
      - **W10, the relink orphan, pinned as a known gap:**
        1. A returning `free` profile's old customer has no live subscription and an open signed-in
           **standard** session (metadata `supabase_user_id`, no `anonymous_checkout`, no trial
           because of billing history).
        2. A guest sale completes: linked to the new customer.
        3. The old standard session then completes paid.
        
        Assert today's behaviour on that standard completion: re-linked to the standard subscription,
        200, no `PAID_CHECKOUT_NOT_LINKED`. A change to it then fails loudly and forces a deliberate
        decision. The sweep test (Verification) must surface the sale's customer as a candidate.
      - **Standard sessions unchanged:** the existing never-billed-link test (`route.test.ts:1104`),
        the billed-account test (`:1117`) and the set-password block (`:1207-1370`) pass unedited.
      - **(b) exits, sale sessions only:**
        - a Stripe customer with no email → `no_email`
        - an auth user whose profile carries a different email: `createUser` refuses "A user with
          this email address has already been registered" → `account_exists_unlinked`
        - **two concurrent deliveries of two different paid sale sessions for one new email:** a
          barrier in the double lets both email lookups resolve before either `createUser`. The
          `createUser` double enforces email uniqueness. The loser → `account_exists_unlinked`.
        - **two concurrent deliveries of the same session:** same barrier; the loser re-reads, finds
          its subscription linked, and sends no alert
        - **the same two sessions delivered one after the other:** the second is a `duplicate`
          (check 2), as the prototype observed
        
        Each alerting case expects 200, the `PAID_CHECKOUT_NOT_LINKED` line with its reason, and
        `notifyAdmin`.
      - **Already resolved:** a re-delivered sale duplicate whose subscription is now `canceled`
        sends no alert and no email. A cancelled sale subscription on a never-billed account still
        links, as the standard path does today.
      - **Customer-id lookup error:** the profile already holds this session's subscription (as
        after `/api/stripe/sync`) and the `:276` lookup fails. Expect 500 and no alert.
      - **Own row:** a matched premium profile whose `stripe_customer_id` is this session's customer
        is not a duplicate.
      - signed-out sale buyer whose Stripe email differs only in case from a free profile: linked to
        that profile, no `createUser`
      - lookup error → 500
      - **Signed-out link and new-account writes:**
        - a returned `error` → 500 with `profile write failed:`
        - a zero-row update → 500 with `profile write matched no row`
        - neither sends a purchase event
        - The route's 500 body is always `Webhook handler failed`
          (`webhook/route.ts:222-235`), so assert each message on the `console.error` spy, alongside
          the status. An errored update also has `data: null`, so only the message tells which check
          fired.
      - **existing suite:**
        - In `webhook/__tests__/route.test.ts`, "routes paid_canceled on charge.refunded" needs a
          linked profile seeded for its customer; the prototype showed it fails otherwise once the
          refund-lifecycle skip exists.
        - Seed a linked customer in the **partial**-refund test too (`:563-583`). Otherwise the new
          unlinked-customer skip, rather than the partial-refund guard, keeps it green.
        - With sale-only detection, no other existing webhook test changed outcome (74 of 75 passed
          unchanged).
      - by-hand refund of an unlinked duplicate: `syncLifecycle` not called, and the payer's
        Beehiiv untouched; with a positive control, a refund on a linked customer still calls
        `syncLifecycle('paid_canceled')`, so deleting the lifecycle handling entirely fails a test
      - by-hand cancel of an unlinked duplicate: 200, no profile change
      - purchase event sent after the profile write; not sent when an earlier step throws
      - expired event only for sale sessions
    - **Purchase event through the webhook:** in `route.promotion.test.ts`, leave
      `@/lib/analyticsServer` unmocked with `GA_API_SECRET` set and `fetch` stubbed. Drive paid
      sale Checkout Session fixtures through the webhook and read the Measurement Protocol body:
      - `amount_total: 4788, currency: 'usd'` → `<prefix>_purchase_completed` with
        `transaction_id`, `value` 47.88 and `currency` `USD` (catches cents sent as dollars)
      - `amount_total: null` → neither `value` nor `currency`
      - `currency: null` → neither
      - `lib/analyticsServer.test.ts` keeps a direct serialisation test, and
        `sendSubscriptionCompleted` still sends `subscription_completed`.
    - **Upgrade page tests:**
      - three cards while live and two outside, Monthly and Annual content unchanged
      - premium, trialing (premium plan) and admin profiles see no sale card
      - a signed-in viewer whose profile failed to load sees none
      - a signed-in viewer with a **retained free profile plus a `useUser` error** sees none. That
        fails if the page's checkout `error` is wired in place of `profileError`.
      - the sale CTA calls `startCheckout` with `{promotion, attribution}`, and fires
        `trackPlanSelected`/`trackCheckoutInitiated` as `yearly` at 47.88
      - admin preview before the real start, with the clock pinned before `startsAt`: sale card
        shown
      - ended notice for a campaign link after the end and with the kill switch, not before the start
      - update the `page.test.tsx` mocks (`useUser` profile, events, `searchParams` beyond `next`)
    - **Banner tests:**
      - shown for signed-out and free
      - hidden for premium, admin without preview, loading, and a signed-in viewer with no profile
      - shown in admin preview with the clock pinned **before** `startsAt`, with the link carrying
        `promo_preview=1`
      - rendered inside Navigation's `<header>` above the menu row; while shown, `<html>` has
        `promo-banner-visible`, and dismissing removes it
      - shown on `/upgrade`, with the link targeting `#sale`; clicking it there leaves
        `source: 'banner'` and the campaign in the session attribution, and the sale CTA then posts
        them; not rendered on `/upgrade/success`
      - outside a campaign period the inner part never mounts and `/api/promotion` is not called
      - dismissal persists for the session
      - countdown text under fake timers, offset including an `Age` header
      - hides itself at `endsAt` with no refetch response and no reload
      - appears after a refetch at `startsAt`; when the first refetch returns a stale `upcoming`, it
        appears on a later 5-second retry
      - while live, a 5-minute refetch returning `ended` (kill switch) hides it
      - while live, a 5-minute refetch that **rejects** leaves it shown, and a later success keeps
        it; a rejected `startsAt` refetch is retried after 5 seconds and the banner appears on
        success, in the same mounted tab
    - **Paywall overlays:** the existing `paywall-upgrade-link.test.tsx` stays green unchanged, which
      shows step 8 changed nothing.
    - **Mutation discipline:**
      - revert each eligibility refusal, each duplicate-detection branch (including the
        premium/admin plan check), the email lowercase, the verified signed-out writes and the
        refund-lifecycle skip, one at a time
      - confirm the *new* test names are among the failures, not merely that the suite reddens

11. **Bring the design doc in line** (`docs/superpowers/specs/2026-11-24-black-friday-sale-design.md`).
    Add a line at its top: "Where this design and `.turbo/plans/black-friday-2026-sale.md` differ,
    the plan wins." Then update each section that contradicts the plan:
    - calls 1 and 2 → superseded: trial users count as subscribers, and duplicates are alerted and
      refunded by hand
    - the coupon `redeem_by` "+30 minutes" (call 6, approach 1, the Stripe block) → +60 minutes
    - "Signed-in buyers holding a trialing subscription are allowed through" (Checkout route) →
      refused
    - the paywall-prompts paragraph → no change to the overlays; the paywall copy lives on
      `/upgrade`
    - the banner → pinned with the menu, one line
    - webhook rules (a)–(c) → the duplicate alert, the email lowercase and the verified writes
    - the analytics note → "no dedupe gate; `transaction_id` on every event"; segment values
      `new`/`returning`/`signed_out`
    - the testing section's "signed-in trial user switching" case → removed

## Owner steps (not code)

1. **Test-mode setup for the practice purchase,** on the Vercel preview for this branch, with
   preview-scoped values:
   - Stripe: `STRIPE_SECRET_KEY` and `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` (test), and
     `STRIPE_PRICE_MONTHLY`/`STRIPE_PRICE_YEARLY` plus their `NEXT_PUBLIC_` twins (test price ids)
   - webhook: `STRIPE_WEBHOOK_SECRET` from a test-mode webhook endpoint pointing at the preview URL,
     with `checkout.session.expired` included
   - coupon: `STRIPE_COUPON_BLACK_FRIDAY_2026` = a test-mode coupon (`amount_off` 2211 USD,
     `duration` once, `applies_to` the test Premium product, `redeem_by` end + 60 min)
   - `NEXT_PUBLIC_SITE_URL` = the preview's URL, so checkout returns to the preview
   - `PROMOTION_WINDOW_OVERRIDE` around "now"
   - blank `RESEND_API_KEY`, Beehiiv keys, Telegram keys and `GA_API_SECRET`
   - a protection bypass for the preview URL
   
   Then redeploy the preview: `NEXT_PUBLIC_*` values are baked in at build.
2. **Live coupon.** Before creating it, list the live account's active annual prices through the
   Stripe MCP: there must be exactly one at $69.99/year USD. Then, with the owner's OK, create the
   coupon:
   - `amount_off` 2211 USD, `duration` once
   - `applies_to` that price's product
   - `redeem_by` = end + 60 minutes (`2026-12-01T08:00:00Z`)
   - name "Black Friday 2026"
   
   Then set `STRIPE_COUPON_BLACK_FRIDAY_2026` in Vercel **production**. The id never goes into the
   repo.
3. **Live webhook event.** Add `checkout.session.expired` to the live Stripe webhook endpoint's event
   list.
4. **Approve the merge.** Then confirm Vercel actually built the merge commit (`list_deployments` by
   sha; see the `vercel-can-skip-a-main-merge` memory) before calling it live.
5. **Emergency off, if ever needed:**
   - Instant: delete the coupon in Stripe. New sale checkouts then fail at creation, and the card
     shows the server's error. Buyers who already purchased keep their discount, because Stripe
     leaves applied discounts in place.
   - Within minutes: set `PROMOTIONS_DISABLED=true` in Vercel production and redeploy.
     - New page loads lose the banner and card within about 30 seconds of the deploy.
     - Tabs already open lose them at their next 5-minute refresh.
     - The campaign link shows the ended notice, and checkout refuses the sale.
   - Check that `/api/promotion` reports `ended` and that an existing sale buyer still opens a team
     page.

## Verification

- **CI gate, in the worktree** (frontend half of `ci.yml`):
  `cd frontend && npx eslint . && npx prettier --check . && npm run typecheck && npm run test && npm run generate-llms && git diff --exit-code public/llms.txt`.
  Expect all green. No Python changes are planned; if `scripts/` is touched, also run
  `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` and
  `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`.
- **Production build smoke, locally:**
  - **Setup:** `next build` (this is what catches a `useSearchParams` in the layout) + `next start`
    with `VERCEL_ENV=preview` and `PROMOTION_WINDOW_OVERRIDE` around now. Fake Stripe per the
    `stripe-billing-data` skill's local recipe, and leave email and analytics keys blank.
  - **Screenshots** at 375, 768 and 1280 wide, signed out:
    - home and rankings with the banner
    - `/upgrade` with three cards and the banner
    - `/upgrade?next=/teams/<a real team id>`, showing the tapped-team header with the sale line
    - `/upgrade?campaign=black-friday-2026` after moving the override into the past
  - The banner and menu stay pinned together after scroll, and dismissing the banner moves the menu
    back to the top.
  - **At 375 wide in WebKit and Chromium,** with the banner showing:
    - open phone search results (`GlobalSearch`): the panel starts below the menu, not over it
    - `/rankings` at scroll 0 and after scrolling past the filters: `RankingsStickyFilters` parks
      and slides in below the menu, not over the banner
    - the same two after dismissing the banner
  - **A signed-in free account's sale checkout** against the fake Stripe, on this production build:
    expect a session created with the coupon. That exercises the server-side premium check in Next's
    RSC layer, which vitest cannot.
    - Use a throwaway account created for this run, deleted in a `finally`, with the owner's OK
      before it is created (the `stripe-billing-data` skill's rule for live Supabase auth).
  - Send the screenshots to the owner.
- **Practice purchase on the preview** (owner chose this), as a signed-out new buyer with Stripe test
  card `4242…` and a throwaway email:
  - The Stripe page shows $47.88 today, then $69.99/year.
  - Checkout returns to the **preview** origin, syncs and signs the buyer in.
  - The subscription has no trial and carries `promotion` and `segment` metadata.
  - The invoice is $47.88 paid with the coupon in `discounts`, and the account is premium.
  - Then start a second sale checkout with the same email while signed out and pay it. Expect the
    `[webhook] PAID_CHECKOUT_NOT_LINKED` line (reason `duplicate`) in the preview's runtime logs, naming the second
    subscription, and no profile change.
  - Afterwards, delete the throwaway account and profile from production Supabase (the owner's OK
    for that one account is in the design), and refund the test-mode charges.
- **Before Friday, on production after merge:**
  - `GET https://pitchrank.io/api/promotion` returns `upcoming`
  - `/upgrade` shows two cards
  - admin `?promo_preview=1` shows the banner and the third card
  - a sale checkout attempt from the preview is refused by the server with the ended notice
  - open a **standard** annual checkout page without paying and confirm it shows $69.99/year
    (after the trial). That is the price id the page posts, which the sale charges too.
  - Confirm that price's product is the one the live coupon's `applies_to` names: read the coupon
    and the price through the Stripe MCP, read-only.
  - The discount line itself is first visible on the live sale page at 00:00 Friday, because the
    server refuses sale checkouts before then.
- **At 00:00 Friday Arizona (07:00 UTC):**
  - within about 30 seconds, `/api/promotion` returns `live`
  - open the live sale checkout page (no payment) and confirm Stripe shows $47.88 today and $69.99
    renewal
  - then watch the first real purchases through the Stripe MCP: a $47.88 invoice, no trial,
    `promotion` metadata, the profile premium
- **Daily duplicate sweep**, each morning Thu–Tue (Arizona), with a final run after 00:31 Tuesday.
  It backs up a lost Telegram alert.
  - **What it reads:** every run reads read-only from the **campaign start**
    (`2026-11-25T07:00:00Z`) through the time it runs, so a late or missed run loses nothing. It
    lists live (`active`, `trialing`, `past_due`) subscriptions created in that span.
  - **What it flags, as candidates:**
    - (a) any whose Stripe customer is stored on no `user_profiles` row. That covers guest
      duplicates, comped and admin buyers, and the W10 relink orphan.
    - (b) any customer holding two live subscriptions.
  - **What it skips:** subscriptions created in the last hour (fulfilment may still be pending),
    subscriptions already `canceled`, and charges already refunded.
  - **For each candidate it shows:**
    - all of that customer's live subscriptions, including any older than the campaign, each with
      created time, amount and payment status
    - the profile its email matches, if any, and that profile's current subscription
  - **The owner decides** which, if any, to refund; the sweep never names one and makes no write.
    Anything unresolved stays a candidate on the next run.
- **At 00:00 Tuesday Arizona:**
  - an open tab's banner and card disappear at 00:00 to within the clock offset (no reload)
  - `/api/promotion` returns `ended` within about 30 seconds
  - the campaign link shows the ended notice
  - a sale checkout request gets the ended 400
  - no open sale checkout outlives 00:31
- **Outcome measurement** (the after-launch summary plan, not this PR): net new paying annual
  subscribers during the window. Count from Stripe subscriptions carrying `promotion` metadata with
  an invoice that charged real money, minus those the owner refunded as duplicates. Compare with the
  same span one week earlier for standard annual paid starts. Its counting rules are
  designed against the real data when it runs.

## Context Files

- `docs/superpowers/specs/2026-11-24-black-friday-sale-design.md`: product intent. Where it and this
  plan differ, this plan wins (see Context and step 11).
- `frontend/components/Navigation.tsx` and `frontend/app/globals.css` (:100): where the banner mounts
  and the header-height variable it extends. Also read `components/GlobalSearch.tsx:223` and
  `components/RankingsStickyFilters.tsx:32`, the fixed elements that read that variable.
- `frontend/app/api/stripe/checkout/route.ts`: the route being extended. Note the two refusal gates
  and the trial rules.
- `frontend/app/api/stripe/webhook/route.ts`: fulfillment, the signed-out linking path,
  `handleChargeRefunded`, `isPermanentError`.
- `frontend/app/api/stripe/sync/route.ts` and `frontend/app/upgrade/success/page.tsx`: they write the
  subscription before the webhook, which is why the purchase event has no stored-id gate.
- `frontend/lib/stripe/server.ts`: the pinned API version, `WEBHOOK_EVENTS`, `mapStatusToPlan`,
  `updateUserProfile`.
- `frontend/app/upgrade/page.tsx` and `frontend/app/upgrade/page.test.tsx`: the page and the layout
  its tests pin.
- `frontend/lib/analyticsServer.ts`: the Measurement Protocol path to generalise.
- `frontend/hooks/useUser.ts`: profile, loading and error shape, and `hasPremiumAccess`. It is
  `'use client'`, so server code must never import from it.
- `frontend/middleware.ts`: why the in-page overlays are unreachable for the sale audience.
- `frontend/app/api/stripe/webhook/__tests__/route.test.ts`,
  `frontend/app/api/stripe/checkout/__tests__/route.test.ts` and `frontend/test/supabase-mock.ts`:
  the doubles to tighten.
- `.claude/skills/stripe-billing-data/SKILL.md` (read `origin/main`'s copy): field locations, the
  $0-invoice and `billing_reason` traps, the local fake-Stripe recipe.
- `frontend/CLAUDE.md`: API route auth inventory, the per-section providers, pitfalls 20 and 22.
