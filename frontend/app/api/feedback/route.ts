import { NextRequest, NextResponse } from 'next/server';
import { parseJsonBody } from '@/lib/api/parseJsonBody';
import { checkRateLimit } from '@/lib/api/rateLimit';
import { createServerSupabase } from '@/lib/supabase/server';
import { sendFeedbackEmail, type FeedbackCategory, type FeedbackIdentity } from '@/lib/email';

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

    if (!body || typeof body !== 'object' || Array.isArray(body)) {
      return bad('Invalid request body');
    }

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

    let identity: FeedbackIdentity;
    if (sessionUser?.email) {
      identity = { kind: 'signed-in', userId: sessionUser.id, email: sessionUser.email };
    } else {
      if (sessionUser) {
        console.warn('[feedback] signed-in user has no email; treating as anonymous', {
          userId: sessionUser.id,
        });
      }
      identity = { kind: 'anonymous', ...(anonymousEmail ? { email: anonymousEmail } : {}) };
    }

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

    // NOTE: openedAt is captured for the min-time floor but is intentionally NOT
    // included in the email context — sendFeedbackEmail's FeedbackContext does not have it.
    const ok = await sendFeedbackEmail({
      category,
      message,
      identity,
      context: {
        pathname: ctx.pathname,
        referrer,
        userAgent,
        viewport,
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
        sessionUserId: sessionUser?.id ?? null,
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
