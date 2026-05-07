# "Something Seems Off?" Feedback Widget — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a global `?` button in the nav that opens a categorized feedback modal; submissions are emailed to `pitchrankio@gmail.com` via existing Resend infra.

**Architecture:** Trigger (client) opens Modal (client). Modal posts to `/api/feedback`. Route validates, applies honeypot + min-time + IP rate-limit, then dispatches via `lib/email/feedback.ts`. No DB.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript 5.9, Tailwind v4, Radix Dialog (`components/ui/dialog`), Resend, lucide-react, Vitest. Manual validation (zod is not in this repo).

**Spec:** `docs/superpowers/specs/2026-05-06-something-seems-off-feedback-design.md`

**File map:**
| File | Status | Purpose |
|---|---|---|
| `frontend/lib/email/feedback.ts` | Create | Build HTML + plain-text email body, expose `sendFeedbackEmail` |
| `frontend/lib/email/__tests__/feedback.test.ts` | Create | Unit tests for builder (escaping, subject shape) |
| `frontend/lib/email/index.ts` | Modify | Re-export `sendFeedbackEmail` |
| `frontend/app/api/feedback/route.ts` | Create | `POST` handler: validate, honeypot, min-time, rate-limit, send |
| `frontend/app/api/feedback/__tests__/route.test.ts` | Create | Route tests covering all branches |
| `frontend/components/FeedbackModal.tsx` | Create | Categorized form, posts to API, three end-states |
| `frontend/components/FeedbackTrigger.tsx` | Create | `?` icon button, mounts the modal |
| `frontend/components/Navigation.tsx` | Modify | Mount `<FeedbackTrigger />` between watchlist star and user/sign-in button |

**Conventions confirmed by reading the codebase:**
- Validation style: manual presence/type/length/regex checks (see `app/api/newsletter/route.ts`).
- IP capture: `request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'unknown'`.
- Rate limiter: `checkRateLimit(ip, maxRequests, windowMs)` from `lib/api/rateLimit.ts`. Returns `boolean`.
- JSON body parsing: `parseJsonBody<T>(request)` from `lib/api/parseJsonBody.ts` returns `{ data, error: null } | { data: null, error: NextResponse }`.
- Server Supabase: `await createServerSupabase()` from `lib/supabase/server.ts`.
- Email send pattern: `if (!resend) { warn; return false } try { await resend.emails.send(...) }`.
- Sender prefix per purpose: `reports@`, `newsletter@`, `noreply@`. We'll add `feedback@`.
- Test runner: Vitest. Test file lives at `app/api/<route>/__tests__/route.test.ts`. Mocks via `vi.hoisted`.

---

## Task 1: Email builder — failing test

**Files:**
- Create: `frontend/lib/email/__tests__/feedback.test.ts`

- [ ] **Step 1.1: Create the test file with failing tests**

```ts
// frontend/lib/email/__tests__/feedback.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockSend } = vi.hoisted(() => ({
  mockSend: vi.fn(),
}));

vi.mock('../resend', () => ({
  resend: { emails: { send: mockSend } },
}));

import { sendFeedbackEmail, CATEGORY_LABELS } from '../feedback';

const baseInput = {
  category: 'rankings-wrong' as const,
  message: 'My U14 team is ranked too low',
  identity: { kind: 'signed-in' as const, userId: 'user-123', email: 'coach@example.com' },
  context: {
    pathname: '/teams/abc-u14-boys',
    referrer: 'https://google.com',
    userAgent: 'Mozilla/5.0',
    viewport: { w: 1280, h: 800 },
    submittedAt: '2026-05-06T18:42:00.000Z',
    openedAt: '2026-05-06T18:41:30.000Z',
  },
  ipMasked: '192.168.1.x',
};

describe('sendFeedbackEmail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSend.mockResolvedValue({ data: { id: 'email-id' }, error: null });
  });

  it('sends from feedback@mail.pitchrank.io to pitchrankio@gmail.com', async () => {
    await sendFeedbackEmail(baseInput);
    const call = mockSend.mock.calls[0][0];
    expect(call.from).toBe('PitchRank <feedback@mail.pitchrank.io>');
    expect(call.to).toBe('pitchrankio@gmail.com');
  });

  it('subject contains category label and message snippet', async () => {
    await sendFeedbackEmail(baseInput);
    const subject = mockSend.mock.calls[0][0].subject;
    expect(subject).toContain('[PitchRank Feedback]');
    expect(subject).toContain(CATEGORY_LABELS['rankings-wrong']);
    expect(subject).toContain('My U14 team is ranked too low');
  });

  it('truncates long messages in subject to 60 chars', async () => {
    const longMsg = 'a'.repeat(200);
    await sendFeedbackEmail({ ...baseInput, message: longMsg });
    const subject = mockSend.mock.calls[0][0].subject;
    const tail = subject.split('—').pop()!.trim();
    expect(tail.length).toBeLessThanOrEqual(63); // 60 + ellipsis
  });

  it('escapes HTML in the user message body', async () => {
    const dangerous = '<script>alert(1)</script><img onerror=x src=y>';
    await sendFeedbackEmail({ ...baseInput, message: dangerous });
    const html = mockSend.mock.calls[0][0].html;
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('<img onerror');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('&lt;img onerror=x src=y&gt;');
  });

  it('sets replyTo to user.email for signed-in submitters', async () => {
    await sendFeedbackEmail(baseInput);
    expect(mockSend.mock.calls[0][0].replyTo).toBe('coach@example.com');
  });

  it('sets replyTo to anonymous email when provided', async () => {
    await sendFeedbackEmail({
      ...baseInput,
      identity: { kind: 'anonymous', email: 'anon@example.com' },
    });
    expect(mockSend.mock.calls[0][0].replyTo).toBe('anon@example.com');
  });

  it('omits replyTo when anonymous with no email', async () => {
    await sendFeedbackEmail({
      ...baseInput,
      identity: { kind: 'anonymous' },
    });
    expect(mockSend.mock.calls[0][0].replyTo).toBeUndefined();
  });

  it('returns false and does not throw when resend is null', async () => {
    vi.resetModules();
    vi.doMock('../resend', () => ({ resend: null }));
    const { sendFeedbackEmail: localSend } = await import('../feedback');
    const result = await localSend(baseInput);
    expect(result).toBe(false);
  });

  it('returns true on successful send', async () => {
    const result = await sendFeedbackEmail(baseInput);
    expect(result).toBe(true);
  });
});
```

- [ ] **Step 1.2: Run the test to confirm it fails**

```bash
cd C:/PitchRank/frontend && npx vitest run lib/email/__tests__/feedback.test.ts
```

Expected: FAIL — module `../feedback` does not exist.

---

## Task 2: Email builder — minimal implementation

**Files:**
- Create: `frontend/lib/email/feedback.ts`

- [ ] **Step 2.1: Create the builder**

```ts
// frontend/lib/email/feedback.ts
import { resend } from './resend';

export type FeedbackCategory = 'cant-find-team' | 'rankings-wrong' | 'wrong-games' | 'bug' | 'other';

export const CATEGORY_LABELS: Record<FeedbackCategory, string> = {
  'cant-find-team': "Can't find my team",
  'rankings-wrong': 'Rankings look wrong',
  'wrong-games': 'Wrong games attached',
  bug: 'Bug or broken page',
  other: 'Other',
};

export type FeedbackIdentity =
  | { kind: 'signed-in'; userId: string; email: string }
  | { kind: 'anonymous'; email?: string };

export interface FeedbackContext {
  pathname: string;
  referrer?: string;
  userAgent?: string;
  viewport?: { w: number; h: number };
  submittedAt: string;
  openedAt: string;
}

export interface SendFeedbackEmailInput {
  category: FeedbackCategory;
  message: string;
  identity: FeedbackIdentity;
  context: FeedbackContext;
  ipMasked: string;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function truncateForSubject(s: string, max = 60): string {
  const oneLine = s.replace(/\s+/g, ' ').trim();
  return oneLine.length <= max ? oneLine : oneLine.slice(0, max) + '…';
}

function buildSubject(category: FeedbackCategory, message: string): string {
  return `[PitchRank Feedback] ${CATEGORY_LABELS[category]} — ${truncateForSubject(message)}`;
}

function buildFromLine(identity: FeedbackIdentity): string {
  if (identity.kind === 'signed-in') {
    return `${identity.email} (signed-in user, id=${identity.userId})`;
  }
  return identity.email ? `${identity.email} (anonymous)` : 'anonymous (no email provided)';
}

function pickReplyTo(identity: FeedbackIdentity): string | undefined {
  if (identity.kind === 'signed-in') return identity.email;
  return identity.email;
}

function buildHtml(input: SendFeedbackEmailInput): string {
  const { category, message, identity, context, ipMasked } = input;
  const safeMessage = escapeHtml(message);
  const safeFrom = escapeHtml(buildFromLine(identity));
  const safePath = escapeHtml(context.pathname);
  const safeRef = escapeHtml(context.referrer ?? '(none)');
  const safeUa = escapeHtml(context.userAgent ?? '(none)');
  const vp = context.viewport ? `${context.viewport.w}×${context.viewport.h}` : '(unknown)';

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1a1a1a; max-width: 640px; margin: 0 auto; padding: 20px;">
  <div style="background-color: #0B5345; padding: 16px 24px; border-radius: 8px 8px 0 0;">
    <h1 style="color: #F4D03F; margin: 0; font-size: 20px; letter-spacing: 2px;">PITCHRANK FEEDBACK</h1>
  </div>
  <div style="background-color: #f9fafb; padding: 24px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 8px 8px;">
    <table style="width:100%; font-size: 14px; margin-bottom: 16px;">
      <tr><td style="padding: 4px 12px 4px 0; color:#6b7280;">Category:</td><td><strong>${CATEGORY_LABELS[category]}</strong></td></tr>
      <tr><td style="padding: 4px 12px 4px 0; color:#6b7280;">From:</td><td>${safeFrom}</td></tr>
      <tr><td style="padding: 4px 12px 4px 0; color:#6b7280;">Page:</td><td><code>${safePath}</code></td></tr>
      <tr><td style="padding: 4px 12px 4px 0; color:#6b7280;">Submitted:</td><td>${escapeHtml(context.submittedAt)}</td></tr>
    </table>
    <div style="background:#fff; border:1px solid #e5e7eb; border-radius:6px; padding:16px; font-family: ui-monospace, Menlo, Consolas, monospace; white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.5;">${safeMessage}</div>
    <hr style="border:none; border-top:1px solid #e5e7eb; margin: 24px 0;">
    <table style="width:100%; font-size: 12px; color:#9ca3af;">
      <tr><td style="padding: 2px 12px 2px 0;">Referrer:</td><td>${safeRef}</td></tr>
      <tr><td style="padding: 2px 12px 2px 0;">Viewport:</td><td>${vp}</td></tr>
      <tr><td style="padding: 2px 12px 2px 0;">User-Agent:</td><td>${safeUa}</td></tr>
      <tr><td style="padding: 2px 12px 2px 0;">IP:</td><td><code>${escapeHtml(ipMasked)}</code></td></tr>
    </table>
  </div>
</body></html>`;
}

function buildText(input: SendFeedbackEmailInput): string {
  const { category, message, identity, context, ipMasked } = input;
  return [
    `PITCHRANK FEEDBACK`,
    ``,
    `Category:  ${CATEGORY_LABELS[category]}`,
    `From:      ${buildFromLine(identity)}`,
    `Page:      ${context.pathname}`,
    `Submitted: ${context.submittedAt}`,
    ``,
    `--- Message ---`,
    message,
    `---------------`,
    ``,
    `Referrer:   ${context.referrer ?? '(none)'}`,
    `Viewport:   ${context.viewport ? `${context.viewport.w}x${context.viewport.h}` : '(unknown)'}`,
    `User-Agent: ${context.userAgent ?? '(none)'}`,
    `IP:         ${ipMasked}`,
  ].join('\n');
}

/**
 * Send a feedback report email. Returns true on success, false on failure
 * (including when Resend is not configured). Does not throw.
 */
export async function sendFeedbackEmail(input: SendFeedbackEmailInput): Promise<boolean> {
  if (!resend) {
    console.warn('Resend not configured - skipping feedback email');
    return false;
  }

  const replyTo = pickReplyTo(input.identity);

  try {
    const { error } = await resend.emails.send({
      from: 'PitchRank <feedback@mail.pitchrank.io>',
      to: 'pitchrankio@gmail.com',
      subject: buildSubject(input.category, input.message),
      html: buildHtml(input),
      text: buildText(input),
      ...(replyTo ? { replyTo } : {}),
    });

    if (error) {
      console.error('Failed to send feedback email:', error);
      return false;
    }

    return true;
  } catch (err) {
    console.error('Error sending feedback email:', err);
    return false;
  }
}
```

- [ ] **Step 2.2: Run tests, expect pass**

```bash
cd C:/PitchRank/frontend && npx vitest run lib/email/__tests__/feedback.test.ts
```

Expected: PASS — all 9 tests green.

- [ ] **Step 2.3: Commit**

```bash
cd C:/PitchRank && git add frontend/lib/email/feedback.ts frontend/lib/email/__tests__/feedback.test.ts
git commit -m "feat(email): add sendFeedbackEmail builder"
```

---

## Task 3: Re-export builder from email index

**Files:**
- Modify: `frontend/lib/email/index.ts`

- [ ] **Step 3.1: Add the export**

Append to `frontend/lib/email/index.ts`:

```ts
export { sendFeedbackEmail } from './feedback';
export type { FeedbackCategory, FeedbackIdentity, FeedbackContext, SendFeedbackEmailInput } from './feedback';
```

- [ ] **Step 3.2: Confirm typecheck still passes**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3.3: Commit**

```bash
cd C:/PitchRank && git add frontend/lib/email/index.ts
git commit -m "feat(email): re-export sendFeedbackEmail"
```

---

## Task 4: API route — failing tests

**Files:**
- Create: `frontend/app/api/feedback/__tests__/route.test.ts`

- [ ] **Step 4.1: Write the route tests**

```ts
// frontend/app/api/feedback/__tests__/route.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { NextRequest } from 'next/server';

vi.mock('server-only', () => ({}));

const { mockSendFeedback, mockCheckRateLimit, mockGetUser } = vi.hoisted(() => ({
  mockSendFeedback: vi.fn(),
  mockCheckRateLimit: vi.fn(),
  mockGetUser: vi.fn(),
}));

vi.mock('@/lib/email', () => ({
  sendFeedbackEmail: mockSendFeedback,
}));

vi.mock('@/lib/api/rateLimit', () => ({
  checkRateLimit: mockCheckRateLimit,
}));

vi.mock('@/lib/supabase/server', () => ({
  createServerSupabase: async () => ({
    auth: { getUser: mockGetUser },
  }),
}));

import { POST } from '../route';

const VALID_OPENED = '2026-05-06T18:00:00.000Z';
const VALID_SUBMITTED = '2026-05-06T18:00:05.000Z'; // 5s after open

function makeRequest(body: unknown) {
  return new Request('http://localhost/api/feedback', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-forwarded-for': '203.0.113.42',
    },
    body: JSON.stringify(body),
  }) as NextRequest;
}

const validBody = {
  category: 'rankings-wrong',
  message: 'My team is ranked too low for sure',
  context: {
    pathname: '/teams/abc-u14-boys',
    openedAt: VALID_OPENED,
    submittedAt: VALID_SUBMITTED,
  },
};

describe('POST /api/feedback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCheckRateLimit.mockReturnValue(true);
    mockSendFeedback.mockResolvedValue(true);
    mockGetUser.mockResolvedValue({ data: { user: null }, error: null });
  });

  it('200s on a valid signed-in submission and dispatches email', async () => {
    mockGetUser.mockResolvedValue({
      data: { user: { id: 'user-1', email: 'coach@example.com' } },
      error: null,
    });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(mockSendFeedback).toHaveBeenCalledTimes(1);
    const sent = mockSendFeedback.mock.calls[0][0];
    expect(sent.identity).toEqual({ kind: 'signed-in', userId: 'user-1', email: 'coach@example.com' });
  });

  it('200s on a valid anonymous submission with replyTo email', async () => {
    const res = await POST(makeRequest({ ...validBody, email: 'anon@example.com' }));
    expect(res.status).toBe(200);
    expect(mockSendFeedback).toHaveBeenCalledOnce();
    const sent = mockSendFeedback.mock.calls[0][0];
    expect(sent.identity).toEqual({ kind: 'anonymous', email: 'anon@example.com' });
  });

  it('200s on a valid anonymous submission with no email', async () => {
    const res = await POST(makeRequest(validBody));
    expect(res.status).toBe(200);
    expect(mockSendFeedback).toHaveBeenCalledOnce();
    expect(mockSendFeedback.mock.calls[0][0].identity).toEqual({ kind: 'anonymous' });
  });

  it('400 when category is missing', async () => {
    const { category, ...rest } = validBody;
    const res = await POST(makeRequest(rest));
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('400 when category is unknown', async () => {
    const res = await POST(makeRequest({ ...validBody, category: 'something-else' }));
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('400 when message is too short', async () => {
    const res = await POST(makeRequest({ ...validBody, message: 'short' }));
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('400 when message exceeds 2000 chars', async () => {
    const res = await POST(makeRequest({ ...validBody, message: 'a'.repeat(2001) }));
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('400 when an anonymous email is malformed', async () => {
    const res = await POST(makeRequest({ ...validBody, email: 'not-an-email' }));
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('200 (silent) but does not send when honeypot is filled', async () => {
    const res = await POST(makeRequest({ ...validBody, website: 'http://spam.example' }));
    expect(res.status).toBe(200);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('200 (silent) but does not send when min-time floor is violated', async () => {
    const res = await POST(
      makeRequest({
        ...validBody,
        context: {
          ...validBody.context,
          submittedAt: '2026-05-06T18:00:01.000Z', // only 1s after open
        },
      })
    );
    expect(res.status).toBe(200);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('429 when rate limit denies', async () => {
    mockCheckRateLimit.mockReturnValue(false);
    const res = await POST(makeRequest(validBody));
    expect(res.status).toBe(429);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('502 when sendFeedbackEmail returns false', async () => {
    mockSendFeedback.mockResolvedValue(false);
    const res = await POST(makeRequest(validBody));
    expect(res.status).toBe(502);
  });

  it('400 on malformed JSON body', async () => {
    const req = new Request('http://localhost/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-forwarded-for': '203.0.113.42' },
      body: '{not valid',
    }) as NextRequest;
    const res = await POST(req);
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('masks the IP last octet in the dispatched payload', async () => {
    await POST(makeRequest(validBody));
    expect(mockSendFeedback.mock.calls[0][0].ipMasked).toBe('203.0.113.x');
  });
});
```

- [ ] **Step 4.2: Run tests, expect failure (route doesn't exist)**

```bash
cd C:/PitchRank/frontend && npx vitest run app/api/feedback/__tests__/route.test.ts
```

Expected: FAIL — module `../route` not found.

---

## Task 5: API route — implementation

**Files:**
- Create: `frontend/app/api/feedback/route.ts`

- [ ] **Step 5.1: Implement the route**

```ts
// frontend/app/api/feedback/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { parseJsonBody } from '@/lib/api/parseJsonBody';
import { checkRateLimit } from '@/lib/api/rateLimit';
import { createServerSupabase } from '@/lib/supabase/server';
import {
  sendFeedbackEmail,
  type FeedbackCategory,
  type FeedbackIdentity,
} from '@/lib/email';

const VALID_CATEGORIES: readonly FeedbackCategory[] = [
  'cant-find-team',
  'rankings-wrong',
  'wrong-games',
  'bug',
  'other',
] as const;

const MIN_MESSAGE = 10;
const MAX_MESSAGE = 2000;
const MAX_PATHNAME = 512;
const MAX_TEXT_FIELD = 512;
const MIN_DWELL_MS = 2000;
const RATE_LIMIT_MAX = 5;
const RATE_LIMIT_WINDOW_MS = 60 * 60 * 1000; // 1 hour
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface IncomingBody {
  category?: unknown;
  message?: unknown;
  email?: unknown;
  website?: unknown;
  context?: {
    pathname?: unknown;
    referrer?: unknown;
    userAgent?: unknown;
    viewport?: { w?: unknown; h?: unknown };
    openedAt?: unknown;
    submittedAt?: unknown;
  };
}

function bad(error: string) {
  return NextResponse.json({ error }, { status: 400 });
}

function maskIp(ip: string): string {
  if (ip === 'unknown') return 'unknown';
  const parts = ip.split('.');
  if (parts.length === 4) return `${parts[0]}.${parts[1]}.${parts[2]}.x`;
  // IPv6 or other: drop the last segment
  const v6 = ip.split(':');
  if (v6.length > 1) return v6.slice(0, -1).concat('x').join(':');
  return 'masked';
}

function isStringWithLen(v: unknown, min: number, max: number): v is string {
  return typeof v === 'string' && v.length >= min && v.length <= max;
}

export async function POST(request: NextRequest) {
  try {
    const ip = request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'unknown';

    const parsed = await parseJsonBody<IncomingBody>(request);
    if (parsed.error) return parsed.error;
    const body = parsed.data;

    // Honeypot — silent accept, do not send.
    if (typeof body.website === 'string' && body.website.length > 0) {
      return NextResponse.json({ ok: true });
    }

    // Category
    if (typeof body.category !== 'string' || !VALID_CATEGORIES.includes(body.category as FeedbackCategory)) {
      return bad('Invalid category');
    }
    const category = body.category as FeedbackCategory;

    // Message
    if (typeof body.message !== 'string') return bad('Message is required');
    const message = body.message.trim();
    if (message.length < MIN_MESSAGE) return bad(`Message must be at least ${MIN_MESSAGE} characters`);
    if (message.length > MAX_MESSAGE) return bad(`Message must be at most ${MAX_MESSAGE} characters`);

    // Optional anonymous email
    let anonymousEmail: string | undefined;
    if (body.email !== undefined && body.email !== null && body.email !== '') {
      if (typeof body.email !== 'string' || !EMAIL_REGEX.test(body.email)) {
        return bad('Email is not valid');
      }
      anonymousEmail = body.email.trim();
    }

    // Context
    const ctx = body.context;
    if (!ctx || typeof ctx !== 'object') return bad('Context is required');
    if (!isStringWithLen(ctx.pathname, 1, MAX_PATHNAME)) return bad('Invalid pathname');
    if (!isStringWithLen(ctx.openedAt, 1, 64)) return bad('Invalid openedAt');
    if (!isStringWithLen(ctx.submittedAt, 1, 64)) return bad('Invalid submittedAt');

    const openedAtMs = Date.parse(ctx.openedAt);
    const submittedAtMs = Date.parse(ctx.submittedAt);
    if (Number.isNaN(openedAtMs) || Number.isNaN(submittedAtMs)) return bad('Invalid timestamps');

    // Min-time floor — silent accept, do not send.
    if (submittedAtMs - openedAtMs < MIN_DWELL_MS) {
      return NextResponse.json({ ok: true });
    }

    // Rate limit by IP
    if (!checkRateLimit(ip, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW_MS)) {
      return NextResponse.json(
        { error: 'rate_limited' },
        { status: 429, headers: { 'Retry-After': String(Math.ceil(RATE_LIMIT_WINDOW_MS / 1000)) } }
      );
    }

    // Identify caller via server session
    const supabase = await createServerSupabase();
    const { data: userResult } = await supabase.auth.getUser();
    const sessionUser = userResult?.user ?? null;

    const identity: FeedbackIdentity = sessionUser?.email
      ? { kind: 'signed-in', userId: sessionUser.id, email: sessionUser.email }
      : { kind: 'anonymous', ...(anonymousEmail ? { email: anonymousEmail } : {}) };

    // Optional context fields (typed as unknown above; coerce safely)
    const referrer = isStringWithLen(ctx.referrer, 0, MAX_TEXT_FIELD) ? ctx.referrer : undefined;
    const userAgent = isStringWithLen(ctx.userAgent, 0, MAX_TEXT_FIELD) ? ctx.userAgent : undefined;
    let viewport: { w: number; h: number } | undefined;
    if (
      ctx.viewport &&
      typeof ctx.viewport.w === 'number' &&
      typeof ctx.viewport.h === 'number' &&
      ctx.viewport.w > 0 &&
      ctx.viewport.h > 0
    ) {
      viewport = { w: Math.floor(ctx.viewport.w), h: Math.floor(ctx.viewport.h) };
    }

    const ok = await sendFeedbackEmail({
      category,
      message,
      identity,
      context: {
        pathname: ctx.pathname,
        referrer,
        userAgent,
        viewport,
        openedAt: ctx.openedAt,
        submittedAt: ctx.submittedAt,
      },
      ipMasked: maskIp(ip),
    });

    if (!ok) {
      return NextResponse.json({ error: 'send_failed' }, { status: 502 });
    }

    console.log(
      JSON.stringify({
        scope: 'feedback',
        category,
        identity: identity.kind === 'signed-in' ? identity.userId : 'anonymous',
        pathname: ctx.pathname,
        outcome: 'sent',
      })
    );

    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error('[feedback] Unexpected error:', err);
    return NextResponse.json({ error: 'send_failed' }, { status: 500 });
  }
}
```

- [ ] **Step 5.2: Run route tests**

```bash
cd C:/PitchRank/frontend && npx vitest run app/api/feedback/__tests__/route.test.ts
```

Expected: PASS — all tests green.

- [ ] **Step 5.3: Run typecheck**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5.4: Commit**

```bash
cd C:/PitchRank && git add frontend/app/api/feedback/route.ts frontend/app/api/feedback/__tests__/route.test.ts
git commit -m "feat(api): POST /api/feedback widget endpoint"
```

---

## Task 6: Feedback modal component

**Files:**
- Create: `frontend/components/FeedbackModal.tsx`

- [ ] **Step 6.1: Create the modal**

```tsx
// frontend/components/FeedbackModal.tsx
'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useUser } from '@/hooks/useUser';

type Category = 'cant-find-team' | 'rankings-wrong' | 'wrong-games' | 'bug' | 'other';

const CATEGORY_OPTIONS: Array<{ value: Category; label: string }> = [
  { value: 'cant-find-team', label: "I can't find my team" },
  { value: 'rankings-wrong', label: 'Rankings look wrong' },
  { value: 'wrong-games', label: 'Wrong games attached to a team' },
  { value: 'bug', label: 'Bug or broken page' },
  { value: 'other', label: 'Other' },
];

const PLACEHOLDERS: Record<Category, string> = {
  'cant-find-team': 'Club name, age group, gender, state — anything that helps us find them.',
  'rankings-wrong': 'Which team, and what looks off about their ranking?',
  'wrong-games': "Which team's game list looks wrong, and which game(s)?",
  bug: 'What did you click, and what happened vs what you expected?',
  other: "Tell us what's on your mind.",
};

const MIN_MESSAGE = 10;
const MAX_MESSAGE = 2000;

interface FeedbackModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Status = 'idle' | 'submitting' | 'success' | 'error' | 'rate_limited';

export function FeedbackModal({ open, onOpenChange }: FeedbackModalProps) {
  const pathname = usePathname();
  const { user } = useUser();

  const [category, setCategory] = useState<Category | ''>('');
  const [message, setMessage] = useState('');
  const [email, setEmail] = useState('');
  const [website, setWebsite] = useState(''); // honeypot
  const [status, setStatus] = useState<Status>('idle');
  const openedAtRef = useRef<string | null>(null);

  // Reset openedAt each time modal opens; clear status, keep form fields.
  useEffect(() => {
    if (open) {
      openedAtRef.current = new Date().toISOString();
      setStatus('idle');
    }
  }, [open]);

  // Clear form on route change
  useEffect(() => {
    setCategory('');
    setMessage('');
    setEmail('');
    setWebsite('');
    setStatus('idle');
  }, [pathname]);

  // Auto-close 4s after success
  useEffect(() => {
    if (status !== 'success') return;
    const t = setTimeout(() => onOpenChange(false), 4000);
    return () => clearTimeout(t);
  }, [status, onOpenChange]);

  const canSubmit = useMemo(
    () => category !== '' && message.trim().length >= MIN_MESSAGE && message.length <= MAX_MESSAGE,
    [category, message]
  );

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || status === 'submitting') return;
    setStatus('submitting');
    try {
      const res = await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category,
          message: message.trim(),
          ...(user ? {} : email.trim() ? { email: email.trim() } : {}),
          ...(website ? { website } : {}),
          context: {
            pathname,
            referrer: typeof document !== 'undefined' ? document.referrer : undefined,
            userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : undefined,
            viewport:
              typeof window !== 'undefined' ? { w: window.innerWidth, h: window.innerHeight } : undefined,
            openedAt: openedAtRef.current ?? new Date().toISOString(),
            submittedAt: new Date().toISOString(),
          },
        }),
      });

      if (res.status === 429) {
        setStatus('rate_limited');
        return;
      }
      if (!res.ok) {
        setStatus('error');
        return;
      }

      setStatus('success');
      setCategory('');
      setMessage('');
      setEmail('');
      setWebsite('');
    } catch {
      setStatus('error');
    }
  };

  const placeholder = category ? PLACEHOLDERS[category] : 'Tell us what you saw…';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]" data-testid="feedback-modal">
        <DialogHeader>
          <DialogTitle>Something seems off?</DialogTitle>
          <DialogDescription>Tell us what you&apos;re seeing — we read every report.</DialogDescription>
        </DialogHeader>

        {status === 'success' ? (
          <div
            className="rounded-md border border-green-300 bg-green-50 p-4 text-sm text-green-900"
            role="status"
            aria-live="polite"
          >
            Thanks — we got it.
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            {status === 'error' && (
              <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900" role="alert">
                Couldn&apos;t send right now. Try again, or email pitchrankio@gmail.com.
              </div>
            )}
            {status === 'rate_limited' && (
              <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" role="alert">
                You&apos;ve sent a few already — give it an hour and try again.
              </div>
            )}

            <div className="space-y-1.5">
              <label htmlFor="feedback-category" className="text-sm font-medium">
                Category
              </label>
              <Select value={category} onValueChange={(v) => setCategory(v as Category)}>
                <SelectTrigger id="feedback-category" data-testid="feedback-category">
                  <SelectValue placeholder="Select one…" />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORY_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <label htmlFor="feedback-message" className="text-sm font-medium">
                What&apos;s happening?
              </label>
              <textarea
                id="feedback-message"
                data-testid="feedback-message"
                className="flex w-full min-h-[120px] rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                placeholder={placeholder}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={5}
                maxLength={MAX_MESSAGE}
                autoFocus
              />
              <p className="text-xs text-muted-foreground">
                {message.trim().length} / {MAX_MESSAGE}
              </p>
            </div>

            {!user && (
              <div className="space-y-1.5">
                <label htmlFor="feedback-email" className="text-sm font-medium">
                  Email <span className="text-muted-foreground font-normal">(optional)</span>
                </label>
                <Input
                  id="feedback-email"
                  data-testid="feedback-email"
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                />
                <p className="text-xs text-muted-foreground">
                  So we can reply if we have questions. We won&apos;t add you to anything.
                </p>
              </div>
            )}

            {/* Honeypot — must remain hidden and not focusable */}
            <div aria-hidden="true" style={{ position: 'absolute', left: '-9999px', top: 'auto', width: 1, height: 1, overflow: 'hidden' }}>
              <label htmlFor="feedback-website">Website</label>
              <input
                id="feedback-website"
                name="website"
                type="text"
                tabIndex={-1}
                autoComplete="off"
                value={website}
                onChange={(e) => setWebsite(e.target.value)}
              />
            </div>

            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={!canSubmit || status === 'submitting'} data-testid="feedback-submit">
                {status === 'submitting' ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Sending…
                  </>
                ) : (
                  'Send'
                )}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 6.2: Verify referenced UI primitives exist**

The modal imports `Button`, `Input`, `Select` (and Dialog) from `components/ui/`. The textarea is rendered as a plain `<textarea>` styled with shadcn's standard token classes because the project does NOT have `components/ui/textarea.tsx` (verified at plan-write time, 2026-05-06). Confirm primitives:

```bash
cd C:/PitchRank/frontend && ls components/ui/button.tsx components/ui/input.tsx components/ui/select.tsx components/ui/dialog.tsx
```

Expected: all four files exist. (No `textarea.tsx` is needed.)

- [ ] **Step 6.3: Typecheck**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 6.4: Commit**

```bash
cd C:/PitchRank && git add frontend/components/FeedbackModal.tsx
git commit -m "feat(ui): FeedbackModal categorized form"
```

---

## Task 7: Feedback trigger component

**Files:**
- Create: `frontend/components/FeedbackTrigger.tsx`

- [ ] **Step 7.1: Create the trigger**

```tsx
// frontend/components/FeedbackTrigger.tsx
'use client';

import { useState } from 'react';
import { usePathname } from 'next/navigation';
import { HelpCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { FeedbackModal } from './FeedbackModal';

const HIDDEN_PREFIXES = ['/embed', '/login', '/signup'];

export function FeedbackTrigger() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  if (pathname && HIDDEN_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + '/'))) {
    return null;
  }

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="Report an issue"
        title="Something seems off?"
        onClick={() => setOpen(true)}
        data-testid="feedback-trigger"
        className="min-w-[44px] min-h-[44px]"
      >
        <HelpCircle className="h-5 w-5" />
      </Button>
      <FeedbackModal open={open} onOpenChange={setOpen} />
    </>
  );
}
```

- [ ] **Step 7.2: Typecheck**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 7.3: Commit**

```bash
cd C:/PitchRank && git add frontend/components/FeedbackTrigger.tsx
git commit -m "feat(ui): FeedbackTrigger nav button"
```

---

## Task 8: Mount trigger in Navigation

**Files:**
- Modify: `frontend/components/Navigation.tsx`

- [ ] **Step 8.1: Read Navigation.tsx to find the right insertion point**

```bash
cd C:/PitchRank/frontend && grep -n -E "(GlobalSearch|user|sign[ -]?in|Star|watchlist)" components/Navigation.tsx | head -30
```

Identify the desktop right-side cluster (the area containing the search, the watchlist star, the user/sign-in button). The trigger goes between the watchlist star and the user menu / sign-in button. The mobile menu may need a separate insertion if it duplicates the nav cluster — read the file carefully.

- [ ] **Step 8.2: Add the import**

At the top of `frontend/components/Navigation.tsx`, with the other component imports:

```ts
import { FeedbackTrigger } from './FeedbackTrigger';
```

- [ ] **Step 8.3: Insert the component**

Insert `<FeedbackTrigger />` between the watchlist star button and the user/sign-in button in the desktop right-side cluster. If the mobile menu has its own duplicated cluster (it does — `mobileMenuOpen` controls a separate render path), insert there too so the trigger is reachable on mobile.

If the desktop cluster looks like:

```tsx
<Button ...><Star ... /></Button>
<UserMenuOrSignIn />
```

Make it:

```tsx
<Button ...><Star ... /></Button>
<FeedbackTrigger />
<UserMenuOrSignIn />
```

- [ ] **Step 8.4: Typecheck and lint**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit && npx eslint components/Navigation.tsx components/FeedbackTrigger.tsx components/FeedbackModal.tsx
```

Expected: no errors.

- [ ] **Step 8.5: Commit**

```bash
cd C:/PitchRank && git add frontend/components/Navigation.tsx
git commit -m "feat(nav): mount FeedbackTrigger in nav"
```

---

## Task 9: Run the full test suite + manual smoke

- [ ] **Step 9.1: Full unit + route tests**

```bash
cd C:/PitchRank/frontend && npx vitest run lib/email/__tests__/feedback.test.ts app/api/feedback/__tests__/route.test.ts
```

Expected: all tests pass.

- [ ] **Step 9.2: Full typecheck**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 9.3: Verify Resend sender domain**

Open the Resend dashboard and confirm `mail.pitchrank.io` is verified. Adding a new mailbox prefix (`feedback@`) on an already-verified domain typically requires no DNS change. If the domain shows as unverified, fix DNS before deploying.

- [ ] **Step 9.4: Manual smoke (dev server)**

```bash
cd C:/PitchRank/frontend && npm run dev
```

Then in a browser, hit `http://localhost:3000`:

1. Confirm the `?` icon appears in the nav between the watchlist star and the sign-in / user button.
2. Click it — the modal opens with the title "Something seems off?".
3. Without selecting a category, confirm Send is disabled.
4. Pick "Rankings look wrong" — placeholder updates to the rankings-specific copy.
5. Type at least 10 characters — Send becomes enabled.
6. Submit. Expect a green "Thanks — we got it." panel that auto-closes after ~4 seconds.
7. Check the `pitchrankio@gmail.com` inbox: an email arrives with subject `[PitchRank Feedback] Rankings look wrong — <your text>`. Hit Reply — the To line should be your account's email (if signed in) or empty (if anonymous with no email entered).
8. Navigate to `/embed/...` (any embed route) — confirm the `?` does NOT appear.
9. Sign out — open the modal again — confirm the optional Email field appears.
10. Submit 6 times in quick succession — the 6th attempt should show the rate-limited copy.

- [ ] **Step 9.5: Commit any final tweaks discovered during smoke**

If smoke reveals issues, fix them and commit individually with descriptive messages. Do **not** bundle smoke fixes with feature commits.

---

## Out of scope reminder

Per the spec, do NOT add in this PR:
- A `feedback_reports` Supabase table or admin page.
- Telegram, Slack, or GitHub-issue routing.
- CAPTCHA / Turnstile.
- Footer mailto link upgrade.
- Smart category preselect from URL.
- Auto-parsing of pathname into structured `team_id` / `game_id`.
