/**
 * Reusable metrics card component for the dashboard
 */

import { LucideIcon } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

interface MetricsCardProps {
  title: string
  value: string | number
  icon: LucideIcon
  description?: string
  trend?: {
    value: number
    label: string
  }
  lastUpdated?: string
  variant?: 'default' | 'success' | 'warning' | 'danger'
}

export function MetricsCard({
  title,
  value,
  icon: Icon,
  description,
  trend,
  lastUpdated,
  variant = 'default',
}: MetricsCardProps) {
  const variantStyles = {
    default: 'border-neutral-200 dark:border-neutral-800',
    success: 'border-green-200 dark:border-green-800 bg-green-50/50 dark:bg-green-950/50',
    warning: 'border-yellow-200 dark:border-yellow-800 bg-yellow-50/50 dark:bg-yellow-950/50',
    danger: 'border-red-200 dark:border-red-800 bg-red-50/50 dark:bg-red-950/50',
  }

  const iconStyles = {
    default: 'text-neutral-600 dark:text-neutral-400',
    success: 'text-green-600 dark:text-green-400',
    warning: 'text-yellow-600 dark:text-yellow-400',
    danger: 'text-red-600 dark:text-red-400',
  }

  return (
    <div
      className={`rounded-lg border p-6 ${variantStyles[variant]} transition-all hover:shadow-lg`}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <p className="text-sm font-medium text-neutral-600 dark:text-neutral-400">
            {title}
          </p>
          <p className="mt-2 text-3xl font-bold text-neutral-900 dark:text-neutral-100">
            {value.toLocaleString()}
          </p>
          {description && (
            <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-500">
              {description}
            </p>
          )}
          {trend && (
            <div className="mt-2 flex items-center gap-1">
              <span
                className={`text-sm font-medium ${
                  trend.value > 0
                    ? 'text-green-600 dark:text-green-400'
                    : trend.value < 0
                    ? 'text-red-600 dark:text-red-400'
                    : 'text-neutral-600 dark:text-neutral-400'
                }`}
              >
                {trend.value > 0 ? '+' : ''}
                {trend.value}%
              </span>
              <span className="text-sm text-neutral-500 dark:text-neutral-500">
                {trend.label}
              </span>
            </div>
          )}
          {lastUpdated && (
            <p className="mt-2 text-xs text-neutral-400 dark:text-neutral-600">
              Updated {formatDistanceToNow(new Date(lastUpdated), { addSuffix: true })}
            </p>
          )}
        </div>
        <div className={`rounded-full p-3 ${iconStyles[variant]} bg-white dark:bg-neutral-900`}>
          <Icon className="h-6 w-6" />
        </div>
      </div>
    </div>
  )
}
