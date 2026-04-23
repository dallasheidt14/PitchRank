import Link from 'next/link';

/**
 * FAQ items shared between the visible FAQ section and the FAQPage JSON-LD
 * emitted on /rankings. Schema must match rendered content — edit both together.
 */
export const rankingsPillarFaqItems: ReadonlyArray<{ q: string; a: string }> = [
  {
    q: 'What are youth soccer rankings?',
    a: 'Youth soccer rankings compare competitive clubs and teams based on their performance over a season. PitchRank ranks more than 77,000 teams across all 50 states, every age group from U10 through U19, for both boys and girls.',
  },
  {
    q: 'How are PitchRank rankings calculated?',
    a: 'Every ranking is built from real game results — wins, losses, margin of victory, and the strength of the opponents a team has played. Our rating engine processes hundreds of thousands of games each season and produces a PowerScore for every team. Rankings update every Monday.',
  },
  {
    q: 'Are youth soccer rankings accurate?',
    a: 'Accuracy depends on the data and the method. PitchRank uses public game results directly from league websites and scoring platforms — not coach votes or subjective polls. When two teams play the same opponents, they can be compared directly. When they don’t, PowerScore uses common opponents and strength-of-schedule to infer relative strength, which is why the rankings hold up across state lines.',
  },
  {
    q: 'How often are rankings updated?',
    a: 'PitchRank updates every Monday. Games from the prior week are processed and every team’s PowerScore is recalculated. You can see when a team’s ranking last changed on its team page.',
  },
  {
    q: 'Are these rankings free?',
    a: 'Yes. Browsing rankings for any state, age group, or team is free and does not require an account. We offer advanced features for registered users, but the full ranking data is always free to view.',
  },
];

/**
 * Popular state links for the pillar section. Order follows GSC traffic —
 * top-trafficked states surfaced first. Keep in sync with state pillar blog guides.
 */
const POPULAR_STATES: ReadonlyArray<{ code: string; name: string; hasGuide: boolean }> = [
  { code: 'ca', name: 'California', hasGuide: true },
  { code: 'tx', name: 'Texas', hasGuide: true },
  { code: 'fl', name: 'Florida', hasGuide: true },
  { code: 'ny', name: 'New York', hasGuide: false },
  { code: 'nj', name: 'New Jersey', hasGuide: true },
  { code: 'md', name: 'Maryland', hasGuide: false },
  { code: 'nc', name: 'North Carolina', hasGuide: true },
  { code: 'co', name: 'Colorado', hasGuide: true },
  { code: 'pa', name: 'Pennsylvania', hasGuide: true },
  { code: 'az', name: 'Arizona', hasGuide: false },
];

/**
 * Pillar content rendered above the interactive table on /rankings.
 * Server-rendered for SEO — targets head-term intent ("youth soccer rankings",
 * "youth soccer rankings by state") that the interactive tool alone does not satisfy.
 */
export function RankingsPillar() {
  return (
    <>
      {/* How rankings work */}
      <section className="container mx-auto px-4 py-8 border-t border-border">
        <h2 className="text-2xl font-bold mb-4">How PitchRank Ranks Youth Soccer Teams</h2>
        <div className="prose prose-sm max-w-none text-muted-foreground space-y-3">
          <p>
            Every team in PitchRank is rated by <strong className="text-foreground">PowerScore</strong>, a single number
            that reflects how strong the team has played this season. PowerScore is calculated from four ingredients:
            whether a team won or lost, the margin of victory or defeat, the strength of the opponent they played, and
            the game context (league, tournament, or friendly).
          </p>
          <p>
            The rating engine is a 13-layer system that processes every game in the dataset — currently more than
            700,000 results across the 2025–2026 season. Teams that beat strong opponents gain more rating than teams
            that beat weak ones. Losses to top teams cost less than losses to weaker teams. Over the course of a season,
            PowerScore separates real strength from easy schedules.
          </p>
          <p>
            Rankings update every Monday with that week’s game results. You can see the last update date at the bottom
            of every state and age group page.{' '}
            <Link href="/methodology" className="text-primary hover:underline font-medium">
              Read the full methodology &rarr;
            </Link>
          </p>
        </div>
      </section>

      {/* How to find your team */}
      <section className="container mx-auto px-4 py-8 border-t border-border">
        <h2 className="text-2xl font-bold mb-4">How to Find Your Team’s Ranking</h2>
        <ol className="list-decimal list-inside space-y-2 text-sm text-muted-foreground">
          <li>
            <span className="text-foreground font-medium">Pick your state</span> from the rankings table below or the
            state grid further down the page.
          </li>
          <li>
            <span className="text-foreground font-medium">Choose your age group</span> — U10 through U19 are all
            covered.
          </li>
          <li>
            <span className="text-foreground font-medium">Choose boys or girls.</span> Rankings are separate for each.
          </li>
          <li>
            <span className="text-foreground font-medium">Search your team name</span> or scan the list. Tap a team to
            see game history and PowerScore trend.
          </li>
        </ol>
        <p className="text-sm text-muted-foreground mt-4">
          If your team plays across multiple age groups (an older playing-up roster, for example), each group’s rating
          stands on its own.
        </p>
      </section>

      {/* Popular states + guides */}
      <section className="container mx-auto px-4 py-8 border-t border-border">
        <h2 className="text-2xl font-bold mb-4">Popular Rankings Right Now</h2>
        <p className="text-sm text-muted-foreground mb-4">
          These state pages see the most traffic. Each links to a full age-group breakdown, and some have a deeper
          parent’s guide blog post alongside.
        </p>
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
          {POPULAR_STATES.map((state) => (
            <li key={state.code} className="flex flex-wrap items-baseline gap-x-2">
              <Link href={`/rankings/${state.code}`} className="text-primary hover:underline font-medium">
                {state.name} rankings &rarr;
              </Link>
              {state.hasGuide && (
                <Link
                  href={`/blog/${state.name.toLowerCase().replace(/ /g, '-')}-youth-soccer-rankings-guide`}
                  className="text-xs text-muted-foreground hover:text-primary"
                >
                  (parent’s guide)
                </Link>
              )}
            </li>
          ))}
        </ul>
      </section>

      {/* What makes these rankings different */}
      <section className="container mx-auto px-4 py-8 border-t border-border">
        <h2 className="text-2xl font-bold mb-4">What Makes PitchRank Different</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-sm">
          <div>
            <h3 className="font-semibold text-foreground mb-1">Real games, not polls</h3>
            <p className="text-muted-foreground">
              Most ranking sites rely on coach votes, recruiter opinions, or tournament-only results. PitchRank uses
              public game results — every league game, state cup match, showcase, and national tournament we can track.
            </p>
          </div>
          <div>
            <h3 className="font-semibold text-foreground mb-1">All 50 states, same rating scale</h3>
            <p className="text-muted-foreground">
              Most rankings are league- or state-specific. PitchRank rates teams on one national scale, so a U14 team in
              Texas and a U14 team in New Jersey can actually be compared. Cross-state results are rare but valuable —
              the algorithm uses them to anchor states to each other.
            </p>
          </div>
          <div>
            <h3 className="font-semibold text-foreground mb-1">Free to browse</h3>
            <p className="text-muted-foreground">
              Every ranking on PitchRank is free and does not require signing up. We believe parents should be able to
              check where their kid’s team stands without hitting a paywall.
            </p>
          </div>
          <div>
            <h3 className="font-semibold text-foreground mb-1">Updated every Monday</h3>
            <p className="text-muted-foreground">
              The season never stops, so the rankings shouldn’t either. Games played Friday through Sunday flow into the
              next week’s PowerScore. You can see the last-updated date on every page.
            </p>
          </div>
        </div>
      </section>

      {/* FAQ — rendered as matching dl; JSON-LD emitted separately in page.tsx */}
      <section className="container mx-auto px-4 py-8 border-t border-border">
        <h2 className="text-2xl font-bold mb-4">Frequently Asked Questions</h2>
        <dl className="divide-y divide-border/60">
          {rankingsPillarFaqItems.map((item) => (
            <div key={item.q} className="py-3 first:pt-0">
              <dt className="text-sm font-semibold text-foreground">{item.q}</dt>
              <dd className="text-sm text-muted-foreground mt-1 leading-relaxed">{item.a}</dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  );
}
