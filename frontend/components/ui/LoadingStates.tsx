'use client';

import { Loader2 } from 'lucide-react';
import { Skeleton } from './skeleton';
import { cn } from '@/lib/utils';

interface InlineLoaderProps {
  text?: string;
  className?: string;
}

/**
 * InlineLoader - Small spinner with optional text for inline loading states
 */
export function InlineLoader({ text, className }: InlineLoaderProps) {
  return (
    <div className={cn('flex items-center gap-2 text-sm text-muted-foreground', className)}>
      <Loader2 className="h-4 w-4 animate-spin" />
      {text && <span>{text}</span>}
    </div>
  );
}

/**
 * FullPageLoader - Centered spinner for full page loads
 */
export function FullPageLoader() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-4">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    </div>
  );
}

interface ContentLoaderProps {
  rows?: number;
  className?: string;
}

/**
 * ContentLoader - Generic skeleton rows for content areas
 */
export function ContentLoader({ rows = 5, className }: ContentLoaderProps) {
  return (
    <div className={cn('space-y-2', className)}>
      {[...Array(rows)].map((_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}

