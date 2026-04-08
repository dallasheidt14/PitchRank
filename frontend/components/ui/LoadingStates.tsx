'use client';

import { Loader2 } from 'lucide-react';
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
