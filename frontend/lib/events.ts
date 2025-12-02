/**
 * Analytics Event Tracking Functions
 * Typed helpers for tracking user interactions with GA4
 *
 * All event names follow GA4 best practices:
 * - snake_case
 * - no spaces
 * - no uppercase
 */

import { gtagEvent } from './analytics';
import type {
  TeamEventPayload,
  FilterEventPayload,
  SortEventPayload,
  SearchEventPayload,
  CompareEventPayload,
  PredictionEventPayload,
  ChartViewEventPayload,
  MissingGameEventPayload,
} from '@/types/events';

// ============================================================================
// Rankings Events
// ============================================================================

/**
 * Track when user views the rankings page
 */
export function trackRankingsViewed(payload: {
  region: string | null;
  age_group: string;
  gender: string | null;
  total_teams?: number;
}): void {
  gtagEvent('rankings_viewed', {
    region: payload.region || 'national',
    age_group: payload.age_group,
    gender: payload.gender || 'all',
    total_teams: payload.total_teams,
  });
}

/**
 * Track when user clicks on a team row in rankings
 */
export function trackTeamRowClicked(team: TeamEventPayload): void {
  gtagEvent('team_row_clicked', {
    team_id_master: team.team_id_master,
    team_name: team.team_name,
    club_name: team.club_name,
    state: team.state,
    age: team.age,
    gender: team.gender,
    rank_in_cohort_final: team.rank_in_cohort_final,
    rank_in_state_final: team.rank_in_state_final,
  });
}

/**
 * Track when user applies sorting
 */
export function trackSortUsed(payload: SortEventPayload): void {
  gtagEvent('sort_used', {
    column: payload.column,
    direction: payload.direction,
    region: payload.region,
    age_group: payload.age_group,
    gender: payload.gender,
  });
}

/**
 * Track when user applies a filter
 */
export function trackFilterApplied(payload: FilterEventPayload): void {
  gtagEvent('filter_applied', {
    region: payload.region,
    age_group: payload.age_group,
    gender: payload.gender,
  });
}

// ============================================================================
// Search Events
// ============================================================================

/**
 * Track when user performs a search
 */
export function trackSearchUsed(payload: SearchEventPayload): void {
  gtagEvent('search_used', {
    query: payload.query,
    results_count: payload.results_count,
  });
}

/**
 * Track when user selects a search result
 */
export function trackSearchResultClicked(team: TeamEventPayload): void {
  gtagEvent('search_result_clicked', {
    team_id_master: team.team_id_master,
    team_name: team.team_name,
    rank_in_cohort_final: team.rank_in_cohort_final,
  });
}

// ============================================================================
// Team Page Events
// ============================================================================

/**
 * Track when user views a team page
 */
export function trackTeamPageViewed(team: TeamEventPayload): void {
  gtagEvent('team_page_viewed', {
    team_id_master: team.team_id_master,
    team_name: team.team_name,
    club_name: team.club_name,
    state: team.state,
    age: team.age,
    gender: team.gender,
    rank_in_cohort_final: team.rank_in_cohort_final,
    power_score_final: team.power_score_final,
  });
}

/**
 * Track when a chart comes into view on team page
 */
export function trackChartViewed(payload: ChartViewEventPayload): void {
  gtagEvent('chart_viewed', {
    chart_type: payload.chart_type,
    team_id_master: payload.team_id_master,
    team_name: payload.team_name,
  });
}

// ============================================================================
// Compare/Predict Events
// ============================================================================

/**
 * Track when user opens the compare tool (selects first team)
 */
export function trackCompareOpened(team: TeamEventPayload): void {
  gtagEvent('compare_opened', {
    team_id_master: team.team_id_master,
    team_name: team.team_name,
    rank_in_cohort_final: team.rank_in_cohort_final,
  });
}

/**
 * Track when comparison is fully generated (both teams selected)
 */
export function trackComparisonGenerated(payload: CompareEventPayload): void {
  gtagEvent('comparison_generated', {
    team_count: payload.team_count,
    team_ids: payload.team_ids?.join(','),
    team_names: payload.team_names?.join(' vs '),
  });
}

/**
 * Track when prediction loads and is viewed
 */
export function trackPredictionViewed(payload: PredictionEventPayload): void {
  gtagEvent('prediction_viewed', {
    team_a_id: payload.team_a_id,
    team_a_name: payload.team_a_name,
    team_b_id: payload.team_b_id,
    team_b_name: payload.team_b_name,
    win_probability_a: payload.win_probability_a,
    win_probability_b: payload.win_probability_b,
    draw_probability: payload.draw_probability,
    predicted_winner: payload.predicted_winner,
  });
}

/**
 * Track when user swaps teams in compare panel
 */
export function trackTeamsSwapped(): void {
  gtagEvent('teams_swapped', {});
}

// ============================================================================
// Watchlist Events
// ============================================================================

/**
 * Track when user adds a team to watchlist
 */
export function trackWatchlistAdded(team: TeamEventPayload): void {
  gtagEvent('watchlist_added', {
    team_id_master: team.team_id_master,
    team_name: team.team_name,
    club_name: team.club_name,
    state: team.state,
    rank_in_cohort_final: team.rank_in_cohort_final,
  });
}

/**
 * Track when user removes a team from watchlist
 */
export function trackWatchlistRemoved(team: TeamEventPayload): void {
  gtagEvent('watchlist_removed', {
    team_id_master: team.team_id_master,
    team_name: team.team_name,
  });
}

// ============================================================================
// Missing Game Events
// ============================================================================

/**
 * Track when user clicks the missing game button
 */
export function trackMissingGameClicked(payload: MissingGameEventPayload): void {
  gtagEvent('missing_game_clicked', {
    team_id_master: payload.team_id_master,
    team_name: payload.team_name,
  });
}

/**
 * Track when user submits a missing game request
 */
export function trackMissingGameSubmitted(payload: MissingGameEventPayload): void {
  gtagEvent('missing_game_submitted', {
    team_id_master: payload.team_id_master,
    team_name: payload.team_name,
    game_date: payload.game_date,
  });
}

// ============================================================================
// Navigation Events
// ============================================================================

/**
 * Track when user clicks back to rankings button
 */
export function trackBackToRankingsClicked(payload: {
  from_team_id?: string;
  to_region: string;
  to_age_group: string;
  to_gender: string;
}): void {
  gtagEvent('back_to_rankings_clicked', {
    from_team_id: payload.from_team_id,
    to_region: payload.to_region,
    to_age_group: payload.to_age_group,
    to_gender: payload.to_gender,
  });
}
