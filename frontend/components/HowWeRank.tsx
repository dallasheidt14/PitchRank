import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import Link from 'next/link';
import { Scale, Layers, TrendingUp, Shield, ChevronRight } from 'lucide-react';

interface MethodologyPoint {
  icon: React.ReactNode;
  title: string;
  description: string;
  detail: string;
}

const methodologyPoints: MethodologyPoint[] = [
  {
    icon: <Scale className="h-6 w-6" />,
    title: 'Schedule Strength First',
    description: 'Your opponents matter more than your record',
    detail: 'SOS accounts for 50% of power score. Beat strong teams to rise—padding records against weak opponents won\'t help.',
  },
  {
    icon: <Layers className="h-6 w-6" />,
    title: 'Cross-Age Intelligence',
    description: 'Unified rankings across U10-U18',
    detail: 'Age-anchored power scaling lets us fairly evaluate cross-age matchups. When U13 plays U14, both teams get proper credit.',
  },
  {
    icon: <TrendingUp className="h-6 w-6" />,
    title: 'ML Trend Detection',
    description: 'We catch rising teams early',
    detail: 'Machine learning analyzes game residuals to identify teams consistently overperforming expectations—before the standings show it.',
  },
  {
    icon: <Shield className="h-6 w-6" />,
    title: 'Stability by Design',
    description: 'No wild swings from one game',
    detail: 'Bayesian shrinkage, outlier clipping, and exponential decay prevent single results from derailing accurate rankings.',
  },
];

/**
 * HowWeRank component - Showcases what makes PitchRank's methodology unique
 * Focuses on key differentiators: SOS-first, cross-age, ML detection, stability
 */
export function HowWeRank() {
  return (
    <Card className="overflow-hidden border-0 shadow-lg">
      <CardHeader className="bg-gradient-to-r from-primary to-[oklch(0.28_0.08_165)] text-primary-foreground relative overflow-hidden">
        <div className="absolute right-0 top-0 w-2 h-full bg-accent -skew-x-12" aria-hidden="true" />
        <CardTitle className="text-2xl sm:text-3xl font-display font-bold uppercase tracking-wide">
          Why Our Rankings Are Different
        </CardTitle>
        <p className="text-primary-foreground/80 text-sm sm:text-base">
          Built to be accurate, not gameable
        </p>
      </CardHeader>
      <CardContent className="p-4 sm:p-6">
        {/* Methodology Points */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {methodologyPoints.map((point, index) => (
            <div
              key={point.title}
              className="group relative p-4 rounded-lg bg-secondary/40 hover:bg-secondary/60 border border-transparent hover:border-primary/20 transition-all duration-300"
            >
              {/* Step number badge */}
              <div className="absolute -top-2 -left-2 w-5 h-5 sm:w-6 sm:h-6 rounded-full bg-accent text-accent-foreground text-[10px] sm:text-xs font-bold flex items-center justify-center shadow-sm">
                {index + 1}
              </div>

              <div className="flex gap-3 sm:gap-4">
                {/* Icon */}
                <div className="flex-shrink-0 w-10 h-10 sm:w-12 sm:h-12 rounded-lg bg-primary/10 flex items-center justify-center text-primary group-hover:bg-primary group-hover:text-primary-foreground transition-colors">
                  {point.icon}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <h3 className="font-display font-bold text-sm sm:text-base uppercase tracking-wide text-foreground mb-0.5">
                    {point.title}
                  </h3>
                  <p className="text-xs sm:text-sm font-medium text-primary mb-1.5">
                    {point.description}
                  </p>
                  <p className="text-[11px] sm:text-xs text-muted-foreground leading-relaxed">
                    {point.detail}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Learn More CTA */}
        <div className="mt-5 sm:mt-6 text-center">
          <Button
            variant="outline"
            size="sm"
            asChild
            className="font-semibold uppercase tracking-wide text-xs sm:text-sm hover:bg-accent hover:text-accent-foreground hover:border-accent transition-colors"
          >
            <Link href="/methodology">
              Explore Full Methodology
              <ChevronRight className="ml-1 h-4 w-4" />
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
