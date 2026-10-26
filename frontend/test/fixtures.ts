import type Stripe from 'stripe';
import type { RankingRow } from '@/types/RankingRow';
import type { CardRow, PairCard, PairCardRow, PairSide, TeamCard, TeamCardRow } from '@/lib/mission-control/cleanup';

/** Defaults describe an established, fully ranked team; override per test. */
export function makeRankingRow(overrides: Partial<RankingRow> = {}): RankingRow {
  return {
    team_id_master: '11111111-1111-1111-1111-111111111111',
    team_name: 'Test FC 2014',
    club_name: 'Test FC',
    league: null,
    distinction: null,
    state: 'AZ',
    age: 12,
    gender: 'M',
    power_score_final: 0.5,
    sos_norm: 0.5,
    offense_norm: 0.5,
    defense_norm: 0.5,
    rank_in_cohort_final: 100,
    wins: 5,
    losses: 2,
    draws: 1,
    games_played: 8,
    total_games_played: 12,
    total_wins: 5,
    total_losses: 2,
    total_draws: 1,
    win_percentage: 62.5,
    status: 'Active',
    rank_change_7d: 40,
    rank_change_30d: 40,
    last_calculated: '2026-08-24T12:00:00Z',
    last_game: '2026-08-22T00:00:00Z',
    ...overrides,
  };
}

// A type alias, not an interface: only an alias carries the implicit index
// signature that lets a fixture row satisfy the mock builder's `MockRow`.
export type GameFixture = {
  game_date: string;
  home_team_master_id: string;
  away_team_master_id: string;
  home_score: number | null;
  away_score: number | null;
  is_excluded: boolean;
};

/**
 * Defaults describe a played home game; override per test.
 *
 * A scheduled fixture is `makeGame({ home_score: null, away_score: null })` —
 * the shape that stops a game being counted as a result.
 */
export function makeGame(overrides: Partial<GameFixture> = {}): GameFixture {
  return {
    game_date: '2026-09-06',
    home_team_master_id: '11111111-1111-1111-1111-111111111111',
    away_team_master_id: '22222222-2222-2222-2222-222222222222',
    home_score: 3,
    away_score: 1,
    is_excluded: false,
    ...overrides,
  };
}

/** A state fill's card as pages.py builds it; override per test. */
export function makeCleanupCard(overrides: Partial<TeamCard> = {}): TeamCard {
  return {
    id: 'build_card',
    n: 1,
    group: 'B fill',
    whole: true,
    alike: null,
    interest: false,
    sure: null,
    change: { field: 'state_code', old: null, new: 'NV' },
    why: 'its club plays in NV',
    team: {
      name: 'Las Vegas Sports Academy 2013 Boys',
      original: null,
      club: 'Las Vegas Sports Academy',
      state: null,
      age: 'u13',
      gender: 'Male',
      provider: 'gotsport',
      games: 12,
      excluded: 0,
      first: '2026-08-15',
      last: '2026-10-11',
    },
    ...overrides,
  };
}

/** One row of a duplicate pair, in the shape the page reads; override per test. */
export function makePairSide(overrides: Partial<PairSide> = {}): PairSide {
  return {
    team_id: '22222222-2222-2222-2222-222222222222',
    name: 'Phoenix Rising 2013 Boys',
    original: null,
    club: 'Phoenix Rising',
    state: 'AZ',
    age: 'u13',
    gender: 'Male',
    provider: 'gotsport',
    games: 9,
    excluded: 0,
    first: '2026-08-22',
    last: '2026-10-18',
    ...overrides,
  };
}

/** A pair the cross-provider scan proposes, in the shape the page reads; override per test. */
export function makePairCard(overrides: Partial<PairCard> = {}): PairCard {
  return {
    id: 'build_pair',
    n: 1,
    group: 'C identical name',
    whole: false,
    alike: null,
    interest: false,
    sure: null,
    why: 'the same name, club and cohort on GotSport and TGS',
    merge: makePairSide({
      team_id: '33333333-3333-3333-3333-333333333333',
      name: 'Phoenix Rising B13 Premier',
      provider: 'tgs',
      games: 3,
      first: '2026-09-12',
      last: '2026-09-14',
    }),
    keep: makePairSide(),
    evidence: {
      doorway: 'C',
      shared_opponents: 2,
      shared_opponent_names: ['SC del Sol 2013', 'Arizona Arsenal 2013'],
      shared_dates: 0,
      opponent_overlap: 0.25,
    },
    ...overrides,
  };
}

type CleanupCardColumns = { run_id: string; decided_by_user_id: string | null };

/** A team_cleanup_cards row, typed to sit in a Supabase double's table. */
export type CleanupCardFixture = CardRow & CleanupCardColumns & Record<string, unknown>;

/** The columns every undecided owner card shares, the stage and the card left to the caller. */
function cardRowColumns({ page_run = '20261021T180000Z-a1b2c3', card_id }: { page_run?: string; card_id?: string }) {
  return {
    run_id: '2026-10-21-all',
    lane: 'owner' as const,
    page_run,
    card_id: card_id ?? `${page_run}_0000000000000001`,
    position: 1,
    decision: null,
    note: null,
    swap: false,
    decided_at: null,
    decided_by_user_id: null,
    created_at: '2026-10-21T18:05:00.25+00:00',
  };
}

/** An undecided owner card of a states page, as team_cleanup_cards holds it; override per test. */
export function makeCleanupCardRow(
  overrides: Partial<Omit<TeamCardRow, 'card'> & CleanupCardColumns> & { card?: Partial<TeamCard> } = {}
): TeamCardRow & CleanupCardColumns & Record<string, unknown> {
  const { card, ...row } = overrides;
  const columns = { ...cardRowColumns(row), stage: 'states' as const, ...row };
  return { ...columns, card: makeCleanupCard({ id: columns.card_id, n: columns.position, ...card }) };
}

/** An undecided owner card of a duplicate-teams page, as team_cleanup_cards holds it; override per test. */
export function makePairCardRow(
  overrides: Partial<Omit<PairCardRow, 'card'> & CleanupCardColumns> & { card?: Partial<PairCard> } = {}
): PairCardRow & CleanupCardColumns & Record<string, unknown> {
  const { card, ...row } = overrides;
  const columns = { ...cardRowColumns(row), stage: 'merges' as const, ...row };
  return { ...columns, card: makePairCard({ id: columns.card_id, n: columns.position, ...card }) };
}

/**
 * Stripe subscription double, returned already typed so callers need no cast.
 *
 * `status` keeps Stripe's union rather than a bare string: the churn and
 * activity branches compare against the exact literal `'canceled'`, so a
 * misspelling would otherwise typecheck and produce a fixture that silently
 * matches nothing.
 */
export function makeStripeSubscription(
  overrides: {
    id?: string;
    status?: Stripe.Subscription.Status;
    interval?: 'month' | 'year';
    unitAmount?: number;
    quantity?: number;
    trialStart?: number | null;
    trialEnd?: number | null;
    canceledAt?: number | null;
    endedAt?: number | null;
    currentPeriodEnd?: number;
    email?: string;
    customer?: unknown;
    cancelAt?: number | null;
    cancelAtPeriodEnd?: boolean;
    created?: number;
    startDate?: number;
  } = {}
): Stripe.Subscription {
  const {
    id = `sub_${Math.random().toString(36).slice(2)}`,
    status = 'active',
    interval = 'month',
    unitAmount = 699,
    quantity = 1,
    trialStart = null,
    trialEnd = null,
    canceledAt = null,
    endedAt = null,
    currentPeriodEnd = 0,
    email = 'test@example.com',
    customer,
    cancelAt = null,
    cancelAtPeriodEnd = false,
    created = 0,
    startDate = created,
  } = overrides;
  return {
    id,
    status,
    created,
    start_date: startDate,
    trial_start: trialStart,
    trial_end: trialEnd,
    canceled_at: canceledAt,
    ended_at: endedAt,
    cancel_at: cancelAt,
    cancel_at_period_end: cancelAtPeriodEnd,
    customer: customer ?? { id: 'cus_x', email, deleted: false },
    items: {
      data: [
        {
          id: 'si_x',
          quantity,
          current_period_end: currentPeriodEnd,
          price: { unit_amount: unitAmount, recurring: { interval } },
        },
      ],
    },
  } as unknown as Stripe.Subscription;
}

/**
 * Stripe invoice double shaped for the pinned API version: the generating
 * subscription hangs off `parent.subscription_details`, not the top-level
 * `subscription` field removed in 2025-03-31.basil.
 *
 * The money defaults differ from one another on purpose. When `total`,
 * `amount_due` and `amount_remaining` all default to the same figure, a
 * predicate that reads the wrong one still passes every test.
 */
export function makeStripeInvoice(
  overrides: {
    id?: string;
    amountPaid?: number;
    amountDue?: number;
    amountRemaining?: number;
    total?: number;
    discounts?: string[];
    billingReason?: Stripe.Invoice.BillingReason;
    subscription?: string | null;
    lineSubscription?: string | null;
    attempted?: boolean;
    attemptCount?: number;
    nextPaymentAttempt?: number | null;
    email?: string | null;
    created?: number;
  } = {}
): Stripe.Invoice {
  const {
    id = `in_${Math.random().toString(36).slice(2)}`,
    amountDue = 699,
    amountPaid = 699,
    amountRemaining = amountDue - amountPaid,
    total = amountDue,
    discounts = [],
    billingReason = 'subscription_cycle',
    subscription = 'sub_default',
    lineSubscription = null,
    attempted = true,
    attemptCount = 0,
    nextPaymentAttempt = null,
    email = 'test@example.com',
    created = 1_700_000_000,
  } = overrides;
  return {
    id,
    amount_paid: amountPaid,
    amount_due: amountDue,
    amount_remaining: amountRemaining,
    total,
    discounts,
    billing_reason: billingReason,
    attempted,
    attempt_count: attemptCount,
    next_payment_attempt: nextPaymentAttempt,
    customer_email: email,
    created,
    parent: subscription ? { subscription_details: { subscription } } : null,
    lines: {
      data: lineSubscription ? [{ parent: { subscription_item_details: { subscription: lineSubscription } } }] : [],
    },
  } as unknown as Stripe.Invoice;
}
