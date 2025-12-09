import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import Link from 'next/link';
import { Database, Shuffle, Brain, Trophy, ChevronRight } from 'lucide-react';

interface ProcessStep {
  icon: React.ReactNode;
  title: string;
  stat: string;
  description: string;
}

const processSteps: ProcessStep[] = [
  {
    icon: <Database className="h-7 w-7" />,
    title: 'Data Collection',
    stat: '16,000+',
    description: 'Games analyzed from providers nationwide',
  },
  {
    icon: <Shuffle className="h-7 w-7" />,
    title: 'Smart Matching',
    stat: '2,800+',
    description: 'Teams unified via fuzzy matching',
  },
  {
    icon: <Brain className="h-7 w-7" />,
    title: 'ML Scoring',
    stat: '0-100',
    description: 'Power scores with SOS adjustments',
  },
  {
    icon: <Trophy className="h-7 w-7" />,
    title: 'Weekly Rankings',
    stat: '50',
    description: 'States with national rankings',
  },
];

/**
 * HowWeRank component - Visual process flow explaining the ranking methodology
 * Shows 4 steps: Data Collection → Smart Matching → ML Scoring → Weekly Rankings
 */
export function HowWeRank() {
  return (
    <Card className="overflow-hidden border-0 shadow-lg">
      <CardHeader className="bg-gradient-to-r from-primary to-[oklch(0.28_0.08_165)] text-primary-foreground relative overflow-hidden">
        <div className="absolute right-0 top-0 w-2 h-full bg-accent -skew-x-12" aria-hidden="true" />
        <CardTitle className="text-2xl sm:text-3xl font-display font-bold uppercase tracking-wide">
          How We Rank
        </CardTitle>
        <p className="text-primary-foreground/80 text-sm sm:text-base">
          Data-driven methodology for accurate youth soccer rankings
        </p>
      </CardHeader>
      <CardContent className="p-4 sm:p-6">
        {/* Process Flow */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          {processSteps.map((step, index) => (
            <div key={step.title} className="relative group">
              {/* Connector chevron (hidden on last item and small screens) */}
              {index < processSteps.length - 1 && (
                <div className="hidden lg:flex absolute -right-2 top-1/2 -translate-y-1/2 translate-x-1/2 z-10 w-4 h-4 items-center justify-center">
                  <ChevronRight className="h-4 w-4 text-primary/40" />
                </div>
              )}

              <div className="relative flex flex-col items-center text-center p-3 sm:p-4 rounded-lg bg-secondary/40 hover:bg-secondary/60 border border-transparent hover:border-primary/20 transition-all duration-300 h-full">
                {/* Step number badge */}
                <div className="absolute -top-2 -left-2 w-5 h-5 sm:w-6 sm:h-6 rounded-full bg-accent text-accent-foreground text-[10px] sm:text-xs font-bold flex items-center justify-center shadow-sm">
                  {index + 1}
                </div>

                {/* Icon */}
                <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-full bg-primary/10 flex items-center justify-center text-primary mb-2 sm:mb-3 group-hover:bg-primary/15 transition-colors">
                  {step.icon}
                </div>

                {/* Stat */}
                <div className="font-mono text-xl sm:text-2xl font-bold text-primary mb-0.5">
                  {step.stat}
                </div>

                {/* Title */}
                <h3 className="font-display font-semibold text-xs sm:text-sm uppercase tracking-wide mb-1 sm:mb-2 text-foreground">
                  {step.title}
                </h3>

                {/* Description */}
                <p className="text-[10px] sm:text-xs text-muted-foreground leading-relaxed">
                  {step.description}
                </p>
              </div>
            </div>
          ))}
        </div>

        {/* Learn More CTA */}
        <div className="mt-4 sm:mt-6 text-center">
          <Button variant="outline" size="sm" asChild className="font-semibold uppercase tracking-wide text-xs sm:text-sm hover:bg-accent hover:text-accent-foreground hover:border-accent transition-colors">
            <Link href="/methodology">
              Learn More About Our Methodology
              <ChevronRight className="ml-1 h-4 w-4" />
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
