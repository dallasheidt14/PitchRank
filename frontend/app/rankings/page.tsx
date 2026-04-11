import type { Metadata } from 'next';
import Link from 'next/link';
import { RankingsPageContent } from '@/components/RankingsPageContent';
import { BASE_URL, US_STATES } from '@/lib/constants';

/**
 * Rankings landing page — server component for SEO.
 * Delegates all interactivity to RankingsPageContent (client component).
 * Default view: national, U12, male — matches the most common search intent.
 */

export const metadata: Metadata = {
  title: '2026 Youth Soccer Rankings by State & Age Group',
  description:
    'Where does your team rank? 77K+ youth soccer teams rated weekly by PowerScore. Browse rankings by state, age group U10-U19, boys and girls. Free.',
  alternates: {
    canonical: `${BASE_URL}/rankings`,
  },
  openGraph: {
    title: '2026 Youth Soccer Rankings by State & Age Group | PitchRank',
    description:
      'Where does your team rank? 77K+ youth soccer teams rated weekly by PowerScore. Browse rankings by state, age group U10-U19, boys and girls. Free.',
    url: `${BASE_URL}/rankings`,
    siteName: 'PitchRank',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: '2026 Youth Soccer Rankings by State & Age Group | PitchRank',
    description:
      'Where does your team rank? 77K+ youth soccer teams rated weekly by PowerScore. Browse rankings by state, age group U10-U19, boys and girls. Free.',
  },
};

const rankingsSchema = {
  '@context': 'https://schema.org',
  '@type': 'CollectionPage',
  name: 'Youth Soccer Rankings',
  description:
    'Comprehensive youth soccer rankings across all 50 states, covering 77,000+ teams in every age group from U10 to U19. Updated weekly with real game results.',
  url: `${BASE_URL}/rankings`,
};

export default function RankingsPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(rankingsSchema).replace(/</g, '\\u003c') }}
      />
      {/* Server-rendered H1 and intro for SEO — appears before client component */}
      <section className="container mx-auto px-4 pt-8 pb-4">
        <h1 className="font-display text-3xl font-bold uppercase tracking-wide mb-2">
          Youth Soccer Rankings — 77,000+ Teams Ranked Weekly
        </h1>
        <p className="text-muted-foreground text-sm mb-6">
          Where does your team rank? PitchRank rates youth soccer teams across all 50 states using a 13-layer algorithm
          built on real game results. Browse rankings by state and age group, from U10 through U19, for both boys and
          girls. Rankings update every Monday — free, data-driven, no bias.
        </p>
      </section>

      <RankingsPageContent region="national" ageGroup="u12" gender="male" />

      {/* Browse by State — server-rendered for Googlebot crawlability */}
      <section className="container mx-auto px-4 pb-8 border-t border-border pt-8 mt-4">
        <h2 className="text-xl font-bold mb-4">Browse Rankings by State</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
          <Link
            href="/rankings/national"
            className="px-3 py-1.5 bg-primary text-primary-foreground rounded text-sm hover:bg-primary/90"
          >
            National
          </Link>
          {US_STATES.map((state) => (
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
    </>
  );
}
