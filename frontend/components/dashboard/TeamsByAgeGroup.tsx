/**
 * Teams by Age Group chart component
 */

'use client'

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { TeamsByAgeGroup } from '@/lib/dashboard'

interface TeamsByAgeGroupChartProps {
  data: TeamsByAgeGroup[]
}

export function TeamsByAgeGroupChart({ data }: TeamsByAgeGroupChartProps) {
  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 p-6">
      <h3 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 mb-4">
        Teams by Age Group & Gender
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-neutral-200 dark:stroke-neutral-800" />
          <XAxis
            dataKey="ageGroup"
            className="text-neutral-600 dark:text-neutral-400"
            tick={{ fill: 'currentColor' }}
          />
          <YAxis
            className="text-neutral-600 dark:text-neutral-400"
            tick={{ fill: 'currentColor' }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'rgb(23 23 23)',
              border: '1px solid rgb(38 38 38)',
              borderRadius: '0.5rem',
              color: 'rgb(245 245 245)',
            }}
          />
          <Legend />
          <Bar dataKey="boys" fill="#3b82f6" name="Boys" />
          <Bar dataKey="girls" fill="#ec4899" name="Girls" />
        </BarChart>
      </ResponsiveContainer>
      <div className="mt-4 text-sm text-neutral-600 dark:text-neutral-400">
        Total teams across all age groups: {data.reduce((sum, d) => sum + d.total, 0).toLocaleString()}
      </div>
    </div>
  )
}
