'use client';

import { useSyncExternalStore } from 'react';
import { captureLandingAttribution } from '@/lib/attribution';
import { hasAdminPlan } from '@/lib/plan';
import { findRelevantPromotion, promotionStateAt, type Promotion, type PromotionState } from '@/lib/promotions';

/**
 * The sale the server says is live, shared by every component that shows it (the header banner and
 * the upgrade page) through one module-level store, so its components share one request schedule.
 *
 * Outside a campaign period (findRelevantPromotion finds no bundled sale) nothing is
 * fetched; a page load that began outside one checks again whenever a component subscribes.
 * Inside one, the store refetches at the sale's start and end and every 5 minutes while
 * its window is current, so a kill switch reaches tabs left open. A failed refetch keeps the last
 * answer, so one dropped request never hides a live sale.
 */

type ServerState = PromotionState | 'none';

interface Answer {
  state: ServerState;
  promotion: Promotion | null;
  /** Server clock minus this browser's clock. */
  offsetMs: number;
}

interface Snapshot {
  bundled: Promotion | null;
  answer: Answer | null;
  previewRequested: boolean;
  nowMs: number;
}

export interface LivePromotion {
  state: ServerState;
  promotion: Promotion | null;
  preview: boolean;
  /** Whether to show the sale, re-evaluated each second while it is live. */
  isLive: boolean;
  /** Until the sale ends, by the server's clock. */
  remainingMs: number;
}

const REFRESH_MS = 5 * 60 * 1000;
const RETRY_MS = 5 * 1000;
/** How long after the start a stale or failed answer, or after the end a failed one, is retried every 5 seconds. */
const NEAR_BOUNDARY_MS = 90 * 1000;
/** Retry interval until the first answer: the banner stays mounted, so no new subscription would trigger one. */
const FIRST_ANSWER_RETRY_MS = 30 * 1000;
const REQUEST_TIMEOUT_MS = 10 * 1000;
const TICK_MS = 1000;
const MAX_TIMEOUT_MS = 2 ** 31 - 1;

const SERVER_SNAPSHOT: Snapshot = { bundled: null, answer: null, previewRequested: false, nowMs: 0 };

let snapshot = SERVER_SNAPSHOT;
let started = false;
let lastAttemptFailed = false;
let inFlight = false;
let refreshTimer: ReturnType<typeof setTimeout> | undefined;
let ticker: ReturnType<typeof setInterval> | undefined;
const listeners = new Set<() => void>();

function update(changes: Partial<Snapshot>): void {
  snapshot = { ...snapshot, ...changes, nowMs: Date.now() };
  for (const listener of listeners) listener();
  syncTicker();
}

function serverNow(): number {
  return Date.now() + (snapshot.answer?.offsetMs ?? 0);
}

/**
 * Null when the request fails or stalls past the timeout, so the retry schedule always runs. The
 * timer is set by hand: `AbortSignal.timeout` is missing from Safari before 16 and Chrome before 103,
 * which the site's browser targets include.
 */
async function fetchAnswer(): Promise<Answer | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch('/api/promotion', { signal: controller.signal });
    if (!res.ok) return null;
    const body = (await res.json()) as { state: ServerState; promotion: Promotion | null; serverNow: number };
    // A CDN copy was generated `Age` seconds ago, so its serverNow is that far behind.
    const ageMs = (Number(res.headers.get('age')) || 0) * 1000;
    return { state: body.state, promotion: body.promotion, offsetMs: body.serverNow + ageMs - Date.now() };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/** A cached answer can still say live after the end; the corrected clock is what ends it. */
function settled(answer: Answer): Answer {
  const ended =
    answer.state === 'live' &&
    answer.promotion !== null &&
    promotionStateAt(answer.promotion, Date.now() + answer.offsetMs) === 'ended';
  return ended ? { ...answer, state: 'ended' } : answer;
}

async function refresh(): Promise<void> {
  inFlight = true;
  const answer = await fetchAnswer();
  inFlight = false;
  lastAttemptFailed = answer === null;
  if (answer) update({ answer: settled(answer) });
  schedule();
}

function boundaryDelay(promotion: Promotion): number | null {
  const now = serverNow();
  const start = Date.parse(promotion.startsAt);
  const end = Date.parse(promotion.endsAt);
  if (now < start) return start - now;
  if (now < end) {
    const unsettled = lastAttemptFailed || snapshot.answer?.state === 'upcoming';
    if (unsettled && now < start + NEAR_BOUNDARY_MS) return RETRY_MS;
    return Math.min(REFRESH_MS, end - now);
  }
  return lastAttemptFailed && now < end + NEAR_BOUNDARY_MS ? RETRY_MS : null;
}

function nextRefreshDelay(): number | null {
  const promotion = snapshot.answer?.promotion ?? snapshot.bundled;
  if (!promotion) return null;
  const delay = boundaryDelay(promotion);
  // With no answer yet, the boundaries above are read off the browser's own clock, which may be off
  // by any amount, so neither may delay the next attempt past 30 seconds or stop it.
  return snapshot.answer ? delay : Math.min(delay ?? Infinity, FIRST_ANSWER_RETRY_MS);
}

function onRefreshTimer(): void {
  if (snapshot.answer) {
    const answer = settled(snapshot.answer);
    if (answer !== snapshot.answer) update({ answer });
  }
  void refresh();
}

function schedule(): void {
  clearTimeout(refreshTimer);
  refreshTimer = undefined;
  // A request in flight schedules its successor when it settles. A second one started meanwhile could
  // settle first, and the older answer, landing last, would then overwrite it.
  if (listeners.size === 0 || inFlight) return;
  const delay = nextRefreshDelay();
  if (delay !== null) refreshTimer = setTimeout(onRefreshTimer, Math.min(Math.max(delay, 0), MAX_TIMEOUT_MS));
}

function syncTicker(): void {
  const shouldTick = listeners.size > 0 && (snapshot.previewRequested || snapshot.answer?.state === 'live');
  if (shouldTick && !ticker) {
    ticker = setInterval(() => update({}), TICK_MS);
  } else if (!shouldTick && ticker) {
    clearInterval(ticker);
    ticker = undefined;
  }
}

function start(): void {
  started = true;
  captureLandingAttribution();
  const bundled = findRelevantPromotion(Date.now());
  const previewRequested = new URLSearchParams(window.location.search).get('promo_preview') === '1';
  update({ bundled, previewRequested });
  if (bundled) void refresh();
}

/** A page load that began outside a campaign period may have reached one since. */
function recheckCampaign(): void {
  const bundled = findRelevantPromotion(Date.now());
  if (!bundled) return;
  update({ bundled });
  void refresh();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (!started) start();
  else if (!snapshot.bundled) recheckCampaign();
  else if (listeners.size === 1) {
    if (!snapshot.answer && !inFlight) void refresh();
    else schedule();
  }
  syncTicker();
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      clearTimeout(refreshTimer);
      refreshTimer = undefined;
      syncTicker();
    }
  };
}

const getSnapshot = () => snapshot;
const getServerSnapshot = () => SERVER_SNAPSHOT;

/** Forget this page load's answer and stop every timer. */
export function resetLivePromotionForTests(): void {
  clearTimeout(refreshTimer);
  clearInterval(ticker);
  refreshTimer = undefined;
  ticker = undefined;
  listeners.clear();
  snapshot = SERVER_SNAPSHOT;
  started = false;
  lastAttemptFailed = false;
  inFlight = false;
}

/**
 * `profile` comes from the caller's own `useUser()`: calling it here would add a second session and
 * profile fetch to every page. `?promo_preview=1` shows an admin the bundled sale outside its window;
 * checkout still decides by the server clock alone, so a preview can never buy.
 */
export function useLivePromotion({ profile }: { profile: { plan: string } | null }): LivePromotion {
  const { bundled, answer, previewRequested, nowMs } = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const preview = previewRequested && hasAdminPlan(profile?.plan) && bundled !== null;
  const promotion = preview ? bundled : (answer?.promotion ?? null);
  const state = answer?.state ?? 'none';
  const serverNowMs = nowMs + (answer?.offsetMs ?? 0);
  const isLive =
    preview || (state === 'live' && promotion !== null && promotionStateAt(promotion, serverNowMs) === 'live');
  const remainingMs = promotion ? Date.parse(promotion.endsAt) - serverNowMs : 0;
  return { state, promotion, preview, isLive, remainingMs };
}

const noopSubscribe = () => () => {};

/**
 * Whether now falls in a campaign period, re-read each render, by the bundled sales alone. False on the server.
 * The clock is read in the snapshot because the repo's purity lint refuses `Date.now()` during render.
 */
export function useInCampaignPeriod(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => findRelevantPromotion(Date.now()) !== null,
    () => false
  );
}
