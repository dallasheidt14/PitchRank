import type { CohortModuleData } from '@/lib/cohort-seo';
import { buildCohortFAQ } from '@/lib/cohort-seo';
import { safeJsonLd } from '@/lib/schema-utils';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';

interface CohortSEOContentProps {
  data: CohortModuleData;
}

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/**
 * Server-rendered SEO content modules for ranking pages.
 * Renders between the H1/intro and the interactive table.
 * FAQ renders separately below the table via CohortFAQ.
 */
export function CohortSEOContent({ data }: CohortSEOContentProps) {
  const {
    totalTeams,
    positioningHook,
    topClubs,
    risers,
    fallers,
    lastGameDate,
    lastCalculated,
    locationText,
    ageGroupDisplay,
    genderLabel,
    isNational,
  } = data;

  const scope = isNational ? 'nationally' : `in ${locationText}`;
  const hasRisers = risers.length > 0;
  const hasFallers = fallers.length > 0;

  return (
    <section className="container mx-auto px-4 pb-6">
      <Card variant="accent" className="py-0 gap-0 hover:scale-100">
        {/* Header: title + summary */}
        <CardHeader className="pb-0 pt-5">
          <CardTitle>
            <h2 className="font-display text-base font-semibold uppercase tracking-wide">
              {locationText} {ageGroupDisplay} {genderLabel === 'boys' ? 'Boys' : 'Girls'} at a Glance
            </h2>
          </CardTitle>
          <CardDescription className="text-sm leading-relaxed">
            The {isNational ? 'national' : locationText} {ageGroupDisplay} {genderLabel} group is{' '}
            <strong className="text-foreground">{positioningHook}</strong>, with{' '}
            <strong className="text-foreground">{totalTeams.toLocaleString()} active teams</strong> competing {scope}{' '}
            across all tracked leagues.
          </CardDescription>
        </CardHeader>

        {/* Body: three-column grid — clubs | risers | fallers */}
        <CardContent className="pt-4 pb-0">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-0 sm:divide-x sm:divide-border">
            {/* Top Clubs */}
            {topClubs.length > 0 && (
              <div className="pb-4 sm:pb-0 sm:pr-5">
                <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
                  Top Clubs
                </p>
                <ul className="text-sm space-y-0">
                  {topClubs.map((club) => (
                    <li key={club.name} className="flex justify-between py-1.5 border-b border-border/40 last:border-0">
                      <span>{club.name}</span>
                      <span className="text-muted-foreground tabular-nums">{club.count}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Rising */}
            {hasRisers && (
              <div className="pt-4 sm:pt-0 sm:px-5 border-t sm:border-t-0 border-border/40">
                <p className="text-[11px] font-semibold uppercase tracking-widest text-green-600 mb-2">
                  Rising This Week
                </p>
                <ul className="text-sm space-y-0">
                  {risers.map((t) => (
                    <li
                      key={t.teamId}
                      className="flex items-baseline gap-1.5 py-1.5 border-b border-border/40 last:border-0"
                    >
                      <span className="text-green-600 text-xs">{'\u25B2'}</span>
                      <a
                        href={`/teams/${t.teamId}`}
                        className="underline decoration-border underline-offset-2 hover:decoration-foreground truncate"
                      >
                        {t.teamName}
                      </a>
                      <span className="ml-auto text-xs font-medium tabular-nums whitespace-nowrap text-green-600">
                        +{t.change}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Falling */}
            {hasFallers && (
              <div className="pt-4 sm:pt-0 sm:pl-5 border-t sm:border-t-0 border-border/40">
                <p className="text-[11px] font-semibold uppercase tracking-widest text-red-500 mb-2">
                  Falling This Week
                </p>
                <ul className="text-sm space-y-0">
                  {fallers.map((t) => (
                    <li
                      key={t.teamId}
                      className="flex items-baseline gap-1.5 py-1.5 border-b border-border/40 last:border-0"
                    >
                      <span className="text-red-500 text-xs">{'\u25BC'}</span>
                      <a
                        href={`/teams/${t.teamId}`}
                        className="underline decoration-border underline-offset-2 hover:decoration-foreground truncate"
                      >
                        {t.teamName}
                      </a>
                      <span className="ml-auto text-xs font-medium tabular-nums whitespace-nowrap text-red-500">
                        {t.change}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </CardContent>

        {/* Footer: freshness */}
        {(lastCalculated || lastGameDate) && (
          <CardFooter className="border-t bg-muted/30 text-xs text-muted-foreground py-2.5 mt-4 rounded-b-xl">
            {lastCalculated && <>Updated {formatShortDate(lastCalculated)}</>}
            {lastCalculated && lastGameDate && <span className="mx-1.5">&middot;</span>}
            {lastGameDate && <>Last game {formatShortDate(lastGameDate)}</>}
          </CardFooter>
        )}
      </Card>
    </section>
  );
}

/**
 * FAQ section rendered below the interactive rankings table.
 * Includes FAQPage JSON-LD for Google/AI citation eligibility.
 */
export function CohortFAQ({ data }: CohortSEOContentProps) {
  const faqItems = buildCohortFAQ(data);

  const faqJsonLd = safeJsonLd({
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: faqItems.map((item) => ({
      '@type': 'Question',
      name: item.question,
      acceptedAnswer: {
        '@type': 'Answer',
        text: item.answer,
      },
    })),
  });

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: faqJsonLd }} />
      <section className="container mx-auto px-4 pt-8 pb-6">
        <h3 className="font-display text-sm font-semibold uppercase tracking-wide mb-4">Frequently Asked Questions</h3>
        <dl className="divide-y divide-border/60">
          {faqItems.map((item) => (
            <div key={item.question} className="py-3 first:pt-0">
              <dt className="text-sm font-medium">{item.question}</dt>
              <dd className="text-sm text-muted-foreground mt-1 leading-relaxed">{item.answer}</dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  );
}
