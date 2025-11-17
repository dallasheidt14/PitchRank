/**
 * GitHub Actions workflow status monitor
 */

'use client'

import { CheckCircle2, XCircle, Clock, GitBranch, ExternalLink } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

interface WorkflowRun {
  name: string
  status: 'success' | 'failure' | 'in_progress' | 'cancelled'
  lastRun: string
  duration?: number
  url: string
}

interface WorkflowStatusProps {
  workflows: WorkflowRun[]
}

export function WorkflowStatus({ workflows }: WorkflowStatusProps) {
  const getStatusIcon = (status: WorkflowRun['status']) => {
    switch (status) {
      case 'success':
        return <CheckCircle2 className="h-5 w-5 text-green-500" />
      case 'failure':
        return <XCircle className="h-5 w-5 text-red-500" />
      case 'in_progress':
        return <Clock className="h-5 w-5 text-blue-500 animate-spin" />
      case 'cancelled':
        return <XCircle className="h-5 w-5 text-neutral-500" />
    }
  }

  const getStatusColor = (status: WorkflowRun['status']) => {
    switch (status) {
      case 'success':
        return 'bg-green-50 dark:bg-green-950/50 border-green-200 dark:border-green-800'
      case 'failure':
        return 'bg-red-50 dark:bg-red-950/50 border-red-200 dark:border-red-800'
      case 'in_progress':
        return 'bg-blue-50 dark:bg-blue-950/50 border-blue-200 dark:border-blue-800'
      case 'cancelled':
        return 'bg-neutral-50 dark:bg-neutral-950/50 border-neutral-200 dark:border-neutral-800'
    }
  }

  const formatDuration = (seconds?: number) => {
    if (!seconds) return 'N/A'
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}m ${secs}s`
  }

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-6">
      <div className="flex items-center gap-2 mb-4">
        <GitBranch className="h-5 w-5 text-neutral-600 dark:text-neutral-400" />
        <h3 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
          GitHub Actions Status
        </h3>
      </div>

      {workflows.length === 0 ? (
        <div className="text-center py-8">
          <p className="text-neutral-600 dark:text-neutral-400">No workflow data available</p>
          <p className="text-sm text-neutral-500 dark:text-neutral-500 mt-2">
            Workflows will appear here once they start running
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {workflows.map((workflow, index) => (
            <div
              key={index}
              className={`flex items-center justify-between p-3 rounded-md border ${getStatusColor(workflow.status)}`}
            >
              <div className="flex items-center gap-3 flex-1 min-w-0">
                {getStatusIcon(workflow.status)}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100 truncate">
                    {workflow.name}
                  </p>
                  <div className="flex items-center gap-3 mt-1">
                    <p className="text-xs text-neutral-600 dark:text-neutral-400">
                      {formatDistanceToNow(new Date(workflow.lastRun), { addSuffix: true })}
                    </p>
                    {workflow.duration && (
                      <p className="text-xs text-neutral-500 dark:text-neutral-500">
                        {formatDuration(workflow.duration)}
                      </p>
                    )}
                  </div>
                </div>
              </div>
              <a
                href={workflow.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex-shrink-0 ml-2 p-2 hover:bg-white dark:hover:bg-neutral-900 rounded-md transition-colors"
                title="View workflow run"
              >
                <ExternalLink className="h-4 w-4 text-neutral-600 dark:text-neutral-400" />
              </a>
            </div>
          ))}
        </div>
      )}

      <div className="mt-4 pt-4 border-t border-neutral-200 dark:border-neutral-800">
        <a
          href="https://github.com/dallasheidt14/PitchRank/actions"
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
        >
          View all workflows on GitHub
          <ExternalLink className="h-3 w-3" />
        </a>
      </div>
    </div>
  )
}
