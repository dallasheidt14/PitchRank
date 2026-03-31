'use client';

import { useFunnelData } from '@/hooks/useAnalytics';
import { formatPercent } from '@/lib/analytics-utils';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { MetricCard } from './MetricCard';
import { Skeleton } from '@/components/ui/skeleton';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';

const FUNNEL_COLORS = ['#22c55e', '#3b82f6', '#f59e0b', '#ef4444'];

interface FunnelTabProps {
  range: string;
}

export function FunnelTab({ range }: FunnelTabProps) {
  const { data, isLoading, error, refetch } = useFunnelData(range);

  if (error) {
    return <ErrorDisplay error={error} retry={refetch} />;
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-64 w-full bg-white/10" />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-24 bg-white/10" />
          ))}
        </div>
      </div>
    );
  }

  if (!data) return null;

  const chartData = data.funnel.map((step, i) => ({
    name: step.label,
    count: step.count,
    fill: FUNNEL_COLORS[i],
  }));

  return (
    <div className="space-y-6">
      {/* Funnel chart */}
      <div>
        <h3 className="mb-3 text-lg font-semibold text-white">Upgrade Funnel</h3>
        <div className="rounded-lg border border-white/10 bg-white/5 p-4">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={chartData} layout="vertical" margin={{ left: 20, right: 40 }}>
              <XAxis type="number" stroke="#9ca3af" fontSize={12} />
              <YAxis type="category" dataKey="name" stroke="#9ca3af" fontSize={12} width={120} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1f2937',
                  border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: '8px',
                  color: '#fff',
                }}
                formatter={(value) => [Number(value).toLocaleString(), 'Events']}
              />
              <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                {chartData.map((entry, i) => (
                  <Cell key={entry.name} fill={FUNNEL_COLORS[i]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Conversion rate cards */}
      <div>
        <h3 className="mb-3 text-lg font-semibold text-white">Conversion Rates</h3>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <MetricCard
            title="View → Plan"
            value={formatPercent(data.conversionRates.viewToPlanSelected)}
            subtitle="Selected a plan"
          />
          <MetricCard
            title="Plan → Checkout"
            value={formatPercent(data.conversionRates.planToCheckout)}
            subtitle="Started checkout"
          />
          <MetricCard
            title="Checkout → Subscribe"
            value={formatPercent(data.conversionRates.checkoutToComplete)}
            subtitle="Completed payment"
          />
          <MetricCard
            title="Overall Conversion"
            value={formatPercent(data.conversionRates.overallConversion)}
            subtitle="View to subscribe"
          />
          <MetricCard
            title="Cart Abandonment"
            value={formatPercent(data.conversionRates.cartAbandonmentRate)}
            subtitle="Started but didn't finish"
          />
        </div>
      </div>

      {/* Raw event counts */}
      <div>
        <h3 className="mb-3 text-lg font-semibold text-white">Event Counts</h3>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {data.funnel.map((step, i) => (
            <MetricCard
              key={step.event}
              title={step.label}
              value={step.count.toLocaleString()}
              subtitle={
                i > 0 && data.funnel[0].count > 0
                  ? `${formatPercent(step.count / data.funnel[0].count)} of views`
                  : undefined
              }
            />
          ))}
        </div>
      </div>
    </div>
  );
}
