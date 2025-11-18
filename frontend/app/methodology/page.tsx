import { PageHeader } from '@/components/PageHeader';
import { MethodologySection } from '@/components/MethodologySection';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Methodology',
  description: 'Learn how PitchRank calculates youth soccer team rankings and power scores using cross-age game support, unified scoring, and data-driven analytics.',
  alternates: {
    canonical: '/methodology',
  },
  openGraph: {
    title: 'Ranking Methodology | PitchRank',
    description: 'Learn how PitchRank calculates youth soccer team rankings and power scores using data-driven analytics.',
    url: '/methodology',
    siteName: 'PitchRank',
    type: 'website',
    images: [
      {
        url: '/logos/pitchrank-wordmark.svg',
        width: 1200,
        height: 630,
        alt: 'PitchRank Methodology',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Ranking Methodology | PitchRank',
    description: 'Learn how PitchRank calculates youth soccer team rankings and power scores.',
    images: ['/logos/pitchrank-wordmark.svg'],
  },
};

export default function MethodologyPage() {
  return (
    <div className="container mx-auto py-8 px-4">
      <PageHeader
        title="Ranking Methodology"
        description="Understanding how PitchRank calculates team rankings and power scores"
        showBackButton
        backHref="/"
      />
      
      <div className="max-w-4xl mx-auto">
        <MethodologySection />
      </div>
    </div>
  );
}

