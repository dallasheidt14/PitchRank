import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

/**
 * GET /api/team-merge/suggestions
 *
 * Returns merge suggestions for potential duplicate teams based on:
 * 1. Opponent overlap (40%) - shared opponents suggest same team
 * 2. Schedule alignment (25%) - similar game dates
 * 3. Name similarity (20%) - fuzzy name matching
 * 4. Geography (10%) - state/club matching
 * 5. Performance fingerprint (5%) - similar win rates
 *
 * Query params:
 * - ageGroup: Filter by age group (e.g., '12', 'u12')
 * - gender: Filter by gender ('Male' or 'Female')
 * - stateCode: Filter by state
 * - minConfidence: Minimum confidence score (default: 0.5)
 * - limit: Max results (default: 20)
 */

interface TeamData {
  team_id_master: string;
  team_name: string;
  club_name: string | null;
  state_code: string | null;
}

interface GameData {
  game_date: string;
  opponent_id: string | null;
  goals_for: number | null;
  goals_against: number | null;
}

interface MergeSuggestion {
  teamAId: string;
  teamAName: string;
  teamBId: string;
  teamBName: string;
  confidenceScore: number;
  recommendation: 'high' | 'medium' | 'low';
  signals: {
    opponentOverlap: number;
    scheduleAlignment: number;
    nameSimilarity: number;
    geography: number;
    performance: number;
  };
  details: {
    opponentOverlap: string;
    scheduleAlignment: string;
    nameSimilarity: string;
    geography: string;
    performance: string;
  };
}

// Signal weights
const WEIGHTS = {
  opponentOverlap: 0.40,
  scheduleAlignment: 0.25,
  nameSimilarity: 0.20,
  geography: 0.10,
  performance: 0.05,
};

// Minimum confidence threshold - only show high-quality suggestions
const MIN_CONFIDENCE_THRESHOLD = 0.90;

/**
 * Detects distinguishing markers in team names that indicate different teams
 * from the same club (e.g., location codes, team numbers, division markers).
 *
 * Returns true if the teams appear to be DIFFERENT teams from the same parent club.
 */
function hasDistinguishingMarkers(nameA: string, nameB: string): { isDifferent: boolean; reason: string } {
  const a = nameA.toLowerCase().trim();
  const b = nameB.toLowerCase().trim();

  // If names are identical, not distinguishable
  if (a === b) {
    return { isDifferent: false, reason: '' };
  }

  // Common location codes used in youth soccer (3-4 letter codes)
  const locationCodes = [
    'clw', 'lwr', 'tpa', 'orl', 'jax', 'mia', 'ftl', 'pbg', 'srq', 'tam',  // Florida
    'atl', 'dal', 'hou', 'aus', 'san', 'phx', 'den', 'sea', 'por', 'lax',  // Other cities
    'north', 'south', 'east', 'west', 'central', 'metro', 'coastal',       // Directional
  ];

  // Extract potential location codes from names
  const extractLocationCode = (name: string): string | null => {
    for (const code of locationCodes) {
      // Match standalone code or code followed by space/punctuation
      const regex = new RegExp(`\\b${code}\\b`, 'i');
      if (regex.test(name)) {
        return code;
      }
    }
    return null;
  };

  const locationA = extractLocationCode(a);
  const locationB = extractLocationCode(b);

  // If both have different location codes, they're different teams
  if (locationA && locationB && locationA !== locationB) {
    return { isDifferent: true, reason: `Different locations: ${locationA.toUpperCase()} vs ${locationB.toUpperCase()}` };
  }

  // Detect team number suffixes: -1, -2, "2", "II", "1st", "2nd", etc.
  const numberPatterns = [
    /[-\s](\d+)$/,                    // Ends with -1, -2, " 1", " 2"
    /\s(\d+)$/,                       // Ends with space + number
    /[-\s](i{1,3}|iv|v)$/i,           // Roman numerals I, II, III, IV, V
    /(\d+)(st|nd|rd|th)$/i,           // 1st, 2nd, 3rd, 4th
    /\steam\s*(\d+)/i,                // "team 1", "team 2"
    /\s(one|two|three|four|five)$/i,  // Written numbers
  ];

  const extractNumber = (name: string): string | null => {
    for (const pattern of numberPatterns) {
      const match = name.match(pattern);
      if (match) {
        return match[1] || match[0];
      }
    }
    return null;
  };

  const numA = extractNumber(a);
  const numB = extractNumber(b);

  // If one has a number suffix and the other doesn't, or they have different numbers
  if ((numA && !numB) || (!numA && numB)) {
    return { isDifferent: true, reason: `One team has number suffix: ${numA || numB}` };
  }
  if (numA && numB && numA !== numB) {
    return { isDifferent: true, reason: `Different team numbers: ${numA} vs ${numB}` };
  }

  // Detect academy/division markers: Academy-1, Academy North, etc.
  const divisionPattern = /(academy|premier|select|elite|classic|challenge)[-\s]*(north|south|east|west|\d+|i{1,3})?/gi;
  const divisionA = a.match(divisionPattern);
  const divisionB = b.match(divisionPattern);

  if (divisionA && divisionB) {
    const divA = divisionA[0].toLowerCase();
    const divB = divisionB[0].toLowerCase();
    if (divA !== divB) {
      return { isDifferent: true, reason: `Different divisions: ${divisionA[0]} vs ${divisionB[0]}` };
    }
  }

  // Check for MLS/Pre-MLS team numbers: "Pre MLS 2", "MLS Next 3"
  const mlsPattern = /(pre\s*mls|mls\s*next|mls)\s*(\d+)?/gi;
  const mlsA = a.match(mlsPattern);
  const mlsB = b.match(mlsPattern);

  if (mlsA && mlsB) {
    // Extract numbers if present
    const numInA = mlsA[0].match(/\d+/);
    const numInB = mlsB[0].match(/\d+/);

    if ((numInA && !numInB) || (!numInA && numInB)) {
      return { isDifferent: true, reason: `Different MLS team: ${mlsA[0]} vs ${mlsB[0]}` };
    }
    if (numInA && numInB && numInA[0] !== numInB[0]) {
      return { isDifferent: true, reason: `Different MLS team numbers: ${numInA[0]} vs ${numInB[0]}` };
    }
  }

  return { isDifferent: false, reason: '' };
}

export async function GET(request: NextRequest) {
  try {
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

    if (!supabaseUrl || !supabaseAnonKey) {
      return NextResponse.json(
        { error: 'Server configuration error' },
        { status: 500 }
      );
    }

    const { searchParams } = new URL(request.url);
    const ageGroup = searchParams.get('ageGroup');
    const gender = searchParams.get('gender');
    const stateCode = searchParams.get('stateCode');
    // Always use 90% minimum confidence - ignore any user-supplied value
    const minConfidence = MIN_CONFIDENCE_THRESHOLD;
    const limit = parseInt(searchParams.get('limit') || '20');

    const supabase = createClient(supabaseUrl, supabaseAnonKey);

    // Fetch teams matching criteria
    let teamsQuery = supabase
      .from('teams')
      .select('team_id_master, team_name, club_name, state_code, age_group, gender')
      .eq('is_deprecated', false);

    if (ageGroup) {
      const ageNum = ageGroup.toLowerCase().replace('u', '');
      teamsQuery = teamsQuery.or(`age_group.eq.${ageNum},age_group.eq.u${ageNum},age_group.eq.U${ageNum}`);
    }
    if (gender) {
      teamsQuery = teamsQuery.eq('gender', gender);
    }
    if (stateCode) {
      teamsQuery = teamsQuery.eq('state_code', stateCode);
    }

    const { data: teams, error: teamsError } = await teamsQuery.limit(200);

    if (teamsError) {
      console.error('[suggestions] Error fetching teams:', teamsError);
      return NextResponse.json(
        { error: 'Failed to fetch teams' },
        { status: 500 }
      );
    }

    if (!teams || teams.length < 2) {
      return NextResponse.json({
        suggestions: [],
        count: 0,
        message: 'Not enough teams for comparison',
      });
    }

    // Fetch games for all teams
    const teamIds = teams.map((t: TeamData) => t.team_id_master);
    const gamesByTeam: Record<string, GameData[]> = {};

    for (const tid of teamIds) {
      gamesByTeam[tid] = [];
    }

    // Fetch home games
    const { data: homeGames } = await supabase
      .from('games')
      .select('home_team_master_id, away_team_master_id, game_date, home_score, away_score')
      .in('home_team_master_id', teamIds);

    // Fetch away games
    const { data: awayGames } = await supabase
      .from('games')
      .select('home_team_master_id, away_team_master_id, game_date, home_score, away_score')
      .in('away_team_master_id', teamIds);

    // Organize games by team
    for (const game of homeGames || []) {
      const tid = game.home_team_master_id;
      if (gamesByTeam[tid]) {
        gamesByTeam[tid].push({
          game_date: game.game_date,
          opponent_id: game.away_team_master_id,
          goals_for: game.home_score,
          goals_against: game.away_score,
        });
      }
    }

    for (const game of awayGames || []) {
      const tid = game.away_team_master_id;
      if (gamesByTeam[tid]) {
        gamesByTeam[tid].push({
          game_date: game.game_date,
          opponent_id: game.home_team_master_id,
          goals_for: game.away_score,
          goals_against: game.home_score,
        });
      }
    }

    // Compare all team pairs
    const suggestions: MergeSuggestion[] = [];
    let skippedDueToMarkers = 0;

    for (let i = 0; i < teams.length; i++) {
      for (let j = i + 1; j < teams.length; j++) {
        const teamA = teams[i];
        const teamB = teams[j];

        // CRITICAL: Skip teams that have distinguishing markers indicating they are
        // different teams from the same club (e.g., different location codes, team numbers)
        const markerCheck = hasDistinguishingMarkers(teamA.team_name, teamB.team_name);
        if (markerCheck.isDifferent) {
          skippedDueToMarkers++;
          continue;
        }

        const gamesA = gamesByTeam[teamA.team_id_master] || [];
        const gamesB = gamesByTeam[teamB.team_id_master] || [];

        // Calculate signals
        const signals = {
          opponentOverlap: calcOpponentOverlap(gamesA, gamesB),
          scheduleAlignment: calcScheduleAlignment(gamesA, gamesB),
          nameSimilarity: calcNameSimilarity(teamA, teamB),
          geography: calcGeography(teamA, teamB),
          performance: calcPerformance(gamesA, gamesB),
        };

        const details = {
          opponentOverlap: getOpponentOverlapDetail(gamesA, gamesB),
          scheduleAlignment: getScheduleAlignmentDetail(gamesA, gamesB),
          nameSimilarity: getNameSimilarityDetail(teamA, teamB),
          geography: getGeographyDetail(teamA, teamB),
          performance: getPerformanceDetail(gamesA, gamesB),
        };

        // Calculate weighted confidence
        const confidence =
          WEIGHTS.opponentOverlap * signals.opponentOverlap +
          WEIGHTS.scheduleAlignment * signals.scheduleAlignment +
          WEIGHTS.nameSimilarity * signals.nameSimilarity +
          WEIGHTS.geography * signals.geography +
          WEIGHTS.performance * signals.performance;

        if (confidence >= minConfidence) {
          suggestions.push({
            teamAId: teamA.team_id_master,
            teamAName: teamA.team_name,
            teamBId: teamB.team_id_master,
            teamBName: teamB.team_name,
            confidenceScore: Math.round(confidence * 1000) / 1000,
            recommendation: confidence >= 0.95 ? 'high' : confidence >= 0.90 ? 'medium' : 'low',
            signals,
            details,
          });
        }
      }
    }

    // Sort by confidence descending
    suggestions.sort((a, b) => b.confidenceScore - a.confidenceScore);

    return NextResponse.json({
      suggestions: suggestions.slice(0, limit),
      count: suggestions.length,
      teamsAnalyzed: teams.length,
      skippedDifferentTeams: skippedDueToMarkers,
      minConfidenceUsed: MIN_CONFIDENCE_THRESHOLD,
    });
  } catch (error) {
    console.error('[suggestions] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}

// Signal calculation functions
function calcOpponentOverlap(gamesA: GameData[], gamesB: GameData[]): number {
  if (!gamesA.length || !gamesB.length) return 0;

  const opponentsA = new Set(gamesA.map(g => g.opponent_id).filter(Boolean));
  const opponentsB = new Set(gamesB.map(g => g.opponent_id).filter(Boolean));

  if (!opponentsA.size || !opponentsB.size) return 0;

  const intersection = [...opponentsA].filter(id => opponentsB.has(id)).length;
  const union = new Set([...opponentsA, ...opponentsB]).size;

  return union > 0 ? intersection / union : 0;
}

function getOpponentOverlapDetail(gamesA: GameData[], gamesB: GameData[]): string {
  if (!gamesA.length || !gamesB.length) return 'Insufficient game data';

  const opponentsA = new Set(gamesA.map(g => g.opponent_id).filter(Boolean));
  const opponentsB = new Set(gamesB.map(g => g.opponent_id).filter(Boolean));

  const intersection = [...opponentsA].filter(id => opponentsB.has(id)).length;
  const union = new Set([...opponentsA, ...opponentsB]).size;

  return `${intersection} shared opponents out of ${union} total`;
}

function calcScheduleAlignment(gamesA: GameData[], gamesB: GameData[]): number {
  if (!gamesA.length || !gamesB.length) return 0;

  const datesA = new Set(gamesA.map(g => g.game_date?.split('T')[0]).filter(Boolean));
  const datesB = new Set(gamesB.map(g => g.game_date?.split('T')[0]).filter(Boolean));

  if (!datesA.size || !datesB.size) return 0;

  // Count dates within 1 day of each other
  let closeMatches = 0;
  for (const dateA of datesA) {
    const da = new Date(dateA);
    for (const dateB of datesB) {
      const db = new Date(dateB);
      const diffDays = Math.abs((da.getTime() - db.getTime()) / (1000 * 60 * 60 * 24));
      if (diffDays <= 1) {
        closeMatches++;
        break;
      }
    }
  }

  return Math.min(closeMatches / Math.min(datesA.size, datesB.size), 1);
}

function getScheduleAlignmentDetail(gamesA: GameData[], gamesB: GameData[]): string {
  if (!gamesA.length || !gamesB.length) return 'Insufficient game data';

  const datesA = new Set(gamesA.map(g => g.game_date?.split('T')[0]).filter(Boolean));
  const datesB = new Set(gamesB.map(g => g.game_date?.split('T')[0]).filter(Boolean));

  let closeMatches = 0;
  for (const dateA of datesA) {
    const da = new Date(dateA);
    for (const dateB of datesB) {
      const db = new Date(dateB);
      const diffDays = Math.abs((da.getTime() - db.getTime()) / (1000 * 60 * 60 * 24));
      if (diffDays <= 1) {
        closeMatches++;
        break;
      }
    }
  }

  return `${closeMatches} games on similar dates`;
}

function calcNameSimilarity(teamA: TeamData, teamB: TeamData): number {
  const nameA = (teamA.team_name || '').toLowerCase().trim();
  const nameB = (teamB.team_name || '').toLowerCase().trim();

  if (!nameA || !nameB) return 0;

  const nameScore = levenshteinSimilarity(nameA, nameB);

  const clubA = (teamA.club_name || '').toLowerCase().trim();
  const clubB = (teamB.club_name || '').toLowerCase().trim();

  let clubScore = 0;
  if (clubA && clubB) {
    clubScore = levenshteinSimilarity(clubA, clubB);
  }

  return 0.7 * nameScore + 0.3 * clubScore;
}

function getNameSimilarityDetail(teamA: TeamData, teamB: TeamData): string {
  const nameA = (teamA.team_name || '').toLowerCase().trim();
  const nameB = (teamB.team_name || '').toLowerCase().trim();
  const nameScore = levenshteinSimilarity(nameA, nameB);

  return `Name match: ${Math.round(nameScore * 100)}%`;
}

function calcGeography(teamA: TeamData, teamB: TeamData): number {
  const stateA = (teamA.state_code || '').toUpperCase();
  const stateB = (teamB.state_code || '').toUpperCase();
  const clubA = (teamA.club_name || '').toLowerCase().trim();
  const clubB = (teamB.club_name || '').toLowerCase().trim();

  let score = 0;

  if (stateA && stateB && stateA === stateB) {
    score += 0.5;
  }

  if (clubA && clubB) {
    if (clubA === clubB) {
      score += 0.5;
    } else if (levenshteinSimilarity(clubA, clubB) > 0.8) {
      score += 0.3;
    }
  }

  return score;
}

function getGeographyDetail(teamA: TeamData, teamB: TeamData): string {
  const stateA = (teamA.state_code || '').toUpperCase();
  const stateB = (teamB.state_code || '').toUpperCase();
  const details: string[] = [];

  if (stateA && stateB) {
    if (stateA === stateB) {
      details.push(`Same state (${stateA})`);
    } else {
      details.push(`Different states (${stateA} vs ${stateB})`);
    }
  }

  return details.join(', ') || 'No geographic info';
}

function calcPerformance(gamesA: GameData[], gamesB: GameData[]): number {
  const statsA = calcStats(gamesA);
  const statsB = calcStats(gamesB);

  if (!statsA || !statsB) return 0;

  const winPctDiff = Math.abs(statsA.winPct - statsB.winPct);
  const gdDiff = Math.abs(statsA.goalDiff - statsB.goalDiff);

  const winScore = Math.max(0, 1 - winPctDiff);
  const gdScore = Math.max(0, 1 - gdDiff / 5);

  return 0.6 * winScore + 0.4 * gdScore;
}

function getPerformanceDetail(gamesA: GameData[], gamesB: GameData[]): string {
  const statsA = calcStats(gamesA);
  const statsB = calcStats(gamesB);

  if (!statsA || !statsB) return 'Cannot calculate stats';

  return `Win%: ${Math.round(statsA.winPct * 100)}% vs ${Math.round(statsB.winPct * 100)}%, GD: ${statsA.goalDiff.toFixed(1)} vs ${statsB.goalDiff.toFixed(1)}`;
}

function calcStats(games: GameData[]) {
  const valid = games.filter(g => g.goals_for !== null && g.goals_against !== null);
  if (!valid.length) return null;

  const wins = valid.filter(g => g.goals_for! > g.goals_against!).length;
  const gf = valid.reduce((sum, g) => sum + (g.goals_for || 0), 0);
  const ga = valid.reduce((sum, g) => sum + (g.goals_against || 0), 0);

  return {
    winPct: wins / valid.length,
    goalDiff: (gf - ga) / valid.length,
  };
}

// Levenshtein distance-based similarity
function levenshteinSimilarity(a: string, b: string): number {
  if (a === b) return 1;
  if (!a.length || !b.length) return 0;

  const matrix: number[][] = [];

  for (let i = 0; i <= a.length; i++) {
    matrix[i] = [i];
  }
  for (let j = 0; j <= b.length; j++) {
    matrix[0][j] = j;
  }

  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      matrix[i][j] = Math.min(
        matrix[i - 1][j] + 1,
        matrix[i][j - 1] + 1,
        matrix[i - 1][j - 1] + cost
      );
    }
  }

  const maxLen = Math.max(a.length, b.length);
  return 1 - matrix[a.length][b.length] / maxLen;
}
