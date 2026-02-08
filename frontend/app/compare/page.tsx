import { Suspense } from 'react';
import { PageHeader } from '@/components/PageHeader';
import { ComparePanel } from '@/components/ComparePanel';
import { CardSkeleton } from '@/components/ui/skeletons';
import type { Metadata } from 'next';

const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

export const metadata: Metadata = {
  title: 'Compare/Predict Teams',
  description: 'Compare multiple youth soccer teams side-by-side to see their rankings, statistics, and performance metrics across different age groups and states.',
  // Prevent indexing - this page is auth-gated and Googlebot will be redirected
  robots: {
    index: false,
    follow: false,
  },
  alternates: {
    canonical: `${baseUrl}/compare`,
  },
  openGraph: {
    title: 'Compare/Predict Teams | PitchRank',
    description: 'Compare multiple youth soccer teams side-by-side to see their rankings, statistics, and performance metrics.',
    url: `${baseUrl}/compare`,
    siteName: 'PitchRank',
    type: 'website',
    images: [
      {
        url: '/logos/pitchrank-wordmark.svg',
        width: 1200,
        height: 630,
        alt: 'PitchRank Compare/Predict Teams',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Compare/Predict Teams | PitchRank',
    description: 'Compare multiple youth soccer teams side-by-side to see their rankings and statistics.',
    images: ['/logos/pitchrank-wordmark.svg'],
  },
};

export default function ComparePage() {
  return (
    <>
      {/* Page Header - Athletic Editorial Style */}
      <div className="relative bg-secondary/30 border-b-2 border-primary py-8 sm:py-12">
        <div className="absolute left-0 top-0 w-2 h-full bg-accent -skew-x-12" aria-hidden="true" />
        <div className="container mx-auto px-4">
          <h1 className="font-display text-3xl sm:text-4xl md:text-5xl font-bold uppercase text-primary mb-2">
            Compare/Predict Teams
          </h1>
          <p className="text-muted-foreground text-base sm:text-lg">
            Select teams to compare rankings, statistics, and performance metrics side-by-side
          </p>
        </div>
      </div>

      <div className="container mx-auto py-6 sm:py-8 px-4">
        <div className="max-w-6xl mx-auto">
          <Suspense fallback={<CardSkeleton />}>
            <ComparePanel />
          </Suspense>
        </div>
      </div>
    </>
  );
}

