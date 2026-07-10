import type { Metadata } from 'next';
import { BASE_URL } from '@/lib/constants';
import { DataProviders } from '@/app/data-providers';

/**
 * Layout for rankings pages.
 *
 * NOTE: Uses absolute URLs for canonical/OG to avoid Google indexing issues
 */
export const metadata: Metadata = {
  title: '2026 Youth Soccer Rankings by State & Age Group',
  description:
    'Where does your team rank? Youth soccer teams across all 50 states rated weekly by PowerScore. Browse rankings by state, age group U10-U19, boys and girls. Free.',
  alternates: {
    canonical: `${BASE_URL}/rankings`,
  },
  openGraph: {
    title: '2026 Youth Soccer Rankings by State & Age Group | PitchRank',
    description:
      'Where does your team rank? Youth soccer teams across all 50 states rated weekly by PowerScore. Browse rankings by state, age group U10-U19, boys and girls. Free.',
    url: `${BASE_URL}/rankings`,
    siteName: 'PitchRank',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: '2026 Youth Soccer Rankings by State & Age Group | PitchRank',
    description:
      'Where does your team rank? Youth soccer teams across all 50 states rated weekly by PowerScore. Browse rankings by state, age group U10-U19, boys and girls. Free.',
  },
};

export default function RankingsLayout({ children }: { children: React.ReactNode }) {
  return <DataProviders>{children}</DataProviders>;
}
