import type { CohortModuleData } from '@/lib/cohort-seo';
import { buildCohortFAQ } from '@/lib/cohort-seo';
import { safeJsonLd } from '@/lib/schema-utils';

interface CohortSEOContentProps {
  data: CohortModuleData;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
}

/**
 * Server-rendered SEO content modules for ranking pages.
 * Renders between the H1/intro and the interactive table (modules 1-3 + freshness).
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
  const hasMovers = risers.length > 0 || fallers.length > 0;

  return (
    <section className="container mx-auto px-4 pb-6 space-y-6">
      {/* Module 1: Group Summary */}
      <div>
        <h2 className="font-display text-lg font-semibold mb-1">
          {locationText} {ageGroupDisplay} {genderLabel === 'boys' ? 'Boys' : 'Girls'} at a Glance
        </h2>
        <p className="text-muted-foreground text-sm">
          The {isNational ? 'national' : locationText} {ageGroupDisplay} {genderLabel} group is{' '}
          <strong>{positioningHook}</strong>, with <strong>{totalTeams.toLocaleString()} active teams</strong>{' '}
          competing {scope} across all tracked leagues.
        </p>
      </div>

      {/* Module 2: Top Clubs */}
      {topClubs.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-2">Top Clubs by Team Count</h3>
          <div className="overflow-x-auto">
            <table className="text-sm w-full max-w-md">
              <thead>
                <tr className="border-b text-left">
                  <th className="pb-1 pr-4 font-medium text-muted-foreground">Club</th>
                  <th className="pb-1 font-medium text-muted-foreground">Teams</th>
                </tr>
              </thead>
              <tbody>
                {topClubs.map((club) => (
                  <tr key={club.name} className="border-b border-border/50">
                    <td className="py-1 pr-4">{club.name}</td>
                    <td className="py-1">{club.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Module 3: Biggest Movers This Week */}
      {hasMovers && (
        <div>
          <h3 className="text-sm font-semibold mb-2">Biggest Movers This Week</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
            {risers.length > 0 && (
              <div>
                <p className="font-medium text-green-600 dark:text-green-400 mb-1">Rising</p>
                <ul className="space-y-0.5">
                  {risers.map((t) => (
                    <li key={t.teamId}>
                      <a
                        href={`/teams/${t.teamId}`}
                        className="underline decoration-1 underline-offset-2 hover:decoration-2"
                      >
                        {t.teamName}
                      </a>
                      {t.clubName && <span className="text-muted-foreground"> ({t.clubName})</span>}
                      <span className="text-green-600 dark:text-green-400"> &mdash; up {t.change} spots</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {fallers.length > 0 && (
              <div>
                <p className="font-medium text-red-500 dark:text-red-400 mb-1">Falling</p>
                <ul className="space-y-0.5">
                  {fallers.map((t) => (
                    <li key={t.teamId}>
                      <a
                        href={`/teams/${t.teamId}`}
                        className="underline decoration-1 underline-offset-2 hover:decoration-2"
                      >
                        {t.teamName}
                      </a>
                      {t.clubName && <span className="text-muted-foreground"> ({t.clubName})</span>}
                      <span className="text-red-500 dark:text-red-400">
                        {' '}&mdash; down {Math.abs(t.change)} spots
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Module 5: Freshness Signal */}
      <p className="text-xs text-muted-foreground">
        {lastCalculated && <>Rankings last calculated {formatDate(lastCalculated)}. </>}
        {lastGameDate && <>Most recent game in this group: {formatDate(lastGameDate)}.</>}
      </p>
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
      <section className="container mx-auto px-4 py-6">
        <h3 className="text-sm font-semibold mb-2">FAQ</h3>
        <dl className="space-y-3 text-sm">
          {faqItems.map((item) => (
            <div key={item.question}>
              <dt className="font-medium">{item.question}</dt>
              <dd className="text-muted-foreground mt-0.5">{item.answer}</dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  );
}
