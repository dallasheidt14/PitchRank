import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { getSubscriptionMetrics } from '@/lib/admin/subscription-metrics';

// Admin gate is enforced by frontend/middleware.ts (ADMIN_ROUTES).
export const dynamic = 'force-dynamic';
export const metadata = { robots: { index: false, follow: false } };

function formatDollars(n: number): string {
  return n.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatRelative(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  const diffMo = Math.floor(diffDay / 30);
  return `${diffMo}mo ago`;
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
            sub={
              metrics.trials.canceledPending > 0
                ? `+${metrics.trials.canceledPending} canceled (won't renew)`
                : metrics.trials.total === 0
                  ? 'no trials in flight'
                  : 'in flight now'
            }
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
            <span className="text-sm text-muted-foreground">
              sorted by soonest end · canceled trials hidden
              {metrics.trials.canceledPending > 0 && ` (${metrics.trials.canceledPending} not shown)`}
            </span>
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
          <h2 className="font-display text-xl font-semibold">Conversion · last {metrics.conversion.windowDays} days</h2>
          <Card variant="flat">
            <CardContent className="py-6">
              {metrics.conversion.percent === null ? (
                <p className="text-sm text-muted-foreground">
                  Not enough data yet. {metrics.conversion.sample} completed trial
                  {metrics.conversion.sample === 1 ? '' : 's'} in the last {metrics.conversion.windowDays} days (need ≥5
                  to compute).
                  {metrics.conversion.excluded > 0 &&
                    ` ${metrics.conversion.excluded} test/internal user${metrics.conversion.excluded === 1 ? '' : 's'} excluded.`}
                </p>
              ) : (
                <div className="space-y-1">
                  <div className="font-display text-4xl font-bold">{metrics.conversion.percent}%</div>
                  <p className="text-sm text-muted-foreground">
                    {metrics.conversion.converted} of {metrics.conversion.sample} completed trials in the last{' '}
                    {metrics.conversion.windowDays} days are now paying (active or past_due). Trials still in flight are
                    excluded.
                    {metrics.conversion.excluded > 0 &&
                      ` ${metrics.conversion.excluded} test/internal user${metrics.conversion.excluded === 1 ? '' : 's'} excluded.`}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </section>

        <section className="space-y-3">
          <div className="flex items-baseline justify-between">
            <h2 className="font-display text-xl font-semibold">Report Card Leads</h2>
            <span className="text-sm text-muted-foreground">
              latest {metrics.reportCard.recentLeads.length} of {metrics.reportCard.totalRequests.toLocaleString()}{' '}
              requests
            </span>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-5">
            <KpiCard label="Total Requests" value={metrics.reportCard.totalRequests.toLocaleString()} sub="all time" />
            <KpiCard
              label="Unique Emails"
              value={metrics.reportCard.uniqueEmails.toLocaleString()}
              sub="distinct addresses"
            />
            <KpiCard
              label="Last 7 Days"
              value={metrics.reportCard.last7Days.toLocaleString()}
              sub={`${metrics.reportCard.last30Days.toLocaleString()} in last 30d`}
            />
            <KpiCard
              label="Lead → Trial"
              value={
                metrics.reportCard.trialConversion.percent === null
                  ? '—'
                  : `${metrics.reportCard.trialConversion.percent}%`
              }
              sub={
                metrics.reportCard.trialConversion.percent === null
                  ? `not enough data yet (${metrics.reportCard.trialConversion.leads} lead${metrics.reportCard.trialConversion.leads === 1 ? '' : 's'}, need ≥5)`
                  : `${metrics.reportCard.trialConversion.trialed} of ${metrics.reportCard.trialConversion.leads} leads started a trial${metrics.reportCard.trialConversion.excluded > 0 ? ` (${metrics.reportCard.trialConversion.excluded} excluded)` : ''}`
              }
            />
            <KpiCard
              label="Lead → Paid"
              value={metrics.reportCard.conversion.percent === null ? '—' : `${metrics.reportCard.conversion.percent}%`}
              sub={
                metrics.reportCard.conversion.percent === null
                  ? `not enough data yet (${metrics.reportCard.conversion.leads} lead${metrics.reportCard.conversion.leads === 1 ? '' : 's'}, need ≥5)`
                  : `${metrics.reportCard.conversion.converted} of ${metrics.reportCard.conversion.leads} leads now paying${metrics.reportCard.conversion.excluded > 0 ? ` (${metrics.reportCard.conversion.excluded} excluded)` : ''}`
              }
            />
          </div>

          <Card variant="flat">
            <CardContent className="p-0">
              {metrics.reportCard.recentLeads.length === 0 ? (
                <div className="p-6 text-sm text-muted-foreground">No report card requests yet.</div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Email</TableHead>
                      <TableHead>Team</TableHead>
                      <TableHead>Role</TableHead>
                      <TableHead>When</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {metrics.reportCard.recentLeads.map((lead) => (
                      <TableRow key={lead.id}>
                        <TableCell>{lead.email}</TableCell>
                        <TableCell>
                          <Link href={`/teams/${lead.teamId}`} className="hover:underline">
                            {lead.teamName}
                          </Link>
                        </TableCell>
                        <TableCell className="text-muted-foreground">{lead.role ?? '—'}</TableCell>
                        <TableCell className="text-muted-foreground">{formatRelative(lead.createdAt)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
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
