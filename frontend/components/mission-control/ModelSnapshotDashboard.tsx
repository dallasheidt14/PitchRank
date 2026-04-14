'use client';

import { ArrowUpRight, Clock3, Database, FlaskConical, GitCompareArrows, History, Info, Target, Trophy, TrendingUp, type LucideIcon } from 'lucide-react';
import { useMissionControlSnapshot } from '@/hooks/useMissionControl';
import type { MissionControlSnapshot, ModelPerformanceSummary, ModelVersionSummary, TrainingRunSummary } from '@/types/mission-control';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LastUpdated } from '@/components/ui/LastUpdated';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

function formatPercent(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return 'N/A';
  return `${(value * 100).toFixed(digits)}%`;
}

function formatNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return 'N/A';
  return value.toLocaleString();
}

function formatDecimal(value: number | null | undefined, digits = 3): string {
  if (value == null || Number.isNaN(value)) return 'N/A';
  return value.toFixed(digits);
}

function formatShortDate(value: string | null | undefined): string {
  if (!value) return 'N/A';
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date(`${value}T00:00:00Z`));
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'N/A';
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(value));
}

function formatPercentPointDelta(value: number | null): string {
  if (value == null || Number.isNaN(value)) return 'N/A';
  const points = value * 100;
  const sign = points > 0 ? '+' : '';
  return `${sign}${points.toFixed(2)} pts`;
}

function formatDeltaMagnitude(value: number, digits = 2): string {
  return `${Math.abs(value * 100).toFixed(digits)} pts`;
}

function formatStrategy(value: string | null | undefined): string {
  if (!value) return 'N/A';
  return value.replace(/_/g, ' ');
}

function githubRunUrl(runId: number): string {
  return `https://github.com/dallasheidt14/PitchRank/actions/runs/${runId}`;
}

function SectionSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-10 w-64 bg-white/10" />
      <Skeleton className="h-48 w-full bg-white/10" />
    </div>
  );
}

function InfoLabel({ label, tooltip }: { label: string; tooltip: string }) {
  return (
    <div className="inline-flex items-center gap-1.5">
      <span>{label}</span>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="rounded-full text-gray-500 transition hover:text-gray-200"
            aria-label={`${label}: more information`}
          >
            <Info className="h-3.5 w-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" sideOffset={8} className="max-w-xs bg-gray-100 text-gray-900">
          {tooltip}
        </TooltipContent>
      </Tooltip>
    </div>
  );
}

function MetricTile({
  title,
  tooltip,
  value,
  subtitle,
  icon: Icon,
}: {
  title: string;
  tooltip: string;
  value: string;
  subtitle?: string;
  icon: LucideIcon;
}) {
  return (
    <Card variant="flat" className="border-white/10 bg-white/5">
      <CardContent className="pt-6">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-2">
            <p className="text-sm text-gray-400">
              <InfoLabel label={title} tooltip={tooltip} />
            </p>
            <p className="text-2xl font-semibold text-white">{value}</p>
            {subtitle ? <p className="text-xs text-gray-500">{subtitle}</p> : null}
          </div>
          <div className="rounded-full border border-white/10 bg-black/20 p-2 text-gray-300">
            <Icon className="h-4 w-4" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function trainingChangeSummary(current: TrainingRunSummary, previous: TrainingRunSummary | null): string {
  if (!previous) {
    return 'No earlier recorded training run yet. This is the baseline holdout snapshot for the new training tracker.';
  }

  const parts: string[] = [];
  if (current.winnerAccuracy != null && previous.winnerAccuracy != null) {
    const delta = current.winnerAccuracy - previous.winnerAccuracy;
    parts.push(`winner accuracy ${delta >= 0 ? 'up' : 'down'} ${formatDeltaMagnitude(delta)}`);
  }
  if (current.drawRecall != null && previous.drawRecall != null) {
    const delta = current.drawRecall - previous.drawRecall;
    parts.push(`draw recall ${delta >= 0 ? 'up' : 'down'} ${formatDeltaMagnitude(delta)}`);
  }
  if (current.logLoss != null && previous.logLoss != null) {
    const delta = current.logLoss - previous.logLoss;
    parts.push(`log loss ${delta <= 0 ? 'down' : 'up'} ${Math.abs(delta).toFixed(3)}`);
  }
  if (current.gamesUsed != null && previous.gamesUsed != null) {
    const delta = current.gamesUsed - previous.gamesUsed;
    const sign = delta > 0 ? '+' : '';
    parts.push(`games used ${sign}${delta.toLocaleString()}`);
  }

  if (!parts.length) {
    return 'No comparable metrics were available from the previous recorded training run.';
  }

  return `Versus the previous recorded run: ${parts.join(', ')}.`;
}

function winnerSummaryText(heuristic: ModelPerformanceSummary, offline: ModelPerformanceSummary): string {
  if (heuristic.winnerAccuracy == null || offline.winnerAccuracy == null) {
    return 'Winner-picking accuracy is not available yet.';
  }
  const delta = offline.winnerAccuracy - heuristic.winnerAccuracy;
  if (Math.abs(delta) < 0.0001) {
    return 'Both models are effectively tied on picking winners.';
  }
  if (delta > 0) {
    return `Offline is ahead on picking winners by ${formatPercentPointDelta(delta)}.`;
  }
  return `Live heuristic is ahead on picking winners by ${formatPercentPointDelta(Math.abs(delta))}.`;
}

function drawSummaryText(heuristic: ModelPerformanceSummary, offline: ModelPerformanceSummary): string {
  if (heuristic.drawRecall == null || offline.drawRecall == null) {
    return 'Draw detection is not available yet.';
  }
  const delta = offline.drawRecall - heuristic.drawRecall;
  if (Math.abs(delta) < 0.0001) {
    return 'Both models are effectively tied on calling draws.';
  }
  if (delta > 0) {
    return `Offline catches actual draws ${formatPercentPointDelta(delta)} more often.`;
  }
  return `Live heuristic catches actual draws ${formatPercentPointDelta(Math.abs(delta))} more often.`;
}

function QuickReadCard({ data }: { data: MissionControlSnapshot }) {
  const latestTrainingRun = data.trainingRuns[0] ?? null;

  return (
    <Card variant="flat" className="border-white/10 bg-white/5">
      <CardHeader className="border-b border-white/10">
        <CardTitle className="text-white">Quick Read</CardTitle>
        <CardDescription className="text-gray-400">
          Plain-English readout of what the current numbers are saying
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 pt-6 text-sm text-gray-200">
        <p>
          The comparison is currently based on <strong>{formatNumber(data.sharedSettledGames)}</strong> comparable games:
          games where both models made a frozen prediction before kickoff and we now have a final score to judge them on.
        </p>
        <p>{winnerSummaryText(data.heuristic, data.offline)}</p>
        <p>{drawSummaryText(data.heuristic, data.offline)}</p>
        {latestTrainingRun ? (
          <p>
            The latest offline training run was recorded on <strong>{formatDateTime(latestTrainingRun.createdAt)}</strong> and
            used <strong>{formatNumber(latestTrainingRun.gamesUsed)}</strong> leakage-safe games, with holdout winner accuracy of{' '}
            <strong>{formatPercent(latestTrainingRun.winnerAccuracy)}</strong> and log loss of{' '}
            <strong>{formatDecimal(latestTrainingRun.logLoss)}</strong>.
          </p>
        ) : null}
        <p>
          There are <strong>{formatNumber(data.pipeline.pendingResult)}</strong> frozen fixtures still waiting on final scores and{' '}
          <strong>{formatNumber(data.pipeline.pendingResolution)}</strong> fixtures that still need cleaner team matching before
          they can be judged.
        </p>
      </CardContent>
    </Card>
  );
}

function LatestTrainingCard({
  runs,
  currentOfflineVersion,
}: {
  runs: TrainingRunSummary[];
  currentOfflineVersion: string | null;
}) {
  const latest = runs[0] ?? null;
  const previous = runs[1] ?? null;

  if (!latest) {
    return (
      <Card variant="flat" className="border-white/10 bg-white/5">
        <CardHeader className="border-b border-white/10">
          <CardTitle className="text-white">Latest Offline Training Run</CardTitle>
          <CardDescription className="text-gray-400">
            Holdout results from the training workflow will appear here once a run is recorded
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-6 text-sm text-gray-400">No recorded training runs yet.</CardContent>
      </Card>
    );
  }

  const isCurrentBenchmark = currentOfflineVersion != null && latest.modelVersion === currentOfflineVersion;

  return (
    <Card variant="flat" className="border-white/10 bg-white/5">
      <CardHeader className="border-b border-white/10">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-2">
            <CardTitle className="text-white">Latest Offline Training Run</CardTitle>
            <CardDescription className="text-gray-400">
              Offline holdout metrics from the training workflow. Use this to spot retrain improvement before the model has enough
              prospective games to judge live.
            </CardDescription>
          </div>
          <a
            href={githubRunUrl(latest.workflowRunId)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-sm text-emerald-200 transition hover:text-white"
          >
            Open run #{latest.workflowRunId}
            <ArrowUpRight className="h-4 w-4" />
          </a>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 pt-6">
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline" className="border-white/20 text-gray-200">
            {latest.modelVersion}
          </Badge>
          <Badge variant="outline" className="border-white/20 text-gray-200">
            strategy: {formatStrategy(latest.selectedProbabilityStrategy ?? latest.requestedProbabilityStrategy)}
          </Badge>
          <Badge
            variant="outline"
            className={isCurrentBenchmark ? 'border-emerald-400/30 text-emerald-200' : 'border-amber-400/30 text-amber-200'}
          >
            {isCurrentBenchmark ? 'current prospective benchmark' : 'newer than current benchmark'}
          </Badge>
          <Badge variant="outline" className="border-white/20 text-gray-200">
            calibration: {latest.calibrationEnabled ? `${latest.calibrationMethod ?? 'on'}` : 'off'}
          </Badge>
        </div>

        <p className="text-sm text-gray-300">{trainingChangeSummary(latest, previous)}</p>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <MetricTile
            title="Games used"
            tooltip="Historical matches that had valid point-in-time snapshots and were actually used to train and test this run."
            value={formatNumber(latest.gamesUsed)}
            subtitle={`${formatNumber(latest.examplesBuilt)} mirrored examples built`}
            icon={Database}
          />
          <MetricTile
            title="Winner accuracy"
            tooltip="Offline holdout accuracy on picking the correct winner or draw outcome for this specific training run."
            value={formatPercent(latest.winnerAccuracy)}
            subtitle={`Requested ${formatStrategy(latest.requestedProbabilityStrategy)}`}
            icon={Trophy}
          />
          <MetricTile
            title="Draw recall"
            tooltip="Out of the holdout games that truly ended in a draw, how often this training run called draw."
            value={formatPercent(latest.drawRecall)}
            subtitle={`Predicted draw rate ${formatPercent(latest.predictedDrawRate)}`}
            icon={Target}
          />
          <MetricTile
            title="Log loss"
            tooltip="Offline holdout probability-quality score for this run. Lower is better."
            value={formatDecimal(latest.logLoss)}
            subtitle={
              latest.calibratedLogLoss != null
                ? `Calibrated ${formatDecimal(latest.calibratedLogLoss)}`
                : `Exact score ${formatPercent(latest.exactScoreAccuracy)}`
            }
            icon={TrendingUp}
          />
          <MetricTile
            title="Margin MAE"
            tooltip="Average offline holdout error in expected goal margin. Lower is better."
            value={formatDecimal(latest.marginMae)}
            subtitle={`Lookback ${formatNumber(latest.lookbackDays)} days`}
            icon={FlaskConical}
          />
          <MetricTile
            title="Snapshot dates used"
            tooltip="How many distinct point-in-time snapshot dates were actually used in this training run."
            value={formatNumber(latest.uniqueSnapshotDatesUsed)}
            subtitle={`Recorded ${formatDateTime(latest.createdAt)}`}
            icon={History}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function TrainingHistoryTable({
  runs,
  currentOfflineVersion,
}: {
  runs: TrainingRunSummary[];
  currentOfflineVersion: string | null;
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5">
      <Table>
        <TableHeader>
          <TableRow className="border-white/10 hover:bg-white/5">
            <TableHead className="text-gray-400">
              <InfoLabel
                label="Run"
                tooltip="GitHub Actions training run that produced this offline model summary."
              />
            </TableHead>
            <TableHead className="text-gray-400">
              <InfoLabel
                label="Model version"
                tooltip="Version string that can later become the offline benchmark in the prospective pipeline."
              />
            </TableHead>
            <TableHead className="text-right text-gray-400">
              <InfoLabel label="Games used" tooltip="Leakage-safe historical matches used by that training run." />
            </TableHead>
            <TableHead className="text-right text-gray-400">
              <InfoLabel label="Winner acc." tooltip="Offline holdout winner accuracy for that run." />
            </TableHead>
            <TableHead className="text-right text-gray-400">
              <InfoLabel label="Draw recall" tooltip="Offline holdout draw recall for that run." />
            </TableHead>
            <TableHead className="text-right text-gray-400">
              <InfoLabel label="Log loss" tooltip="Offline holdout probability-quality score. Lower is better." />
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((run) => {
            const isCurrentBenchmark = currentOfflineVersion != null && run.modelVersion === currentOfflineVersion;
            return (
              <TableRow key={run.workflowRunId} className="border-white/10 hover:bg-white/5">
                <TableCell className="text-white">
                  <div className="space-y-1">
                    <a
                      href={githubRunUrl(run.workflowRunId)}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-white transition hover:text-emerald-200"
                    >
                      #{run.workflowRunId}
                      <ArrowUpRight className="h-3.5 w-3.5" />
                    </a>
                    <div className="text-xs text-gray-500">{formatDateTime(run.createdAt)}</div>
                  </div>
                </TableCell>
                <TableCell className="max-w-[360px] truncate text-white" title={run.modelVersion}>
                  <div className="flex items-center gap-2">
                    <span>{run.modelVersion}</span>
                    {isCurrentBenchmark ? (
                      <Badge variant="outline" className="border-emerald-400/30 text-emerald-200">
                        benchmark
                      </Badge>
                    ) : null}
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
                    {formatStrategy(run.selectedProbabilityStrategy ?? run.requestedProbabilityStrategy)}
                  </div>
                </TableCell>
                <TableCell className="text-right text-gray-300">{formatNumber(run.gamesUsed)}</TableCell>
                <TableCell className="text-right text-gray-300">{formatPercent(run.winnerAccuracy)}</TableCell>
                <TableCell className="text-right text-gray-300">{formatPercent(run.drawRecall)}</TableCell>
                <TableCell className="text-right text-gray-300">
                  <div>{formatDecimal(run.logLoss)}</div>
                  {run.calibratedLogLoss != null ? (
                    <div className="text-xs text-gray-500">cal {formatDecimal(run.calibratedLogLoss)}</div>
                  ) : null}
                </TableCell>
              </TableRow>
            );
          })}
          {runs.length === 0 ? (
            <TableRow className="border-white/10">
              <TableCell colSpan={6} className="text-center text-gray-500">
                No recorded training runs yet
              </TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </Table>
    </div>
  );
}

type ComparisonMetric = {
  label: string;
  tooltip: string;
  heuristicValue: string;
  offlineValue: string;
};

function ComparisonTable({
  heuristic,
  offline,
  comparableGames,
}: {
  heuristic: ModelPerformanceSummary;
  offline: ModelPerformanceSummary;
  comparableGames: number;
}) {
  const rows: ComparisonMetric[] = [
    {
      label: 'Comparable games',
      tooltip:
        'Games where both models made a frozen pregame prediction and we already have a final score. This is the fairest head-to-head sample.',
      heuristicValue: formatNumber(comparableGames),
      offlineValue: formatNumber(comparableGames),
    },
    {
      label: 'Winner accuracy',
      tooltip: 'How often the model picked the correct winner or draw outcome.',
      heuristicValue: formatPercent(heuristic.winnerAccuracy),
      offlineValue: formatPercent(offline.winnerAccuracy),
    },
    {
      label: 'Draw recall',
      tooltip: 'Out of the games that actually ended in a draw, how often the model correctly called draw.',
      heuristicValue: formatPercent(heuristic.drawRecall),
      offlineValue: formatPercent(offline.drawRecall),
    },
    {
      label: 'Predicted draw rate',
      tooltip: 'How often the model predicts draw overall. Useful for spotting models that almost never call draws.',
      heuristicValue: formatPercent(heuristic.predictedDrawRate),
      offlineValue: formatPercent(offline.predictedDrawRate),
    },
    {
      label: 'Log loss',
      tooltip: 'Probability-quality score. Lower is better. It rewards confident correct calls and punishes confident misses.',
      heuristicValue: formatDecimal(heuristic.logLoss),
      offlineValue: formatDecimal(offline.logLoss),
    },
    {
      label: 'Brier score',
      tooltip: 'Another probability-quality score. Lower is better. It measures how close the predicted probabilities were to what actually happened.',
      heuristicValue: formatDecimal(heuristic.brierScore),
      offlineValue: formatDecimal(offline.brierScore),
    },
    {
      label: 'Margin MAE',
      tooltip: 'Average error in expected goal margin. Lower is better.',
      heuristicValue: formatDecimal(heuristic.marginMae),
      offlineValue: formatDecimal(offline.marginMae),
    },
    {
      label: 'Exact score accuracy',
      tooltip: 'How often the predicted exact scoreline matched the real final score.',
      heuristicValue: formatPercent(heuristic.exactScoreAccuracy),
      offlineValue: formatPercent(offline.exactScoreAccuracy),
    },
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
          {rows.map((row) => (
            <TableRow key={row.label} className="border-white/10 hover:bg-white/5">
              <TableCell className="text-white">
                <InfoLabel label={row.label} tooltip={row.tooltip} />
              </TableCell>
              <TableCell className="text-right text-gray-300">{row.heuristicValue}</TableCell>
              <TableCell className="text-right text-gray-300">{row.offlineValue}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function StatusTable({ snapshot }: { snapshot: MissionControlSnapshot }) {
  const rows = [
    {
      label: 'Settled rows across all versions',
      tooltip:
        'Fixtures where we matched the final result back to frozen predictions. This includes older model versions, so it can be larger than the current apples-to-apples comparison sample above.',
      value: formatNumber(snapshot.pipeline.settled),
      meaning: 'Final score found and at least one version pairing can be judged.',
    },
    {
      label: 'Waiting on final score',
      tooltip:
        'Fixtures where we already froze predictions before kickoff, but the actual game result has not been scraped or matched yet.',
      value: formatNumber(snapshot.pipeline.pendingResult),
      meaning: 'Predictions are stored; we are just waiting for the real result.',
    },
    {
      label: 'Needs fixture matching',
      tooltip:
        'Fixtures that still need better team resolution before we can safely compare predictions against results.',
      value: formatNumber(snapshot.pipeline.pendingResolution),
      meaning: 'The fixture exists, but the team/result matching is not clean enough yet.',
    },
    {
      label: 'Could not find result',
      tooltip:
        'We expected a result by now, but no clean matching scored game was found in the main games table.',
      value: formatNumber(snapshot.pipeline.resultNotFound),
      meaning: 'Likely a scrape coverage or matching problem.',
    },
    {
      label: 'Multiple possible results',
      tooltip: 'More than one scored game looked like a candidate match, so the row was left unresolved on purpose.',
      value: formatNumber(snapshot.pipeline.ambiguousResult),
      meaning: 'Needs manual cleanup or stronger matching rules.',
    },
    {
      label: 'Heuristic prediction errors',
      tooltip: 'Rows where the live heuristic path failed to produce a frozen prediction.',
      value: formatNumber(snapshot.pipeline.heuristicError),
      meaning: 'The current live model could not score these fixtures.',
    },
    {
      label: 'Offline prediction errors',
      tooltip: 'Rows where the offline model failed to produce a frozen prediction.',
      value: formatNumber(snapshot.pipeline.offlineError),
      meaning: 'The offline candidate could not score these fixtures.',
    },
  ];

  return (
    <div className="rounded-lg border border-white/10 bg-white/5">
      <Table>
        <TableHeader>
          <TableRow className="border-white/10 hover:bg-white/5">
            <TableHead className="text-gray-400">Status</TableHead>
            <TableHead className="text-right text-gray-400">Count</TableHead>
            <TableHead className="text-gray-400">What it means</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.label} className="border-white/10 hover:bg-white/5">
              <TableCell className="text-white">
                <InfoLabel label={row.label} tooltip={row.tooltip} />
              </TableCell>
              <TableCell className="text-right text-gray-300">{row.value}</TableCell>
              <TableCell className="text-gray-400">{row.meaning}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function VersionTable({ versions, currentVersion }: { versions: ModelVersionSummary[]; currentVersion: string | null }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5">
      <Table>
        <TableHeader>
          <TableRow className="border-white/10 hover:bg-white/5">
            <TableHead className="text-gray-400">
              <InfoLabel
                label="Offline model version"
                tooltip="Exact model artifact/version string used when freezing those prospective predictions."
              />
            </TableHead>
            <TableHead className="text-right text-gray-400">
              <InfoLabel label="Games" tooltip="Comparable games available for that specific offline version." />
            </TableHead>
            <TableHead className="text-right text-gray-400">
              <InfoLabel label="Winner acc." tooltip="How often that version picked the correct winner or draw." />
            </TableHead>
            <TableHead className="text-right text-gray-400">
              <InfoLabel label="Draw recall" tooltip="How often that version correctly called games that really ended in a draw." />
            </TableHead>
            <TableHead className="text-right text-gray-400">
              <InfoLabel label="Log loss" tooltip="Probability-quality score. Lower is better." />
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {versions.slice(0, 8).map((version) => (
            <TableRow key={version.modelVersion ?? 'unknown'} className="border-white/10 hover:bg-white/5">
              <TableCell className="max-w-[360px] truncate text-white" title={version.modelVersion ?? 'Unknown'}>
                <div className="flex items-center gap-2">
                  <span>{version.modelVersion ?? 'Unknown'}</span>
                  {currentVersion && version.modelVersion === currentVersion ? (
                    <Badge variant="outline" className="border-emerald-400/30 text-emerald-200">
                      current
                    </Badge>
                  ) : null}
                </div>
              </TableCell>
              <TableCell className="text-right text-gray-300">{formatNumber(version.games)}</TableCell>
              <TableCell className="text-right text-gray-300">{formatPercent(version.winnerAccuracy)}</TableCell>
              <TableCell className="text-right text-gray-300">{formatPercent(version.drawRecall)}</TableCell>
              <TableCell className="text-right text-gray-300">{formatDecimal(version.logLoss)}</TableCell>
            </TableRow>
          ))}
          {versions.length === 0 ? (
            <TableRow className="border-white/10">
              <TableCell colSpan={5} className="text-center text-gray-500">
                No evaluated offline versions yet
              </TableCell>
            </TableRow>
          ) : null}
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
        <div className="grid grid-cols-2 gap-4 xl:grid-cols-5">
          {Array.from({ length: 5 }).map((_, index) => (
            <Card key={index} variant="flat" className="border-white/10 bg-white/5">
              <CardContent className="pt-6">
                <Skeleton className="h-4 w-24 bg-white/10" />
                <Skeleton className="mt-3 h-8 w-20 bg-white/10" />
                <Skeleton className="mt-2 h-3 w-32 bg-white/10" />
              </CardContent>
            </Card>
          ))}
        </div>
        <SectionSkeleton />
        <SectionSkeleton />
      </div>
    );
  }

  const winnerDelta =
    data.offline.winnerAccuracy != null && data.heuristic.winnerAccuracy != null
      ? data.offline.winnerAccuracy - data.heuristic.winnerAccuracy
      : null;
  const drawDelta =
    data.offline.drawRecall != null && data.heuristic.drawRecall != null
      ? data.offline.drawRecall - data.heuristic.drawRecall
      : null;

  return (
    <TooltipProvider>
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
              This page is the live scorecard for model quality. It only uses frozen pregame predictions and actual finished
              results, so the comparison stays honest.
            </p>
          </div>
          <LastUpdated date={data.generatedAt} label="Snapshot generated" />
        </div>

        <QuickReadCard data={data} />

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
          <MetricTile
            title="Comparable games"
            tooltip="Games where both models predicted before kickoff and we now have a final score to compare against."
            value={formatNumber(data.sharedSettledGames)}
            subtitle="This is the fair head-to-head sample."
            icon={GitCompareArrows}
          />
          <MetricTile
            title="Winner accuracy edge"
            tooltip="Difference in winner accuracy between offline and live heuristic. Positive means offline is ahead."
            value={formatPercentPointDelta(winnerDelta)}
            subtitle={`${formatPercent(data.heuristic.winnerAccuracy)} live vs ${formatPercent(data.offline.winnerAccuracy)} offline`}
            icon={Trophy}
          />
          <MetricTile
            title="Draw recall edge"
            tooltip="Difference in draw recall between offline and live heuristic. Positive means offline catches more actual draws."
            value={formatPercentPointDelta(drawDelta)}
            subtitle={`${formatPercent(data.heuristic.drawRecall)} live vs ${formatPercent(data.offline.drawRecall)} offline`}
            icon={Target}
          />
          <MetricTile
            title="Waiting on results"
            tooltip="Frozen fixtures that still do not have a final score attached."
            value={formatNumber(data.pipeline.pendingResult)}
            subtitle="Predictions already stored, score still pending."
            icon={Clock3}
          />
          <MetricTile
            title="Trainable games"
            tooltip="Scored games that fall inside the current point-in-time snapshot window, so they can be used without leakage."
            value={formatNumber(data.pitCoverage.trainableScoredGames)}
            subtitle={`PIT window: ${formatShortDate(data.pitCoverage.windowStart)} to ${formatShortDate(data.pitCoverage.windowEnd)}`}
            icon={Database}
          />
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.7fr_1fr]">
          <Card variant="flat" className="border-white/10 bg-white/5">
            <CardHeader className="border-b border-white/10">
              <CardTitle className="text-white">Current Model Comparison</CardTitle>
              <CardDescription className="text-gray-400">
                Offline draw probability lift: {formatPercent(data.headToHead.avgDrawProbabilityDeltaOfflineMinusHeuristic)}.
                Winner disagreement: {formatPercent(data.headToHead.winnerDisagreementRate)}.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-6">
              <ComparisonTable
                heuristic={data.heuristic}
                offline={data.offline}
                comparableGames={data.sharedSettledGames}
              />
            </CardContent>
          </Card>

          <Card variant="flat" className="border-white/10 bg-white/5">
            <CardHeader className="border-b border-white/10">
              <CardTitle className="text-white">How to Read This</CardTitle>
              <CardDescription className="text-gray-400">Short definitions for the most important ideas on this page</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 pt-6 text-sm text-gray-300">
              <div>
                <p className="font-medium text-white">Comparable games</p>
                <p>Both models predicted before the game started, and we now have a final score. This is the sample that matters most.</p>
              </div>
              <div>
                <p className="font-medium text-white">Winner accuracy</p>
                <p>How often the model picked the correct outcome: team A win, draw, or team B win.</p>
              </div>
              <div>
                <p className="font-medium text-white">Draw recall</p>
                <p>Out of the games that really ended in a draw, how often the model actually said draw.</p>
              </div>
              <div>
                <p className="font-medium text-white">PIT coverage</p>
                <p>How much point-in-time history we have. More coverage means more leakage-safe training games.</p>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.15fr_1fr]">
          <Card variant="flat" className="border-white/10 bg-white/5">
            <CardHeader className="border-b border-white/10">
              <CardTitle className="text-white">Pipeline Status</CardTitle>
              <CardDescription className="text-gray-400">
                Operational counts for the prospective evaluation pipeline, including older model versions
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 pt-6">
              <div className="grid grid-cols-2 gap-4">
                <MetricTile
                  title="Total tracked fixtures"
                  tooltip="All prospective fixtures currently in the comparison pipeline."
                  value={formatNumber(data.pipeline.totalFixtures)}
                  icon={GitCompareArrows}
                />
                <MetricTile
                  title="Could not find result"
                  tooltip="Fixtures where we expected a final score but could not match one back cleanly."
                  value={formatNumber(data.pipeline.resultNotFound)}
                  icon={Clock3}
                />
              </div>
              <StatusTable snapshot={data} />
            </CardContent>
          </Card>

          <Card variant="flat" className="border-white/10 bg-white/5">
            <CardHeader className="border-b border-white/10">
              <CardTitle className="text-white">PIT Coverage</CardTitle>
              <CardDescription className="text-gray-400">
                Point-in-time snapshot coverage for leakage-safe model training
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 pt-6">
              <div className="grid grid-cols-2 gap-4">
                <MetricTile
                  title="Snapshot rows"
                  tooltip="Total rows stored in prediction_feature_history."
                  value={formatNumber(data.pitCoverage.snapshotRows)}
                  icon={Database}
                />
                <MetricTile
                  title="All scored games"
                  tooltip="Total scored games in the main games table."
                  value={formatNumber(data.pitCoverage.totalScoredGames)}
                  icon={Database}
                />
                <MetricTile
                  title="Trainable scored games"
                  tooltip="Scored games that are inside the PIT snapshot window and can be used safely for PIT training."
                  value={formatNumber(data.pitCoverage.trainableScoredGames)}
                  icon={Database}
                />
                <MetricTile
                  title="Last 365d trainable"
                  tooltip="Scored games from the last 365 days that are also inside the PIT snapshot window."
                  value={formatNumber(data.pitCoverage.last365TrainableGames)}
                  icon={Database}
                />
              </div>
              <div className="rounded-lg border border-white/10 bg-black/20 p-4 text-sm text-gray-300">
                <div className="flex items-center justify-between gap-4">
                  <span>Coverage start</span>
                  <span>{formatShortDate(data.pitCoverage.windowStart)}</span>
                </div>
                <div className="mt-2 flex items-center justify-between gap-4">
                  <span>Coverage end</span>
                  <span>{formatShortDate(data.pitCoverage.windowEnd)}</span>
                </div>
                <div className="mt-2 flex items-center justify-between gap-4">
                  <span>Last 365d scored games</span>
                  <span>{formatNumber(data.pitCoverage.last365ScoredGames)}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.2fr_1fr]">
          <LatestTrainingCard runs={data.trainingRuns} currentOfflineVersion={data.currentOfflineVersion} />

          <Card variant="flat" className="border-white/10 bg-white/5">
            <CardHeader className="border-b border-white/10">
              <CardTitle className="text-white">Training vs Live Results</CardTitle>
              <CardDescription className="text-gray-400">
                Why both sections matter and how to interpret them together
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 pt-6 text-sm text-gray-300">
              <div>
                <p className="font-medium text-white">Training run metrics</p>
                <p>Offline holdout numbers from the training workflow. Useful for seeing whether a retrain got better before enough live games finish.</p>
              </div>
              <div>
                <p className="font-medium text-white">Prospective comparison</p>
                <p>Frozen pregame predictions judged against real final scores. This is the real scoreboard for deciding whether to swap models live.</p>
              </div>
              <div>
                <p className="font-medium text-white">Best decision rule</p>
                <p>If a new training run looks better here, freeze it into future fixtures and wait for the prospective section to confirm the gain on real games.</p>
              </div>
            </CardContent>
          </Card>
        </div>

        <Card variant="flat" className="border-white/10 bg-white/5">
          <CardHeader className="border-b border-white/10">
            <CardTitle className="text-white">Offline Version Benchmarks</CardTitle>
            <CardDescription className="text-gray-400">
              Prospective performance by offline model version so you can see whether a newer retrain actually improved things
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-6">
            <VersionTable versions={data.offlineVersions} currentVersion={data.currentOfflineVersion} />
          </CardContent>
        </Card>

        <Card variant="flat" className="border-white/10 bg-white/5">
          <CardHeader className="border-b border-white/10">
            <CardTitle className="text-white">Recent Training Runs</CardTitle>
            <CardDescription className="text-gray-400">
              Latest recorded offline training runs so you can see whether retrains are trending in the right direction
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-6">
            <TrainingHistoryTable runs={data.trainingRuns} currentOfflineVersion={data.currentOfflineVersion} />
          </CardContent>
        </Card>
      </div>
    </TooltipProvider>
  );
}
