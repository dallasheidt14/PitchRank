import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Breadcrumbs } from '@/components/Breadcrumbs';
import { US_STATES } from '@/lib/constants';
import { api } from '@/lib/api';

// Revalidate every hour for ISR caching
export const revalidate = 3600;

const AGE_GROUPS = ['u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'u18'];

interface StateOverviewPageProps {
  params: Promise<{
    region: string;
  }>;
}

/**
 * Get state info from code
 */
function getStateInfo(stateCode: string): { code: string; name: string } | null {
  const state = US_STATES.find(s => s.code.toLowerCase() === stateCode.toLowerCase());
  if (state) return { code: state.code, name: state.name };
  if (stateCode.toLowerCase() === 'national') return { code: 'national', name: 'National' };
  return null;
}

/**
 * Generate metadata for state overview pages
 */
export async function generateMetadata({ params }: StateOverviewPageProps): Promise<Metadata> {
  const resolvedParams = await params;
  const { region } = resolvedParams;
  
  const stateInfo = getStateInfo(region);
  if (!stateInfo) {
    return { title: 'Not Found | PitchRank' };
  }

  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';
  const canonicalUrl = `${baseUrl}/rankings/${region.toLowerCase()}`;
  const isNational = region.toLowerCase() === 'national';

  const title = isNational
    ? 'National Youth Soccer Rankings | PitchRank'
    : `${stateInfo.name} Youth Soccer Rankings | PitchRank`;
    
  const description = isNational
    ? 'View national youth soccer rankings for all age groups. Compare top boys and girls teams across the USA with PowerScore ratings updated weekly.'
    : `View ${stateInfo.name} youth soccer rankings for all age groups. Find top boys and girls teams in ${stateInfo.name} with PowerScore ratings updated weekly.`;

  return {
    title,
    description,
    alternates: {
      canonical: canonicalUrl,
    },
    openGraph: {
      title,
      description,
      url: canonicalUrl,
      siteName: 'PitchRank',
      type: 'website',
    },
    twitter: {
      card: 'summary_large_image',
      title,
      description,
    },
  };
}

/**
 * Generate static params for popular states
 */
export async function generateStaticParams() {
  // Pre-generate pages for popular states + national
  const popularStates = ['national', 'ca', 'fl', 'tx', 'az', 'ny', 'nj', 'ga', 'pa', 'il', 'nc', 'wa', 'co', 'oh'];
  return popularStates.map(region => ({ region }));
}

export default async function StateOverviewPage({ params }: StateOverviewPageProps) {
  const resolvedParams = await params;
  const { region } = resolvedParams;
  
  const stateInfo = getStateInfo(region);
  if (!stateInfo) {
    notFound();
  }

  const isNational = region.toLowerCase() === 'national';
  
  // Fetch top teams for each gender in popular age groups (for preview)
  let boysTeamCount = 0;
  let girlsTeamCount = 0;
  let topBoys: Array<{ age: string; teams: Array<{ team_id_master: string; team_name: string; club_name: string | null; power_score_final: number }> }> = [];
  let topGirls: Array<{ age: string; teams: Array<{ team_id_master: string; team_name: string; club_name: string | null; power_score_final: number }> }> = [];

  try {
    // Get total counts and top teams for U12, U13, U14 (most popular)
    const previewAges = ['u12', 'u13', 'u14'];
    
    for (const age of previewAges) {
      const [boysData, girlsData] = await Promise.all([
        api.getRankings(isNational ? null : region, age, 'M'),
        api.getRankings(isNational ? null : region, age, 'F'),
      ]);
      
      if (age === 'u12') {
        boysTeamCount = boysData.length;
        girlsTeamCount = girlsData.length;
      }
      
      topBoys.push({
        age: age.toUpperCase(),
        teams: boysData.slice(0, 3).map(t => ({
          team_id_master: t.team_id_master,
          team_name: t.team_name,
          club_name: t.club_name,
          power_score_final: t.power_score_final,
        })),
      });
      
      topGirls.push({
        age: age.toUpperCase(),
        teams: girlsData.slice(0, 3).map(t => ({
          team_id_master: t.team_id_master,
          team_name: t.team_name,
          club_name: t.club_name,
          power_score_final: t.power_score_final,
        })),
      });
    }
  } catch (error) {
    console.error('Error fetching state overview data:', error);
  }

  // Structured data for SEO
  const structuredData = {
    '@context': 'https://schema.org',
    '@type': 'CollectionPage',
    name: isNational 
      ? 'National Youth Soccer Rankings' 
      : `${stateInfo.name} Youth Soccer Rankings`,
    description: isNational
      ? 'Comprehensive national youth soccer rankings by age group and gender'
      : `Youth soccer rankings for ${stateInfo.name} across all age groups`,
    url: `https://pitchrank.io/rankings/${region.toLowerCase()}`,
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }}
      />
      
      <div className="container mx-auto py-8 px-4">
        <Breadcrumbs />

        {/* Page Header */}
        <div className="relative bg-secondary/30 border-b-2 border-primary py-8 sm:py-12 mb-8 -mx-4 px-4">
          <div className="absolute left-0 top-0 w-2 h-full bg-accent -skew-x-12" aria-hidden="true" />
          <h1 className="font-display text-3xl sm:text-4xl md:text-5xl font-bold uppercase text-primary mb-2">
            {isNational ? 'National' : stateInfo.name} Soccer Rankings
          </h1>
          <p className="text-muted-foreground text-base sm:text-lg">
            {isNational 
              ? 'Browse youth soccer rankings across the USA'
              : `Youth soccer team rankings in ${stateInfo.name}`}
          </p>
          {(boysTeamCount > 0 || girlsTeamCount > 0) && (
            <p className="text-sm text-muted-foreground mt-2">
              {boysTeamCount > 0 && `${boysTeamCount.toLocaleString()} Boys teams`}
              {boysTeamCount > 0 && girlsTeamCount > 0 && ' • '}
              {girlsTeamCount > 0 && `${girlsTeamCount.toLocaleString()} Girls teams`}
              {' '}(U12 division)
            </p>
          )}
        </div>

        {/* Age Group Grid */}
        <section className="mb-12">
          <h2 className="text-2xl font-bold mb-6">Browse by Age Group</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
            {AGE_GROUPS.map(age => (
              <div key={age} className="bg-card border border-border rounded-lg p-4 hover:border-primary transition-colors">
                <h3 className="font-bold text-lg mb-2">{age.toUpperCase()}</h3>
                <div className="space-y-1">
                  <Link 
                    href={`/rankings/${region.toLowerCase()}/${age}/male`}
                    className="block text-sm text-primary hover:underline"
                  >
                    Boys →
                  </Link>
                  <Link 
                    href={`/rankings/${region.toLowerCase()}/${age}/female`}
                    className="block text-sm text-primary hover:underline"
                  >
                    Girls →
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Top Teams Preview */}
        <div className="grid md:grid-cols-2 gap-8 mb-12">
          {/* Top Boys */}
          <section>
            <h2 className="text-2xl font-bold mb-4">Top Boys Teams</h2>
            <div className="space-y-4">
              {topBoys.map(({ age, teams }) => (
                <div key={age} className="bg-card border border-border rounded-lg p-4">
                  <div className="flex justify-between items-center mb-2">
                    <h3 className="font-semibold">{age} Boys</h3>
                    <Link 
                      href={`/rankings/${region.toLowerCase()}/${age.toLowerCase()}/male`}
                      className="text-xs text-primary hover:underline"
                    >
                      View All →
                    </Link>
                  </div>
                  {teams.length > 0 ? (
                    <ol className="space-y-1">
                      {teams.map((team, idx) => (
                        <li key={team.team_id_master} className="text-sm flex items-center gap-2">
                          <span className="text-muted-foreground w-4">{idx + 1}.</span>
                          <Link 
                            href={`/teams/${team.team_id_master}`}
                            className="hover:text-primary truncate"
                          >
                            {team.team_name}
                          </Link>
                          <span className="text-xs text-muted-foreground ml-auto">
                            {team.power_score_final.toFixed(1)}
                          </span>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="text-sm text-muted-foreground">No teams ranked yet</p>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* Top Girls */}
          <section>
            <h2 className="text-2xl font-bold mb-4">Top Girls Teams</h2>
            <div className="space-y-4">
              {topGirls.map(({ age, teams }) => (
                <div key={age} className="bg-card border border-border rounded-lg p-4">
                  <div className="flex justify-between items-center mb-2">
                    <h3 className="font-semibold">{age} Girls</h3>
                    <Link 
                      href={`/rankings/${region.toLowerCase()}/${age.toLowerCase()}/female`}
                      className="text-xs text-primary hover:underline"
                    >
                      View All →
                    </Link>
                  </div>
                  {teams.length > 0 ? (
                    <ol className="space-y-1">
                      {teams.map((team, idx) => (
                        <li key={team.team_id_master} className="text-sm flex items-center gap-2">
                          <span className="text-muted-foreground w-4">{idx + 1}.</span>
                          <Link 
                            href={`/teams/${team.team_id_master}`}
                            className="hover:text-primary truncate"
                          >
                            {team.team_name}
                          </Link>
                          <span className="text-xs text-muted-foreground ml-auto">
                            {team.power_score_final.toFixed(1)}
                          </span>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="text-sm text-muted-foreground">No teams ranked yet</p>
                  )}
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* Other States */}
        {!isNational && (
          <section className="border-t border-border pt-8">
            <h2 className="text-xl font-bold mb-4">Rankings in Other States</h2>
            <div className="flex flex-wrap gap-2">
              <Link 
                href="/rankings/national"
                className="px-3 py-1.5 bg-primary text-primary-foreground rounded text-sm hover:bg-primary/90"
              >
                National
              </Link>
              {US_STATES.filter(s => s.code.toLowerCase() !== region.toLowerCase())
                .slice(0, 15)
                .map(state => (
                  <Link 
                    key={state.code}
                    href={`/rankings/${state.code.toLowerCase()}`}
                    className="px-3 py-1.5 bg-muted text-foreground rounded text-sm hover:bg-muted/80"
                  >
                    {state.name}
                  </Link>
                ))}
            </div>
          </section>
        )}
        
        {isNational && (
          <section className="border-t border-border pt-8">
            <h2 className="text-xl font-bold mb-4">Browse by State</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
              {US_STATES.map(state => (
                <Link 
                  key={state.code}
                  href={`/rankings/${state.code.toLowerCase()}`}
                  className="px-3 py-2 bg-muted text-foreground rounded text-sm hover:bg-muted/80 text-center"
                >
                  {state.name}
                </Link>
              ))}
            </div>
          </section>
        )}
      </div>
    </>
  );
}
