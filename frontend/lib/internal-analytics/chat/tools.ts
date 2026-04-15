import 'server-only';
import { z } from 'zod';
import { tool, zodSchema } from 'ai';
import { runReport, type ReportKey } from '../report-registry';
import {
  ALLOWED_GA4_METRICS,
  ALLOWED_GA4_DIMENSIONS,
  ALLOWED_GSC_DIMENSIONS,
  MAX_ROW_LIMIT,
  DATE_RANGE_PRESETS,
  GA4_PROPERTY_ID,
  GSC_SITE_URL,
} from '../constants';
import { getAnalyticsDataClient, getSearchConsoleClient } from '@/lib/google-auth';
import { resolveDateRange } from '../dates';
import { ga4RowsToObjects } from '../transforms/ga4';
import { gscRowsToObjects } from '../transforms/gsc';
import { TaxonomyAwareError, toTaxonomyError } from '../queries/_error';
import { logChatToolCall } from '../logging';
import type { DateRange, TaxonomyError } from '../types';

const DateRangeArg = z.union([
  z.enum(DATE_RANGE_PRESETS as readonly [string, ...string[]]),
  z.object({ start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/), end: z.string().regex(/^\d{4}-\d{2}-\d{2}$/) }),
]);

type ToolContext = {
  turnId: string;
  userEmail: string;
  modelName: string;
  question: string;
  inheritedRange: DateRange;
  forceFresh: boolean;
};

const namedReportSchema = z.object({
  report: z.enum([
    'ga4_traffic_overview',
    'ga4_top_pages',
    'ga4_upgrade_views',
    'gsc_performance',
    'gsc_top_queries',
    'gsc_landing_pages',
  ]),
  date_range: DateRangeArg,
  compare_to_previous: z.boolean().optional(),
  limit: z.number().int().min(1).max(MAX_ROW_LIMIT).optional(),
});

const ga4QuerySchema = z.object({
  metrics: z
    .array(z.enum(ALLOWED_GA4_METRICS as readonly [string, ...string[]]))
    .min(1)
    .max(5),
  dimensions: z
    .array(z.enum(ALLOWED_GA4_DIMENSIONS as readonly [string, ...string[]]))
    .max(3)
    .optional(),
  date_range: DateRangeArg,
  filter: z
    .object({
      dimension: z.enum(ALLOWED_GA4_DIMENSIONS as readonly [string, ...string[]]),
      match_type: z.enum(['EXACT', 'CONTAINS', 'BEGINS_WITH']),
      value: z.string(),
    })
    .optional(),
  order_by: z
    .object({
      metric: z.enum(ALLOWED_GA4_METRICS as readonly [string, ...string[]]),
      desc: z.boolean(),
    })
    .optional(),
  limit: z.number().int().min(1).max(MAX_ROW_LIMIT),
});

const gscQuerySchema = z.object({
  dimensions: z
    .array(z.enum(ALLOWED_GSC_DIMENSIONS as readonly [string, ...string[]]))
    .min(1)
    .max(3),
  date_range: DateRangeArg,
  filters: z
    .array(
      z.object({
        dimension: z.enum(ALLOWED_GSC_DIMENSIONS as readonly [string, ...string[]]),
        operator: z.enum(['equals', 'contains', 'notEquals', 'notContains']),
        expression: z.string(),
      })
    )
    .optional(),
  limit: z.number().int().min(1).max(MAX_ROW_LIMIT),
});

export function buildTools(ctx: ToolContext) {
  return {
    run_named_report: tool({
      description:
        'Run a pre-defined analytics report. Prefer this over raw queries when the question matches a known report.',
      inputSchema: zodSchema(namedReportSchema),
      execute: async (args: z.infer<typeof namedReportSchema>) =>
        runWithLog(ctx, 'run_named_report', args, async () => {
          const params = { ...args, forceFresh: ctx.forceFresh };
          return await runReport(args.report as ReportKey, params);
        }),
    }),

    query_ga4: tool({
      description: 'Run a custom GA4 query. Use only when no named report fits.',
      inputSchema: zodSchema(ga4QuerySchema),
      execute: async (args: z.infer<typeof ga4QuerySchema>) =>
        runWithLog(ctx, 'query_ga4', args, async () => {
          const range = resolveDateRange(args.date_range as never, 'America/Phoenix');
          try {
            const client = getAnalyticsDataClient();
            const res = await client.properties.runReport({
              property: `properties/${GA4_PROPERTY_ID}`,
              requestBody: {
                dateRanges: [{ startDate: range.start, endDate: range.end }],
                metrics: args.metrics.map((name: string) => ({ name })),
                dimensions: args.dimensions?.map((name: string) => ({ name })),
                dimensionFilter: args.filter
                  ? {
                      filter: {
                        fieldName: args.filter.dimension,
                        stringFilter: { matchType: args.filter.match_type, value: args.filter.value },
                      },
                    }
                  : undefined,
                orderBys: args.order_by
                  ? [{ metric: { metricName: args.order_by.metric }, desc: args.order_by.desc }]
                  : undefined,
                limit: String(args.limit),
                keepEmptyRows: args.dimensions?.includes('date') ? true : undefined,
              },
            });
            return { source: 'ga4', rows: ga4RowsToObjects(res.data as never), date_range: range };
          } catch (e) {
            throw new TaxonomyAwareError(toTaxonomyError(e));
          }
        }),
    }),

    query_gsc: tool({
      description: 'Run a custom Search Console Search Analytics query. Use only when no named report fits.',
      inputSchema: zodSchema(gscQuerySchema),
      execute: async (args: z.infer<typeof gscQuerySchema>) =>
        runWithLog(ctx, 'query_gsc', args, async () => {
          const range = resolveDateRange(args.date_range as never, 'America/Phoenix');
          try {
            const client = getSearchConsoleClient();
            const res = await client.searchanalytics.query({
              siteUrl: GSC_SITE_URL,
              requestBody: {
                startDate: range.start,
                endDate: range.end,
                dimensions: args.dimensions,
                dimensionFilterGroups: args.filters ? [{ filters: args.filters }] : undefined,
                rowLimit: args.limit,
              },
            });
            return { source: 'gsc', rows: gscRowsToObjects(res.data as never, args.dimensions), date_range: range };
          } catch (e) {
            throw new TaxonomyAwareError(toTaxonomyError(e));
          }
        }),
    }),
  };
}

async function runWithLog<T>(
  ctx: ToolContext,
  toolName: string,
  args: unknown,
  fn: () => Promise<T>
): Promise<T | { error: TaxonomyError }> {
  const start = Date.now();
  try {
    const result = await fn();
    await logChatToolCall({
      turn_id: ctx.turnId,
      user_email: ctx.userEmail,
      model_name: ctx.modelName,
      user_question: ctx.question,
      inherited_date_range: ctx.inheritedRange,
      overridden_date_range: null,
      tool_name: toolName,
      tool_args: args,
      tool_result_summary: summarize(result),
      force_fresh: ctx.forceFresh,
      execution_ms: Date.now() - start,
      success: true,
    });
    return result;
  } catch (e) {
    const taxonomy: TaxonomyError =
      e instanceof TaxonomyAwareError ? e.taxonomy : { type: 'API_ERROR', message: String(e), retryable: false };
    await logChatToolCall({
      turn_id: ctx.turnId,
      user_email: ctx.userEmail,
      model_name: ctx.modelName,
      user_question: ctx.question,
      inherited_date_range: ctx.inheritedRange,
      overridden_date_range: null,
      tool_name: toolName,
      tool_args: args,
      tool_result_summary: null,
      force_fresh: ctx.forceFresh,
      execution_ms: Date.now() - start,
      success: false,
      error: taxonomy,
    });
    return { error: taxonomy };
  }
}

function summarize(result: unknown) {
  if (!result || typeof result !== 'object') return null;
  const r = result as { rows?: unknown; totals?: unknown; truncated?: unknown };
  return {
    row_count: Array.isArray(r.rows) ? r.rows.length : undefined,
    has_totals: !!r.totals,
    truncated: !!r.truncated,
  };
}
