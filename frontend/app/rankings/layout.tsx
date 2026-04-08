import type { Metadata } from 'next';
import { BASE_URL } from '@/lib/constants';

/**
 * Layout for rankings pages
 * Provides metadata for the /rankings landing page
 * Since the page.tsx is a client component, metadata must be in layout.tsx
 *
 * NOTE: Uses absolute URLs for canonical/OG to avoid Google indexing issues
 */
export const metadata: Metadata = {
  title: 'Youth Soccer Rankings: 101,000+ Teams Ranked by PowerScore',
  description:
    'Youth soccer rankings for every state, age group, and gender. 101,354 teams scored from 726,730+ real game results—updated weekly. Find where your club ranks.',
  alternates: {
    canonical: `${BASE_URL}/rankings`,
  },
  openGraph: {
    title: 'Youth Soccer Rankings: 101,000+ Teams Ranked by PowerScore',
    description:
      'Youth soccer rankings for every state, age group, and gender. 101,354 teams scored from 726,730+ real game results—updated weekly.',
    url: `${BASE_URL}/rankings`,
    siteName: 'PitchRank',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Youth Soccer Rankings | 101K+ Teams Ranked',
    description:
      'Youth soccer rankings for every state, age group, and gender. 101,354 teams scored weekly from real game results.',
  },
};

export default function RankingsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
