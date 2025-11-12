import { PageHeader } from '@/components/PageHeader';
import { ComparePanel } from '@/components/ComparePanel';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Compare Teams | PitchRank',
  description: 'Compare multiple teams side-by-side to see their rankings and statistics',
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
        <ComparePanel />
      </div>
    </div>
  );
}

