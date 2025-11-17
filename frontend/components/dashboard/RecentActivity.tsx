/**
 * Recent activity feed component
 * Shows recent operations from build logs
 */

'use client'

import { Activity, CheckCircle2, XCircle, AlertCircle, Database, TrendingUp, Download } from 'lucide-react'
import { RecentActivity } from '@/lib/dashboard'
import { formatDistanceToNow } from 'date-fns'

interface RecentActivityFeedProps {
  activities: RecentActivity[]
}

export function RecentActivityFeed({ activities }: RecentActivityFeedProps) {
  const getIcon = (type: RecentActivity['type']) => {
    switch (type) {
      case 'ranking_calculation':
        return TrendingUp
      case 'game_import':
        return Database
      case 'team_import':
        return Download
      case 'scrape':
        return Activity
      default:
        return Activity
    }
  }

  const getStatusIcon = (status: RecentActivity['status']) => {
    switch (status) {
      case 'success':
        return <CheckCircle2 className="h-5 w-5 text-green-500" />
      case 'error':
        return <XCircle className="h-5 w-5 text-red-500" />
      case 'warning':
        return <AlertCircle className="h-5 w-5 text-yellow-500" />
    }
  }

  const getStatusColor = (status: RecentActivity['status']) => {
    switch (status) {
      case 'success':
        return 'bg-green-50 dark:bg-green-950/50 border-green-200 dark:border-green-800'
      case 'error':
        return 'bg-red-50 dark:bg-red-950/50 border-red-200 dark:border-red-800'
      case 'warning':
        return 'bg-yellow-50 dark:bg-yellow-950/50 border-yellow-200 dark:border-yellow-800'
    }
  }

  if (activities.length === 0) {
    return (
      <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-6">
        <h3 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 mb-4">
          Recent Activity
        </h3>
        <div className="text-center py-8">
          <Activity className="h-12 w-12 text-neutral-400 dark:text-neutral-600 mx-auto mb-2" />
          <p className="text-neutral-600 dark:text-neutral-400">No recent activity</p>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-6">
      <h3 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 mb-4">
        Recent Activity
      </h3>

      <div className="space-y-3 max-h-96 overflow-y-auto">
        {activities.map((activity) => {
          const Icon = getIcon(activity.type)
          return (
            <div
              key={activity.id}
              className={`flex items-start gap-3 p-3 rounded-md border ${getStatusColor(activity.status)}`}
            >
              <div className="flex-shrink-0 mt-0.5">
                <Icon className="h-5 w-5 text-neutral-600 dark:text-neutral-400" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
                    {activity.description}
                  </p>
                  {getStatusIcon(activity.status)}
                </div>
                <p className="text-xs text-neutral-600 dark:text-neutral-400 mt-1">
                  {formatDistanceToNow(new Date(activity.timestamp), { addSuffix: true })}
                </p>
                {activity.details && Object.keys(activity.details).length > 0 && (
                  <details className="mt-2">
                    <summary className="text-xs text-neutral-500 dark:text-neutral-500 cursor-pointer hover:text-neutral-700 dark:hover:text-neutral-300">
                      View details
                    </summary>
                    <pre className="mt-2 text-xs bg-neutral-900 dark:bg-neutral-950 text-neutral-100 p-2 rounded overflow-x-auto">
                      {JSON.stringify(activity.details, null, 2)}
                    </pre>
                  </details>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
