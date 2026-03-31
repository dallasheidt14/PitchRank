'use client';

import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

interface MetricCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  loading?: boolean;
}

export function MetricCard({ title, value, subtitle, loading }: MetricCardProps) {
  if (loading) {
    return (
      <Card variant="flat" className="bg-white/5 border-white/10">
        <CardContent>
          <Skeleton className="h-4 w-24 bg-white/10" />
          <Skeleton className="mt-2 h-8 w-16 bg-white/10" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card variant="flat" className="bg-white/5 border-white/10">
      <CardContent>
        <p className="text-sm text-gray-400">{title}</p>
        <p className="mt-1 text-2xl font-semibold text-white">{value}</p>
        {subtitle && <p className="mt-1 text-xs text-gray-500">{subtitle}</p>}
      </CardContent>
    </Card>
  );
}
