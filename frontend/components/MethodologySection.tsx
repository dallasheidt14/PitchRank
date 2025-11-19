import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { FAQSchema } from '@/components/FAQSchema';

/**
 * MethodologySection component - explains the ranking methodology
 * This is a placeholder component for Phase 2
 */
export function MethodologySection() {
  return (
    <>
      <FAQSchema />
      <div className="space-y-6">
        <Card>
        <CardHeader>
          <CardTitle>Ranking Methodology</CardTitle>
          <CardDescription>
            How PitchRank calculates team rankings and power scores
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <h3 className="text-lg font-semibold mb-2">Power Score Calculation</h3>
            <p className="text-muted-foreground">
              Our power score algorithm considers multiple factors including win percentage, 
              strength of schedule, goals for/against, and recent performance trends.
            </p>
          </div>
          <div>
            <h3 className="text-lg font-semibold mb-2">Data Sources</h3>
            <p className="text-muted-foreground">
              Rankings are calculated from verified game results across multiple youth soccer 
              leagues and competitions. Data is updated weekly.
            </p>
          </div>
          <div>
            <h3 className="text-lg font-semibold mb-2">Age Groups & Regions</h3>
            <p className="text-muted-foreground">
              Teams are ranked within their specific age group (U10, U11, etc.) and gender. 
              Regional rankings are available for state-level comparisons.
            </p>
          </div>
          <p className="mt-4 text-sm text-muted-foreground italic">
            Detailed methodology documentation will be added in Phase 3
          </p>
        </CardContent>
      </Card>
      </div>
    </>
  );
}

