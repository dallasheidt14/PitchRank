import { RankingsPageContent } from '@/components/RankingsPageContent';
import type { Metadata } from 'next';
import { US_STATES } from '@/lib/constants';

// Revalidate every hour for ISR caching
export const revalidate = 3600;

interface RankingsPageProps {
  params: {
    region: string;
    ageGroup: string;
    gender: string;
  };
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
function formatGender(gender: string): string {
  return gender.toLowerCase() === 'male' ? 'Boys' : 'Girls';
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
  const { region, ageGroup, gender } = params;
  
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.com';
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
}

export default function RankingsPage({ params }: RankingsPageProps) {
  const { region, ageGroup, gender } = params;

  return <RankingsPageContent region={region} ageGroup={ageGroup} gender={gender} />;
}
