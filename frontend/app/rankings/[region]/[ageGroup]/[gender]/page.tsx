import { RankingsPageContent } from '@/components/RankingsPageContent';
import type { Metadata } from 'next';
import { US_STATES } from '@/lib/constants';

// Revalidate every hour for ISR caching
export const revalidate = 3600;

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
 * Format gender for display (e.g., "male" -> "Boys", "female" -> "Girls")
 */
const VALID_GENDERS: Record<string, string> = {
  male: 'Boys',
  female: 'Girls',
  boys: 'Boys',
  girls: 'Girls',
};

function formatGender(gender: string): string {
  return VALID_GENDERS[gender.toLowerCase()] ?? 'Unknown';
}

/**
 * Get state name from code
 */
function getStateName(stateCode: string): string {
  const state = US_STATES.find(s => s.code.toLowerCase() === stateCode.toLowerCase());
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
    
    const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';
    const canonicalUrl = `${baseUrl}/rankings/${region}/${ageGroup}/${gender}`;
    
    const formattedAgeGroup = formatAgeGroup(ageGroup);
    const formattedGender = formatGender(gender);
    const isNational = region.toLowerCase() === 'national';
    const locationText = isNational 
      ? 'National' 
      : getStateName(region);
    
    const title = `${formattedAgeGroup} ${formattedGender} Soccer Rankings${isNational ? '' : ` - ${locationText}`} | PitchRank`;
    const description = `View comprehensive ${formattedAgeGroup} ${formattedGender.toLowerCase()} soccer team rankings${isNational ? ' nationally' : ` in ${locationText}`}. Compare power scores, win percentages, and team performance metrics.`;

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
            url: '/logos/pitchrank-wordmark.svg',
            width: 1200,
            height: 630,
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
      description: 'View comprehensive soccer team rankings. Compare power scores, win percentages, and team performance metrics.',
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
    'name': `${formattedAgeGroup} ${formattedGender} Soccer Rankings${isNational ? '' : ` - ${locationText}`}`,
    'description': 'Youth soccer team rankings by power rating',
    'url': `https://pitchrank.io/rankings/${safeRegion}/${safeAgeGroup}/${safeGender}`,
  };

  // Escape </script> sequences to prevent XSS in JSON-LD structured data
  const safeJsonLd = JSON.stringify(structuredData).replace(/</g, '\\u003c');

  return (
    <>
      <RankingsPageContent key={routeKey} region={region} ageGroup={ageGroup} gender={gender} />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: safeJsonLd }}
      />
    </>
  );
}
