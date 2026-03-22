/**
 * k6 Load Testing Script for PitchRank API
 *
 * Tests the main API endpoints under load to identify bottlenecks.
 *
 * Prerequisites:
 *   brew install k6  (macOS)
 *   sudo apt install k6  (Ubuntu)
 *   choco install k6  (Windows)
 *
 * Usage:
 *   # Quick smoke test (1 user, 30s)
 *   k6 run scripts/load_test.js --env TARGET=http://localhost:3000
 *
 *   # Load test (50 users ramping up over 2 min)
 *   k6 run scripts/load_test.js --env TARGET=http://localhost:3000 --env SCENARIO=load
 *
 *   # Stress test (100 users, find breaking point)
 *   k6 run scripts/load_test.js --env TARGET=http://localhost:3000 --env SCENARIO=stress
 *
 *   # Output results to JSON
 *   k6 run scripts/load_test.js --out json=data/profiles/load_test_results.json
 */

import http from 'k6/http'
import { check, sleep, group } from 'k6'
import { Rate, Trend, Counter } from 'k6/metrics'

// ─── Custom Metrics ──────────────────────────────────────────────────

const errorRate = new Rate('errors')
const rankingsLatency = new Trend('rankings_latency', true)
const searchLatency = new Trend('search_latency', true)
const teamDetailLatency = new Trend('team_detail_latency', true)
const apiCalls = new Counter('api_calls')

// ─── Configuration ───────────────────────────────────────────────────

const BASE_URL = __ENV.TARGET || 'http://localhost:3000'
const SCENARIO = __ENV.SCENARIO || 'smoke'

const scenarios = {
  smoke: {
    executor: 'constant-vus',
    vus: 1,
    duration: '30s',
  },
  load: {
    executor: 'ramping-vus',
    startVUs: 0,
    stages: [
      { duration: '30s', target: 10 },
      { duration: '1m', target: 25 },
      { duration: '1m', target: 50 },
      { duration: '30s', target: 50 },
      { duration: '30s', target: 0 },
    ],
  },
  stress: {
    executor: 'ramping-vus',
    startVUs: 0,
    stages: [
      { duration: '30s', target: 25 },
      { duration: '1m', target: 50 },
      { duration: '1m', target: 100 },
      { duration: '2m', target: 100 },
      { duration: '30s', target: 0 },
    ],
  },
  spike: {
    executor: 'ramping-vus',
    startVUs: 0,
    stages: [
      { duration: '10s', target: 5 },
      { duration: '5s', target: 100 },
      { duration: '30s', target: 100 },
      { duration: '10s', target: 5 },
      { duration: '30s', target: 5 },
    ],
  },
}

export const options = {
  scenarios: {
    default: scenarios[SCENARIO] || scenarios.smoke,
  },
  thresholds: {
    http_req_duration: ['p(95)<2000', 'p(99)<5000'],
    errors: ['rate<0.05'],
    rankings_latency: ['p(95)<3000'],
    search_latency: ['p(95)<1500'],
    team_detail_latency: ['p(95)<2000'],
  },
}

// ─── Test Data ───────────────────────────────────────────────────────

const AGE_GROUPS = ['U10', 'U11', 'U12', 'U13', 'U14', 'U15', 'U16', 'U17', 'U18']
const GENDERS = ['Male', 'Female']
const REGIONS = ['national', 'west', 'east', 'south', 'midwest']
const SEARCH_TERMS = [
  'FC Barcelona',
  'Real Salt Lake',
  'Surf',
  'ECNL',
  'Arsenal',
  'Galaxy',
  'United',
  'City',
  'Rapids',
  'Thorns',
]

function randomItem(arr) {
  return arr[Math.floor(Math.random() * arr.length)]
}

// ─── Test Scenarios ──────────────────────────────────────────────────

export default function () {
  // Simulate realistic user behavior: browse rankings, search, view team detail

  group('Homepage', () => {
    const res = http.get(`${BASE_URL}/`)
    check(res, {
      'homepage status 200': (r) => r.status === 200,
      'homepage loads under 3s': (r) => r.timings.duration < 3000,
    })
    errorRate.add(res.status !== 200)
    apiCalls.add(1)
    sleep(1)
  })

  group('Rankings Page', () => {
    const age = randomItem(AGE_GROUPS)
    const gender = randomItem(GENDERS)
    const region = randomItem(REGIONS)

    // API endpoint for rankings data
    const res = http.get(
      `${BASE_URL}/api/rankings?age_group=${age}&gender=${gender}&region=${region}`,
      { tags: { name: 'GET /api/rankings' } }
    )

    check(res, {
      'rankings status 200': (r) => r.status === 200,
      'rankings has data': (r) => {
        try {
          const body = JSON.parse(r.body)
          return Array.isArray(body) || (body && body.data)
        } catch {
          return false
        }
      },
    })

    rankingsLatency.add(res.timings.duration)
    errorRate.add(res.status !== 200)
    apiCalls.add(1)
    sleep(2)
  })

  group('Team Search', () => {
    const query = randomItem(SEARCH_TERMS)
    const res = http.get(
      `${BASE_URL}/api/teams/search?q=${encodeURIComponent(query)}`,
      { tags: { name: 'GET /api/teams/search' } }
    )

    check(res, {
      'search status 200': (r) => r.status === 200,
      'search returns results': (r) => {
        try {
          const body = JSON.parse(r.body)
          return Array.isArray(body) ? body.length > 0 : true
        } catch {
          return false
        }
      },
      'search under 1.5s': (r) => r.timings.duration < 1500,
    })

    searchLatency.add(res.timings.duration)
    errorRate.add(res.status !== 200)
    apiCalls.add(1)
    sleep(1)
  })

  group('Team Detail', () => {
    // First search for a team, then load its detail page
    const query = randomItem(SEARCH_TERMS)
    const searchRes = http.get(
      `${BASE_URL}/api/teams/search?q=${encodeURIComponent(query)}`,
      { tags: { name: 'GET /api/teams/search' } }
    )

    if (searchRes.status === 200) {
      try {
        const results = JSON.parse(searchRes.body)
        const teams = Array.isArray(results) ? results : results?.data || []
        if (teams.length > 0) {
          const team = randomItem(teams)
          const teamId = team.id || team.team_id
          if (teamId) {
            const detailRes = http.get(
              `${BASE_URL}/api/teams/${teamId}`,
              { tags: { name: 'GET /api/teams/:id' } }
            )
            check(detailRes, {
              'team detail status 200': (r) => r.status === 200,
            })
            teamDetailLatency.add(detailRes.timings.duration)
            errorRate.add(detailRes.status !== 200)
            apiCalls.add(1)
          }
        }
      } catch {
        // Search returned non-JSON
      }
    }
    sleep(2)
  })
}

// ─── Lifecycle Hooks ─────────────────────────────────────────────────

export function handleSummary(data) {
  return {
    stdout: textSummary(data),
  }
}

function textSummary(data) {
  const metrics = data.metrics
  const lines = [
    '\n============================================================',
    ' PitchRank Load Test Results',
    '============================================================',
    `  Scenario:         ${SCENARIO}`,
    `  Target:           ${BASE_URL}`,
    '',
  ]

  if (metrics.http_req_duration) {
    const d = metrics.http_req_duration.values
    lines.push('  HTTP Request Duration:')
    lines.push(`    avg:  ${d.avg?.toFixed(0) || 'N/A'}ms`)
    lines.push(`    p50:  ${d['p(50)']?.toFixed(0) || 'N/A'}ms`)
    lines.push(`    p95:  ${d['p(95)']?.toFixed(0) || 'N/A'}ms`)
    lines.push(`    p99:  ${d['p(99)']?.toFixed(0) || 'N/A'}ms`)
    lines.push(`    max:  ${d.max?.toFixed(0) || 'N/A'}ms`)
  }

  if (metrics.http_reqs) {
    lines.push(`\n  Total requests:   ${metrics.http_reqs.values.count}`)
    lines.push(`  Requests/sec:     ${metrics.http_reqs.values.rate?.toFixed(1)}`)
  }

  if (metrics.errors) {
    lines.push(`  Error rate:       ${(metrics.errors.values.rate * 100).toFixed(2)}%`)
  }

  lines.push('\n============================================================\n')
  return lines.join('\n')
}
