import type { Metadata } from 'next';

/**
 * Layout for rankings pages
 * Provides metadata for the /rankings landing page
 * Since the page.tsx is a client component, metadata must be in layout.tsx
 */
export const metadata: Metadata = {
  title: 'Youth Soccer Rankings',
  description: 'Browse comprehensive youth soccer team rankings for U10-U18 boys and girls teams. Filter by region, age group, and gender to find top teams nationwide.',
  alternates: {
    canonical: '/rankings',
  },
  openGraph: {
    title: 'Youth Soccer Rankings | PitchRank',
    description: 'Browse comprehensive youth soccer team rankings for U10-U18 boys and girls teams. Filter by region, age group, and gender to find top teams.',
    url: '/rankings',
    siteName: 'PitchRank',
    type: 'website',
    images: [
      {
        url: '/logos/pitchrank-wordmark.svg',
        width: 1200,
        height: 630,
        alt: 'PitchRank - Youth Soccer Rankings',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Youth Soccer Rankings | PitchRank',
    description: 'Browse comprehensive youth soccer team rankings for U10-U18 boys and girls teams.',
    images: ['/logos/pitchrank-wordmark.svg'],
  },
};

export default function RankingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}

