/**
 * Teams by State chart component
 */

'use client'

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { TeamsByState } from '@/lib/dashboard'

interface TeamsByStateChartProps {
  data: TeamsByState[]
}

export function TeamsByStateChart({ data }: TeamsByStateChartProps) {
  // Take top 15 for better visualization
  const topStates = data.slice(0, 15)

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-6">
      <h3 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 mb-4">
        Teams by State (Top 15)
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={topStates} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" className="stroke-neutral-200 dark:stroke-neutral-800" />
          <XAxis
            type="number"
            className="text-neutral-600 dark:text-neutral-400"
            tick={{ fill: 'currentColor' }}
          />
          <YAxis
            type="category"
            dataKey="state"
            className="text-neutral-600 dark:text-neutral-400"
            tick={{ fill: 'currentColor' }}
            width={50}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'rgb(23 23 23)',
              border: '1px solid rgb(38 38 38)',
              borderRadius: '0.5rem',
              color: 'rgb(245 245 245)',
            }}
          />
          <Bar dataKey="count" fill="#8b5cf6" name="Teams" />
        </BarChart>
      </ResponsiveContainer>
      <div className="mt-4 text-sm text-neutral-600 dark:text-neutral-400">
        Showing top 15 states out of {data.length} total states/regions
      </div>
    </div>
  )
}
