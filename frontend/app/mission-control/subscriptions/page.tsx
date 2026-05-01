import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { getSubscriptionMetrics } from '@/lib/admin/subscription-metrics';

// Admin gate is enforced by frontend/middleware.ts (ADMIN_ROUTES).
export const dynamic = 'force-dynamic';
export const metadata = { robots: { index: false, follow: false } };

function formatDollars(n: number): string {
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export default async function SubscriptionsDashboardPage() {
  const metrics = await getSubscriptionMetrics();

  return (
    <div className="min-h-screen bg-background">
      <div className="container mx-auto space-y-8 p-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="space-y-2">
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <Link href="/mission-control" className="hover:text-foreground">
                Mission Control
              </Link>
              <span>/</span>
              <span>Subscriptions</span>
            </div>
            <h1 className="font-display text-3xl font-bold tracking-tight">Subscriptions</h1>
            <p className="text-sm text-muted-foreground">
              As of {new Date(metrics.generatedAt).toLocaleString('en-US')}
            </p>
          </div>
          <Link href="/mission-control/subscriptions">
            <Button variant="outline" size="sm">
              Refresh
            </Button>
          </Link>
        </div>

        {metrics.errors.length > 0 && (
          <Card variant="accent" className="border-l-destructive">
            <CardHeader>
              <CardTitle className="text-destructive">Some data failed to load</CardTitle>
              <CardDescription>
                {metrics.errors.length} section{metrics.errors.length === 1 ? '' : 's'} returned an error. The rest of
                the dashboard reflects what loaded successfully.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                {metrics.errors.map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label="MRR"
            value={formatDollars(metrics.mrr)}
            sub={`from ${metrics.activePaid.total} active sub${metrics.activePaid.total === 1 ? '' : 's'}`}
          />
          <KpiCard
            label="Active Paid"
            value={metrics.activePaid.total.toString()}
            sub={`${metrics.activePaid.monthly} monthly · ${metrics.activePaid.annual} annual`}
          />
          <KpiCard
            label="Active Trials"
            value={metrics.trials.total.toString()}
            sub={metrics.trials.total === 0 ? 'no trials in flight' : 'in flight now'}
          />
          <KpiCard
            label="Trials Ending ≤7d"
            value={metrics.trials.endingIn7Days.toString()}
            sub={`${metrics.trials.endingIn3Days} in next 3d`}
            emphasize={metrics.trials.endingIn7Days > 0}
          />
        </div>

        <section className="space-y-3">
          <div className="flex items-baseline justify-between">
            <h2 className="font-display text-xl font-semibold">Attention Needed</h2>
            <span className="text-sm text-muted-foreground">
              {metrics.pastDue.total} past_due {metrics.pastDue.total === 1 ? 'subscription' : 'subscriptions'}{' '}
              (excluded from MRR)
            </span>
          </div>
          <Card variant="flat">
            <CardContent className="p-0">
              {metrics.pastDue.list.length === 0 ? (
                <div className="p-6 text-sm text-muted-foreground">No past_due subscriptions. All clear.</div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Customer</TableHead>
                      <TableHead>Plan</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {metrics.pastDue.list.map((row) => (
                      <TableRow key={row.id}>
                        <TableCell>{row.email}</TableCell>
                        <TableCell className="capitalize">{row.interval === 'year' ? 'Annual' : 'Monthly'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </section>

        <section className="space-y-3">
          <div className="flex items-baseline justify-between">
            <h2 className="font-display text-xl font-semibold">Trial Pipeline</h2>
            <span className="text-sm text-muted-foreground">sorted by soonest end</span>
          </div>
          <Card variant="flat">
            <CardContent className="p-0">
              {metrics.trials.list.length === 0 ? (
                <div className="p-6 text-sm text-muted-foreground">No active trials.</div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Customer</TableHead>
                      <TableHead>Trial ends</TableHead>
                      <TableHead>Days</TableHead>
                      <TableHead>Plan</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {metrics.trials.list.map((row) => (
                      <TableRow key={row.id}>
                        <TableCell>{row.email}</TableCell>
                        <TableCell>{formatDate(row.trialEnd)}</TableCell>
                        <TableCell className={row.daysRemaining <= 3 ? 'font-semibold text-destructive' : ''}>
                          {row.daysRemaining}
                        </TableCell>
                        <TableCell>{row.interval === 'year' ? 'Annual' : 'Monthly'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </section>

        <section className="space-y-3">
          <h2 className="font-display text-xl font-semibold">Conversion · 30-day rolling</h2>
          <Card variant="flat">
            <CardContent className="py-6">
              {metrics.conversion.percent === null ? (
                <p className="text-sm text-muted-foreground">
                  Not enough data yet. {metrics.conversion.sample} trial
                  {metrics.conversion.sample === 1 ? '' : 's'} completed in the cohort window (need ≥5 to compute).
                </p>
              ) : (
                <div className="space-y-1">
                  <div className="font-display text-4xl font-bold">{metrics.conversion.percent}%</div>
                  <p className="text-sm text-muted-foreground">
                    {metrics.conversion.converted} of {metrics.conversion.sample} trials started 31–60 days ago are now
                    active.
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </section>
      </div>
    </div>
  );
}

function KpiCard({
  label,
  value,
  sub,
  emphasize = false,
}: {
  label: string;
  value: string;
  sub: string;
  emphasize?: boolean;
}) {
  return (
    <Card variant={emphasize ? 'primary' : 'default'}>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="font-display text-3xl">{value}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">{sub}</p>
      </CardContent>
    </Card>
  );
}
