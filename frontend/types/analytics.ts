export interface DateRange {
  start: string;
  end: string;
}

export interface SearchConsoleRow {
  query: string;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
}

export interface SearchConsolePageRow {
  page: string;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
}

export interface SearchConsoleTotals {
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
}

export interface SearchConsoleData {
  topQueries: SearchConsoleRow[];
  topPages: SearchConsolePageRow[];
  totals: SearchConsoleTotals;
  dateRange: DateRange;
}

export interface TrafficOverview {
  sessions: number;
  users: number;
  pageviews: number;
  avgSessionDuration: number;
}

export interface ReferralSource {
  source: string;
  sessions: number;
  users: number;
}

export interface PageMetric {
  path: string;
  pageviews: number;
  users: number;
}

export interface TrafficData {
  overview: TrafficOverview;
  referrals: ReferralSource[];
  topPages: PageMetric[];
  dateRange: DateRange;
}

export interface FunnelStep {
  event: string;
  label: string;
  count: number;
}

export interface ConversionRates {
  viewToPlanSelected: number;
  planToCheckout: number;
  checkoutToComplete: number;
  overallConversion: number;
  cartAbandonmentRate: number;
}

export interface FunnelData {
  funnel: FunnelStep[];
  conversionRates: ConversionRates;
  dateRange: DateRange;
}
