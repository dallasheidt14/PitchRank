'use client';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { AlertCircle, Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';

export type TileState =
  | { status: 'loading' }
  | { status: 'error'; message: string; retry?: () => void }
  | { status: 'empty'; suggestion?: string }
  | { status: 'success' };

export function TileShell({
  title,
  description,
  state,
  children,
}: {
  title: string;
  description?: string;
  state: TileState;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>
        {state.status === 'loading' && (
          <div className="flex items-center gap-2 text-muted-foreground py-8 justify-center">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        )}
        {state.status === 'error' && (
          <div className="flex flex-col items-center gap-2 text-destructive py-8">
            <AlertCircle className="h-4 w-4" />
            <span className="text-sm">{state.message}</span>
            {state.retry && (
              <button className="text-xs underline" onClick={state.retry}>
                Retry
              </button>
            )}
          </div>
        )}
        {state.status === 'empty' && (
          <div className="text-sm text-muted-foreground py-8 text-center">
            No data for this range. {state.suggestion}
          </div>
        )}
        {state.status === 'success' && children}
      </CardContent>
    </Card>
  );
}
