/**
 * Frontend Performance Monitoring Utilities
 *
 * Tracks Web Vitals (LCP, FID, CLS, INP, TTFB), API response times,
 * component render times, and bundle load performance.
 *
 * Usage:
 *   import { trackWebVitals, apiTimer, measureRender } from '@/lib/performance'
 *
 *   // In layout.tsx or root component:
 *   trackWebVitals()
 *
 *   // For API calls:
 *   const data = await apiTimer('getRankings', () => api.getRankings(params))
 *
 *   // For components:
 *   const renderTime = measureRender('RankingsTable')
 */

// ─── Types ───────────────────────────────────────────────────────────

interface PerfEntry {
  name: string
  value: number
  rating: 'good' | 'needs-improvement' | 'poor'
  timestamp: number
}

interface ApiTimingEntry {
  endpoint: string
  method: string
  duration_ms: number
  status: 'success' | 'error'
  timestamp: number
  metadata?: Record<string, unknown>
}

interface PerfConfig {
  /** Log to console in development */
  logToConsole: boolean
  /** Send metrics to analytics endpoint */
  reportEndpoint?: string
  /** Slow API threshold in ms */
  slowApiThreshold: number
  /** Enable detailed logging */
  verbose: boolean
}

// ─── Configuration ───────────────────────────────────────────────────

const DEFAULT_CONFIG: PerfConfig = {
  logToConsole: process.env.NODE_ENV === 'development',
  slowApiThreshold: 1000,
  verbose: false,
}

let config: PerfConfig = { ...DEFAULT_CONFIG }

export function configurePerfMonitoring(overrides: Partial<PerfConfig>) {
  config = { ...config, ...overrides }
}

// ─── Storage ─────────────────────────────────────────────────────────

const vitals: PerfEntry[] = []
const apiTimings: ApiTimingEntry[] = []

// ─── Web Vitals ──────────────────────────────────────────────────────

/** Web Vitals thresholds per https://web.dev/vitals/ */
const THRESHOLDS = {
  LCP: { good: 2500, poor: 4000 },
  FID: { good: 100, poor: 300 },
  CLS: { good: 0.1, poor: 0.25 },
  INP: { good: 200, poor: 500 },
  TTFB: { good: 800, poor: 1800 },
} as const

type MetricName = keyof typeof THRESHOLDS

function rateMetric(name: MetricName, value: number): PerfEntry['rating'] {
  const t = THRESHOLDS[name]
  if (value <= t.good) return 'good'
  if (value <= t.poor) return 'needs-improvement'
  return 'poor'
}

/**
 * Track Core Web Vitals using PerformanceObserver.
 * Call once in your root layout or _app component.
 */
export function trackWebVitals() {
  if (typeof window === 'undefined' || typeof PerformanceObserver === 'undefined') return

  // LCP - Largest Contentful Paint
  try {
    const lcpObserver = new PerformanceObserver((list) => {
      const entries = list.getEntries()
      const last = entries[entries.length - 1]
      if (last) {
        const value = last.startTime
        recordVital('LCP', value)
      }
    })
    lcpObserver.observe({ type: 'largest-contentful-paint', buffered: true })
  } catch { /* Observer not supported */ }

  // FID - First Input Delay
  try {
    const fidObserver = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const e = entry as PerformanceEventTiming
        const value = e.processingStart - e.startTime
        recordVital('FID', value)
      }
    })
    fidObserver.observe({ type: 'first-input', buffered: true })
  } catch { /* Observer not supported */ }

  // CLS - Cumulative Layout Shift
  try {
    let clsValue = 0
    const clsObserver = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const e = entry as LayoutShift
        if (!e.hadRecentInput) {
          clsValue += e.value
          recordVital('CLS', clsValue)
        }
      }
    })
    clsObserver.observe({ type: 'layout-shift', buffered: true })
  } catch { /* Observer not supported */ }

  // INP - Interaction to Next Paint
  try {
    const inpObserver = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const e = entry as PerformanceEventTiming
        const value = e.duration
        recordVital('INP', value)
      }
    })
    inpObserver.observe({ type: 'event', buffered: true })
  } catch { /* Observer not supported */ }

  // TTFB - Time to First Byte
  try {
    const navObserver = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const nav = entry as PerformanceNavigationTiming
        const value = nav.responseStart - nav.requestStart
        recordVital('TTFB', value)
      }
    })
    navObserver.observe({ type: 'navigation', buffered: true })
  } catch { /* Observer not supported */ }
}

function recordVital(name: MetricName, value: number) {
  const entry: PerfEntry = {
    name,
    value: Math.round(name === 'CLS' ? value * 1000 : value) / (name === 'CLS' ? 1000 : 1),
    rating: rateMetric(name, value),
    timestamp: Date.now(),
  }
  vitals.push(entry)

  if (config.logToConsole) {
    const emoji = entry.rating === 'good' ? '✅' : entry.rating === 'needs-improvement' ? '⚠️' : '❌'
    const unit = name === 'CLS' ? '' : 'ms'
    console.log(
      `%c[Perf] ${emoji} ${name}: ${entry.value}${unit} (${entry.rating})`,
      `color: ${entry.rating === 'good' ? 'green' : entry.rating === 'poor' ? 'red' : 'orange'}`
    )
  }

  if (config.reportEndpoint) {
    navigator.sendBeacon?.(config.reportEndpoint, JSON.stringify(entry))
  }
}

// ─── API Timing ──────────────────────────────────────────────────────

/**
 * Measure an async API call's duration.
 *
 * @param endpoint - Name/description of the API call
 * @param fn - The async function to measure
 * @param metadata - Optional metadata (params, filters, etc.)
 * @returns The result of the function
 *
 * Usage:
 *   const rankings = await apiTimer('getRankings', () => getRankings({ age: '14' }))
 */
export async function apiTimer<T>(
  endpoint: string,
  fn: () => Promise<T>,
  metadata?: Record<string, unknown>,
): Promise<T> {
  const start = performance.now()
  let status: 'success' | 'error' = 'success'

  try {
    const result = await fn()
    return result
  } catch (error) {
    status = 'error'
    throw error
  } finally {
    const duration_ms = performance.now() - start
    const entry: ApiTimingEntry = {
      endpoint,
      method: 'async',
      duration_ms: Math.round(duration_ms * 100) / 100,
      status,
      timestamp: Date.now(),
      metadata,
    }
    apiTimings.push(entry)

    if (config.logToConsole) {
      const isSlow = duration_ms > config.slowApiThreshold
      console.log(
        `%c[API] ${isSlow ? '🐢' : '⚡'} ${endpoint}: ${duration_ms.toFixed(0)}ms (${status})`,
        `color: ${isSlow ? 'red' : status === 'error' ? 'orange' : 'gray'}`
      )
    }
  }
}

// ─── Component Render Timing ─────────────────────────────────────────

/**
 * Measure component render time using Performance API marks.
 *
 * Usage in a component:
 *   useEffect(() => {
 *     const measure = measureRender('RankingsTable')
 *     return measure.end
 *   }, [])
 */
export function measureRender(componentName: string) {
  const markStart = `render-start-${componentName}-${Date.now()}`
  const markEnd = `render-end-${componentName}-${Date.now()}`

  if (typeof performance !== 'undefined') {
    performance.mark(markStart)
  }

  return {
    end: () => {
      if (typeof performance === 'undefined') return 0
      performance.mark(markEnd)
      try {
        const measure = performance.measure(
          `render-${componentName}`,
          markStart,
          markEnd,
        )
        const duration = measure.duration
        if (config.logToConsole && config.verbose) {
          console.log(`[Render] ${componentName}: ${duration.toFixed(1)}ms`)
        }
        return duration
      } catch {
        return 0
      }
    },
  }
}

// ─── Bundle Size Tracking ────────────────────────────────────────────

/**
 * Track resource loading performance (JS bundles, images, fonts).
 * Call after page load to get resource timing data.
 */
export function getResourceTimings(): {
  scripts: { name: string; size: number; duration: number }[]
  totalJsSize: number
  totalLoadTime: number
} {
  if (typeof performance === 'undefined') {
    return { scripts: [], totalJsSize: 0, totalLoadTime: 0 }
  }

  const resources = performance.getEntriesByType('resource') as PerformanceResourceTiming[]
  const scripts = resources
    .filter((r) => r.initiatorType === 'script' || r.name.endsWith('.js'))
    .map((r) => ({
      name: r.name.split('/').pop() || r.name,
      size: r.transferSize,
      duration: Math.round(r.duration),
    }))
    .sort((a, b) => b.size - a.size)

  return {
    scripts,
    totalJsSize: scripts.reduce((sum, s) => sum + s.size, 0),
    totalLoadTime: scripts.reduce((sum, s) => sum + s.duration, 0),
  }
}

// ─── Reporting ───────────────────────────────────────────────────────

/**
 * Get all collected performance data.
 */
export function getPerfReport() {
  return {
    vitals: [...vitals],
    apiTimings: [...apiTimings],
    resources: getResourceTimings(),
    summary: {
      totalApiCalls: apiTimings.length,
      avgApiTime:
        apiTimings.length > 0
          ? Math.round(apiTimings.reduce((s, t) => s + t.duration_ms, 0) / apiTimings.length)
          : 0,
      slowApiCalls: apiTimings.filter((t) => t.duration_ms > config.slowApiThreshold).length,
      errorApiCalls: apiTimings.filter((t) => t.status === 'error').length,
    },
  }
}

/**
 * Print a formatted performance report to console.
 */
export function printPerfReport() {
  const report = getPerfReport()

  console.group('📊 Performance Report')

  if (report.vitals.length > 0) {
    console.group('Web Vitals')
    const latest = new Map<string, PerfEntry>()
    for (const v of report.vitals) {
      latest.set(v.name, v)
    }
    for (const [, entry] of latest) {
      const unit = entry.name === 'CLS' ? '' : 'ms'
      console.log(`${entry.name}: ${entry.value}${unit} (${entry.rating})`)
    }
    console.groupEnd()
  }

  if (report.apiTimings.length > 0) {
    console.group(`API Calls (${report.summary.totalApiCalls} total)`)
    console.log(`Avg: ${report.summary.avgApiTime}ms`)
    console.log(`Slow (>${config.slowApiThreshold}ms): ${report.summary.slowApiCalls}`)
    console.log(`Errors: ${report.summary.errorApiCalls}`)

    // Top 5 slowest
    const sorted = [...report.apiTimings].sort((a, b) => b.duration_ms - a.duration_ms)
    console.group('Slowest calls')
    for (const call of sorted.slice(0, 5)) {
      console.log(`${call.duration_ms.toFixed(0)}ms - ${call.endpoint} (${call.status})`)
    }
    console.groupEnd()
    console.groupEnd()
  }

  if (report.resources.scripts.length > 0) {
    console.group('JS Bundles')
    console.log(`Total: ${(report.resources.totalJsSize / 1024).toFixed(0)} KB`)
    for (const s of report.resources.scripts.slice(0, 5)) {
      console.log(`${(s.size / 1024).toFixed(0)} KB - ${s.name} (${s.duration}ms)`)
    }
    console.groupEnd()
  }

  console.groupEnd()
}

// ─── Type augmentations ──────────────────────────────────────────────

interface PerformanceEventTiming extends PerformanceEntry {
  processingStart: number
  duration: number
}

interface LayoutShift extends PerformanceEntry {
  hadRecentInput: boolean
  value: number
}
