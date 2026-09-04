import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { getSubscriptionMetrics } from '@/lib/admin/subscription-metrics';
import { describeRate } from '@/lib/admin/month-projection';

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

function formatCount(n: number): string {
  return n.toLocaleString('en-US', { maximumFractionDigits: 1 });
}

function signedCount(n: number): string {
  return `${n >= 0 ? '+' : '−'}${formatCount(Math.abs(n))}`;
}

function signedDollars(n: number): string {
  return `${n >= 0 ? '+' : '−'}${formatDollars(Math.abs(n))}`;
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
  const projection = metrics.monthProjection;

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
            <h2 className="font-display text-xl font-semibold">Month Projection</h2>
            <span className="text-sm text-muted-foreground">
              {projection.available
                ? `day ${projection.trials.daysElapsed} of ${projection.trials.daysInMonth} · measured from paid invoices`
                : 'could not be loaded'}
            </span>
          </div>
          {!projection.available ? (
            <Card variant="flat">
              <CardContent className="p-6 text-sm text-muted-foreground">
                Stripe did not return the data this projection is built from, so there is nothing to show. Rendering the
                figures anyway would put plausible-looking zeros under a heading that says they could not be loaded. The
                error is listed above.
              </CardContent>
            </Card>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
                <KpiCard
                  label="Projected Trials"
                  value={formatCount(Math.round(projection.trials.projected))}
                  sub={`${projection.trials.trialsToDate} so far · ${projection.trials.dailyRate.toFixed(2)}/day · range ${Math.round(projection.trials.low)}–${Math.round(projection.trials.high)}`}
                />
                <KpiCard
                  label="New Subs This Month"
                  value={formatCount(projection.grossNewSubs)}
                  sub={`from ${formatCount(projection.trials.landedConverted + projection.trials.landingUnresolved)} trials ending inside this month`}
                />
                <KpiCard
                  label="Net MRR Change"
                  value={signedDollars(projection.netMrr)}
                  sub={`${signedCount(projection.netSubs)} net subscribers`}
                  emphasize={projection.netMrr > 0}
                />
                <KpiCard
                  label="LTV"
                  value={projection.ltv === null ? '—' : formatDollars(projection.ltv)}
                  sub={
                    projection.avgLifetimeMonths === null
                      ? 'not measurable — nobody in the cohort has churned'
                      : `${projection.avgLifetimeMonths.toFixed(1)} month lifetime, first-month churn basis`
                  }
                />
              </div>

              <Card variant="flat">
                <CardContent className="p-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Lands inside this month</TableHead>
                        <TableHead className="text-right">Subscribers</TableHead>
                        <TableHead className="text-right">MRR</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      <TableRow>
                        <TableCell>
                          Gross new
                          <span className="ml-2 text-xs text-muted-foreground">
                            {formatCount(projection.trials.landedConverted)} already converted
                          </span>
                        </TableCell>
                        <TableCell className="text-right">{signedCount(projection.grossNewSubs)}</TableCell>
                        <TableCell className="text-right">{signedDollars(projection.grossNewMrr)}</TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell>
                          Churned
                          <span className="ml-2 text-xs text-muted-foreground">
                            {formatCount(projection.observedChurn)} already cancelled
                            {projection.annualRenewalsAhead > 0 &&
                              ` · ${projection.annualRenewalsAhead} annual renewal${projection.annualRenewalsAhead === 1 ? '' : 's'} due`}
                          </span>
                        </TableCell>
                        <TableCell className="text-right">{signedCount(-projection.churnedSubs)}</TableCell>
                        <TableCell className="text-right">{signedDollars(-projection.lostMrr)}</TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell className="font-semibold">Net</TableCell>
                        <TableCell className="text-right font-semibold">{signedCount(projection.netSubs)}</TableCell>
                        <TableCell className="text-right font-semibold">{signedDollars(projection.netMrr)}</TableCell>
                      </TableRow>
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>

              <Card variant="flat">
                <CardContent className="p-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Whole cohort started this month, whenever it converts</TableHead>
                        <TableHead className="text-right">Subscribers</TableHead>
                        <TableHead className="text-right">Value</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      <TableRow>
                        <TableCell className="text-muted-foreground">Monthly recurring</TableCell>
                        <TableCell className="text-right text-muted-foreground">
                          {formatCount(projection.cohortSubs)}
                        </TableCell>
                        <TableCell className="text-right text-muted-foreground">
                          {formatDollars(projection.cohortMrr)}
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell className="text-muted-foreground">Lifetime</TableCell>
                        <TableCell className="text-right text-muted-foreground">
                          {formatCount(projection.cohortSubs)}
                        </TableCell>
                        <TableCell className="text-right text-muted-foreground">
                          {projection.cohortValue === null ? '—' : formatDollars(projection.cohortValue)}
                        </TableCell>
                      </TableRow>
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>

              <p className="text-sm text-muted-foreground">
                Trial conversion {describeRate(projection.conversion)} · paid churn {describeRate(projection.churn)} ·
                blended ARPU {formatDollars(projection.arpu)}/mo. The first table counts what has already happened this
                month — trials that converted, subscribers who cancelled — and applies those rates only to the part of
                the month still outstanding, so it converges on the actual rather than drifting from it. The second
                values every trial the month starts, including those converting next month. Annual subscribers count
                toward churn only in the month they actually renew. The range on projected trials is this month&apos;s
                own sampling error — no prior month is blended in, so an in-season month is never dragged toward an
                off-season average.
              </p>
            </>
          )}
        </section>

        <section className="space-y-3">
          <div className="flex items-baseline justify-between">
            <h2 className="font-display text-xl font-semibold">Unpaid Invoices</h2>
            <span className="text-sm text-muted-foreground">
              {metrics.unpaidInvoices.available
                ? `${formatDollars(metrics.unpaidInvoices.outstanding)} outstanding · ${metrics.unpaidInvoices.noRetryScheduled} with no retry scheduled`
                : 'could not be loaded'}
            </span>
          </div>
          <Card variant="flat">
            <CardContent className="p-0">
              {!metrics.unpaidInvoices.available ? (
                <div className="p-6 text-sm text-muted-foreground">
                  Stripe did not return open invoices on this load, so this list is unknown rather than empty. The error
                  is listed above.
                </div>
              ) : metrics.unpaidInvoices.list.length === 0 ? (
                <div className="p-6 text-sm text-muted-foreground">No unpaid invoices. Every charge cleared.</div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Customer</TableHead>
                      <TableHead className="text-right">Outstanding</TableHead>
                      <TableHead className="text-right">Attempts</TableHead>
                      <TableHead>Retry</TableHead>
                      <TableHead>Invoiced</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {metrics.unpaidInvoices.list.map((row) => (
                      <TableRow key={row.id}>
                        <TableCell>{row.email}</TableCell>
                        <TableCell className="text-right">{formatDollars(row.amountRemaining)}</TableCell>
                        <TableCell className="text-right">{row.attemptCount}</TableCell>
                        <TableCell
                          className={row.retryScheduled ? 'text-muted-foreground' : 'font-semibold text-destructive'}
                        >
                          {row.retryScheduled ? 'scheduled' : 'none'}
                        </TableCell>
                        <TableCell className="text-muted-foreground">{formatDate(row.created)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
          <p className="text-sm text-muted-foreground">
            Subscription charges Stripe finalized and could not collect — a mix of first charges after a trial and later
            renewal failures. &ldquo;No retry&rdquo; means Stripe has nothing further on the calendar; the reverse does
            not hold, because after a hard decline Stripe keeps scheduling attempts that only run once a new card is
            added.
          </p>
        </section>

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
                    {metrics.conversion.converted} of {metrics.conversion.sample} trials that ended in the last{' '}
                    {metrics.conversion.windowDays} days went on to a paid subscription. Counted whether or not they are
                    still subscribed today, so this measures conversion rather than retention. Trials still in flight
                    are excluded.
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
