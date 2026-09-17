import { NextRequest, NextResponse } from 'next/server';
import { parseJsonBody } from '@/lib/api/parseJsonBody';
import { checkRateLimit, getClientIp } from '@/lib/api/rateLimit';
import { createServiceSupabase } from '@/lib/supabase/service';
import {
  sendMatchBalanceInquiryAlert,
  sendMatchBalanceInquiryConfirmation,
  type MatchBalanceLeadEmail,
} from '@/lib/email';
import { MATCHBALANCE_LIMITS, MATCHBALANCE_REQUEST_TYPES, type MatchBalanceRequestType } from '@/lib/matchbalance';
import { isValidEmail } from '@/lib/validation';

// Public by design: /api sits outside the middleware matcher and a tournament
// director has no account. The guards below are this route's whole defence.

const MIN_DWELL_MS = 2000;
const RATE_LIMIT_MAX = 5;
const RATE_LIMIT_WINDOW_MS = 60 * 60 * 1000; // 1 hour

const SAVE_FAILED = 'Could not save your request. Please email pitchrankio@gmail.com instead.';

interface IncomingBody {
  name?: unknown;
  email?: unknown;
  organization?: unknown;
  tournamentName?: unknown;
  eventDates?: unknown;
  teamCount?: unknown;
  bracketReviewDate?: unknown;
  eventUrl?: unknown;
  requestType?: unknown;
  notes?: unknown;
  website?: unknown;
  openedAt?: unknown;
  submittedAt?: unknown;
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

/** The form omits blank optionals; a body that sends `""` instead means the same thing. */
function isPresent(v: unknown): boolean {
  return v !== undefined && v !== null && !(typeof v === 'string' && v.trim() === '');
}

function trimmedText(v: unknown, max: number): string | null {
  if (typeof v !== 'string') return null;
  const trimmed = v.trim();
  return isStringWithLen(trimmed, 1, max) ? trimmed : null;
}

/**
 * `Date.parse('2026-02-31')` is March 3, so a parse check lets an impossible date
 * through to the `date` column, which rejects it as a 500 rather than a 400.
 */
function isCalendarDate(v: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  if (!match) return false;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

function isHttpUrl(v: string): boolean {
  try {
    const url = new URL(v);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

export async function POST(request: NextRequest) {
  try {
    const ip = getClientIp(request);

    // request.json() parses any body, so without this a page on another site could
    // post plain text from each visitor's browser with no CORS preflight.
    if (!request.headers.get('content-type')?.toLowerCase().startsWith('application/json')) {
      return NextResponse.json({ error: 'Content-Type must be application/json' }, { status: 415 });
    }

    const parsed = await parseJsonBody<IncomingBody>(request);
    if (parsed.error) return parsed.error;
    const body = parsed.data;

    if (!body || typeof body !== 'object' || Array.isArray(body)) {
      return bad('Invalid request body');
    }

    // Honeypot — silent accept, do not save. Same status as a real save so a bot
    // cannot tell it was dropped.
    if (typeof body.website === 'string' && body.website.length > 0) {
      return NextResponse.json({ ok: true }, { status: 201 });
    }

    if (!isStringWithLen(body.openedAt, 1, 64) || !isStringWithLen(body.submittedAt, 1, 64)) {
      return bad('Invalid timestamps');
    }
    const openedAtMs = Date.parse(body.openedAt);
    const submittedAtMs = Date.parse(body.submittedAt);
    if (Number.isNaN(openedAtMs) || Number.isNaN(submittedAtMs)) return bad('Invalid timestamps');

    // Min-time floor, ahead of validation so a bot's fast garbage gets the same
    // silent accept as its fast valid body. Both timestamps come from the client,
    // so a skewed client clock cannot drop a real lead.
    if (submittedAtMs - openedAtMs < MIN_DWELL_MS) {
      return NextResponse.json({ ok: true }, { status: 201 });
    }

    const name = trimmedText(body.name, MATCHBALANCE_LIMITS.name);
    if (name === null) return bad(`Your name is required (at most ${MATCHBALANCE_LIMITS.name} characters)`);

    // Length first: the email pattern backtracks quadratically on a long malformed value.
    const email = trimmedText(body.email, MATCHBALANCE_LIMITS.email);
    if (email === null || !isValidEmail(email)) return bad('Email is not valid');

    const organization = trimmedText(body.organization, MATCHBALANCE_LIMITS.organization);
    if (organization === null) {
      return bad(`Organization is required (at most ${MATCHBALANCE_LIMITS.organization} characters)`);
    }

    const tournamentName = trimmedText(body.tournamentName, MATCHBALANCE_LIMITS.tournamentName);
    if (tournamentName === null) {
      return bad(`Tournament name is required (at most ${MATCHBALANCE_LIMITS.tournamentName} characters)`);
    }

    const eventDates = trimmedText(body.eventDates, MATCHBALANCE_LIMITS.eventDates);
    if (eventDates === null) {
      return bad(`Event dates are required (at most ${MATCHBALANCE_LIMITS.eventDates} characters)`);
    }

    let teamCount: number | null = null;
    if (isPresent(body.teamCount)) {
      if (
        typeof body.teamCount !== 'number' ||
        !Number.isInteger(body.teamCount) ||
        body.teamCount < 0 ||
        body.teamCount > MATCHBALANCE_LIMITS.teamCount
      ) {
        return bad(`Number of teams must be a whole number from 0 to ${MATCHBALANCE_LIMITS.teamCount}`);
      }
      teamCount = body.teamCount;
    }

    let bracketReviewDate: string | null = null;
    if (isPresent(body.bracketReviewDate)) {
      if (typeof body.bracketReviewDate !== 'string' || !isCalendarDate(body.bracketReviewDate.trim())) {
        return bad('Bracket review date must be a real date');
      }
      bracketReviewDate = body.bracketReviewDate.trim();
    }

    let eventUrl: string | null = null;
    if (isPresent(body.eventUrl)) {
      const url = trimmedText(body.eventUrl, MATCHBALANCE_LIMITS.eventUrl);
      if (url === null || !isHttpUrl(url)) {
        return bad(`Event link must be an http or https address under ${MATCHBALANCE_LIMITS.eventUrl} characters`);
      }
      eventUrl = url;
    }

    if (
      typeof body.requestType !== 'string' ||
      !MATCHBALANCE_REQUEST_TYPES.includes(body.requestType as MatchBalanceRequestType)
    ) {
      return bad('Choose a free sample or a quote');
    }
    const requestType = body.requestType as MatchBalanceRequestType;

    let notes: string | null = null;
    if (isPresent(body.notes)) {
      notes = trimmedText(body.notes, MATCHBALANCE_LIMITS.notes);
      if (notes === null) return bad(`Notes must be at most ${MATCHBALANCE_LIMITS.notes} characters`);
    }

    // Rate limit last, so only well-formed submissions consume a slot and a
    // director correcting a typo is not locked out.
    if (!checkRateLimit(`matchbalance:${ip}`, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW_MS)) {
      return NextResponse.json(
        { error: 'rate_limited' },
        { status: 429, headers: { 'Retry-After': String(Math.ceil(RATE_LIMIT_WINDOW_MS / 1000)) } }
      );
    }

    // Saved before either email goes out: an email is never the only record of a lead.
    const supabase = createServiceSupabase();
    const { error } = await supabase.from('matchbalance_leads').insert({
      name,
      email,
      organization,
      tournament_name: tournamentName,
      event_dates: eventDates,
      team_count: teamCount,
      bracket_review_date: bracketReviewDate,
      event_url: eventUrl,
      request_type: requestType,
      notes,
      source_ip_masked: maskIp(ip),
    });

    if (error) {
      console.error('[matchbalance-inquiry] Failed to save lead:', error);
      return NextResponse.json({ error: SAVE_FAILED }, { status: 500 });
    }

    const lead: MatchBalanceLeadEmail = {
      name,
      email,
      organization,
      tournamentName,
      eventDates,
      teamCount,
      bracketReviewDate,
      eventUrl,
      requestType,
      notes,
    };

    // Awaited: Vercel can freeze the function once the response returns, cutting
    // off an unawaited send. Neither sender throws.
    const [alertSent, confirmationSent] = await Promise.all([
      sendMatchBalanceInquiryAlert(lead),
      sendMatchBalanceInquiryConfirmation(lead),
    ]);
    if (!alertSent) console.warn('[matchbalance-inquiry] Owner alert not sent; the lead is saved');
    if (!confirmationSent) console.warn('[matchbalance-inquiry] Director confirmation not sent; the lead is saved');

    return NextResponse.json({ ok: true }, { status: 201 });
  } catch (err) {
    console.error('[matchbalance-inquiry] Unexpected error:', err);
    return NextResponse.json({ error: SAVE_FAILED }, { status: 500 });
  }
}
