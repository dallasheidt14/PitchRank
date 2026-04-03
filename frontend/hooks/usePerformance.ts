'use client';

/**
 * React hooks for performance monitoring.
 *
 * Usage:
 *   // In root layout or providers:
 *   useWebVitals()
 */

import { useEffect } from 'react';
import { trackWebVitals, printPerfReport } from '@/lib/performance';

/**
 * Initialize Web Vitals tracking. Call once in your root layout.
 */
export function useWebVitals() {
  useEffect(() => {
    trackWebVitals();

    // Print report on page hide (tab switch / close)
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        printPerfReport();
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);
}
