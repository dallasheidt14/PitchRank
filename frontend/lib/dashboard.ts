/**
 * Dashboard data fetching utilities
 * Provides analytics and monitoring data for the PitchRank admin dashboard
 */

import { createClient } from '@/lib/supabase'

export interface DashboardMetrics {
  totalTeams: number
  totalGames: number
  totalRankings: number
  lastRankingRun: string | null
  lastDataImport: string | null
}

export interface TeamsByAgeGroup {
  ageGroup: string
  boys: number
  girls: number
  total: number
}

export interface TeamsByState {
  state: string
  count: number
}

export interface StaleTeam {
  id: string
  name: string
  ageGroup: string
  state: string
  lastScraped: string
  daysSinceUpdate: number
}

export interface RecentActivity {
  id: string
  type: 'game_import' | 'team_import' | 'ranking_calculation' | 'scrape'
  description: string
  timestamp: string
  status: 'success' | 'error' | 'warning'
  details?: Record<string, any>
}

export interface WorkflowRun {
  name: string
  status: 'success' | 'failure' | 'in_progress' | 'cancelled'
  lastRun: string
  duration: number | null
  url: string
}

/**
 * Get overall dashboard metrics
 */
export async function getDashboardMetrics(): Promise<DashboardMetrics> {
  const supabase = createClient()

  try {
    // Get total teams
    const { count: totalTeams } = await supabase
      .from('teams')
      .select('*', { count: 'exact', head: true })

    // Get total games
    const { count: totalGames } = await supabase
      .from('games')
      .select('*', { count: 'exact', head: true })

    // Get total rankings (current rankings)
    const { count: totalRankings } = await supabase
      .from('rankings_full')
      .select('*', { count: 'exact', head: true })

    // Get last ranking run from build_logs
    const { data: lastRankingLog } = await supabase
      .from('build_logs')
      .select('completed_at')
      .eq('build_type', 'rankings')
      .order('completed_at', { ascending: false })
      .limit(1)
      .single()

    // Get last data import from build_logs
    const { data: lastImportLog } = await supabase
      .from('build_logs')
      .select('completed_at')
      .eq('build_type', 'import')
      .order('completed_at', { ascending: false })
      .limit(1)
      .single()

    return {
      totalTeams: totalTeams || 0,
      totalGames: totalGames || 0,
      totalRankings: totalRankings || 0,
      lastRankingRun: lastRankingLog?.completed_at || null,
      lastDataImport: lastImportLog?.completed_at || null,
    }
  } catch (error) {
    console.error('Error fetching dashboard metrics:', error)
    return {
      totalTeams: 0,
      totalGames: 0,
      totalRankings: 0,
      lastRankingRun: null,
      lastDataImport: null,
    }
  }
}

/**
 * Get teams grouped by age group and gender
 */
export async function getTeamsByAgeGroup(): Promise<TeamsByAgeGroup[]> {
  const supabase = createClient()

  try {
    const { data: teams } = await supabase
      .from('teams')
      .select('age_group, gender')

    if (!teams) return []

    // Group by age group and gender
    const grouped = teams.reduce((acc, team) => {
      const ageGroup = team.age_group || 'Unknown'
      if (!acc[ageGroup]) {
        acc[ageGroup] = { boys: 0, girls: 0 }
      }
      if (team.gender === 'boys') {
        acc[ageGroup].boys++
      } else if (team.gender === 'girls') {
        acc[ageGroup].girls++
      }
      return acc
    }, {} as Record<string, { boys: number; girls: number }>)

    // Convert to array and sort
    const ageGroupOrder = ['U10', 'U11', 'U12', 'U13', 'U14', 'U15', 'U16', 'U17', 'U18', 'U19']

    return Object.entries(grouped)
      .map(([ageGroup, counts]) => ({
        ageGroup,
        boys: counts.boys,
        girls: counts.girls,
        total: counts.boys + counts.girls,
      }))
      .sort((a, b) => {
        const aIndex = ageGroupOrder.indexOf(a.ageGroup)
        const bIndex = ageGroupOrder.indexOf(b.ageGroup)
        if (aIndex === -1) return 1
        if (bIndex === -1) return -1
        return aIndex - bIndex
      })
  } catch (error) {
    console.error('Error fetching teams by age group:', error)
    return []
  }
}

/**
 * Get teams grouped by state
 */
export async function getTeamsByState(): Promise<TeamsByState[]> {
  const supabase = createClient()

  try {
    const { data: teams } = await supabase
      .from('teams')
      .select('state')

    if (!teams) return []

    // Group by state
    const grouped = teams.reduce((acc, team) => {
      const state = team.state || 'Unknown'
      acc[state] = (acc[state] || 0) + 1
      return acc
    }, {} as Record<string, number>)

    // Convert to array and sort by count
    return Object.entries(grouped)
      .map(([state, count]) => ({ state, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 20) // Top 20 states
  } catch (error) {
    console.error('Error fetching teams by state:', error)
    return []
  }
}

/**
 * Get teams that haven't been scraped/updated recently
 */
export async function getStaleTeams(daysThreshold: number = 30): Promise<StaleTeam[]> {
  const supabase = createClient()

  try {
    // Calculate the threshold date
    const thresholdDate = new Date()
    thresholdDate.setDate(thresholdDate.getDate() - daysThreshold)

    const { data: teams } = await supabase
      .from('teams')
      .select('id, name, age_group, state, updated_at')
      .lt('updated_at', thresholdDate.toISOString())
      .order('updated_at', { ascending: true })
      .limit(50)

    if (!teams) return []

    return teams.map(team => {
      const lastScraped = new Date(team.updated_at)
      const now = new Date()
      const daysSinceUpdate = Math.floor((now.getTime() - lastScraped.getTime()) / (1000 * 60 * 60 * 24))

      return {
        id: team.id,
        name: team.name,
        ageGroup: team.age_group || 'Unknown',
        state: team.state || 'Unknown',
        lastScraped: team.updated_at,
        daysSinceUpdate,
      }
    })
  } catch (error) {
    console.error('Error fetching stale teams:', error)
    return []
  }
}

/**
 * Get recent activity from build logs
 */
export async function getRecentActivity(limit: number = 20): Promise<RecentActivity[]> {
  const supabase = createClient()

  try {
    const { data: logs } = await supabase
      .from('build_logs')
      .select('*')
      .order('started_at', { ascending: false })
      .limit(limit)

    if (!logs) return []

    return logs.map(log => {
      const type = log.build_type as RecentActivity['type']
      const status = log.status === 'completed' ? 'success' : log.status === 'failed' ? 'error' : 'warning'

      let description = ''
      if (type === 'rankings') {
        description = `Rankings calculation ${log.status}`
      } else if (type === 'import') {
        description = `Data import ${log.status}`
      } else if (type === 'scrape') {
        description = `Scrape operation ${log.status}`
      } else {
        description = `${log.build_type} ${log.status}`
      }

      return {
        id: log.id,
        type,
        description,
        timestamp: log.started_at,
        status,
        details: log.metadata,
      }
    })
  } catch (error) {
    console.error('Error fetching recent activity:', error)
    return []
  }
}

/**
 * Get team distribution by gender
 */
export async function getTeamsByGender(): Promise<{ gender: string; count: number }[]> {
  const supabase = createClient()

  try {
    const { data: teams } = await supabase
      .from('teams')
      .select('gender')

    if (!teams) return []

    const grouped = teams.reduce((acc, team) => {
      const gender = team.gender || 'Unknown'
      acc[gender] = (acc[gender] || 0) + 1
      return acc
    }, {} as Record<string, number>)

    return Object.entries(grouped)
      .map(([gender, count]) => ({ gender, count }))
      .sort((a, b) => b.count - a.count)
  } catch (error) {
    console.error('Error fetching teams by gender:', error)
    return []
  }
}

/**
 * Get games import statistics for the last 30 days
 */
export async function getGamesImportStats(): Promise<{ date: string; count: number }[]> {
  const supabase = createClient()

  try {
    const thirtyDaysAgo = new Date()
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30)

    const { data: games } = await supabase
      .from('games')
      .select('created_at')
      .gte('created_at', thirtyDaysAgo.toISOString())
      .order('created_at', { ascending: true })

    if (!games) return []

    // Group by date
    const grouped = games.reduce((acc, game) => {
      const date = game.created_at.split('T')[0]
      acc[date] = (acc[date] || 0) + 1
      return acc
    }, {} as Record<string, number>)

    // Fill in missing dates with 0
    const result: { date: string; count: number }[] = []
    const currentDate = new Date(thirtyDaysAgo)
    const today = new Date()

    while (currentDate <= today) {
      const dateStr = currentDate.toISOString().split('T')[0]
      result.push({
        date: dateStr,
        count: grouped[dateStr] || 0,
      })
      currentDate.setDate(currentDate.getDate() + 1)
    }

    return result
  } catch (error) {
    console.error('Error fetching games import stats:', error)
    return []
  }
}

/**
 * Get match rate statistics (fully matched vs partial vs unmatched)
 */
export async function getMatchRateStats(): Promise<{
  fullyMatched: number
  partiallyMatched: number
  unmatched: number
  total: number
  matchRate: number
}> {
  const supabase = createClient()

  try {
    const { data: games } = await supabase
      .from('games')
      .select('home_team_id, away_team_id')

    if (!games) {
      return { fullyMatched: 0, partiallyMatched: 0, unmatched: 0, total: 0, matchRate: 0 }
    }

    let fullyMatched = 0
    let partiallyMatched = 0
    let unmatched = 0

    games.forEach(game => {
      if (game.home_team_id && game.away_team_id) {
        fullyMatched++
      } else if (game.home_team_id || game.away_team_id) {
        partiallyMatched++
      } else {
        unmatched++
      }
    })

    const total = games.length
    const matchRate = total > 0 ? (fullyMatched / total) * 100 : 0

    return {
      fullyMatched,
      partiallyMatched,
      unmatched,
      total,
      matchRate,
    }
  } catch (error) {
    console.error('Error fetching match rate stats:', error)
    return { fullyMatched: 0, partiallyMatched: 0, unmatched: 0, total: 0, matchRate: 0 }
  }
}
