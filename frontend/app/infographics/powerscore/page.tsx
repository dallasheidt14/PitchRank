/**
 * Infographic Preview Page
 * Visit /infographics/powerscore to preview
 * Screenshot at exact dimensions for social media
 */

import { PowerScoreExplainer } from '@/components/infographics';

export const metadata = {
  title: 'PowerScore Explainer - Infographic',
  robots: 'noindex', // Don't index preview pages
};

export default function PowerScoreInfographicPage() {
  return (
    <div className="min-h-screen bg-neutral-900 p-8">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-white text-2xl font-bold mb-4">
          PowerScore Explainer Infographic
        </h1>
        <p className="text-neutral-400 mb-8">
          Screenshot at 1080×1350 (4:5 portrait) for Instagram or 1080×1080 (1:1 square)
        </p>
        
        <div className="space-y-12">
          {/* Portrait Version */}
          <div>
            <h2 className="text-white text-lg font-semibold mb-3">
              Portrait (4:5) — Instagram Feed
            </h2>
            <div className="inline-block border-2 border-neutral-700">
              <PowerScoreExplainer variant="portrait" />
            </div>
          </div>
          
          {/* Square Version */}
          <div>
            <h2 className="text-white text-lg font-semibold mb-3">
              Square (1:1) — General Use
            </h2>
            <div className="inline-block border-2 border-neutral-700">
              <PowerScoreExplainer variant="square" />
            </div>
          </div>
        </div>
        
        <div className="mt-12 p-6 bg-neutral-800 rounded-lg">
          <h3 className="text-white font-semibold mb-2">How to Export</h3>
          <ol className="text-neutral-300 space-y-2 list-decimal list-inside">
            <li>Open browser DevTools (F12)</li>
            <li>Right-click on the infographic → Inspect</li>
            <li>Right-click the element → Capture node screenshot</li>
            <li>Or use a screenshot tool at exact dimensions</li>
          </ol>
        </div>
      </div>
    </div>
  );
}
