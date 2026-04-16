import Link from 'next/link';
import { US_STATES, AGE_GROUPS, formatGender } from '@/lib/constants';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';

interface RelatedRankingsProps {
  currentRegion: string;
  currentAgeGroup: string;
  currentGender: string;
}

/**
 * Internal linking component for SEO
 * Shows related rankings pages to improve crawlability and user navigation
 */
export function RelatedRankings({ currentRegion, currentAgeGroup, currentGender }: RelatedRankingsProps) {
  const genderDisplay = formatGender(currentGender);
  const ageDisplay = currentAgeGroup.toUpperCase();
  const isNational = currentRegion === 'national';

  // Get current state info
  const currentState = US_STATES.find((s) => s.code.toLowerCase() === currentRegion.toLowerCase());

  // Get neighboring age groups
  const currentAgeIndex = (AGE_GROUPS as readonly string[]).indexOf(currentAgeGroup.toLowerCase());
  const neighboringAges = AGE_GROUPS.filter((_, i) => Math.abs(i - currentAgeIndex) <= 2 && i !== currentAgeIndex);

  // Get nearby states (simplified - just show a few popular ones + national)
  const popularStates = ['CA', 'TX', 'FL', 'NY', 'GA', 'PA', 'IL', 'NC', 'AZ', 'WA'];
  const relatedRegions = isNational
    ? popularStates.slice(0, 6)
    : ['national', ...popularStates.filter((s) => s.toLowerCase() !== currentRegion.toLowerCase()).slice(0, 5)];

  // Opposite gender
  const oppositeGender = currentGender === 'male' ? 'female' : 'male';
  const oppositeGenderDisplay = formatGender(oppositeGender);

  return (
    <Card variant="flat" className="gap-0 py-0">
      <CardHeader className="pt-5 pb-0">
        <CardTitle>
          <h3 className="font-display text-base font-semibold uppercase tracking-wide">Explore More Rankings</h3>
        </CardTitle>
      </CardHeader>

      <CardContent className="pt-4 pb-5">
        <div className="grid gap-6 sm:grid-cols-3">
          {/* Same region, different age groups */}
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
              Other Ages {isNational ? '' : `in ${currentState?.name || currentRegion.toUpperCase()}`}
            </p>
            <ul className="space-y-0">
              {neighboringAges.map((age) => (
                <li key={age} className="py-1 border-b border-border/40 last:border-0">
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
            <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
              {ageDisplay} {genderDisplay} Elsewhere
            </p>
            <ul className="space-y-0">
              {relatedRegions.map((region) => {
                const stateName =
                  region === 'national' ? 'National' : US_STATES.find((s) => s.code === region)?.name || region;
                return (
                  <li key={region} className="py-1 border-b border-border/40 last:border-0">
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
            <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
              {oppositeGenderDisplay} Rankings
            </p>
            <ul className="space-y-0">
              <li className="py-1 border-b border-border/40">
                <Link
                  href={`/rankings/${currentRegion}/${currentAgeGroup}/${oppositeGender}`}
                  className="text-sm text-primary hover:underline"
                >
                  {ageDisplay} {oppositeGenderDisplay}{' '}
                  {isNational ? '(National)' : `\u2014 ${currentState?.name || currentRegion.toUpperCase()}`}
                </Link>
              </li>
              {neighboringAges.slice(0, 2).map((age) => (
                <li key={age} className="py-1 border-b border-border/40 last:border-0">
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

        {/* National quick links */}
        {!isNational && (
          <div className="mt-5 pt-4 border-t border-border/60">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
              National Rankings
            </p>
            <div className="flex flex-wrap gap-2">
              {['u12', 'u13', 'u14', 'u15'].map((age) => (
                <Link
                  key={age}
                  href={`/rankings/national/${age}/${currentGender}`}
                  className="text-xs px-3 py-1.5 bg-muted rounded-lg hover:bg-muted/80 text-foreground font-medium"
                >
                  {age.toUpperCase()} {genderDisplay} National
                </Link>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
