import { RankingsPageContent } from '@/components/RankingsPageContent';

/**
 * Rankings landing page — server component for SEO.
 * Delegates all interactivity to RankingsPageContent (client component).
 * Default view: national, U12, male — matches the most common search intent.
 */
export default function RankingsPage() {
  return <RankingsPageContent region="national" ageGroup="u12" gender="male" />;
}
