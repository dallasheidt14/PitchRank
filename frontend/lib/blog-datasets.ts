/**
 * Dataset structured-data entries for blog posts that publish first-party data.
 * Keyed by blog post slug, mirroring BLOG_FAQS — page.tsx renders a DatasetSchema
 * only for slugs present here, so it emits exclusively on report pages.
 */
import type { DatasetSchemaProps } from '@/components/DatasetSchema';
import { report as texasReport } from '@/content/reports/state-of-texas-youth-soccer-2026';

export const BLOG_DATASETS: Record<string, DatasetSchemaProps> = {
  [texasReport.slug]: {
    name: `State of ${texasReport.stateName} Youth Soccer ${texasReport.year}`,
    description: `First-party rankings dataset for ${texasReport.stateName} youth soccer: ${texasReport.rankedTeams.toLocaleString()} ranked teams across ${texasReport.totalGroups} age and gender groups, derived from ${texasReport.matchesAnalyzed.toLocaleString()} competitive matches over the trailing 12 months.`,
    slug: texasReport.slug,
    dateModified: texasReport.generatedAt,
    temporalCoverage: texasReport.temporalCoverage,
    variableMeasured: ['Ranked teams', 'Matches analyzed', 'Leagues covered', 'Ranked teams by age group'],
  },
};
