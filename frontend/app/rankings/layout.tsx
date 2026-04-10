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
  title: '2026 Youth Soccer Rankings by State & Age Group',
  description:
    'Where does your team rank? 77K+ youth soccer teams rated weekly by PowerScore. Browse rankings by state, age group U10-U19, boys and girls. Free.',
  alternates: {
    canonical: `${BASE_URL}/rankings`,
  },
  openGraph: {
    title: '2026 Youth Soccer Rankings by State & Age Group | PitchRank',
    description:
      'Where does your team rank? 77K+ youth soccer teams rated weekly by PowerScore. Browse rankings by state, age group U10-U19, boys and girls. Free.',
    url: `${BASE_URL}/rankings`,
    siteName: 'PitchRank',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: '2026 Youth Soccer Rankings by State & Age Group | PitchRank',
    description:
      'Where does your team rank? 77K+ youth soccer teams rated weekly by PowerScore. Browse rankings by state, age group U10-U19, boys and girls. Free.',
  },
};

export default function RankingsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
