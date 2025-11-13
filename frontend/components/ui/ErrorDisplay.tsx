'use client';

import { AlertCircle, Wifi, WifiOff } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { getErrorMessage, isNetworkError } from '@/lib/errors';
import type { ReactNode } from 'react';

interface ErrorDisplayProps {
  error: unknown;
  retry?: () => void;
  compact?: boolean;
  fallback?: ReactNode;
}

/**
 * ErrorDisplay component - displays consistent error messages across the app
 * Shows WiFi icon for network errors, AlertCircle for others
 * Includes retry button when retry callback is provided
 */
export function ErrorDisplay({ error, retry, compact = false, fallback }: ErrorDisplayProps) {
  const message = getErrorMessage(error);
  const isNetwork = isNetworkError(error);

  // If fallback is provided and error is not critical, show fallback
  if (fallback && !isNetwork) {
    return <>{fallback}</>;
  }

  const Icon = isNetwork ? WifiOff : AlertCircle;
  const errorTitle = isNetwork ? 'Connection Error' : 'Error';
  const errorDescription = isNetwork
    ? 'Unable to connect to the server. Please check your internet connection.'
    : message;

  if (compact) {
    return (
      <div className="flex items-center gap-2 text-sm text-destructive">
        <Icon className="h-4 w-4 shrink-0" />
        <span className="flex-1">{errorDescription}</span>
        {retry && (
          <Button variant="outline" size="sm" onClick={retry}>
            Try Again
          </Button>
        )}
      </div>
    );
  }

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex flex-col items-center justify-center gap-4 py-8 text-center">
          <div className="rounded-full bg-destructive/10 p-4">
            <Icon className="h-8 w-8 text-destructive" />
          </div>
          <div className="space-y-2">
            <h3 className="text-lg font-semibold">{errorTitle}</h3>
            <p className="text-sm text-muted-foreground max-w-md">{errorDescription}</p>
          </div>
          {retry && (
            <Button onClick={retry} variant="default">
              Try Again
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

