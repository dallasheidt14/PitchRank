'use client';

import { useEffect } from 'react';
import { TooltipProvider } from '@/components/ui/tooltip';

export function SiteProviders({ children }: { children: React.ReactNode }) {
  // Handle unhandled promise rejections
  useEffect(() => {
    const handleUnhandledRejection = (event: PromiseRejectionEvent) => {
      console.error('Unhandled promise rejection:', event.reason);
      // Prevent the default browser behavior (console error)
      // but still log for debugging
    };

    window.addEventListener('unhandledrejection', handleUnhandledRejection);

    return () => {
      window.removeEventListener('unhandledrejection', handleUnhandledRejection);
    };
  }, []);

  return (
    <TooltipProvider delayDuration={300} skipDelayDuration={100}>
      {children}
    </TooltipProvider>
  );
}
