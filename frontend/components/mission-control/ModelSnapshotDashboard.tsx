'use client';

import { useMissionControlSnapshot } from '@/hooks/useMissionControl';
import type { MissionControlSnapshot, ModelPerformanceSummary, ModelVersionSummary } from '@/types/mission-control';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LastUpdated } from '@/components/ui/LastUpdated';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { MetricCard } from '@/components/analytics/MetricCard';

function formatPercent(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(digits)}%`;
}

function formatNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—';
  return value.toLocaleString();
}

function formatDecimal(value: number | null | undefined, digits = 3): string {
  if (value == null || Number.isNaN(value)) return '—';
  return value.toFixed(digits);
}

function formatShortDate(value: string | null | undefined): string {
  if (!value) return '—';
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date(`${value}T00:00:00Z`));
}

function SectionSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-10 w-64 bg-white/10" />
      <Skeleton className="h-48 w-full bg-white/10" />
    </div>
  );
}

function ComparisonTable({ heuristic, offline, sharedSettledGames }: { heuristic: ModelPerformanceSummary; offline: ModelPerformanceSummary; sharedSettledGames: number }) {
  const rows = [
    ['Settled games', formatNumber(sharedSettledGames), formatNumber(sharedSettledGames)],
    ['Winner accuracy', formatPercent(heuristic.winnerAccuracy), formatPercent(offline.winnerAccuracy)],
    ['Draw recall', formatPercent(heuristic.drawRecall), formatPercent(offline.drawRecall)],
    ['Predicted draw rate', formatPercent(heuristic.predictedDrawRate), formatPercent(offline.predictedDrawRate)],
    ['Log loss', formatDecimal(heuristic.logLoss), formatDecimal(offline.logLoss)],
    ['Brier score', formatDecimal(heuristic.brierScore), formatDecimal(offline.brierScore)],
    ['Margin MAE', formatDecimal(heuristic.marginMae), formatDecimal(offline.marginMae)],
    ['Exact score accuracy', formatPercent(heuristic.exactScoreAccuracy), formatPercent(offline.exactScoreAccuracy)],
  ];

  return (
    <div className="rounded-lg border border-white/10 bg-white/5">
      <Table>
        <TableHeader>
          <TableRow className="border-white/10 hover:bg-white/5">
            <TableHead className="text-gray-400">Metric</TableHead>
            <TableHead className="text-right text-gray-400">Live heuristic</TableHead>
            <TableHead className="text-right text-gray-400">Offline benchmark</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(([label, heuristicValue, offlineValue]) => (
            <TableRow key={label} className="border-white/10 hover:bg-white/5">
              <TableCell className="text-white">{label}</TableCell>
              <TableCell className="text-right text-gray-300">{heuristicValue}</TableCell>
              <TableCell className="text-right text-gray-300">{offlineValue}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function VersionTable({ versions }: { versions: ModelVersionSummary[] }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5">
      <Table>
        <TableHeader>
          <TableRow className="border-white/10 hover:bg-white/5">
            <TableHead className="text-gray-400">Offline model version</TableHead>
            <TableHead className="text-right text-gray-400">Games</TableHead>
            <TableHead className="text-right text-gray-400">Winner acc.</TableHead>
            <TableHead className="text-right text-gray-400">Draw recall</TableHead>
            <TableHead className="text-right text-gray-400">Log loss</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {versions.slice(0, 8).map((version) => (
            <TableRow key={version.modelVersion ?? 'unknown'} className="border-white/10 hover:bg-white/5">
              <TableCell className="max-w-[320px] truncate text-white" title={version.modelVersion ?? 'Unknown'}>
                {version.modelVersion ?? 'Unknown'}
              </TableCell>
              <TableCell className="text-right text-gray-300">{formatNumber(version.games)}</TableCell>
              <TableCell className="text-right text-gray-300">{formatPercent(version.winnerAccuracy)}</TableCell>
              <TableCell className="text-right text-gray-300">{formatPercent(version.drawRecall)}</TableCell>
              <TableCell className="text-right text-gray-300">{formatDecimal(version.logLoss)}</TableCell>
            </TableRow>
          ))}
          {versions.length === 0 && (
            <TableRow className="border-white/10">
              <TableCell colSpan={5} className="text-center text-gray-500">
                No evaluated offline versions yet
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}

function StatusTable({ snapshot }: { snapshot: MissionControlSnapshot }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5">
      <Table>
        <TableHeader>
          <TableRow className="border-white/10 hover:bg-white/5">
            <TableHead className="text-gray-400">Pipeline state</TableHead>
            <TableHead className="text-right text-gray-400">Count</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow className="border-white/10 hover:bg-white/5">
            <TableCell className="text-white">Settled</TableCell>
            <TableCell className="text-right text-gray-300">{formatNumber(snapshot.pipeline.settled)}</TableCell>
          </TableRow>
          <TableRow className="border-white/10 hover:bg-white/5">
            <TableCell className="text-white">Pending result</TableCell>
            <TableCell className="text-right text-gray-300">{formatNumber(snapshot.pipeline.pendingResult)}</TableCell>
          </TableRow>
          <TableRow className="border-white/10 hover:bg-white/5">
            <TableCell className="text-white">Pending resolution</TableCell>
            <TableCell className="text-right text-gray-300">{formatNumber(snapshot.pipeline.pendingResolution)}</TableCell>
          </TableRow>
          <TableRow className="border-white/10 hover:bg-white/5">
            <TableCell className="text-white">Result not found</TableCell>
            <TableCell className="text-right text-gray-300">{formatNumber(snapshot.pipeline.resultNotFound)}</TableCell>
          </TableRow>
          <TableRow className="border-white/10 hover:bg-white/5">
            <TableCell className="text-white">Ambiguous result</TableCell>
            <TableCell className="text-right text-gray-300">{formatNumber(snapshot.pipeline.ambiguousResult)}</TableCell>
          </TableRow>
          <TableRow className="border-white/10 hover:bg-white/5">
            <TableCell className="text-white">Heuristic errors</TableCell>
            <TableCell className="text-right text-gray-300">{formatNumber(snapshot.pipeline.heuristicError)}</TableCell>
          </TableRow>
          <TableRow className="border-white/10 hover:bg-white/5">
            <TableCell className="text-white">Offline errors</TableCell>
            <TableCell className="text-right text-gray-300">{formatNumber(snapshot.pipeline.offlineError)}</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>
  );
}

export function ModelSnapshotDashboard() {
  const { data, isLoading, error, refetch } = useMissionControlSnapshot();

  if (error) {
    return <ErrorDisplay error={error} retry={refetch} />;
  }

  if (isLoading || !data) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-4 xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, index) => (
            <MetricCard key={index} title="Loading" value="—" loading />
          ))}
        </div>
        <SectionSkeleton />
        <SectionSkeleton />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline" className="border-white/20 text-gray-200">
              Live: {data.currentHeuristicVersion ?? 'Unknown'}
            </Badge>
            <Badge variant="outline" className="border-emerald-400/30 text-emerald-200">
              Offline: {data.currentOfflineVersion ?? 'Unknown'}
            </Badge>
          </div>
          <p className="max-w-3xl text-sm text-gray-400">
            Snapshot based on settled prospective fixtures with frozen pregame predictions. This is the clean head-to-head view
            of the live heuristic path versus the current offline benchmark.
          </p>
        </div>
        <LastUpdated date={data.generatedAt} label="Snapshot generated" />
      </div>

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-6">
        <MetricCard title="Shared Settled Games" value={formatNumber(data.sharedSettledGames)} />
        <MetricCard title="Live Winner Acc." value={formatPercent(data.heuristic.winnerAccuracy)} />
        <MetricCard title="Offline Winner Acc." value={formatPercent(data.offline.winnerAccuracy)} />
        <MetricCard title="Live Draw Recall" value={formatPercent(data.heuristic.drawRecall)} />
        <MetricCard title="Offline Draw Recall" value={formatPercent(data.offline.drawRecall)} />
        <MetricCard
          title="Winner Disagreement"
          value={formatPercent(data.headToHead.winnerDisagreementRate)}
          subtitle="Offline minus heuristic draw lift shown below"
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.6fr_1fr]">
        <Card variant="flat" className="border-white/10 bg-white/5">
          <CardHeader className="border-b border-white/10">
            <CardTitle className="text-white">Current Model Comparison</CardTitle>
            <CardDescription className="text-gray-400">
              Offline draw probability lift: {formatPercent(data.headToHead.avgDrawProbabilityDeltaOfflineMinusHeuristic)}
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-6">
            <ComparisonTable heuristic={data.heuristic} offline={data.offline} sharedSettledGames={data.sharedSettledGames} />
          </CardContent>
        </Card>

        <Card variant="flat" className="border-white/10 bg-white/5">
          <CardHeader className="border-b border-white/10">
            <CardTitle className="text-white">Pipeline Snapshot</CardTitle>
            <CardDescription className="text-gray-400">
              Frozen fixture coverage and current evaluation backlog
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 pt-6">
            <div className="grid grid-cols-2 gap-4">
              <MetricCard title="Total Fixtures" value={formatNumber(data.pipeline.totalFixtures)} />
              <MetricCard title="Pending Result" value={formatNumber(data.pipeline.pendingResult)} />
              <MetricCard title="Pending Resolution" value={formatNumber(data.pipeline.pendingResolution)} />
              <MetricCard title="Result Not Found" value={formatNumber(data.pipeline.resultNotFound)} />
            </div>
            <StatusTable snapshot={data} />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_1.2fr]">
        <Card variant="flat" className="border-white/10 bg-white/5">
          <CardHeader className="border-b border-white/10">
            <CardTitle className="text-white">PIT Coverage</CardTitle>
            <CardDescription className="text-gray-400">Live snapshot coverage for leakage-safe training</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 pt-6">
            <div className="grid grid-cols-2 gap-4">
              <MetricCard title="Snapshot Rows" value={formatNumber(data.pitCoverage.snapshotRows)} />
              <MetricCard title="Scored Games" value={formatNumber(data.pitCoverage.totalScoredGames)} />
              <MetricCard title="Trainable Games" value={formatNumber(data.pitCoverage.trainableScoredGames)} />
              <MetricCard title="Last 365d Trainable" value={formatNumber(data.pitCoverage.last365TrainableGames)} />
            </div>
            <div className="rounded-lg border border-white/10 bg-black/20 p-4 text-sm text-gray-300">
              <div className="flex items-center justify-between gap-4">
                <span>PIT window start</span>
                <span>{formatShortDate(data.pitCoverage.windowStart)}</span>
              </div>
              <div className="mt-2 flex items-center justify-between gap-4">
                <span>PIT window end</span>
                <span>{formatShortDate(data.pitCoverage.windowEnd)}</span>
              </div>
              <div className="mt-2 flex items-center justify-between gap-4">
                <span>Last 365d scored games</span>
                <span>{formatNumber(data.pitCoverage.last365ScoredGames)}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card variant="flat" className="border-white/10 bg-white/5">
          <CardHeader className="border-b border-white/10">
            <CardTitle className="text-white">Offline Version Benchmarks</CardTitle>
            <CardDescription className="text-gray-400">
              Settled prospective performance by offline model version
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-6">
            <VersionTable versions={data.offlineVersions} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
