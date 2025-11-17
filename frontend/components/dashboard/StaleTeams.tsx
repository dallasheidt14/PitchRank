/**
 * Stale teams alert component
 * Shows teams that haven't been updated/scraped recently
 */

'use client'

import { AlertTriangle } from 'lucide-react'
import { StaleTeam } from '@/lib/dashboard'
import { formatDistanceToNow } from 'date-fns'

interface StaleTeamsProps {
  teams: StaleTeam[]
  threshold: number
}

export function StaleTeams({ teams, threshold }: StaleTeamsProps) {
  if (teams.length === 0) {
    return (
      <div className="rounded-lg border border-green-200 dark:border-green-800 bg-green-50/50 dark:bg-green-950/50 p-6">
        <div className="flex items-center gap-3">
          <div className="text-green-600 dark:text-green-400">
            <svg
              className="h-6 w-6"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M5 13l4 4L19 7"
              />
            </svg>
          </div>
          <div>
            <h3 className="text-lg font-semibold text-green-900 dark:text-green-100">
              All Teams Up to Date
            </h3>
            <p className="text-sm text-green-700 dark:text-green-300">
              No teams found that haven't been updated in the last {threshold} days
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-yellow-200 dark:border-yellow-800 bg-yellow-50/50 dark:bg-yellow-950/50 p-6">
      <div className="flex items-center gap-3 mb-4">
        <AlertTriangle className="h-6 w-6 text-yellow-600 dark:text-yellow-400" />
        <div>
          <h3 className="text-lg font-semibold text-yellow-900 dark:text-yellow-100">
            Stale Teams Alert
          </h3>
          <p className="text-sm text-yellow-700 dark:text-yellow-300">
            {teams.length} team{teams.length !== 1 ? 's' : ''} haven't been updated in {threshold}+ days
          </p>
        </div>
      </div>

      <div className="mt-4 space-y-2 max-h-96 overflow-y-auto">
        {teams.slice(0, 20).map((team) => (
          <div
            key={team.id}
            className="flex items-center justify-between p-3 rounded-md bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800"
          >
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100 truncate">
                {team.name}
              </p>
              <p className="text-xs text-neutral-600 dark:text-neutral-400">
                {team.ageGroup} • {team.state}
              </p>
            </div>
            <div className="text-right ml-4">
              <p className="text-sm font-semibold text-yellow-600 dark:text-yellow-400">
                {team.daysSinceUpdate} days
              </p>
              <p className="text-xs text-neutral-500 dark:text-neutral-500">
                {formatDistanceToNow(new Date(team.lastScraped), { addSuffix: true })}
              </p>
            </div>
          </div>
        ))}
      </div>

      {teams.length > 20 && (
        <p className="mt-4 text-sm text-neutral-600 dark:text-neutral-400">
          Showing 20 of {teams.length} stale teams
        </p>
      )}
    </div>
  )
}
