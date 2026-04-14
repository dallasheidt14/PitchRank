// frontend/lib/internal-analytics/types.ts

export type DateRangePreset = 'today' | 'last_7_days' | 'last_28_days' | 'mtd';

export type DateRange = {
  start: string; // ISO date YYYY-MM-DD, inclusive
  end: string; // ISO date YYYY-MM-DD, inclusive
  preset?: DateRangePreset;
};

export type DataFreshness = 'complete' | 'partial';

export type TileResponse<Row> = {
  report?: string;
  source: 'ga4' | 'gsc';
  date_range: DateRange;
  timezone: string;
  rows: Row[];
  row_count: number;
  totals: Record<string, number>;
  derived: Record<string, number | string>;
  previous_period?: {
    rows: Row[];
    totals: Record<string, number>;
    derived: Record<string, number | string>;
  };
  truncated: boolean;
  truncation_reason?: 'limit_reached' | 'api_max' | 'post_filter';
  available_rows_hint?: number;
  data_freshness: DataFreshness;
  warnings: string[];
  generated_at: string; // ISO 8601
  debug?: {
    cost: {
      estimated_units: number;
      range_days: number;
      metric_count: number;
      dimension_count: number;
      limit: number;
    };
  };
};

export type TaxonomyError = {
  type: 'VALIDATION' | 'RATE_LIMIT' | 'API_ERROR' | 'NO_DATA' | 'AUTH' | 'QUOTA';
  message: string;
  retryable: boolean;
  retry_after_ms?: number;
};
