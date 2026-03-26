'use client'

/**
 * React hooks for performance monitoring.
 *
 * Usage:
 *   // In root layout or providers:
 *   useWebVitals()
 *
 *   // In any component:
 *   const renderTime = useRenderTime('RankingsTable')
 *
 *   // For API timing with React Query:
 *   useApiPerformance()
 */

import { useEffect, useRef } from 'react'
import {
  trackWebVitals,
  measureRender,
  printPerfReport,
} from '@/lib/performance'

/**
 * Initialize Web Vitals tracking. Call once in your root layout.
 */
export function useWebVitals() {
  useEffect(() => {
    trackWebVitals()

    // Print report on page hide (tab switch / close)
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        printPerfReport()
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [])
}

/**
 * Measure a component's mount render time.
 *
 * @param componentName - Name for the measurement
 * @returns Render duration in ms (0 until mount completes)
 */
function useRenderTime(componentName: string) {
  const durationRef = useRef(0)

  useEffect(() => {
    const m = measureRender(componentName)
    // requestAnimationFrame ensures we measure after paint
    const raf = requestAnimationFrame(() => {
      durationRef.current = m.end()
    })
    return () => cancelAnimationFrame(raf)
  }, [componentName])

  return durationRef
}

/**
 * Track when a component re-renders and how often.
 * Useful for detecting unnecessary re-renders.
 *
 * @param componentName - Name for logging
 */
function useRenderCount(componentName: string) {
  const count = useRef(0)
  const lastRender = useRef(Date.now())

  useEffect(() => {
    count.current += 1
    const now = Date.now()
    const delta = now - lastRender.current

    if (process.env.NODE_ENV === 'development' && count.current > 1) {
      if (delta < 100) {
        console.warn(
          `[RenderCount] ${componentName}: render #${count.current} ` +
          `(${delta}ms since last — possible unnecessary re-render)`
        )
      }
    }
    lastRender.current = now
  })

  return count
}
