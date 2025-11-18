import { Suspense } from 'react';
import { PageHeader } from '@/components/PageHeader';
import { ComparePanel } from '@/components/ComparePanel';
import { CardSkeleton } from '@/components/ui/skeletons';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Compare Teams',
  description: 'Compare multiple youth soccer teams side-by-side to see their rankings, statistics, and performance metrics across different age groups and states.',
  alternates: {
    canonical: '/compare',
  },
  openGraph: {
    title: 'Compare Teams | PitchRank',
    description: 'Compare multiple youth soccer teams side-by-side to see their rankings, statistics, and performance metrics.',
    url: '/compare',
    siteName: 'PitchRank',
    type: 'website',
    images: [
      {
        url: '/logos/pitchrank-wordmark.svg',
        width: 1200,
        height: 630,
        alt: 'PitchRank Compare Teams',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Compare Teams | PitchRank',
    description: 'Compare multiple youth soccer teams side-by-side to see their rankings and statistics.',
    images: ['/logos/pitchrank-wordmark.svg'],
  },
};

export default function ComparePage() {
  return (
    <div className="container mx-auto py-8 px-4">
      <PageHeader
        title="Compare Teams"
        description="Select teams to compare their rankings, statistics, and performance metrics side-by-side"
        showBackButton
        backHref="/"
      />
      
      <div className="max-w-6xl mx-auto">
        <Suspense fallback={<CardSkeleton />}>
          <ComparePanel />
        </Suspense>
      </div>
    </div>
  );
}

