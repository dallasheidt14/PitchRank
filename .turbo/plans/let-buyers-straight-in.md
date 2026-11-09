---
status: done
---

# Plan: Let buyers straight in after a guest checkout

## Context

A parent taps a team, pays through Stripe, and lands logged out on a page telling them to find an email and set a
password before they can use what they bought. Some new buyers never get in, some buy a second time, and the team they
tapped is lost along the way. The audit of 2026-11-06 ranked this as the site's weakest moment.

The change signs a brand-new buyer in when they return from Stripe, opens the team they tapped, and emails a reminder
to new buyers who never made it in.

**Owner decisions, 2026-11-06:**
- Build the sign-in, accepting that a mistyped email gets the buyer in under the wrong address on a brand-new account.
- No password prompt, before or after. A buyer who needs a password later uses the existing "forgot password" email.
- Reminders go to new buyers only. Nobody who bought before this ships is emailed.

**Out of scope:** Manage subscription button, `/rankings` speed, search.

**Depends on** the tracking PR (branch `fix/subscription-tracking`), which makes the success page remove `session_id`
from the address bar, sends no Referer from that page, and counts subscriptions from the webhook. Analytics stays off
the success page, so the session id is never in a document that runs third-party code.

## Pattern Survey

Paths are relative to `frontend/` unless they start with `scripts/` or `src/`. Line numbers are from the tree
before #1410 and this change.

### Analogous Features

- **Server-side session creation:** `app/auth/confirm/actions.ts:22-23` calls `verifyOtp` on `createServerSupabase`, and
  cookies land through `setAll` (`lib/supabase/server.ts:8-40`). That write fails silently in a Server Component, so the
  new code must be a Route Handler or Server Action.
- **Token minting:** the only runtime `generateLink` is `app/api/stripe/webhook/route.ts:399`. The only `verifyOtp` is
  `app/auth/confirm/actions.ts:23`.
- **Webhook guest branch:** `app/api/stripe/webhook/route.ts` looks up the profile by `stripe_customer_id`
  (`:274-283`), then by email (`:302-306`), blocks or links on a match (`:315-362`), and otherwise creates the user
  (`:365-369`), updates the profile (`:377-380`), updates the Stripe customer (`:383`) and emails a set-password link
  (`:399-417`).
- **Stuck buyers:** `scripts/check_stuck_signups.py:116` `find_stuck_users` selects never-signed-in users with a live
  subscription, older than 2 hours, and `:195` emails an admin digest every 6 hours.

### Reusable Utilities

- `lib/auth/emailTokens.ts:26` `safeNextPath` validates same-origin paths.
- `app/upgrade/page.tsx:36` `TEAM_PATH` is the strict team-path regex.
- `lib/supabase/service.ts:43` `getSupabaseAdmin` gives service-role `auth.admin`.
- `lib/stripe/server.ts:72` `isSessionPaymentSettled`, including trial sessions.
- `lib/api/rateLimit.ts:22` `checkRateLimit`, per instance.
- `src/utils/resend_email.py:17` `send_email(to, subject, html) -> bool`, the shared Python sender.
- `scripts/team_cleanup/advance.py:259-264` `email_once`: stamp only after a successful send.

### Convention Anchors

- Emailed tokens are redeemed by POST only (`CLAUDE.md` rule 11). The new token is never emailed: it is minted and
  redeemed inside one server request.
- A page that renders with a credential in its URL is listed in `SECRET_QUERY_PATHS` (rule 12).
- `/api` skips middleware, so the route enforces everything itself. Public POST routes check `Content-Type` first.
- Scheduled Python monitors take `--dry-run`, never log addresses, and put no credential in a shared mailbox.

### Proposed Alignment

Follow the existing patterns for cookies, redirects and scheduled mail. This change deliberately departs from one
thing: nothing here has granted a session without mailbox or password proof. That is the new trust boundary, and
every gate in step 4 exists to keep it from reaching any account but one this checkout just created.

## Implementation Steps

1. **Share one team-path validator**
   - Add `safeTeamPath(raw): string | null` to `lib/auth/emailTokens.ts` beside `safeNextPath`, holding the regex now at
     `app/upgrade/page.tsx:36`. Have the upgrade page use it.

2. **Carry the tapped team through checkout**
   - `lib/stripe/client.ts:7`: `startCheckout(priceId, next)`. `handleUpgrade` in `app/upgrade/page.tsx` passes the
     page's `next`.
   - `app/api/stripe/checkout/route.ts:30`: read `next` and validate it with `safeTeamPath`. Write `return_to` into
     session metadata on both paths (`:120` and `:138`), never on the subscription.
   - `baseSessionParams` `:13`: `cancel_url` returns to `/upgrade?next=...` when a team is present.

3. **Mark accounts this checkout created, after their email is handled**
   - `app/api/stripe/webhook/route.ts`: leave `createUser` at `:365` as it is. After the password email attempt at
     `:417`, including when that send fails, call `auth.admin.updateUserById` to set
     `app_metadata: { checkout_session_id: session.id, return_to }`.
   - Stamp it last because a sign-in link and the emailed link share one Supabase token slot, so a sign-in minted before
     the email would be overwritten by it.
   - Use `app_metadata`, which a signed-in user cannot edit. `user_metadata` can be edited by the user.
   - Add nothing on the link-to-existing path (`:353-362`) or the blocked paths (`:315-349`). The absence of the marker
     is what keeps those accounts out of step 4 and step 8.

4. **Add `POST /api/stripe/checkout-login`** (`app/api/stripe/checkout-login/route.ts`)
   - Check `Content-Type`, then `checkRateLimit` under its own key at 10 a minute. Set `Cache-Control: no-store`.
   - Retrieve the Stripe session. Require `status === 'complete'`, `isSessionPaymentSettled`, and
     `metadata.anonymous_checkout === 'true'`.
   - A signed-in caller whose id matches `metadata.supabase_user_id` needs no minting: return
     `{ status: 'signed_in', next }`.
   - Find the profile by `stripe_customer_id`. None yet, or no marker yet: return `{ status: 'pending' }` with 202.
   - Load the user with `auth.admin.getUserById` and require all of these, or return `{ status: 'email' }`:
     - `app_metadata.checkout_session_id === session.id`
     - `last_sign_in_at` is empty, which makes the pass single-use with no new table
     - the account is under 30 minutes old
   - Mint with `auth.admin.generateLink({ type: 'magiclink', email })`, checking its `error`. Redeem `hashed_token` with
     `verifyOtp` on `createServerSupabase`.
   - Return `{ status: 'signed_in', next }`, taking `next` from `safeTeamPath(session.metadata.return_to)` and falling
     back to `/rankings`. Any failure returns `{ status: 'email' }`, never an error page.
   - Log the outcome and user id, never the email or the session id.

5. **Sign the buyer in from the success page** (`app/upgrade/success/page.tsx`)
   - After the existing sync, POST the captured `sessionId` to the new route. On `pending`, retry at 1, 2, 3 and 4
     seconds, then stop.
   - While waiting, show "Setting up your account...". Do not show the check-your-email box until the attempts end.
   - On `signed_in`, `window.location.replace(next)`. A full load is what makes `useUser` and the middleware see the new
     cookies. Never `<Link>` or `router.push` to the bare `/upgrade/success`: Next can restore the query from its route
     cache (vercel/next.js#91658).
   - On `email`, or when the attempts run out, show today's check-your-email state.

6. **Open the tapped team after setting a password**
   - `app/reset-password/page.tsx:68`: read `user.app_metadata.return_to` through `safeTeamPath`. When present, the button
     says "Go to your team" and goes there. Otherwise keep "Go to rankings".

7. **Word the email for someone already inside**
   - `lib/email/password-setup.ts`: add one line saying that if they already got in after paying, they can ignore this.
     Their link stops working once they are signed in, and the expired page already offers a new one.

8. **Email new buyers who never got in** (`scripts/check_stuck_signups.py`)
   - Keep the admin digest exactly as it is: no link, no address in logs.
   - Add a separate step over `find_stuck_users`, limited to users whose `app_metadata.checkout_session_id` is set. That
     marker is the "new buyers only" rule, because no account from before this change has it.
   - First reminder at 24 hours or older with none sent; second at 72 hours or older with one sent; never a third.
   - Mint a fresh recovery link with `auth.admin.generate_link`, build the same `/auth/confirm` URL as the webhook, and
     send through `send_email` to the buyer only.
   - After `send_email` returns true, write `app_metadata.setup_reminders_sent`. A failed send stays unstamped and retries
     on the next 6-hour run.
   - Log counts only. `--dry-run` sends and stamps nothing.

9. **Document the new boundary**
    - `frontend/CLAUDE.md`: list the route under Billing, and add one rule stating when a session may be granted without
      mailbox proof and which gates enforce it.

## Verification

- **Unit, the route:** one row per gate in step 4, each violating exactly one condition. A marker from a different
  session, a pre-existing account with no marker, `last_sign_in_at` set, an account past 30 minutes, an unsettled
  payment, and a signed-in checkout's session reached by a logged-out caller each return `email` and mint nothing.
  The double records at the terminal call, so a dropped `verifyOtp` fails.
- **Unit, the webhook:** the new-account path stamps the marker after the email attempt, including when it fails; the
  link-to-existing and blocked paths stamp nothing.
- **Unit, checkout:** a `next` that is not a team path never reaches Stripe metadata.
- **Unit, reminders:** a marker-less stuck user gets nothing; 23 hours gets nothing; 24 hours gets one and is stamped;
  a failed send is not stamped; two sent gets nothing; `--dry-run` sends and stamps nothing.
- **Mutation:** remove each gate alone and confirm its own named test fails.
- **End to end, on a production build, Stripe stubbed:** a throwaway account created for the run and deleted after it
  (owner OK needed first, because it writes to production auth). Confirm the buyer lands on the team page signed in, a
  second POST with the same session returns `email`, and no outgoing request carries `session_id`.
- **After it ships:** read the signed-in share for accounts created after the release from `auth.users`, grouped by
  `raw_user_meta_data->>'source'`. Do not filter on a token column. Compare with the share before the release, at 7 and
  14 days, and keep the figures out of public PRs and tracked files.
- **Confirm one assumption on the throwaway account:** that minting the sign-in link cancels the emailed link. The plan
  is safe either way, and only step 7's wording depends on it.

## Context Files

- `frontend/app/api/stripe/webhook/route.ts` — the guest branch, and where the marker goes
- `frontend/app/api/stripe/sync/route.ts` — the closest model for reading a checkout session
- `frontend/app/api/stripe/checkout/route.ts` — session metadata on both paths
- `frontend/app/upgrade/success/page.tsx` — the page this changes most
- `frontend/app/auth/confirm/actions.ts` — how a session is redeemed today
- `frontend/lib/auth/emailTokens.ts` — redirect validation
- `scripts/check_stuck_signups.py` and `tests/unit/test_check_stuck_signups.py` — the reminder's home, and the guard
  against links in the admin digest

## As built

Built 2026-11-09 on `fix/sign-buyers-in-on-return`, after the tracking PR merged as #1410. The steps above stand as
approved. The build differs from them in these ways, all from two seven-reviewer rounds and the live runs.

- **The sign-in is tied to the browser that started checkout.** Not in the plan, and the largest change. The session
  id alone is not proof: it sits in Stripe's hosted checkout URL, so a forwarded link or browser history carries it.
  The checkout route's guest branch sets an HttpOnly, Secure, SameSite=Lax cookie `checkout_browser` (path
  `/api/stripe/checkout-login`, one day) and stores the SHA-256 of its key as session metadata `browser_key_hash`.
  The route refuses any browser whose cookie does not hash to it, before any account lookup. The owner chose this
  on 2026-11-09. It also closes two concurrent sign-ins from different browsers.
- **Step 4's gates run in a different order, and there is one more.** The signed-in shortcut comes before the guest
  check, since a signed-in checkout carries no `anonymous_checkout`; read in the plan's order it could never be
  reached. A browser already signed in is never switched: signed in as this checkout's account it gets
  `signed_in` with nothing minted, as any other account `email`, so a second POST answers `email` only from a
  signed-out or different browser. The account's age and sign-in are checked before its marker, so only a fresh,
  unused account waits for the webhook; one with no marker that is older or already used is refused at once.
- **Reminders key on a flag written at account creation, not on the marker.** `createUser` sets
  `app_metadata.anonymous_checkout = true`, and step 8 reads that. A webhook that fails after creating the account
  then still leaves it eligible, where keying on the marker, written last, would have dropped exactly the buyers the
  reminders exist for. Only `createUser` writes the flag, so accounts from before this change and accounts the
  webhook links or blocks never carry it, and "new buyers only" holds.
- **The shared token slot is confirmed**, which step 3's ordering and step 7's wording both rest on. On a live run,
  a set-password link minted before the sign-in was rejected after it. The email now says the link stops working once the buyer is signed in, and points to
  Forgot password.
- **One team-path check.** `safeTeamPath` is built on `isValidUuid` from `lib/validation.ts` rather than a second
  copy of the UUID pattern.

Verified: unit tests for every gate, each removed alone in three rounds of deliberate breaks and caught by its own
named test; and three runs on a production build with Stripe faked. Two of those ran against live Supabase auth,
each with one throwaway account deleted afterwards: the first before the browser tie, the second through the real
checkout route after it. The third, after the last edits, created no account. Not run: a real Stripe checkout, a
real webhook delivery, a reminder email actually sent, the deployed site, and Safari.
