/**
 * Infographic Gallery - Preview all templates
 * Visit /infographics to preview and screenshot
 */

import { PowerScoreExplainer, RankingCard, WeeklyMovers, StateSpotlight } from '@/components/infographics';
import Link from 'next/link';

export const metadata = {
  title: 'Infographic Gallery - PitchRank',
  robots: 'noindex',
};

// Sample data for previews
const sampleMovers = [
  { teamName: 'LAFC Academy', state: 'CA', ageGroup: 'U14', gender: 'Boys' as const, movement: 47, newRank: 12 },
  { teamName: 'Solar SC', state: 'TX', ageGroup: 'U13', gender: 'Girls' as const, movement: 35, newRank: 8 },
  { teamName: 'Baltimore Armour', state: 'MD', ageGroup: 'U15', gender: 'Boys' as const, movement: 29, newRank: 23 },
  { teamName: 'Tophat SC', state: 'GA', ageGroup: 'U12', gender: 'Girls' as const, movement: 24, newRank: 15 },
  { teamName: 'SC del Sol', state: 'AZ', ageGroup: 'U16', gender: 'Boys' as const, movement: 21, newRank: 31 },
];

const sampleStateTeams = [
  { rank: 1, teamName: 'LAFC Academy 2012', powerScore: 1892, movement: 3 },
  { rank: 2, teamName: 'LA Galaxy SD', powerScore: 1847, movement: -2 },
  { rank: 3, teamName: 'San Jose Earthquakes', powerScore: 1823, movement: 0 },
  { rank: 4, teamName: 'Strikers FC', powerScore: 1801, movement: 1 },
  { rank: 5, teamName: 'Real So Cal', powerScore: 1789, movement: 12 },
];

export default function InfographicGalleryPage() {
  return (
    <div className="min-h-screen bg-neutral-900 p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-12">
          <h1 className="text-white text-4xl font-bold mb-4">
            🎨 PitchRank Infographic Templates
          </h1>
          <p className="text-neutral-400 text-lg mb-6">
            Brand-consistent templates for social media. Click any template to view full-size for screenshotting.
          </p>
          <div className="bg-neutral-800 rounded-lg p-4">
            <h3 className="text-white font-semibold mb-2">Export Instructions:</h3>
            <ol className="text-neutral-300 space-y-1 list-decimal list-inside text-sm">
              <li>Click a template to open full-size view</li>
              <li>Use browser DevTools → Right-click element → "Capture node screenshot"</li>
              <li>Or use a screenshot tool at exact dimensions (shown below each template)</li>
            </ol>
          </div>
        </div>
        
        {/* Template Grid */}
        <div className="grid gap-12">
          
          {/* PowerScore Explainer */}
          <section>
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-white text-2xl font-bold">1. PowerScore Explainer</h2>
                <p className="text-neutral-400">Methodology explainer — evergreen content</p>
              </div>
              <Link 
                href="/infographics/powerscore" 
                className="bg-[#F4D03F] text-[#052E27] px-4 py-2 rounded-lg font-semibold hover:bg-[#F4D03F]/90"
              >
                View Full Size →
              </Link>
            </div>
            <div className="inline-block border border-neutral-700 rounded-lg overflow-hidden" style={{ transform: 'scale(0.4)', transformOrigin: 'top left', marginBottom: '-400px' }}>
              <PowerScoreExplainer variant="square" />
            </div>
          </section>
          
          {/* Ranking Card */}
          <section className="pt-8">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-white text-2xl font-bold">2. Ranking Card</h2>
                <p className="text-neutral-400">Individual team spotlight — 1080×1080</p>
              </div>
            </div>
            <div className="inline-block border border-neutral-700 rounded-lg overflow-hidden" style={{ transform: 'scale(0.4)', transformOrigin: 'top left', marginBottom: '-400px' }}>
              <RankingCard
                rank={1}
                teamName="LAFC Academy 2012"
                clubName="Los Angeles FC"
                state="CA"
                ageGroup="U14"
                gender="Boys"
                powerScore={1892}
                record="12-1-0"
                movement={5}
              />
            </div>
          </section>
          
          {/* Weekly Movers */}
          <section className="pt-8">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-white text-2xl font-bold">3. Weekly Movers</h2>
                <p className="text-neutral-400">Biggest climbers this week — 1080×1350</p>
              </div>
            </div>
            <div className="inline-block border border-neutral-700 rounded-lg overflow-hidden" style={{ transform: 'scale(0.35)', transformOrigin: 'top left', marginBottom: '-500px' }}>
              <WeeklyMovers movers={sampleMovers} week={12} />
            </div>
          </section>
          
          {/* State Spotlight */}
          <section className="pt-8">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-white text-2xl font-bold">4. State Spotlight</h2>
                <p className="text-neutral-400">Top teams by state/age — 1080×1350</p>
              </div>
            </div>
            <div className="inline-block border border-neutral-700 rounded-lg overflow-hidden" style={{ transform: 'scale(0.35)', transformOrigin: 'top left', marginBottom: '-500px' }}>
              <StateSpotlight
                state="California"
                stateCode="CA"
                ageGroup="U14"
                gender="Boys"
                teams={sampleStateTeams}
                totalTeams={1247}
              />
            </div>
          </section>
          
        </div>
        
        {/* Footer */}
        <div className="mt-24 pt-8 border-t border-neutral-700">
          <h3 className="text-white text-xl font-bold mb-4">Adding New Templates</h3>
          <p className="text-neutral-400 mb-4">
            All templates follow the PitchRank Creative Kit. New templates go in:
          </p>
          <code className="text-green-400 bg-neutral-800 px-3 py-1 rounded">
            /components/infographics/
          </code>
          <p className="text-neutral-400 mt-4">
            See <code className="text-blue-400">~/clawd/workspace/brand/creative-kit.md</code> for brand guidelines.
          </p>
        </div>
      </div>
    </div>
  );
}
