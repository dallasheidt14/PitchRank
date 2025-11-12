import { PageHeader } from '@/components/PageHeader';
import { MethodologySection } from '@/components/MethodologySection';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Methodology | PitchRank',
  description: 'Learn how PitchRank calculates team rankings and power scores',
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

