/**
 * Admin Dashboard Page
 * Comprehensive analytics and monitoring for PitchRank
 */

import { Suspense } from 'react'
import {
  Users,
  Trophy,
  Activity,
  Calendar,
  Database,
  TrendingUp,
  AlertTriangle,
  Clock
} from 'lucide-react'
import { MetricsCard } from '@/components/dashboard/MetricsCard'
import { TeamsByAgeGroupChart } from '@/components/dashboard/TeamsByAgeGroup'
import { TeamsByStateChart } from '@/components/dashboard/TeamsByState'
import { StaleTeams } from '@/components/dashboard/StaleTeams'
import { RecentActivityFeed } from '@/components/dashboard/RecentActivity'
import { WorkflowStatus } from '@/components/dashboard/WorkflowStatus'
import {
  getDashboardMetrics,
  getTeamsByAgeGroup,
  getTeamsByState,
  getStaleTeams,
  getRecentActivity,
  getMatchRateStats,
} from '@/lib/dashboard'

// Loading skeleton components
function MetricsCardSkeleton() {
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-6 animate-pulse">
      <div className="h-4 bg-neutral-200 dark:bg-neutral-800 rounded w-1/3 mb-2"></div>
      <div className="h-8 bg-neutral-200 dark:bg-neutral-800 rounded w-1/2"></div>
    </div>
  )
}

function ChartSkeleton() {
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-6 animate-pulse">
      <div className="h-6 bg-neutral-200 dark:bg-neutral-800 rounded w-1/3 mb-4"></div>
      <div className="h-64 bg-neutral-200 dark:bg-neutral-800 rounded"></div>
    </div>
  )
}

async function DashboardContent() {
  // Fetch all data in parallel
  const [
    metrics,
    teamsByAgeGroup,
    teamsByState,
    staleTeams,
    recentActivity,
    matchRateStats,
  ] = await Promise.all([
    getDashboardMetrics(),
    getTeamsByAgeGroup(),
    getTeamsByState(),
    getStaleTeams(30),
    getRecentActivity(15),
    getMatchRateStats(),
  ])

  // Mock workflow data (in production, fetch from GitHub API)
  const mockWorkflows = [
    {
      name: 'Weekly Update',
      status: 'success' as const,
      lastRun: metrics.lastDataImport || new Date().toISOString(),
      duration: 1800,
      url: 'https://github.com/dallasheidt14/PitchRank/actions/workflows/weekly-update.yml',
    },
    {
      name: 'Calculate Rankings',
      status: 'success' as const,
      lastRun: metrics.lastRankingRun || new Date().toISOString(),
      duration: 600,
      url: 'https://github.com/dallasheidt14/PitchRank/actions/workflows/calculate-rankings.yml',
    },
    {
      name: 'Process Missing Games',
      status: 'success' as const,
      lastRun: new Date(Date.now() - 300000).toISOString(), // 5 minutes ago
      duration: 45,
      url: 'https://github.com/dallasheidt14/PitchRank/actions/workflows/process-missing-games.yml',
    },
  ]

  return (
    <>
      {/* Key Metrics */}
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        <MetricsCard
          title="Total Teams"
          value={metrics.totalTeams}
          icon={Users}
          description="Tracked across all age groups"
          variant="default"
        />
        <MetricsCard
          title="Total Games"
          value={metrics.totalGames}
          icon={Trophy}
          description={`${matchRateStats.matchRate.toFixed(1)}% match rate`}
          variant={matchRateStats.matchRate >= 80 ? 'success' : 'warning'}
        />
        <MetricsCard
          title="Active Rankings"
          value={metrics.totalRankings}
          icon={TrendingUp}
          description="Currently ranked teams"
          lastUpdated={metrics.lastRankingRun || undefined}
          variant="default"
        />
        <MetricsCard
          title="Stale Teams"
          value={staleTeams.length}
          icon={AlertTriangle}
          description="Not updated in 30+ days"
          variant={staleTeams.length > 0 ? 'warning' : 'success'}
        />
      </div>

      {/* Last Run Times */}
      <div className="grid gap-6 md:grid-cols-2">
        <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-6">
          <div className="flex items-center gap-2 mb-2">
            <Calendar className="h-5 w-5 text-neutral-600 dark:text-neutral-400" />
            <h3 className="text-sm font-medium text-neutral-600 dark:text-neutral-400">
              Last Ranking Run
            </h3>
          </div>
          <p className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">
            {metrics.lastRankingRun
              ? new Date(metrics.lastRankingRun).toLocaleString()
              : 'Never'}
          </p>
        </div>
        <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-6">
          <div className="flex items-center gap-2 mb-2">
            <Database className="h-5 w-5 text-neutral-600 dark:text-neutral-400" />
            <h3 className="text-sm font-medium text-neutral-600 dark:text-neutral-400">
              Last Data Import
            </h3>
          </div>
          <p className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">
            {metrics.lastDataImport
              ? new Date(metrics.lastDataImport).toLocaleString()
              : 'Never'}
          </p>
        </div>
      </div>

      {/* Match Rate Breakdown */}
      <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-6">
        <h3 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 mb-4">
          Game Matching Statistics
        </h3>
        <div className="grid gap-4 md:grid-cols-3">
          <div className="text-center p-4 bg-green-50 dark:bg-green-950/50 rounded-lg">
            <p className="text-3xl font-bold text-green-600 dark:text-green-400">
              {matchRateStats.fullyMatched.toLocaleString()}
            </p>
            <p className="text-sm text-green-700 dark:text-green-300 mt-1">Fully Matched</p>
            <p className="text-xs text-neutral-600 dark:text-neutral-400 mt-1">
              {((matchRateStats.fullyMatched / matchRateStats.total) * 100).toFixed(1)}%
            </p>
          </div>
          <div className="text-center p-4 bg-yellow-50 dark:bg-yellow-950/50 rounded-lg">
            <p className="text-3xl font-bold text-yellow-600 dark:text-yellow-400">
              {matchRateStats.partiallyMatched.toLocaleString()}
            </p>
            <p className="text-sm text-yellow-700 dark:text-yellow-300 mt-1">Partially Matched</p>
            <p className="text-xs text-neutral-600 dark:text-neutral-400 mt-1">
              {((matchRateStats.partiallyMatched / matchRateStats.total) * 100).toFixed(1)}%
            </p>
          </div>
          <div className="text-center p-4 bg-red-50 dark:bg-red-950/50 rounded-lg">
            <p className="text-3xl font-bold text-red-600 dark:text-red-400">
              {matchRateStats.unmatched.toLocaleString()}
            </p>
            <p className="text-sm text-red-700 dark:text-red-300 mt-1">Unmatched</p>
            <p className="text-xs text-neutral-600 dark:text-neutral-400 mt-1">
              {((matchRateStats.unmatched / matchRateStats.total) * 100).toFixed(1)}%
            </p>
          </div>
        </div>
      </div>

      {/* Charts */}
      <div className="grid gap-6 lg:grid-cols-2">
        <TeamsByAgeGroupChart data={teamsByAgeGroup} />
        <TeamsByStateChart data={teamsByState} />
      </div>

      {/* Stale Teams Alert */}
      <StaleTeams teams={staleTeams} threshold={30} />

      {/* Recent Activity and Workflow Status */}
      <div className="grid gap-6 lg:grid-cols-2">
        <RecentActivityFeed activities={recentActivity} />
        <WorkflowStatus workflows={mockWorkflows} />
      </div>
    </>
  )
}

export default function DashboardPage() {
  return (
    <div className="container mx-auto px-4 py-8 max-w-7xl">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <Activity className="h-8 w-8 text-blue-600 dark:text-blue-400" />
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-neutral-100">
            PitchRank Dashboard
          </h1>
        </div>
        <p className="text-neutral-600 dark:text-neutral-400">
          Monitor your ranking system, teams, and data operations in real-time
        </p>
      </div>

      {/* Dashboard Content */}
      <div className="space-y-6">
        <Suspense
          fallback={
            <>
              <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
                <MetricsCardSkeleton />
                <MetricsCardSkeleton />
                <MetricsCardSkeleton />
                <MetricsCardSkeleton />
              </div>
              <div className="grid gap-6 lg:grid-cols-2">
                <ChartSkeleton />
                <ChartSkeleton />
              </div>
            </>
          }
        >
          <DashboardContent />
        </Suspense>
      </div>

      {/* Footer */}
      <div className="mt-12 pt-6 border-t border-neutral-200 dark:border-neutral-800">
        <p className="text-sm text-neutral-500 dark:text-neutral-500 text-center">
          Dashboard updates in real-time • Last refreshed: {new Date().toLocaleTimeString()}
        </p>
      </div>
    </div>
  )
}
