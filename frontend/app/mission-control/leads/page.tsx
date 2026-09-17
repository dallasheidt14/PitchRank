import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { fetchMatchBalanceLeads } from '@/lib/admin/matchbalance-leads';
import { BUSINESS_TIMEZONE } from '@/lib/admin/timezone';
import { MATCHBALANCE_REQUEST_LABELS, type MatchBalanceRequestType } from '@/lib/matchbalance';

// Admin gate is enforced by frontend/middleware.ts (ADMIN_ROUTES).
export const dynamic = 'force-dynamic';
export const metadata = { robots: { index: false, follow: false } };

// The submitted address only has to look like local@domain.tld, so it can carry a
// "?bcc=" or ",other@" that a mail client would act on. Encode each side and keep
// the separating @ literal, as RFC 6068 section 2 requires.
function mailtoHref(address: string): string {
  const at = address.lastIndexOf('@');
  return `mailto:${encodeURIComponent(address.slice(0, at))}@${encodeURIComponent(address.slice(at + 1))}`;
}

// Every instant on this page is named in BUSINESS_TIMEZONE. Vercel runs with
// TZ=UTC, so an unzoned format renders the server's calendar day, which is
// already tomorrow's from 5pm local onward.
function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: BUSINESS_TIMEZONE,
  });
}

// A Postgres `date` names a calendar day, not an instant. Through formatDate,
// 2026-09-16 parses as UTC midnight and renders as Sep 15 in Phoenix.
function formatCalendarDate(value: string): string {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  });
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

export default async function MatchBalanceLeadsPage() {
  const { leads, total, thisWeek, awaitingReply, errors } = await fetchMatchBalanceLeads();

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
              <span>MatchBalance Leads</span>
            </div>
            <h1 className="font-display text-3xl font-bold tracking-tight">MatchBalance Leads</h1>
            <p className="text-sm text-muted-foreground">Inquiries from tournament directors on /matchbalance</p>
          </div>
          <Link href="/mission-control/leads">
            <Button variant="outline" size="sm">
              Refresh
            </Button>
          </Link>
        </div>

        {errors.length > 0 && (
          <Card variant="accent" className="border-l-destructive">
            <CardHeader>
              <CardTitle className="text-destructive">Some data failed to load</CardTitle>
              <CardDescription>
                {errors.length} section{errors.length === 1 ? '' : 's'} returned an error. The rest of the page reflects
                what loaded successfully.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                {errors.map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        <section className="space-y-3">
          <div className="flex items-baseline justify-between">
            <h2 className="font-display text-xl font-semibold">Inquiries</h2>
            <span className="text-sm text-muted-foreground">
              latest {leads.length} of {total.toLocaleString()} inquiries
            </span>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <KpiCard label="Total" value={total.toLocaleString()} sub="all time" />
            <KpiCard label="This Week" value={thisWeek.toLocaleString()} sub="last 7 days" />
            <KpiCard
              label="Awaiting Reply"
              value={awaitingReply.toLocaleString()}
              sub="status still new"
              emphasize={awaitingReply > 0}
            />
          </div>

          <Card variant="flat">
            <CardContent className="p-0">
              {leads.length === 0 ? (
                <div className="p-6 text-sm text-muted-foreground">No MatchBalance inquiries yet.</div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>When</TableHead>
                      <TableHead>Name</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>Organization</TableHead>
                      <TableHead>Tournament</TableHead>
                      <TableHead>Dates</TableHead>
                      <TableHead className="text-right">Teams</TableHead>
                      <TableHead>Bracket review</TableHead>
                      <TableHead>Request</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Notes</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {leads.map((lead) => (
                      <TableRow key={lead.id}>
                        <TableCell className="text-muted-foreground" title={formatDate(lead.created_at)}>
                          {formatRelative(lead.created_at)}
                        </TableCell>
                        <TableCell>{lead.name}</TableCell>
                        <TableCell>
                          <a href={mailtoHref(lead.email)} className="hover:underline">
                            {lead.email}
                          </a>
                        </TableCell>
                        <TableCell>{lead.organization}</TableCell>
                        <TableCell>
                          {lead.event_url ? (
                            <a
                              href={lead.event_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="hover:underline"
                            >
                              {lead.tournament_name}
                            </a>
                          ) : (
                            lead.tournament_name
                          )}
                        </TableCell>
                        <TableCell>{lead.event_dates}</TableCell>
                        <TableCell className="text-right">{lead.team_count ?? '—'}</TableCell>
                        <TableCell>
                          {lead.bracket_review_date ? formatCalendarDate(lead.bracket_review_date) : '—'}
                        </TableCell>
                        <TableCell>
                          {MATCHBALANCE_REQUEST_LABELS[lead.request_type as MatchBalanceRequestType] ??
                            lead.request_type}
                        </TableCell>
                        <TableCell className={lead.status === 'new' ? 'font-semibold' : 'text-muted-foreground'}>
                          {lead.status}
                        </TableCell>
                        <TableCell className="max-w-[24ch] truncate text-muted-foreground" title={lead.notes ?? ''}>
                          {lead.notes ?? '—'}
                        </TableCell>
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
