import Link from 'next/link';
import { US_STATES } from '@/lib/constants';

interface RelatedRankingsProps {
  currentRegion: string;
  currentAgeGroup: string;
  currentGender: string;
}

const AGE_GROUPS = ['u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'u18'];

/**
 * Internal linking component for SEO
 * Shows related rankings pages to improve crawlability and user navigation
 */
export function RelatedRankings({ currentRegion, currentAgeGroup, currentGender }: RelatedRankingsProps) {
  const genderDisplay = currentGender === 'male' ? 'Boys' : 'Girls';
  const ageDisplay = currentAgeGroup.toUpperCase();
  const isNational = currentRegion === 'national';
  
  // Get current state info
  const currentState = US_STATES.find(s => s.code.toLowerCase() === currentRegion.toLowerCase());
  
  // Get neighboring age groups
  const currentAgeIndex = AGE_GROUPS.indexOf(currentAgeGroup.toLowerCase());
  const neighboringAges = AGE_GROUPS.filter((_, i) => 
    Math.abs(i - currentAgeIndex) <= 2 && i !== currentAgeIndex
  );

  // Get nearby states (simplified - just show a few popular ones + national)
  const popularStates = ['CA', 'TX', 'FL', 'NY', 'GA', 'PA', 'IL', 'NC', 'AZ', 'WA'];
  const relatedRegions = isNational 
    ? popularStates.slice(0, 6)
    : ['national', ...popularStates.filter(s => s.toLowerCase() !== currentRegion.toLowerCase()).slice(0, 5)];

  // Opposite gender
  const oppositeGender = currentGender === 'male' ? 'female' : 'male';
  const oppositeGenderDisplay = oppositeGender === 'male' ? 'Boys' : 'Girls';

  return (
    <div className="mt-8 pt-6 border-t border-border">
      <h3 className="text-lg font-semibold mb-4 text-foreground">Related Rankings</h3>
      
      <div className="grid gap-4 md:grid-cols-3">
        {/* Same region, different age groups */}
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-2">
            Other Age Groups {isNational ? '(National)' : `in ${currentState?.name || currentRegion.toUpperCase()}`}
          </h4>
          <ul className="space-y-1">
            {neighboringAges.map(age => (
              <li key={age}>
                <Link 
                  href={`/rankings/${currentRegion}/${age}/${currentGender}`}
                  className="text-sm text-primary hover:underline"
                >
                  {age.toUpperCase()} {genderDisplay}
                </Link>
              </li>
            ))}
          </ul>
        </div>

        {/* Same age group, different regions */}
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-2">
            {ageDisplay} {genderDisplay} in Other Regions
          </h4>
          <ul className="space-y-1">
            {relatedRegions.map(region => {
              const stateName = region === 'national' 
                ? 'National' 
                : US_STATES.find(s => s.code === region)?.name || region;
              return (
                <li key={region}>
                  <Link 
                    href={`/rankings/${region.toLowerCase()}/${currentAgeGroup}/${currentGender}`}
                    className="text-sm text-primary hover:underline"
                  >
                    {stateName}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>

        {/* Opposite gender */}
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-2">
            {oppositeGenderDisplay} Rankings
          </h4>
          <ul className="space-y-1">
            <li>
              <Link 
                href={`/rankings/${currentRegion}/${currentAgeGroup}/${oppositeGender}`}
                className="text-sm text-primary hover:underline"
              >
                {ageDisplay} {oppositeGenderDisplay} {isNational ? '(National)' : `- ${currentState?.name || currentRegion.toUpperCase()}`}
              </Link>
            </li>
            {neighboringAges.slice(0, 2).map(age => (
              <li key={age}>
                <Link 
                  href={`/rankings/${currentRegion}/${age}/${oppositeGender}`}
                  className="text-sm text-primary hover:underline"
                >
                  {age.toUpperCase()} {oppositeGenderDisplay}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Popular national rankings */}
      {!isNational && (
        <div className="mt-4">
          <h4 className="text-sm font-medium text-muted-foreground mb-2">
            National Rankings
          </h4>
          <div className="flex flex-wrap gap-2">
            {['u12', 'u13', 'u14', 'u15'].map(age => (
              <Link 
                key={age}
                href={`/rankings/national/${age}/${currentGender}`}
                className="text-xs px-2 py-1 bg-muted rounded hover:bg-muted/80 text-foreground"
              >
                {age.toUpperCase()} {genderDisplay} National
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
