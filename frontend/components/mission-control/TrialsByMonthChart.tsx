'use client';

import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { MonthTrials } from '@/lib/admin/month-projection';

const TICK = { fontSize: 11, fill: 'var(--muted-foreground)' };

/** Trials started per month, oldest first; the last month is the current one, counted to date. */
export function TrialsByMonthChart({ months }: { months: MonthTrials[] }) {
  const currentLabel = months.at(-1)?.label;
  const countText = (m: MonthTrials) =>
    `${m.trials} trial${m.trials === 1 ? '' : 's'}${m.label === currentLabel ? ' so far' : ''}`;
  const ariaLabel = `Trials started per month. ${months.map((m) => `${m.label}: ${countText(m)}`).join(', ')}.`;

  return (
    <div className="h-[220px] w-full" role="img" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={months} margin={{ top: 20, right: 8, left: 4, bottom: 0 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" className="stroke-muted" />
          <XAxis
            dataKey="label"
            tickFormatter={(label: string) => label.slice(0, 3)}
            tick={TICK}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
            minTickGap={8}
          />
          <YAxis tick={TICK} tickLine={false} axisLine={false} width={40} allowDecimals={false} />
          <Tooltip
            cursor={{ fill: 'var(--muted)' }}
            content={({
              active,
              payload,
            }: {
              active?: boolean;
              payload?: ReadonlyArray<{ payload?: MonthTrials }>;
            }) => {
              if (!active || !payload?.[0]?.payload) return null;
              const d = payload[0].payload;
              return (
                <div className="rounded-lg border bg-background p-2 shadow-md text-xs">
                  <p className="font-medium">{d.label}</p>
                  <p className="font-mono font-semibold">{countText(d)}</p>
                </div>
              );
            }}
          />
          <Bar dataKey="trials" fill="var(--primary)" radius={[4, 4, 0, 0]} maxBarSize={24}>
            <LabelList dataKey="trials" position="top" fontSize={11} className="fill-foreground" />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
