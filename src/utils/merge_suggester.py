"""
Intelligent Team Merge Suggestion Engine (Option 8).

This module analyzes teams to suggest potential duplicates for merging.
Uses 5 weighted signals to score similarity between teams:
1. Opponent overlap (40%) - shared opponents suggest same team
2. Schedule alignment (25%) - similar game dates suggest same team
3. Name similarity (20%) - fuzzy name matching
4. Geography (10%) - state/club matching
5. Performance fingerprint (5%) - similar win rates, goal differentials

IMPORTANT: Minimum confidence threshold is 90%. Teams with distinguishing
markers (different location codes, team numbers, division markers) are
automatically excluded to prevent false positives.

Part of Phase 4 of the team merge implementation.
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime, timedelta
import pandas as pd
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Minimum confidence threshold - only high-quality suggestions
MIN_CONFIDENCE_THRESHOLD = 0.90

# Common location codes used in youth soccer
LOCATION_CODES = [
    'clw', 'lwr', 'tpa', 'orl', 'jax', 'mia', 'ftl', 'pbg', 'srq', 'tam',  # Florida
    'atl', 'dal', 'hou', 'aus', 'san', 'phx', 'den', 'sea', 'por', 'lax',  # Other cities
    'north', 'south', 'east', 'west', 'central', 'metro', 'coastal',       # Directional
]


def has_distinguishing_markers(name_a: str, name_b: str) -> Tuple[bool, str]:
    """
    Detects distinguishing markers in team names that indicate different teams
    from the same club (e.g., location codes, team numbers, division markers).

    Returns: (is_different, reason)
    """
    a = name_a.lower().strip()
    b = name_b.lower().strip()

    # If names are identical, not distinguishable
    if a == b:
        return False, ''

    # Check for different location codes
    def extract_location_code(name: str) -> Optional[str]:
        for code in LOCATION_CODES:
            pattern = rf'\b{code}\b'
            if re.search(pattern, name, re.IGNORECASE):
                return code
        return None

    loc_a = extract_location_code(a)
    loc_b = extract_location_code(b)

    if loc_a and loc_b and loc_a != loc_b:
        return True, f"Different locations: {loc_a.upper()} vs {loc_b.upper()}"

    # Detect team number suffixes
    # Also handles numbers directly appended to text like "Mahe1"
    number_patterns = [
        r'[-\s](\d+)$',                    # Ends with -1, -2, " 1", " 2"
        r'\s(\d+)$',                        # Ends with space + number
        r'[a-z](\d+)$',                    # Number directly after letter: Mahe1, Team2
        r'[-\s](i{1,3}|iv|v)$',            # Roman numerals
        r'(\d+)(st|nd|rd|th)$',            # 1st, 2nd, 3rd
        r'\steam\s*(\d+)',                  # "team 1", "team 2"
        r'\s(one|two|three|four|five)$',   # Written numbers
    ]

    def extract_number(name: str) -> Optional[str]:
        for pattern in number_patterns:
            match = re.search(pattern, name, re.IGNORECASE)
            if match:
                return match.group(1) or match.group(0)
        return None

    num_a = extract_number(a)
    num_b = extract_number(b)

    if (num_a and not num_b) or (not num_a and num_b):
        return True, f"One team has number suffix: {num_a or num_b}"
    if num_a and num_b and num_a != num_b:
        return True, f"Different team numbers: {num_a} vs {num_b}"

    # Detect coach/manager name suffixes: "- C. Oliveira" vs "- P. Oliveira"
    # Pattern: dash or space followed by initial(s) and last name at end
    coach_pattern = r'[-–]\s*([a-z]\.?\s*)+[a-z]+$'
    coach_a = re.search(coach_pattern, a, re.IGNORECASE)
    coach_b = re.search(coach_pattern, b, re.IGNORECASE)

    if coach_a and coach_b:
        # Both have coach suffixes - check if they're different
        coach_name_a = re.sub(r'[-–]\s*', '', coach_a.group(0)).lower()
        coach_name_b = re.sub(r'[-–]\s*', '', coach_b.group(0)).lower()
        if coach_name_a != coach_name_b:
            return True, f"Different coaches: {coach_a.group(0)} vs {coach_b.group(0)}"

    # Detect academy/division markers
    division_pattern = r'(academy|premier|select|elite|classic|challenge)[-\s]*(\d+|north|south|east|west|i{1,3})?'
    div_a = re.search(division_pattern, a, re.IGNORECASE)
    div_b = re.search(division_pattern, b, re.IGNORECASE)

    if div_a and div_b:
        if div_a.group(0).lower() != div_b.group(0).lower():
            return True, f"Different divisions: {div_a.group(0)} vs {div_b.group(0)}"

    # Check for MLS/Pre-MLS team numbers
    mls_pattern = r'(pre\s*mls|mls\s*next|mls)\s*(\d+)?'
    mls_a = re.search(mls_pattern, a, re.IGNORECASE)
    mls_b = re.search(mls_pattern, b, re.IGNORECASE)

    if mls_a and mls_b:
        num_in_a = re.search(r'\d+', mls_a.group(0))
        num_in_b = re.search(r'\d+', mls_b.group(0))

        if (num_in_a and not num_in_b) or (not num_in_a and num_in_b):
            return True, f"Different MLS team: {mls_a.group(0)} vs {mls_b.group(0)}"
        if num_in_a and num_in_b and num_in_a.group(0) != num_in_b.group(0):
            return True, f"Different MLS team numbers: {num_in_a.group(0)} vs {num_in_b.group(0)}"

    # Check for 2-letter team designator codes (e.g., HD vs AD for MLS Next teams)
    # These are typically after the club name, before or after age group
    team_designators = ['HD', 'AD', 'DA', 'GA', 'RL', 'NL']

    def extract_designator(name: str) -> Optional[str]:
        for code in team_designators:
            # Match the designator as a standalone word
            pattern = rf'\b{code}\b'
            if re.search(pattern, name, re.IGNORECASE):
                return code.upper()
        return None

    desig_a = extract_designator(a)
    desig_b = extract_designator(b)

    if desig_a and desig_b and desig_a != desig_b:
        return True, f"Different team designators: {desig_a} vs {desig_b}"

    return False, ''


@dataclass
class MergeSuggestion:
    """A suggested team merge with confidence score and signal breakdown."""
    team_a_id: str
    team_a_name: str
    team_b_id: str
    team_b_name: str
    confidence_score: float  # 0.0 to 1.0
    signals: Dict[str, float]  # Individual signal scores
    signal_details: Dict[str, str]  # Human-readable explanations
    recommendation: str  # "high", "medium", "low"


class MergeSuggester:
    """
    Analyzes teams within a cohort to suggest potential duplicates.

    Usage:
        suggester = MergeSuggester(supabase_client)
        suggestions = await suggester.find_suggestions(
            age_group='12',
            gender='Male',
            min_confidence=0.6
        )
    """

    # Signal weights (must sum to 1.0)
    WEIGHTS = {
        'opponent_overlap': 0.40,
        'schedule_alignment': 0.25,
        'name_similarity': 0.20,
        'geography': 0.10,
        'performance': 0.05,
    }

    def __init__(self, supabase_client):
        """Initialize with Supabase client."""
        self.client = supabase_client

    async def find_suggestions(
        self,
        age_group: Optional[str] = None,
        gender: Optional[str] = None,
        state_code: Optional[str] = None,
        min_confidence: float = MIN_CONFIDENCE_THRESHOLD,
        limit: int = 50,
    ) -> List[MergeSuggestion]:
        """
        Find potential merge candidates within a cohort.

        Args:
            age_group: Filter by age group (e.g., '12', 'u12')
            gender: Filter by gender ('Male' or 'Female')
            state_code: Filter by state code (e.g., 'CA', 'TX')
            min_confidence: Minimum confidence score (default: 0.90)
            limit: Maximum suggestions to return

        Returns:
            List of MergeSuggestion objects sorted by confidence
        """
        # Enforce minimum confidence of 90%
        min_confidence = max(min_confidence, MIN_CONFIDENCE_THRESHOLD)

        logger.info(f"Finding merge suggestions (age={age_group}, gender={gender}, state={state_code}, min_conf={min_confidence})")

        # Fetch teams in cohort
        teams = await self._fetch_teams(age_group, gender, state_code)
        if len(teams) < 2:
            logger.info(f"Not enough teams for comparison ({len(teams)} teams)")
            return []

        logger.info(f"Analyzing {len(teams)} teams for potential duplicates")

        # Fetch game data for all teams
        team_ids = [t['team_id_master'] for t in teams]
        games_by_team = await self._fetch_games_by_team(team_ids)

        # Compare all team pairs
        suggestions = []
        teams_list = list(teams)
        skipped_due_to_markers = 0

        for i in range(len(teams_list)):
            for j in range(i + 1, len(teams_list)):
                team_a = teams_list[i]
                team_b = teams_list[j]

                # Skip if teams are already identical (shouldn't happen)
                if team_a['team_id_master'] == team_b['team_id_master']:
                    continue

                # CRITICAL: Skip teams that have distinguishing markers indicating
                # they are different teams from the same club
                is_different, reason = has_distinguishing_markers(
                    team_a['team_name'],
                    team_b['team_name']
                )
                if is_different:
                    skipped_due_to_markers += 1
                    logger.debug(f"Skipping {team_a['team_name']} vs {team_b['team_name']}: {reason}")
                    continue

                # Calculate signals
                signals, details = self._calculate_signals(
                    team_a, team_b,
                    games_by_team.get(team_a['team_id_master'], []),
                    games_by_team.get(team_b['team_id_master'], []),
                )

                # Calculate weighted confidence
                confidence = sum(
                    self.WEIGHTS[signal] * score
                    for signal, score in signals.items()
                )

                # Only include if above threshold
                if confidence >= min_confidence:
                    suggestions.append(MergeSuggestion(
                        team_a_id=team_a['team_id_master'],
                        team_a_name=team_a['team_name'],
                        team_b_id=team_b['team_id_master'],
                        team_b_name=team_b['team_name'],
                        confidence_score=round(confidence, 3),
                        signals=signals,
                        signal_details=details,
                        recommendation=self._get_recommendation(confidence),
                    ))

        # Sort by confidence descending
        suggestions.sort(key=lambda s: s.confidence_score, reverse=True)

        logger.info(f"Found {len(suggestions)} potential merge candidates (>= {min_confidence} confidence), skipped {skipped_due_to_markers} different teams")

        return suggestions[:limit]

    async def _fetch_teams(
        self,
        age_group: Optional[str],
        gender: Optional[str],
        state_code: Optional[str],
    ) -> List[Dict]:
        """Fetch teams matching the filter criteria."""
        query = self.client.table('teams').select(
            'team_id_master, team_name, club_name, state_code, age_group, gender'
        ).eq('is_deprecated', False)

        if age_group:
            # Normalize age group (remove 'u' prefix if present)
            age_num = age_group.lower().replace('u', '')
            query = query.or_(f"age_group.eq.{age_num},age_group.eq.u{age_num},age_group.eq.U{age_num}")

        if gender:
            query = query.eq('gender', gender)

        if state_code:
            query = query.eq('state_code', state_code)

        response = query.limit(1000).execute()
        return response.data or []

    async def _fetch_games_by_team(self, team_ids: List[str]) -> Dict[str, List[Dict]]:
        """Fetch games for multiple teams, grouped by team."""
        if not team_ids:
            return {}

        games_by_team: Dict[str, List[Dict]] = {tid: [] for tid in team_ids}

        # Fetch in batches to avoid query limits
        batch_size = 100
        for i in range(0, len(team_ids), batch_size):
            batch = team_ids[i:i + batch_size]

            # Home games
            home_response = self.client.table('games').select(
                'id, home_team_master_id, away_team_master_id, game_date, home_score, away_score'
            ).in_('home_team_master_id', batch).execute()

            # Away games
            away_response = self.client.table('games').select(
                'id, home_team_master_id, away_team_master_id, game_date, home_score, away_score'
            ).in_('away_team_master_id', batch).execute()

            # Organize by team
            for game in (home_response.data or []):
                tid = game['home_team_master_id']
                if tid in games_by_team:
                    games_by_team[tid].append({
                        **game,
                        'is_home': True,
                        'opponent_id': game['away_team_master_id'],
                        'goals_for': game['home_score'],
                        'goals_against': game['away_score'],
                    })

            for game in (away_response.data or []):
                tid = game['away_team_master_id']
                if tid in games_by_team:
                    games_by_team[tid].append({
                        **game,
                        'is_home': False,
                        'opponent_id': game['home_team_master_id'],
                        'goals_for': game['away_score'],
                        'goals_against': game['home_score'],
                    })

        return games_by_team

    def _calculate_signals(
        self,
        team_a: Dict,
        team_b: Dict,
        games_a: List[Dict],
        games_b: List[Dict],
    ) -> Tuple[Dict[str, float], Dict[str, str]]:
        """Calculate all similarity signals between two teams."""
        signals = {}
        details = {}

        # Signal 1: Opponent overlap
        signals['opponent_overlap'], details['opponent_overlap'] = self._opponent_overlap(
            games_a, games_b
        )

        # Signal 2: Schedule alignment
        signals['schedule_alignment'], details['schedule_alignment'] = self._schedule_alignment(
            games_a, games_b
        )

        # Signal 3: Name similarity
        signals['name_similarity'], details['name_similarity'] = self._name_similarity(
            team_a, team_b
        )

        # Signal 4: Geography
        signals['geography'], details['geography'] = self._geography_match(
            team_a, team_b
        )

        # Signal 5: Performance fingerprint
        signals['performance'], details['performance'] = self._performance_fingerprint(
            games_a, games_b
        )

        return signals, details

    def _opponent_overlap(
        self,
        games_a: List[Dict],
        games_b: List[Dict],
    ) -> Tuple[float, str]:
        """Calculate opponent overlap signal (40% weight)."""
        if not games_a or not games_b:
            return 0.0, "Insufficient game data"

        opponents_a = {g['opponent_id'] for g in games_a if g['opponent_id']}
        opponents_b = {g['opponent_id'] for g in games_b if g['opponent_id']}

        if not opponents_a or not opponents_b:
            return 0.0, "No opponents found"

        # Jaccard similarity
        intersection = len(opponents_a & opponents_b)
        union = len(opponents_a | opponents_b)

        if union == 0:
            return 0.0, "No opponents to compare"

        score = intersection / union
        detail = f"{intersection} shared opponents out of {union} total"

        return round(score, 3), detail

    def _schedule_alignment(
        self,
        games_a: List[Dict],
        games_b: List[Dict],
    ) -> Tuple[float, str]:
        """Calculate schedule alignment signal (25% weight)."""
        if not games_a or not games_b:
            return 0.0, "Insufficient game data"

        def parse_date(d):
            if isinstance(d, str):
                try:
                    return datetime.fromisoformat(d.replace('Z', '+00:00')).date()
                except:
                    return None
            return None

        dates_a = {parse_date(g['game_date']) for g in games_a}
        dates_b = {parse_date(g['game_date']) for g in games_b}

        dates_a = {d for d in dates_a if d}
        dates_b = {d for d in dates_b if d}

        if not dates_a or not dates_b:
            return 0.0, "No valid dates"

        # Count dates within 1 day of each other (same tournament/event)
        close_matches = 0
        for da in dates_a:
            for db in dates_b:
                if abs((da - db).days) <= 1:
                    close_matches += 1
                    break

        # Normalize by smaller team's game count
        score = close_matches / min(len(dates_a), len(dates_b))
        detail = f"{close_matches} games on similar dates"

        return round(min(score, 1.0), 3), detail

    def _name_similarity(
        self,
        team_a: Dict,
        team_b: Dict,
    ) -> Tuple[float, str]:
        """Calculate name similarity signal (20% weight)."""
        name_a = (team_a.get('team_name') or '').lower().strip()
        name_b = (team_b.get('team_name') or '').lower().strip()

        if not name_a or not name_b:
            return 0.0, "Missing team names"

        # Use SequenceMatcher for fuzzy matching
        name_score = SequenceMatcher(None, name_a, name_b).ratio()

        # Also compare club names
        club_a = (team_a.get('club_name') or '').lower().strip()
        club_b = (team_b.get('club_name') or '').lower().strip()

        club_score = 0.0
        if club_a and club_b:
            club_score = SequenceMatcher(None, club_a, club_b).ratio()

        # Weight name more heavily than club
        score = 0.7 * name_score + 0.3 * club_score

        detail = f"Name match: {name_score:.0%}"
        if club_score > 0:
            detail += f", Club match: {club_score:.0%}"

        return round(score, 3), detail

    def _geography_match(
        self,
        team_a: Dict,
        team_b: Dict,
    ) -> Tuple[float, str]:
        """Calculate geography signal (10% weight)."""
        state_a = (team_a.get('state_code') or '').upper()
        state_b = (team_b.get('state_code') or '').upper()

        club_a = (team_a.get('club_name') or '').lower().strip()
        club_b = (team_b.get('club_name') or '').lower().strip()

        score = 0.0
        details = []

        # Same state: +0.5
        if state_a and state_b:
            if state_a == state_b:
                score += 0.5
                details.append(f"Same state ({state_a})")
            else:
                details.append(f"Different states ({state_a} vs {state_b})")

        # Same club: +0.5
        if club_a and club_b:
            if club_a == club_b:
                score += 0.5
                details.append("Same club")
            elif SequenceMatcher(None, club_a, club_b).ratio() > 0.8:
                score += 0.3
                details.append("Similar club names")

        detail = ", ".join(details) if details else "No geographic info"
        return round(score, 3), detail

    def _performance_fingerprint(
        self,
        games_a: List[Dict],
        games_b: List[Dict],
    ) -> Tuple[float, str]:
        """Calculate performance fingerprint signal (5% weight)."""
        if not games_a or not games_b:
            return 0.0, "Insufficient game data"

        def calc_stats(games):
            valid = [g for g in games if g['goals_for'] is not None and g['goals_against'] is not None]
            if not valid:
                return None

            wins = sum(1 for g in valid if g['goals_for'] > g['goals_against'])
            losses = sum(1 for g in valid if g['goals_for'] < g['goals_against'])
            draws = sum(1 for g in valid if g['goals_for'] == g['goals_against'])
            total = len(valid)

            gf = sum(g['goals_for'] for g in valid)
            ga = sum(g['goals_against'] for g in valid)

            return {
                'win_pct': wins / total if total > 0 else 0,
                'gf_per_game': gf / total if total > 0 else 0,
                'ga_per_game': ga / total if total > 0 else 0,
                'goal_diff': (gf - ga) / total if total > 0 else 0,
            }

        stats_a = calc_stats(games_a)
        stats_b = calc_stats(games_b)

        if not stats_a or not stats_b:
            return 0.0, "Cannot calculate stats"

        # Compare metrics (smaller difference = higher score)
        win_pct_diff = abs(stats_a['win_pct'] - stats_b['win_pct'])
        gd_diff = abs(stats_a['goal_diff'] - stats_b['goal_diff'])

        # Score inversely proportional to difference
        win_score = max(0, 1 - win_pct_diff)  # 0% diff = 1.0, 100% diff = 0.0
        gd_score = max(0, 1 - gd_diff / 5)  # 5 goal diff = 0.0

        score = 0.6 * win_score + 0.4 * gd_score
        detail = f"Win%: {stats_a['win_pct']:.0%} vs {stats_b['win_pct']:.0%}, GD: {stats_a['goal_diff']:.1f} vs {stats_b['goal_diff']:.1f}"

        return round(score, 3), detail

    def _get_recommendation(self, confidence: float) -> str:
        """Get recommendation level based on confidence score."""
        if confidence >= 0.95:
            return "high"
        elif confidence >= 0.90:
            return "medium"
        else:
            return "low"


async def suggest_merges_for_cohort(
    supabase_client,
    age_group: str,
    gender: str,
    min_confidence: float = MIN_CONFIDENCE_THRESHOLD,
) -> List[MergeSuggestion]:
    """
    Convenience function to find merge suggestions for a specific cohort.

    Args:
        supabase_client: Supabase client instance
        age_group: Age group (e.g., '12', 'u12')
        gender: Gender ('Male' or 'Female')
        min_confidence: Minimum confidence threshold (default: 0.90)

    Returns:
        List of MergeSuggestion objects
    """
    suggester = MergeSuggester(supabase_client)
    return await suggester.find_suggestions(
        age_group=age_group,
        gender=gender,
        min_confidence=min_confidence,
    )
