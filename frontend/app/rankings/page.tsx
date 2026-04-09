import type { Metadata } from 'next';
import { RankingsPageContent } from '@/components/RankingsPageContent';
import { BASE_URL } from '@/lib/constants';

/**
 * Rankings landing page — server component for SEO.
 * Delegates all interactivity to RankingsPageContent (client component).
 * Default view: national, U12, male — matches the most common search intent.
 */

export const metadata: Metadata = {
  title: 'Youth Soccer Rankings 2026 — 77K+ Teams Ranked Weekly | PitchRank',
  description:
    'Free youth soccer rankings for every state, age group, and gender. 77,000+ teams rated by PowerScore from real game results. Updated every Monday. Find where your team ranks.',
  alternates: {
    canonical: `${BASE_URL}/rankings`,
  },
  openGraph: {
    title: 'Youth Soccer Rankings 2026 — 77K+ Teams Ranked Weekly | PitchRank',
    description:
      'Free youth soccer rankings for every state, age group, and gender. 77,000+ teams rated by PowerScore from real game results. Updated every Monday.',
    url: `${BASE_URL}/rankings`,
    siteName: 'PitchRank',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Youth Soccer Rankings 2026 — 77K+ Teams Ranked Weekly | PitchRank',
    description:
      'Free youth soccer rankings for every state, age group, and gender. 77,000+ teams rated by PowerScore from real game results. Updated every Monday.',
  },
};

const rankingsSchema = {
  '@context': 'https://schema.org',
  '@type': 'CollectionPage',
  name: 'Youth Soccer Rankings',
  description:
    'Comprehensive youth soccer rankings across all 50 states, covering 77,000+ teams in every age group from U10 to U19. Updated weekly with real game results.',
  url: `${BASE_URL}/rankings`,
};

export default function RankingsPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(rankingsSchema).replace(/</g, '\\u003c') }}
      />
      <RankingsPageContent region="national" ageGroup="u12" gender="male" />
    </>
  );
}
