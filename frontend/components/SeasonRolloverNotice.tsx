import { ArrowRight } from 'lucide-react';

/**
 * SeasonRolloverNotice - Temporary homepage banner explaining the 2026-27 shift
 * from birth-year cohorts to the Aug 1 - Jul 31 age-group window.
 *
 * Remove once the new season's results have settled the boards (target: Oct 2026).
 */
export function SeasonRolloverNotice() {
  return (
    <section
      data-testid="season-rollover-notice"
      aria-labelledby="season-rollover-heading"
      className="relative border-y border-border bg-muted/50 overflow-hidden"
    >
      <div className="absolute left-0 top-0 h-full w-2 bg-accent lg:-skew-x-12" aria-hidden="true" />

      <div className="container mx-auto px-4 sm:px-6 py-8 sm:py-10">
        <div className="grid gap-8 lg:grid-cols-[1fr_auto] lg:items-center motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-500">
          <div className="max-w-2xl">
            <p className="font-semibold uppercase tracking-widest text-xs text-muted-foreground mb-2">
              Note from the team
            </p>
            <h2
              id="season-rollover-heading"
              className="font-display text-2xl sm:text-3xl font-bold uppercase leading-tight mb-3"
            >
              We&apos;ve moved to age groups
            </h2>
            <p className="text-base leading-relaxed mb-3">
              US youth soccer now runs on an August 1 &ndash; July 31 window, so every team has moved up one group. We
              carried each team&apos;s history over from last season to keep the rankings steady through the switch.
            </p>
            <p className="text-base leading-relaxed text-muted-foreground">
              Expect the next 30&ndash;60 days to be rockier than you&apos;re used to. As this season&apos;s games come
              in, the cream rises back to the top.
            </p>
            <p className="mt-4 text-sm font-semibold uppercase tracking-wide">
              Onward and upward. <span className="text-muted-foreground">&mdash; The PitchRank Team</span>
            </p>
          </div>

          <div className="flex items-center gap-4 lg:gap-5 lg:border-l lg:border-border lg:pl-10">
            <div>
              <p className="text-xs uppercase tracking-widest text-muted-foreground mb-1">Was</p>
              <p className="font-display text-3xl sm:text-4xl font-bold leading-none">2014</p>
              <p className="text-xs text-muted-foreground mt-1">birth year</p>
            </div>
            <ArrowRight className="h-6 w-6 text-accent shrink-0" aria-hidden="true" />
            <div>
              <p className="text-xs uppercase tracking-widest text-muted-foreground mb-1">Now</p>
              <p className="font-display text-3xl sm:text-4xl font-bold leading-none text-primary">U13</p>
              <p className="text-xs text-muted-foreground mt-1">age group</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
