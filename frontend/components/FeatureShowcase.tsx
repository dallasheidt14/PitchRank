import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import Link from 'next/link';
import { Swords, Star, MapPin, FileText, ChevronRight } from 'lucide-react';

interface FeatureCard {
  icon: React.ReactNode;
  title: string;
  description: string;
  href: string;
  cta: string;
  premium?: boolean;
}

const features: FeatureCard[] = [
  {
    icon: <Swords className="h-6 w-6" />,
    title: 'Compare & Predict',
    description: 'Head-to-head stats, win probabilities, and match predictions powered by ML.',
    href: '/compare',
    cta: 'Compare Teams',
    premium: true,
  },
  {
    icon: <Star className="h-6 w-6" />,
    title: 'Build Your Watchlist',
    description: 'Track your favorite teams and monitor their ranking changes over time.',
    href: '/watchlist',
    cta: 'Start Tracking',
    premium: true,
  },
  {
    icon: <MapPin className="h-6 w-6" />,
    title: 'State Rankings',
    description: 'Explore rankings for all 50 states. Find the best teams in your area.',
    href: '/rankings',
    cta: 'Explore States',
  },
  {
    icon: <FileText className="h-6 w-6" />,
    title: 'Free Team Report Card',
    description: "Your team's national and state rank, PowerScore, record and last 5 games, as a free PDF.",
    href: '/report-card',
    cta: 'Get the Report Card',
  },
];

/**
 * FeatureShowcase component - Grid of feature cards highlighting key platform capabilities
 */
export function FeatureShowcase() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
      {features.map((feature) => (
        <Card
          key={feature.title}
          variant="primary"
          className="group hover:border-l-accent transition-colors overflow-hidden"
        >
          <CardContent className="p-4 sm:p-5">
            <div className="flex items-start gap-3 sm:gap-4">
              {/* Icon */}
              <div className="flex-shrink-0 w-10 h-10 sm:w-12 sm:h-12 rounded-lg bg-primary/10 flex items-center justify-center text-primary group-hover:bg-accent group-hover:text-accent-foreground transition-colors duration-300">
                {feature.icon}
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mb-1">
                  <h3 className="font-display font-bold text-sm sm:text-base uppercase tracking-wide text-foreground group-hover:text-primary transition-colors">
                    {feature.title}
                  </h3>
                  {feature.premium && <Badge variant="secondary">PitchRank+</Badge>}
                </div>
                <p className="text-xs sm:text-sm text-muted-foreground leading-relaxed mb-3">{feature.description}</p>
                <Button
                  variant="outline"
                  size="sm"
                  asChild
                  className="text-xs font-semibold uppercase tracking-wide group-hover:bg-accent group-hover:text-accent-foreground group-hover:border-accent transition-colors"
                >
                  <Link href={feature.href}>
                    {feature.cta}
                    <ChevronRight className="ml-1 h-3 w-3" />
                  </Link>
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
