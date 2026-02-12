import { HowWeRank } from '@/components/HowWeRank';
import { FeatureShowcase } from '@/components/FeatureShowcase';
import { RecentMovers } from '@/components/RecentMovers';
import { HomeStats } from '@/components/HomeStats';
import Link from 'next/link';
import { Button } from '@/components/ui/button';

export default function Home() {
  return (
    <>
      {/* Hero Section - Athletic Editorial Style */}
      <div data-testid="hero-section" className="relative bg-gradient-to-br from-primary via-primary to-[oklch(0.28_0.08_163)] text-primary-foreground py-16 sm:py-24 overflow-hidden">
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
              Data-driven performance analytics for U10-U18 boys and girls nationwide
            </p>

            {/* Stats Row - Client component for reliable data fetching */}
            <HomeStats />

            <div className="flex flex-wrap gap-3">
              <Button data-testid="cta-rankings" size="lg" variant="secondary" asChild className="font-semibold uppercase tracking-wide">
                <Link href="/rankings">
                  View Rankings
                </Link>
              </Button>
              <Button data-testid="cta-methodology" size="lg" variant="outline" asChild className="font-semibold uppercase tracking-wide bg-transparent border-primary-foreground text-primary-foreground hover:bg-primary-foreground hover:text-primary">
                <Link href="/methodology">
                  Our Methodology
                </Link>
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
            <RecentMovers />
          </div>
        </div>
      </div>
    </>
  );
}
