export const MATCHBALANCE_REQUEST_TYPES = ['sample', 'quote'] as const;

export type MatchBalanceRequestType = (typeof MATCHBALANCE_REQUEST_TYPES)[number];

export const MATCHBALANCE_REQUEST_LABELS: Record<MatchBalanceRequestType, string> = {
  sample: 'Free sample',
  quote: 'Quote for the whole event',
};

export const MATCHBALANCE_LIMITS = {
  name: 120,
  email: 254,
  organization: 160,
  tournamentName: 200,
  eventDates: 120,
  eventUrl: 500,
  notes: 2000,
  teamCount: 5000,
} as const;
