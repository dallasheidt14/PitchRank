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
  title: 'Youth Soccer Rankings',
  description: 'Browse comprehensive youth soccer team rankings across the country. Filter by region, age group, and gender to find top teams nationwide.',
  alternates: {
    canonical: `${baseUrl}/rankings`,
  },
  openGraph: {
    title: 'Youth Soccer Rankings | PitchRank',
    description: 'Browse comprehensive youth soccer team rankings across the country.',
    url: `${baseUrl}/rankings`,
    siteName: 'PitchRank',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Youth Soccer Rankings | PitchRank',
    description: 'Data-driven youth soccer rankings. Find your team.',
  },
};

export default function RankingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}

