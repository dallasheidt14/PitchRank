import type { Metadata } from 'next';

const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

/**
 * Layout for rankings pages
 * Provides metadata for the /rankings landing page
 * Since the page.tsx is a client component, metadata must be in layout.tsx
 * 
 * NOTE: Uses absolute URLs for canonical/OG to avoid Google indexing issues
 */
export const metadata: Metadata = {
  title: 'See Where Your Team Ranks: 101,000+ Youth Soccer Teams',
  description: 'Find your team among 101,354 youth soccer teams nationwide. Compare rankings by state, age, and gender. Updated daily from 726,730+ real game results. No fluff, just data.',
  alternates: {
    canonical: `${baseUrl}/rankings`,
  },
  openGraph: {
    title: 'See Where Your Team Ranks: 101,000+ Youth Soccer Teams',
    description: 'Find your team among 101,354 youth soccer teams nationwide. Compare rankings by state, age, and gender. Updated daily from real game results.',
    url: `${baseUrl}/rankings`,
    siteName: 'PitchRank',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Youth Soccer Rankings | 101K+ Teams Ranked',
    description: 'Data-driven youth soccer rankings. Find your team among 101,354 teams nationwide.',
  },
};

export default function RankingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}

