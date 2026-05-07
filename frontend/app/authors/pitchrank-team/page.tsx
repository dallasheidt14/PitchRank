import { PageHeader } from '@/components/PageHeader';
import { BreadcrumbSchema } from '@/components/BreadcrumbSchema';
import { AuthorEntitySchema } from '@/components/AuthorEntitySchema';
import type { Metadata } from 'next';
import { BASE_URL, PITCHRANK_TEAM_AUTHOR_PATH } from '@/lib/constants';

export const metadata: Metadata = {
  title: 'PitchRank Team',
  description:
    'Meet the PitchRank Team — the people behind the youth soccer ranking platform that publishes weekly rankings, methodology, and guides for U10–U19 teams across all 50 states.',
  alternates: {
    canonical: `${BASE_URL}${PITCHRANK_TEAM_AUTHOR_PATH}`,
  },
  openGraph: {
    title: 'PitchRank Team | PitchRank',
    description:
      'Meet the PitchRank Team — the people behind PitchRank.io and the rankings, methodology, and guides published on the site.',
    url: `${BASE_URL}${PITCHRANK_TEAM_AUTHOR_PATH}`,
    siteName: 'PitchRank',
    type: 'website',
    images: [
      {
        url: '/logos/pitchrank-wordmark.svg',
        width: 1200,
        height: 630,
        alt: 'PitchRank Team',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'PitchRank Team | PitchRank',
    description: 'The team behind PitchRank.io youth soccer rankings, methodology, and guides.',
    images: ['/logos/pitchrank-wordmark.svg'],
  },
};

export default function PitchRankTeamPage() {
  return (
    <div className="container mx-auto py-8 px-4">
      <BreadcrumbSchema items={[{ name: 'PitchRank Team', href: PITCHRANK_TEAM_AUTHOR_PATH }]} />
      <AuthorEntitySchema />
      <PageHeader
        title="PitchRank Team"
        description="The team behind PitchRank's youth soccer rankings, methodology, and guides."
        showBackButton
        backHref="/"
      />

      <div className="max-w-4xl mx-auto">
        <div className="space-y-6">
          <p className="text-muted-foreground leading-relaxed">
            PitchRank is built by a small team focused on bringing transparent, data-first rankings to youth soccer. We
            collect verified game results, run them through a rating engine that weighs opponent quality, schedule
            strength, and recent form, then publish weekly rankings for every age group across all 50 states.
          </p>
          <p className="text-muted-foreground leading-relaxed">
            The platform combines a core rating algorithm with a machine-learning layer that flags teams trending up or
            down based on performance versus expectations. Rankings refresh every Monday morning so coaches, parents,
            and players see how their team stacks up against the rest of the country — not just their local league.
          </p>
          <p className="text-muted-foreground leading-relaxed">
            The PitchRank Team writes the methodology, blog, and state guides published on this site. We are based in
            Arizona and built the platform after years of frustration with the lack of objective, cross-state
            comparisons in youth club soccer.
          </p>
        </div>
      </div>
    </div>
  );
}
