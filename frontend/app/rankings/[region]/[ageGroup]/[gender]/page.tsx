import { RankingsPageContent } from '@/components/RankingsPageContent';
import type { Metadata } from 'next';
import { US_STATES, BASE_URL, formatGender } from '@/lib/constants';
import { api } from '@/lib/api';
import { formatPowerScore } from '@/lib/utils';
import BreadcrumbSchema from '@/components/BreadcrumbSchema';

// Revalidate every hour for ISR caching
export const revalidate = 3600;

// Pre-generate popular state/age/gender combos at build time (196 pages).
// Remaining pages render on-demand with ISR.
export async function generateStaticParams() {
  const popularStates = ['national', 'ca', 'tx', 'fl', 'az', 'ny', 'nj', 'md', 'ga', 'pa', 'co', 'oh', 'nc', 'il'];
  const ageGroups = ['u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16'];
  const genders = ['male', 'female'];
  return popularStates.flatMap((region) =>
    ageGroups.flatMap((ageGroup) => genders.map((gender) => ({ region, ageGroup, gender })))
  );
}

interface RankingsPageProps {
  params: Promise<{
    region: string;
    ageGroup: string;
    gender: string;
  }>;
}

/**
 * Format age group for display (e.g., "u12" -> "U12")
 */
function formatAgeGroup(ageGroup: string): string {
  return ageGroup.toUpperCase();
}

/**
 * Get state name from code
 */
function getStateName(stateCode: string): string {
  const state = US_STATES.find((s) => s.code.toLowerCase() === stateCode.toLowerCase());
  return state ? state.name : stateCode.toUpperCase();
}

/**
 * Generate metadata for rankings pages
 */
export async function generateMetadata({ params }: RankingsPageProps): Promise<Metadata> {
  try {
    // In Next.js 16, params is a Promise - await it
    const resolvedParams = await params;
    const { region, ageGroup, gender } = resolvedParams;

    const canonicalUrl = `${BASE_URL}/rankings/${region}/${ageGroup}/${gender}`;

    const formattedAgeGroup = formatAgeGroup(ageGroup);
    const formattedGender = formatGender(gender);
    const isNational = region.toLowerCase() === 'national';
    const locationText = isNational ? 'National' : getStateName(region);

    const title = `${locationText} ${formattedAgeGroup} ${formattedGender} Soccer Rankings | PitchRank`;
    const description = `${locationText} ${formattedAgeGroup} ${formattedGender} youth soccer rankings — see where your team stands. Browse top-ranked clubs, compare PowerScores, and track weekly changes. Free, updated every Monday.`;

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
        images: [
          {
            url: '/logos/icon-512.png',
            width: 512,
            height: 512,
            alt: 'PitchRank Logo',
          },
        ],
      },
      twitter: {
        card: 'summary_large_image',
        title,
        description,
        images: ['/logos/pitchrank-wordmark.svg'],
      },
    };
  } catch (error) {
    console.error('Error generating metadata for rankings page:', error);
    // Return fallback metadata
    return {
      title: 'Soccer Rankings | PitchRank',
      description:
        'Youth soccer rankings by PowerScore — browse top-ranked clubs, compare teams, and track weekly changes. Free, updated every Monday.',
    };
  }
}

export default async function RankingsPage({ params }: RankingsPageProps) {
  // In Next.js 16, params is a Promise - await it
  const resolvedParams = await params;
  const { region, ageGroup, gender } = resolvedParams;

  // key prop forces React to unmount/remount the component when route params change
  // This ensures fresh data fetching on client-side navigation between different rankings pages
  const routeKey = `${region}-${ageGroup}-${gender}`;

  // Server-side fetch top 25 teams so the initial HTML has real content for Googlebot.
  // Rendered as a static section below the interactive table — does not interfere with client-side loading.
  const genderForAPI = (gender === 'male' ? 'M' : gender === 'female' ? 'F' : null) as 'M' | 'F' | null;
  const regionForAPI = region.toLowerCase() === 'national' ? null : region;
  let topTeams: Array<{
    team_id_master: string;
    team_name: string;
    club_name: string | null;
    power_score_final: number;
  }> = [];
  try {
    const data = await api.getRankings(regionForAPI, ageGroup, genderForAPI, { limit: 25 });
    topTeams = data.map((t) => ({
      team_id_master: t.team_id_master,
      team_name: t.team_name,
      club_name: t.club_name,
      power_score_final: t.power_score_final,
    }));
  } catch (e) {
    console.warn(`[ISR] Failed to fetch top teams for ${region}/${ageGroup}/${gender}:`, e);
  }

  // Prepare structured data for SEO
  const formattedAgeGroup = formatAgeGroup(ageGroup);
  const formattedGender = formatGender(gender);
  const isNational = region.toLowerCase() === 'national';
  const locationText = isNational ? 'National' : getStateName(region);

  // Sanitize route params to prevent XSS via </script> injection in JSON-LD
  const safeRegion = region.replace(/[<>"'&]/g, '');
  const safeAgeGroup = ageGroup.replace(/[<>"'&]/g, '');
  const safeGender = gender.replace(/[<>"'&]/g, '');

  const structuredData = {
    '@context': 'https://schema.org',
    '@type': 'RankingTable',
    name: `${locationText} ${formattedAgeGroup} ${formattedGender} Soccer Rankings`,
    description: 'Youth soccer team rankings by PowerScore rating, updated weekly',
    url: `${BASE_URL}/rankings/${safeRegion}/${safeAgeGroup}/${safeGender}`,
  };

  // Escape </script> sequences to prevent XSS in JSON-LD structured data
  const safeJsonLd = JSON.stringify(structuredData).replace(/</g, '\\u003c');

  // Build breadcrumb trail
  const breadcrumbItems = [
    { name: 'Home', href: '/' },
    { name: 'Rankings', href: '/rankings' },
    { name: locationText, href: `/rankings/${safeRegion}` },
    { name: formattedAgeGroup, href: `/rankings/${safeRegion}/${safeAgeGroup}` },
    { name: formattedGender, href: `/rankings/${safeRegion}/${safeAgeGroup}/${safeGender}` },
  ];

  return (
    <>
      <RankingsPageContent key={routeKey} region={region} ageGroup={ageGroup} gender={gender} />
      <BreadcrumbSchema items={breadcrumbItems} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd }} />

      {/* Unique intro — renders regardless of API success so Googlebot always sees real content */}
      <p className="container mx-auto px-4 text-muted-foreground text-sm mt-2">
        {isNational
          ? `National ${formattedAgeGroup} ${formattedGender} youth soccer rankings, updated weekly from real game results. Browse PowerScores for top clubs across all 50 states.`
          : `${locationText} ${formattedAgeGroup} ${formattedGender} youth soccer rankings, updated weekly. See where ${locationText} clubs stand by PowerScore rating.`}
      </p>

      {/* Server-rendered top teams for SEO — gives Googlebot real content in the initial HTML.
          The interactive table above loads the full dataset client-side. */}
      {topTeams.length > 0 && (
        <section className="container mx-auto px-4 pb-8">
          <h2 className="text-xl font-bold mb-4">
            Top {locationText} {formattedAgeGroup} {formattedGender} Teams
          </h2>
          <ol className="space-y-1 text-sm">
            {topTeams.map((team, idx) => (
              <li key={team.team_id_master} className="flex items-center gap-2">
                <span className="text-muted-foreground w-6">{idx + 1}.</span>
                <span>{team.team_name}</span>
                {team.club_name && <span className="text-muted-foreground">({team.club_name})</span>}
                <span className="text-xs text-muted-foreground ml-auto">
                  {formatPowerScore(team.power_score_final)}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}
    </>
  );
}
