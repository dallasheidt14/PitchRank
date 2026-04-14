// frontend/lib/internal-analytics/constants.ts

export const GA4_PROPERTY_ID = '514724174';
export const GSC_SITE_URL = 'sc-domain:pitchrank.io';

export const DEFAULT_ROW_LIMIT = 10;
export const MAX_ROW_LIMIT = 100;

export const DATE_RANGE_PRESETS = ['today', 'last_7_days', 'last_28_days', 'mtd'] as const;
export const DEFAULT_PRESET: (typeof DATE_RANGE_PRESETS)[number] = 'last_7_days';

export const ALLOWED_GA4_METRICS = [
  'activeUsers',
  'sessions',
  'screenPageViews',
  'engagementRate',
  'averageSessionDuration',
  'bounceRate',
  'eventCount',
] as const;

export const ALLOWED_GA4_DIMENSIONS = [
  'date',
  'pagePath',
  'pageTitle',
  'country',
  'deviceCategory',
  'sessionSource',
  'sessionMedium',
  'eventName',
] as const;

export const ALLOWED_GSC_METRICS = ['clicks', 'impressions', 'ctr', 'position'] as const;
export const ALLOWED_GSC_DIMENSIONS = ['date', 'query', 'page', 'country', 'device'] as const;

export const CACHE_TTL_SECONDS = 600; // 10 min
export const REACT_QUERY_STALE_MS = 5 * 60 * 1000;
export const REACT_QUERY_GC_MS = 15 * 60 * 1000;
