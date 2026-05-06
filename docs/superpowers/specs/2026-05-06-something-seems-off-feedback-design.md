# "Something Seems Off?" In-Product Feedback Widget

**Date:** 2026-05-06
**Status:** Approved (pending user review of this written spec)

## Summary

Add a small `?` icon to the global navigation bar that opens a categorized feedback modal. Users (signed-in or anonymous) can submit short reports — "I can't find my team", "Rankings look wrong", etc. — which are emailed to `pitchrankio@gmail.com` via the existing Resend integration. No database, no admin page, no third-party widgets.

The current state has only a `mailto:pitchrankio@gmail.com` link in the footer. That is high-friction and low-discoverability, especially for the two highest-value report types (a coach who can't find their team, a parent who thinks rankings look off).

## Goals

- One-click "report what I'm looking at" path from any page.
- Auto-attach page context (URL, signed-in identity, viewport, user-agent) so triage doesn't require back-and-forth.
- Land in the existing inbox (`pitchrankio@gmail.com`) — no new tools to check.
- Anonymous users can submit; signed-in users don't have to type their email.
- Replyable: hitting Reply in Gmail goes back to the submitter.

## Non-goals (v1)

- Admin review page (`/admin/feedback`).
- Database storage of reports (`feedback_reports` table). Only optional touch is a future rate-limit table if in-memory limiting becomes insufficient.
- Categories beyond the five fixed options. No file uploads, screenshots, or team/game pickers.
- Telegram, Slack, or GitHub-issue routing.
- CAPTCHA / Turnstile (honeypot + min-time + IP rate-limit covers v1).
- Footer `mailto:` link upgrade — stays as-is.
- Auto-attach of structured `team_id` / `game_id` — only `pathname` is captured.
- Reply-tracking, threading, or anonymous-identity verification.

## Architecture

Three new files, one tweak. No new npm dependencies. No DB migration.

| File | Role |
|---|---|
| `frontend/components/FeedbackTrigger.tsx` | Client component. `?` icon button mounted in `Navigation.tsx`. Owns no logic except opening the modal. |
| `frontend/components/FeedbackModal.tsx` | Client component. Radix Dialog form. Posts to `/api/feedback`. |
| `frontend/lib/email/feedback.ts` | Builds HTML + plain-text email body. Mirrors `report-card.ts` / `welcome.ts` patterns. |
| `frontend/app/api/feedback/route.ts` | Next.js route handler. Validates, rate-limits, sends via Resend. |
| `frontend/components/Navigation.tsx` | **Modified.** Mount `<FeedbackTrigger />` between watchlist star and user/sign-in button. |

### Boundaries

Each unit has one clear job:

- **Trigger** — open modal. No state. No fetching.
- **Modal** — collect input, post the form. No knowledge of how the email is shaped or sent.
- **API route** — validate, rate-limit, dispatch. No knowledge of UI.
- **Email builder** — produce HTML + plain-text. No knowledge of HTTP or transport.

## UI / Interaction

### Trigger

- `<Button variant="ghost" size="icon">` containing lucide `HelpCircle` (20px).
- Position: in `Navigation.tsx`, between the watchlist star and the user/sign-in button.
- `aria-label="Report an issue"`, `title="Something seems off?"` for hover tooltip.
- 44×44px hit target on mobile (matches the project's existing icon-button standard).
- `data-testid="feedback-trigger"`.
- Hidden when `usePathname()` starts with `/embed`, or matches `/login` or `/signup`. Implementation: early-return `null`.

### Modal

- Radix Dialog (`components/ui/dialog`), max-width ~480px, centered.
- **Title:** "Something seems off?"
- **Subtitle:** "Tell us what you're seeing — we read every report."

**Fields, top to bottom:**

1. **Category** (`<Select>`, required) — fixed list:
   - `cant-find-team` → "I can't find my team"
   - `rankings-wrong` → "Rankings look wrong"
   - `wrong-games` → "Wrong games attached to a team"
   - `bug` → "Bug or broken page"
   - `other` → "Other"
2. **What's happening?** (`<Textarea>`, required, 10–2000 chars, autofocus). Placeholder text varies by category:
   - `cant-find-team` → *"Club name, age group, gender, state — anything that helps us find them."*
   - `rankings-wrong` → *"Which team, and what looks off about their ranking?"*
   - `wrong-games` → *"Which team's game list looks wrong, and which game(s)?"*
   - `bug` → *"What did you click, and what happened vs what you expected?"*
   - `other` → *"Tell us what's on your mind."*
3. **Email** (`<Input type="email">`, optional) — only rendered when `!user` (anonymous submitter). Helper text: *"So we can reply if we have questions. We won't add you to anything."*
4. **Honeypot** — hidden `<input name="website">` styled `display: none` and `tabIndex={-1}` and `autoComplete="off"`. Bots fill it; humans don't.

**Hidden auto-attached context** (no UI, included in submit body): `pathname`, `referrer`, `userAgent`, viewport `{w,h}`, `submittedAt` (ISO), `openedAt` (ISO; recorded when modal mounts).

**Buttons:** "Send" (primary, disabled until category + ≥10 chars message), "Cancel" (ghost).

**States:**

| State | UI |
|---|---|
| Idle | Form visible. Send disabled until valid. |
| Submitting | Send shows spinner. All fields disabled. |
| Success | Replace form with green-tinted panel: "Thanks — we got it. [Close]". Auto-close after 4s. |
| Error (network / 5xx) | Banner: "Couldn't send right now. Try again, or email pitchrankio@gmail.com." Send re-enabled. |
| Rate-limited (429) | Same panel as error, copy: "You've sent a few already — give it an hour and try again." |

**Accessibility:** Radix Dialog handles focus trap, ESC, `aria-labelledby`. Submit is the form's submit button (Enter from textarea submits). Live region announces success and error.

**Persistence detail:** Form values persist in component state across an open/close cycle within the same page navigation, so accidental Cancel doesn't lose typing. Cleared on successful submit and on route change.

## API: `POST /api/feedback`

### Request body shape

Validation is manual (mirroring `app/api/newsletter/route.ts`); zod is not installed in this project and we won't add it for one route.

```ts
{
  category: 'cant-find-team' | 'rankings-wrong' | 'wrong-games' | 'bug' | 'other',
  message: string,            // 10..2000 chars, trimmed
  email?: string,             // optional, must parse as email if present
  website?: string,           // honeypot — must be empty/absent
  context: {
    pathname: string,         // 1..512 chars
    referrer?: string,        // <=512 chars
    userAgent?: string,       // <=512 chars
    viewport?: { w: number, h: number },
    openedAt: string,         // ISO; modal mount time (client clock)
    submittedAt: string       // ISO; client-recorded at submit (client clock)
  }
}
```

### Flow

1. Parse JSON via `parseJsonBody` helper. Bad JSON → 400.
2. Validate fields manually (presence, type, length, email regex matching the project's existing pattern). Validation fail → 400 with a single `error` string.
3. **Honeypot check.** If `website` is non-empty → return 200 `{ ok: true }` *without sending* (silent reject so bots don't learn).
4. **Min-time floor.** If `submittedAt - openedAt < 2000ms` → return 200 `{ ok: true }` without sending. Same silent-reject rationale. Both timestamps are client-clock; the *delta* is meaningful even under clock skew, so the server uses the client values as-given for this check (it does not substitute its own clock).
5. **Identify caller.** Try `getUser()` from server Supabase client. If session present, capture `user.id` + `user.email` from the *server-side*, not the client body (never trust client identity).
6. **Rate-limit check** via `lib/api/rateLimit.ts`. Key: IP address (signed-in identity is ignored for limiting — IP is what bots share). Limits: **5 requests / hour**, window `3_600_000ms`. If denied → 429 with `Retry-After` header.
7. Build email via `buildFeedbackEmail({ category, message, replyTo, identity, context, ipMasked })`.
8. Send via Resend.
   - `to`: `pitchrankio@gmail.com`
   - `from`: `PitchRank <feedback@mail.pitchrank.io>` (matches existing per-purpose sender pattern: `reports@`, `newsletter@`, `noreply@`)
   - `replyTo`: signed-in `user.email` if present, else submitted `email` if present, else omitted
   - `subject`: `[PitchRank Feedback] {Category Label} — {first 60 chars of message}`
9. On Resend error → log structured error, return 502 `{ error: 'send_failed' }`.
10. On success → 200 `{ ok: true }`.

### Response shapes

- **200** `{ ok: true }` — success, honeypot reject, or min-time reject.
- **400** `{ error: <human-readable string, e.g. "Message must be at least 10 characters"> }`
- **429** `{ error: 'rate_limited' }` + `Retry-After` header
- **502** `{ error: 'send_failed' }`

The modal maps these to the four UX states (Idle/Submitting are client-only).

### Identity rules (security)

- Server reads `user.id` / `user.email` from the Supabase session, *never* from the request body. A client could lie about who they are; the server doesn't accept that input.
- The optional anonymous `email` field is treated as untrusted display text — used only for `replyTo` and rendered in the email's "From" line. No auth implications.
- IP is captured server-side from `x-forwarded-for` (Vercel sets this), last octet masked in the email body for log-privacy.

## Email body (`lib/email/feedback.ts`)

Mirrors the structure of `report-card.ts` and `welcome.ts`: dark-green header bar, gray content card, plain-text fallback.

**Top summary block** (so inbox preview is useful):

```
Category:   Rankings look wrong
From:       coach@example.com (signed-in user, id=abc-123)
Page:       /teams/buena-soccer-club-u14-boys
When:       2026-05-06 11:42 AM CT
```

**Body:** the user's message in a monospace block, preserved newlines, HTML-escaped to prevent injection. Even though the recipient is internal, escaping is non-optional — it protects against breakage of the email layout, not just security.

**Footer block** (small / muted): referrer, viewport, user-agent, IP with last octet masked.

## Spam protection

Three cheap layers, no CAPTCHA:

1. **Honeypot field** — hidden `<input name="website">`. Server silently 200s any submission where it's non-empty.
2. **Min-time floor** — server silently 200s if `submittedAt - openedAt < 2000ms`. Bots auto-submit instantly; humans need >2s to type ≥10 chars.
3. **IP rate limit** — 5/hour via `lib/api/rateLimit.ts`. Reuses the existing in-memory helper, accepting that on Vercel each function instance has its own counter (so the real cap is `5 × instance_count`). For v1's expected volume this is fine. If real spam appears, swap to a Redis-backed implementation in a follow-up — not part of this spec.

**Anti-pattern intentionally avoided:** CAPTCHA, account-required gating, or aggressive bot detection in v1.

## Error handling philosophy

- **User-facing copy:** human, short, no HTTP codes, no stack traces.
- **Server logs:** structured. Every send attempt logs `{ category, identity: user_id_or_anonymous, pathname, outcome, resendId? }`.
- **No leaking signal to bots:** honeypot and min-time rejects return 200; rate-limit copy is vague ("you've sent a few already") rather than specific.

## Testing

Three layers, each small:

1. **Unit test for `lib/email/feedback.ts`.** Inputs: synthetic category/message/identity/context. Assert: HTML contains the message, subject is shaped right, message containing `<script>`/`<img onerror=...>` is escaped.
2. **Route test for `POST /api/feedback`** (mirrors `app/api/match-prediction/__tests__/route.test.ts`). Cases:
   - Valid signed-in submission → 200, Resend called once with correct `from`/`to`/`replyTo`/`subject`.
   - Valid anonymous submission with email → 200, `replyTo` is the submitted email.
   - Valid anonymous submission without email → 200, no `replyTo`.
   - Missing category → 400.
   - Message <10 chars or >2000 chars → 400.
   - Honeypot filled → 200 *and* Resend not called.
   - `submittedAt - openedAt < 2000ms` → 200 *and* Resend not called.
   - 6th request from same IP within hour → 429 with `Retry-After`.
   - Resend throws → 502.
3. **One manual smoke** before merge: open any non-`/embed` page, click `?` in nav, fill form, submit, see success state, confirm email lands in `pitchrankio@gmail.com` with correct subject and replyTo.

No frontend unit tests for the modal — Radix Dialog is well-tested, and the form logic is thin.

## Open dependencies (handle during implementation, not blockers)

- **Sender domain:** `feedback@mail.pitchrank.io` must be a verified sender in Resend. If not yet configured, add the DNS record during implementation. The existing `mail.pitchrank.io` is already verified for `reports@`, `newsletter@`, `noreply@` — adding another mailbox prefix on the same domain typically requires no DNS change, but worth confirming in Resend's dashboard.
- **Vercel `x-forwarded-for`:** standard on Vercel; no config needed.

## Future / not-now

If the widget proves useful and volume grows:

- Persist submissions to a `feedback_reports` Supabase table (status, category, message, URL, user_id, ip, ua, created_at). Enables analytics, dedup, and an admin review page.
- Build `/admin/feedback` triage UI (similar shape to existing admin views).
- Add Telegram or push notification for `cant-find-team` category specifically (signal of a coach trying to onboard).
- Swap in-memory rate-limit for Redis-backed if abuse appears.
- Add Turnstile if a real spam attack happens.
- Smart category preselect based on URL (parking-lot from brainstorming).
- Auto-parse pathname into structured team_id / game_id for richer email context.
