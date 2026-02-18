import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Breadcrumbs } from '@/components/Breadcrumbs';
import { US_STATES } from '@/lib/constants';
import { api } from '@/lib/api';

// Revalidate every hour for ISR caching
export const revalidate = 3600;

const VALID_AGE_GROUPS = ['u8', 'u9', 'u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'u18', 'u19'];

// Popular states to highlight
const POPULAR_STATES = ['CA', 'TX', 'FL', 'NY', 'GA', 'PA', 'IL', 'NC', 'AZ', 'WA', 'NJ', 'CO'];

interface AgeGroupPageProps {
  params: Promise<{
    ageGroup: string;
  }>;
}

/**
 * Validate and format age group
 */
function validateAgeGroup(ageGroup: string): string | null {
  const normalized = ageGroup.toLowerCase();
  if (VALID_AGE_GROUPS.includes(normalized)) {
    return normalized;
  }
  return null;
}

/**
 * Generate metadata for age group landing pages
 */
export async function generateMetadata({ params }: AgeGroupPageProps): Promise<Metadata> {
  const resolvedParams = await params;
  const { ageGroup } = resolvedParams;
  
  const validAge = validateAgeGroup(ageGroup);
  if (!validAge) {
    return { title: 'Not Found | PitchRank' };
  }

  const ageDisplay = validAge.toUpperCase();
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';
  const canonicalUrl = `${baseUrl}/rankings/age/${validAge}`;

  const title = `${ageDisplay} Youth Soccer Rankings - National | PitchRank`;
  const description = `National ${ageDisplay} youth soccer rankings. View top boys and girls soccer teams in the ${ageDisplay} age group across all states. Updated weekly with PowerScore ratings.`;

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
 * Generate static params for all age groups
 */
export async function generateStaticParams() {
  return VALID_AGE_GROUPS.map(ageGroup => ({ ageGroup }));
}

export default async function AgeGroupPage({ params }: AgeGroupPageProps) {
  const resolvedParams = await params;
  const { ageGroup } = resolvedParams;
  
  const validAge = validateAgeGroup(ageGroup);
  if (!validAge) {
    notFound();
  }

  const ageDisplay = validAge.toUpperCase();
  
  // Fetch national top 25 for boys and girls
  let topBoys: Array<{ team_id_master: string; team_name: string; club_name: string | null; state: string | null; power_score_final: number; rank_in_cohort_final: number }> = [];
  let topGirls: Array<{ team_id_master: string; team_name: string; club_name: string | null; state: string | null; power_score_final: number; rank_in_cohort_final: number }> = [];
  let totalBoys = 0;
  let totalGirls = 0;

  try {
    const [boysData, girlsData] = await Promise.all([
      api.getRankings(null, validAge, 'M'),
      api.getRankings(null, validAge, 'F'),
    ]);
    
    totalBoys = boysData.length;
    totalGirls = girlsData.length;
    
    topBoys = boysData.slice(0, 25).map(t => ({
      team_id_master: t.team_id_master,
      team_name: t.team_name,
      club_name: t.club_name,
      state: t.state,
      power_score_final: t.power_score_final,
      rank_in_cohort_final: t.rank_in_cohort_final,
    }));
    
    topGirls = girlsData.slice(0, 25).map(t => ({
      team_id_master: t.team_id_master,
      team_name: t.team_name,
      club_name: t.club_name,
      state: t.state,
      power_score_final: t.power_score_final,
      rank_in_cohort_final: t.rank_in_cohort_final,
    }));
  } catch (error) {
    console.error('Error fetching age group data:', error);
  }

  // Adjacent age groups for navigation
  const currentIdx = VALID_AGE_GROUPS.indexOf(validAge);
  const prevAge = currentIdx > 0 ? VALID_AGE_GROUPS[currentIdx - 1] : null;
  const nextAge = currentIdx < VALID_AGE_GROUPS.length - 1 ? VALID_AGE_GROUPS[currentIdx + 1] : null;

  // Structured data for SEO
  const structuredData = {
    '@context': 'https://schema.org',
    '@type': 'CollectionPage',
    name: `${ageDisplay} Youth Soccer Rankings`,
    description: `National ${ageDisplay} youth soccer rankings for boys and girls`,
    url: `https://pitchrank.io/rankings/age/${validAge}`,
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }}
      />
      
      <div className="container mx-auto py-8 px-4">
        <Breadcrumbs items={[
          { label: 'Home', href: '/' },
          { label: 'Rankings', href: '/rankings' },
          { label: ageDisplay, href: `/rankings/age/${validAge}` },
        ]} />

        {/* Page Header */}
        <div className="relative bg-secondary/30 border-b-2 border-primary py-8 sm:py-12 mb-8 -mx-4 px-4">
          <div className="absolute left-0 top-0 w-2 h-full bg-accent -skew-x-12" aria-hidden="true" />
          <h1 className="font-display text-3xl sm:text-4xl md:text-5xl font-bold uppercase text-primary mb-2">
            {ageDisplay} Soccer Rankings
          </h1>
          <p className="text-muted-foreground text-base sm:text-lg">
            National {ageDisplay} youth soccer rankings
          </p>
          <p className="text-sm text-muted-foreground mt-2">
            {totalBoys.toLocaleString()} Boys teams • {totalGirls.toLocaleString()} Girls teams
          </p>
        </div>

        {/* Age Navigation */}
        <div className="flex items-center justify-between mb-8">
          {prevAge ? (
            <Link 
              href={`/rankings/age/${prevAge}`}
              className="text-primary hover:underline flex items-center gap-1"
            >
              ← {prevAge.toUpperCase()}
            </Link>
          ) : <div />}
          
          <div className="flex gap-2">
            <Link 
              href={`/rankings/national/${validAge}/male`}
              className="px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90 text-sm"
            >
              View {ageDisplay} Boys Full Rankings
            </Link>
            <Link 
              href={`/rankings/national/${validAge}/female`}
              className="px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90 text-sm"
            >
              View {ageDisplay} Girls Full Rankings
            </Link>
          </div>
          
          {nextAge ? (
            <Link 
              href={`/rankings/age/${nextAge}`}
              className="text-primary hover:underline flex items-center gap-1"
            >
              {nextAge.toUpperCase()} →
            </Link>
          ) : <div />}
        </div>

        {/* Top 25 Tables */}
        <div className="grid lg:grid-cols-2 gap-8 mb-12">
          {/* Boys Top 25 */}
          <section>
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-2xl font-bold">{ageDisplay} Boys - National Top 25</h2>
              <Link 
                href={`/rankings/national/${validAge}/male`}
                className="text-sm text-primary hover:underline"
              >
                View All →
              </Link>
            </div>
            <div className="bg-card border border-border rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-muted">
                  <tr>
                    <th className="px-3 py-2 text-left w-12">#</th>
                    <th className="px-3 py-2 text-left">Team</th>
                    <th className="px-3 py-2 text-left w-16">State</th>
                    <th className="px-3 py-2 text-right w-20">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {topBoys.length > 0 ? (
                    topBoys.map((team, idx) => (
                      <tr key={team.team_id_master} className="border-t border-border hover:bg-muted/50">
                        <td className="px-3 py-2 text-muted-foreground">{idx + 1}</td>
                        <td className="px-3 py-2">
                          <Link 
                            href={`/teams/${team.team_id_master}`}
                            className="hover:text-primary font-medium"
                          >
                            {team.team_name}
                          </Link>
                          {team.club_name && (
                            <span className="block text-xs text-muted-foreground truncate">
                              {team.club_name}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {team.state ? (
                            <Link 
                              href={`/rankings/${team.state.toLowerCase()}/${validAge}/male`}
                              className="hover:text-primary"
                            >
                              {team.state}
                            </Link>
                          ) : '—'}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">
                          {team.power_score_final.toFixed(1)}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={4} className="px-3 py-8 text-center text-muted-foreground">
                        No teams ranked yet
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          {/* Girls Top 25 */}
          <section>
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-2xl font-bold">{ageDisplay} Girls - National Top 25</h2>
              <Link 
                href={`/rankings/national/${validAge}/female`}
                className="text-sm text-primary hover:underline"
              >
                View All →
              </Link>
            </div>
            <div className="bg-card border border-border rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-muted">
                  <tr>
                    <th className="px-3 py-2 text-left w-12">#</th>
                    <th className="px-3 py-2 text-left">Team</th>
                    <th className="px-3 py-2 text-left w-16">State</th>
                    <th className="px-3 py-2 text-right w-20">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {topGirls.length > 0 ? (
                    topGirls.map((team, idx) => (
                      <tr key={team.team_id_master} className="border-t border-border hover:bg-muted/50">
                        <td className="px-3 py-2 text-muted-foreground">{idx + 1}</td>
                        <td className="px-3 py-2">
                          <Link 
                            href={`/teams/${team.team_id_master}`}
                            className="hover:text-primary font-medium"
                          >
                            {team.team_name}
                          </Link>
                          {team.club_name && (
                            <span className="block text-xs text-muted-foreground truncate">
                              {team.club_name}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {team.state ? (
                            <Link 
                              href={`/rankings/${team.state.toLowerCase()}/${validAge}/female`}
                              className="hover:text-primary"
                            >
                              {team.state}
                            </Link>
                          ) : '—'}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">
                          {team.power_score_final.toFixed(1)}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={4} className="px-3 py-8 text-center text-muted-foreground">
                        No teams ranked yet
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        {/* Browse by State */}
        <section className="mb-12">
          <h2 className="text-xl font-bold mb-4">{ageDisplay} Rankings by State</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {/* Popular states first */}
            {POPULAR_STATES.map(stateCode => {
              const state = US_STATES.find(s => s.code === stateCode);
              if (!state) return null;
              return (
                <div key={stateCode} className="bg-card border border-border rounded-lg p-3">
                  <h3 className="font-medium mb-1">{state.name}</h3>
                  <div className="flex gap-2 text-sm">
                    <Link 
                      href={`/rankings/${stateCode.toLowerCase()}/${validAge}/male`}
                      className="text-primary hover:underline"
                    >
                      Boys
                    </Link>
                    <span className="text-muted-foreground">•</span>
                    <Link 
                      href={`/rankings/${stateCode.toLowerCase()}/${validAge}/female`}
                      className="text-primary hover:underline"
                    >
                      Girls
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
          
          {/* All states link */}
          <details className="mt-4">
            <summary className="cursor-pointer text-sm text-primary hover:underline">
              View all states →
            </summary>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2 mt-4">
              {US_STATES.filter(s => !POPULAR_STATES.includes(s.code)).map(state => (
                <Link 
                  key={state.code}
                  href={`/rankings/${state.code.toLowerCase()}/${validAge}/male`}
                  className="text-sm text-muted-foreground hover:text-primary"
                >
                  {state.name}
                </Link>
              ))}
            </div>
          </details>
        </section>

        {/* Other Age Groups */}
        <section className="border-t border-border pt-8">
          <h2 className="text-xl font-bold mb-4">Other Age Groups</h2>
          <div className="flex flex-wrap gap-2">
            {VALID_AGE_GROUPS.filter(a => a !== validAge).map(age => (
              <Link 
                key={age}
                href={`/rankings/age/${age}`}
                className="px-3 py-1.5 bg-muted text-foreground rounded text-sm hover:bg-muted/80"
              >
                {age.toUpperCase()}
              </Link>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
