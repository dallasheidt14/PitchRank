# MatchBalance Website Lead Capture — Design

- **Date**: 2026-09-16
- **Status**: approved 2026-09-16; plan at .turbo/plans/matchbalance-website-lead-capture.md
- **Surface**: the public Next.js site (`frontend/`). The Streamlit Seeding intake
  (`tournament_intake.py`, `src/tournaments/*`) is untouched.
- **Branch**: `feat/matchbalance-site`

## Problem

MatchBalance exists only as an operator tool. A tournament director has no way to find
out it exists, see what the deliverable looks like, learn the price, or ask for it. The
service process after the first contact (collect the accepted-team list, prepare a free
sample, send a fixed quote, deliver the package and one update) already works over email
and Streamlit; what is missing is the front door.

The website's job is to get the conversation started and record that it started. It does
not run the intake, take payment, or give directors an account.

## Decisions taken during design

| Question | Decision |
|---|---|
| What lives on the site | Sales page and inquiry form only. Operator work stays in Streamlit. |
| Price on the page | The whole-event tier table and the à la carte block below (see Pricing). This replaces the "$3 per team, never shown" rule in the earlier build brief for the public page; the Streamlit quote engine will need to be reconciled with these tiers when that work is picked up. |
| Sample | One real cohort from a past event, as-is: the saved run `san-antonio-labor-cup-2026-u13-male` under `reports/seeding/`. Club and team names are public tournament data. |
| Spam protection | Honeypot field, minimum fill time, per-IP rate limit, copied from `/api/feedback`. No captcha service. |
| Lead storage | A new `matchbalance_leads` table, readable and writable only through the service role. Email alone is not the record. |
| Admin access | A Leads page under `/mission-control`, protected by the existing middleware admin gate. |

## Page: `/matchbalance`

`frontend/app/matchbalance/page.tsx`, a server component cloned from
`frontend/app/report-card/page.tsx`: static `metadata` with canonical and Open Graph
title/description only, as that page does — no Twitter block and no image, because the
only image is a portrait Letter page that a 2:1 card would crop; `revalidate = 3600`; no
React Query. Add the route to `staticPages` in
`frontend/app/sitemap.ts` and to `renderCoreContent()` in
`frontend/scripts/generate-llms-txt.ts`, then regenerate `public/llms.txt`.

Sections, in order:

1. **Hero.** MatchBalance is a ranked cheat sheet for tournament directors, built from
   PitchRank ratings, delivered per age group and gender before the bracket meeting. One
   button scrolls to the inquiry form.
2. **What you get.** The PDF sheet for every covered age group, the editable team file
   (CSV), and one consolidated update before the director's bracket review. The director
   keeps full control of flights and brackets; MatchBalance does not place teams.
3. **Sample.** The U13 Boys sheet from the San Antonio Labor Cup 2026, shown as an image
   of page one with a link to the full PDF (`public/matchbalance/sample-u13-boys.pdf`).
4. **How it works.** Four steps: send the accepted-team list or event link; receive a
   free sample cohort; receive one fixed price for the event; receive the package and
   one update.
5. **Pricing.** The tables below, verbatim.
6. **FAQ.** Rendered as `<details>` blocks with FAQ JSON-LD from the existing
   `frontend/components/BlogFAQSchema.tsx`, which is already generic and takes plain-string
   question/answer pairs. Covers: which ages are supported,
   what happens to teams PitchRank has no current rank for, turnaround, what the update
   covers, what the director needs to send to get started, and what MatchBalance does not
   do. The page does not name any registration platform.
7. **Inquiry form.** See below.

Also add `BreadcrumbSchema`, a nav or footer link (footer at minimum,
`frontend/components/Footer.tsx`), and an entry in the "Public" block of
`frontend/CLAUDE.md`'s API route catalogue for the new route.

### Pricing (exact copy for the page)

**MatchBalance Pricing**

| Total teams | Price |
|---|---|
| Up to 75 | $199 |
| 76–150 | $399 |
| 151–300 | $699 |
| 301–450 | $1,199 |
| 451–600 | $1,499 |
| 601+ | Custom quote |

*Need help with only part of your tournament?*

**À la carte**

| Cohorts | Price |
|---|---|
| 1 cohort | $49 |
| 3 cohorts | $129 |
| 6 cohorts | $239 |

Every package includes: MatchBalance PDF, editable team file, and one update before your
bracket review.

Free sample: one age group + gender from your tournament.

The page never shows a per-team rate or a percentage of entry fees.

## Inquiry form

`frontend/components/MatchBalanceInquiryForm.tsx`, a client component. State machine and
success card from `frontend/components/ReportCardForm.tsx`; honeypot input and
opened-at timestamp from `frontend/components/FeedbackModal.tsx`.

| Field | Required | Notes |
|---|---|---|
| Your name | yes | |
| Email | yes | `isValidEmail`; show `suggestEmailCorrection` hint |
| Organization | yes | club, league or event operator |
| Tournament name | yes | |
| Event dates | yes | free text, one line |
| Approximate number of teams | no | integer |
| Bracket review date | no | date input; drives turnaround |
| Event link | no | URL of any event page |
| What do you need | yes | radio: "Free sample" or "Quote for the whole event" |
| Anything else | no | textarea |
| `website` (honeypot) | hidden | visually hidden, `tabIndex=-1`, `autoComplete="off"` |
| `openedAt` | hidden | set when the form mounts |

On success the form is replaced by a card: "Thanks. We'll reply within one business day.
If you have the accepted-team list already, reply to the confirmation email with it
attached." On error the form stays filled and shows the message.

## API route: `POST /api/matchbalance-inquiry`

`frontend/app/api/matchbalance-inquiry/route.ts`, modelled on `app/api/feedback/route.ts`
for the guards and their order, and on `app/api/track-team-view/route.ts:39-45` for the
awaited service-role save that returns 500 on failure. (The report-card route's
fire-and-forget insert cannot express that, so it is not the model.)

1. `Content-Type` not `application/json` → 415, so another site cannot post from its
   visitors' browsers without a CORS preflight. `parseJsonBody` → 400 on bad JSON or a
   non-object body.
2. Honeypot filled → 201 `{ ok: true }`, do nothing (same status as a real save, so a bot
   cannot tell it was dropped).
3. `openedAt` and `submittedAt` both required and parseable → else 400. Fill time
   (`submittedAt - openedAt`, both from the client so clock skew cannot drop a real
   lead) under 2000 ms → 201, do nothing.
4. Validate: required strings with length caps (name 120, organization 160, tournament
   200, event dates 120, notes 2000), email at most 254 characters (checked before
   `isValidEmail`, whose pattern is quadratic on long input), team count an integer
   0–5000 when present, bracket date `YYYY-MM-DD` and parseable when present, event link
   an `http(s)` URL under 500 chars when present, request type one of `sample` or
   `quote`. "Present" means not `undefined`, `null` or blank; the form omits blank
   optionals and the route treats `""` the same way. Any failure → 400 with a plain
   message.
5. `checkRateLimit('matchbalance:' + ip, 5, 60 * 60 * 1000)` → 429. It runs last, as in
   the feedback route, so only well-formed submissions consume a slot and a director
   correcting a typo is not locked out.
6. Insert one row into `matchbalance_leads` with `createServiceSupabase()`, awaited.
   Failure → 500; nothing else runs.
7. Await both email sends (they never throw; each returns `false` on failure, which is
   logged). Return 201 `{ ok: true }`. Awaiting matches `/api/feedback`, and an unawaited
   send on Vercel can be cut off when the response returns.

Auth: none, deliberately. All `/api` routes are outside the middleware matcher, so this
route is public by construction, and the guards above are its whole defence.

## Data: `matchbalance_leads`

Migration `supabase/migrations/20260916120000_create_matchbalance_leads.sql`, modelled on
`20260903120000_add_team_page_views.sql` for the access pattern and on
`20260615000000_create_outreach_targets.sql` for the `updated_at` trigger and comments.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk default `gen_random_uuid()` | |
| `created_at` | timestamptz default `now()` | |
| `updated_at` | timestamptz default `now()` | trigger-maintained |
| `name` | text not null | |
| `email` | text not null | |
| `organization` | text not null | |
| `tournament_name` | text not null | |
| `event_dates` | text not null | free text |
| `team_count` | integer | nullable |
| `bracket_review_date` | date | nullable |
| `event_url` | text | nullable |
| `request_type` | text not null | `sample` or `quote`; free text by repo convention, no CHECK |
| `notes` | text | nullable |
| `source_ip_masked` | text | via `maskIp()` from the feedback route |
| `status` | text not null default `'new'` | pipeline stage, free text (`new`, `contacted`, `sample_sent`, `quoted`, `won`, `lost`) |

Access: `ENABLE ROW LEVEL SECURITY`; a `deny_all` policy for `anon, authenticated`; a
full-access policy for `service_role`; `REVOKE ALL ON public.matchbalance_leads FROM anon,
authenticated`, because this project's default ACL grants anon every privilege on a new
public relation. Index on `created_at DESC`.

No TypeScript type generation exists in this repo; declare a hand-written
`MatchBalanceLead` interface beside the admin data function.

## Emails

`frontend/lib/email/matchbalance-inquiry.ts`, exported from `lib/email/index.ts`. Both
senders follow the repo contract: return `false` and log when `RESEND_API_KEY` is unset,
never throw.

- **Owner alert.** From `PitchRank <matchbalance@mail.pitchrank.io>`, to
  `pitchrankio@gmail.com` (the same inbox the feedback alert uses), `replyTo` the
  director. Subject: `MatchBalance inquiry: {tournament_name} ({request_type})`. Body: every
  field, HTML-escaped, plus a link to `/mission-control/leads`.
- **Confirmation.** From the same address, to the director. Subject:
  `We received your MatchBalance request`. Body: what happens next (reply within one
  business day; send the accepted-team list or event link by replying), and the free-sample
  note. No price in this email, and nothing the submitter typed: the address is
  unverified, so echoing a name or tournament would let anyone send branded text to any
  inbox.

## Admin: `/mission-control/leads`

`frontend/app/mission-control/leads/page.tsx`, a `force-dynamic`, `noindex` server
component cloned from `app/mission-control/subscriptions/page.tsx`. Data function
`fetchMatchBalanceLeads()` in `frontend/lib/admin/matchbalance-leads.ts` with
`import 'server-only'`, using `createServiceSupabase()`, returning rows newest first plus
an `errors[]` the page renders instead of throwing.

Table columns: When, Name, Email (mailto), Organization, Tournament, Dates, Teams, Bracket
review, Request, Status, Notes (truncated, full text on hover). Above it, three counts:
total, this week, awaiting reply (`status = 'new'`). A button on `app/mission-control/page.tsx`
links to it. Status editing is out of scope for this build; the column is shown, not edited.

## Sample asset

Render the saved run `reports/seeding/san-antonio-labor-cup-2026-u13-male` through the
current `seeding_sheet` and `seeding_pdf` code on `origin/main` and commit two files:
`frontend/public/matchbalance/sample-u13-boys.pdf` and a PNG of page one
(`sample-u13-boys.png`, 2x, under 500 KB) for the page. The PDF is served as a static file,
so `next.config.ts` needs no change. If the run does not render cleanly under the current
code, fix the run data, not the renderer.

## Wording rules

- Say "placement discrepancy"; never "sandbagger" or "sandbagging".
- Unranked teams: "PitchRank has no current rank for these teams."
- Do not claim the sheet makes placements fair. It is evidence the director can use.
- Do not promise turnaround shorter than one business day for the reply, and do not quote a
  delivery time on the page; the quote email sets that per event.

## Testing

- `frontend/app/api/matchbalance-inquiry/__tests__/route.test.ts`, mirroring
  `app/api/feedback/__tests__/route.test.ts`: 400 on each missing required field and each
  malformed optional field, silent 201 on honeypot and on fast fill, 429 on the sixth call
  in an hour, 201 with the insert recorded by the mock's terminal call and both senders
  invoked once, 500 when the insert fails and no email sent. Use `filteringClientMock` from
  `test/supabase-mock.ts` if any test asserts on a filter.
- `frontend/lib/email/__tests__/matchbalance-inquiry.test.ts`: both senders return
  `false` without a key; with a key, the owner alert carries `replyTo` and the escaped
  fields, the confirmation carries no price.
- `tests/unit/test_matchbalance_leads_migration.py`: resolve the table by name across all
  migrations, extract the `CREATE TABLE`, `CREATE POLICY` and `REVOKE` statements, and assert
  each on its own statement (deny-all policy names both `anon` and `authenticated`; the
  REVOKE names both roles; the service-role policy exists). Assert no later migration
  touches the table, so a widening ALTER fails loudly.
- Sitemap and llms.txt: assert the new route is present in both.
- The seven CI gates from `CLAUDE.md`, run from this worktree after `npm ci` in `frontend/`.

## Not in this build

- Payments, invoicing, customer accounts, or any self-serve delivery.
- Any change to `tournament_intake.py`, `src/tournaments/*`, or the Streamlit quote logic.
- Captcha or Turnstile.
- Editing lead status from the admin page.
- Beehiiv sync for directors.
- The blog line at `frontend/content/blog-posts.tsx:819` ("not for tournament directors")
  contradicts this page and should be revised in its own change.

## Rejected alternatives

- **Embedded third-party form (Tally, Typeform, HubSpot).** Faster to ship, but leads
  live outside the site, there is no admin view without another login, and the repo already
  has every piece the in-house version needs.
- **Email-only capture.** Rejected by the brief: an email notification must not be the only
  record.
- **Turnstile.** Net-new service, env vars and a verify call, for a form that expects a few
  submissions a week. The feedback route's honeypot, dwell floor and rate limit have held.
- **Showing the "$3 per team" rate.** The owner replaced it with fixed tiers because a
  director should not have to calculate anything.
