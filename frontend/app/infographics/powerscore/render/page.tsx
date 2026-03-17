'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { PowerScoreExplainer } from '@/components/infographics';

function InfographicContent() {
  const searchParams = useSearchParams();
  const variant = (searchParams.get('variant') as 'square' | 'portrait') || 'square';
  
  return (
    <div data-infographic="powerscore">
      <PowerScoreExplainer variant={variant} />
    </div>
  );
}

/**
 * Clean render page - no layout, no nav, just the infographic
 */
export default function PowerScoreRenderPage() {
  return (
    <Suspense fallback={<div style={{ width: 1080, height: 1080, background: '#052E27' }} />}>
      <InfographicContent />
    </Suspense>
  );
}
