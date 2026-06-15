import { HowWeRank } from '@/components/HowWeRank';
import { FeatureShowcase } from '@/components/FeatureShowcase';
import { RecentMovers } from '@/components/RecentMovers';
import { HomeStats } from '@/components/HomeStats';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { selectTopMovers } from '@/lib/movers';
import type { RankingRow } from '@/types/RankingRow';

// Revalidate hourly so above-the-fold stats and movers are server-rendered
// rather than fetched on the client after first paint.
export const revalidate = 3600;

export default async function Home() {
  // Fetch above-the-fold data server-side; degrade to fallbacks on failure so a
  // Supabase hiccup never breaks the static render. Stats (a cheap cached read)
  // and movers (a heavy national-cohort scan that can hit the anon statement
  // timeout during the bulk static build) are fetched independently so a movers
  // failure can't blank the stats.
  let totalGames: number | undefined;
  let totalTeams: number | undefined;
  let movers7d: RankingRow[] = [];
  let movers30d: RankingRow[] = [];

  try {
    const stats = await api.getDbStats();
    totalGames = stats.totalGames;
    totalTeams = stats.totalTeams;
  } catch (e) {
    console.error('[home] stats fetch failed, using fallbacks:', e);
  }

  try {
    const national = await api.getRankings(null, 'u12', 'M');
    movers7d = selectTopMovers(national, '7d', 5);
    movers30d = selectTopMovers(national, '30d', 5);
  } catch (e) {
    console.error('[home] movers fetch failed, using empty lists:', e);
  }

  return (
    <>
      {/* Hero Section - Athletic Editorial Style */}
      <div
        data-testid="hero-section"
        className="relative bg-gradient-to-br from-primary via-primary to-[oklch(0.28_0.08_163)] text-primary-foreground py-16 sm:py-24 overflow-hidden"
      >
        {/* Diagonal stripe pattern overlay */}
        <div className="absolute inset-0 bg-diagonal-stripes opacity-50" aria-hidden="true" />
        {/* Diagonal slash accent */}
        <div className="absolute left-0 top-0 w-3 h-full bg-accent -skew-x-12" aria-hidden="true" />

        <div className="container mx-auto px-4 sm:px-6 relative">
          <div className="max-w-4xl">
            <h1 className="font-display text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-bold uppercase leading-tight mb-4">
              <span className="text-gradient-athletic">America&apos;s</span>{' '}
              <span className="relative inline-block">
                <span className="text-accent">Definitive</span>
                <span className="absolute bottom-0 left-0 w-full h-1 sm:h-1.5 bg-accent" aria-hidden="true" />
              </span>
              <br />
              <span className="text-gradient-athletic">Youth Soccer Rankings</span>
            </h1>
            <p className="text-lg sm:text-xl md:text-2xl font-light tracking-wide mb-8">
              Data-driven performance analytics for U10-U19 boys and girls nationwide
            </p>

            {/* Stats Row - server-rendered for fast first paint */}
            <HomeStats totalGames={totalGames} totalTeams={totalTeams} />

            <div className="flex flex-wrap gap-3">
              <Button
                data-testid="cta-rankings"
                size="lg"
                variant="secondary"
                asChild
                className="font-semibold uppercase tracking-wide"
              >
                <Link href="/rankings">View Rankings</Link>
              </Button>
              <Button
                data-testid="cta-report-card"
                size="lg"
                asChild
                className="font-semibold uppercase tracking-wide bg-accent text-primary hover:bg-accent/90"
              >
                <Link href="/report-card">Free Team Report Card</Link>
              </Button>
              <Button
                data-testid="cta-methodology"
                size="lg"
                variant="outline"
                asChild
                className="font-semibold uppercase tracking-wide bg-transparent border-primary-foreground text-primary-foreground hover:bg-primary-foreground hover:text-primary"
              >
                <Link href="/methodology">Our Methodology</Link>
              </Button>
            </div>
          </div>
        </div>

        {/* Decorative gradient overlay */}
        <div className="absolute bottom-0 left-0 right-0 h-24 bg-gradient-to-t from-background to-transparent pointer-events-none" />
      </div>

      {/* Main Content */}
      <div className="container mx-auto py-8 sm:py-12 px-4 sm:px-6">
        <div className="grid gap-6 lg:grid-cols-3">
          {/* Main Column - How We Rank (takes 2 columns) */}
          <div className="lg:col-span-2 space-y-6">
            <HowWeRank />
            <FeatureShowcase />
          </div>

          {/* Sidebar Column */}
          <div className="space-y-6">
            <RecentMovers initialMovers7d={movers7d} initialMovers30d={movers30d} />
          </div>
        </div>
      </div>
    </>
  );
}
