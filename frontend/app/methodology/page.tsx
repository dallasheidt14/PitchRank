import { PageHeader } from '@/components/PageHeader';
import { MethodologySection } from '@/components/MethodologySection';
import { BreadcrumbSchema } from '@/components/BreadcrumbSchema';
import { MethodologySchema } from '@/components/MethodologySchema';
import type { Metadata } from 'next';
import { BASE_URL } from '@/lib/constants';

export const metadata: Metadata = {
  title: 'How Our Rankings Work',
  description:
    'How PitchRank calculates youth soccer team rankings using opponent quality, cross-league strength calibration, and machine-learning trend detection. Updated weekly with game data from all 50 states.',
  alternates: {
    canonical: `${BASE_URL}/methodology`,
  },
  openGraph: {
    title: 'How PitchRank Youth Soccer Rankings Work',
    description:
      'How PitchRank calculates youth soccer team rankings using data-driven analytics, cross-league calibration, and ML trend detection.',
    url: `${BASE_URL}/methodology`,
    siteName: 'PitchRank',
    type: 'website',
    images: [
      {
        url: '/logos/pitchrank-wordmark.svg',
        width: 1200,
        height: 630,
        alt: 'How PitchRank Rankings Work',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'How PitchRank Youth Soccer Rankings Work',
    description: 'How PitchRank calculates youth soccer rankings with cross-league calibration and ML trend detection.',
    images: ['/logos/pitchrank-wordmark.svg'],
  },
};

export default function MethodologyPage() {
  return (
    <div className="container mx-auto py-8 px-4">
      <BreadcrumbSchema items={[{ name: 'Methodology', href: '/methodology' }]} />
      <MethodologySchema datePublished="2026-04-30T00:00:00Z" dateModified="2026-05-26T00:00:00Z" />
      <PageHeader
        title="How Our Rankings Work"
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
