#!/usr/bin/env python3
"""
Analyze Desert Super Cup tournament brackets using event scraper

This script:
1. Scrapes teams from Desert Super Cup tournament using GotSport event scraper
2. Gets their current rankings and power scores
3. Creates optimal brackets using balanced seeding (snake draft)
4. Runs predictions for all matchups in both actual and optimal brackets
5. Compares goal differentials to show our seedings reduce blowouts
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict
import statistics
import itertools
import random

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.scrapers.gotsport_event import GotSportEventScraper, EventTeam
from scripts.predictor_python import (
    TeamRanking, Game, predict_match, calculate_recent_form
)

console = Console()
load_dotenv()

# Load .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)


@dataclass
class TournamentTeam:
    """Team with ranking data for tournament analysis"""
    team_id_master: str
    team_name: str
    club_name: Optional[str]
    bracket_name: str  # Actual bracket from tournament
    power_score_final: float
    rank_in_cohort_final: Optional[int]
    sos_norm: Optional[float] = None
    offense_norm: Optional[float] = None
    defense_norm: Optional[float] = None
    age: Optional[int] = None
    games_played: int = 0


@dataclass
class MatchupPrediction:
    """Prediction for a single matchup"""
    team_a: TournamentTeam
    team_b: TournamentTeam
    expected_margin: float
    expected_score_a: float
    expected_score_b: float
    win_prob_a: float
    is_blowout: bool  # True if margin > 3 goals


def normalize_age_group(age_group: str) -> Optional[int]:
    """Convert age group string to integer (e.g., 'u12' -> 12)"""
    if not age_group:
        return None
    age_str = age_group.lower().replace('u', '').strip()
    try:
        return int(age_str)
    except ValueError:
        return None


def fetch_team_rankings(
    supabase,
    team_ids: List[str],
    age_group: str = 'u12',
    gender: str = 'M'
) -> Dict[str, TournamentTeam]:
    """Fetch ranking data for teams"""
    console.print(f"[cyan]Fetching rankings for {len(team_ids)} teams...[/cyan]")
    
    # Fetch from state_rankings_view (includes state ranks)
    age_int = normalize_age_group(age_group)
    if not age_int:
        console.print(f"[red]Could not parse age group: {age_group}[/red]")
        return {}
    
    # Convert gender
    gender_code = 'M' if gender.lower() in ['m', 'male', 'boys', 'b'] else 'F'
    
    teams_data = {}
    batch_size = 100
    
    for i in range(0, len(team_ids), batch_size):
        batch = team_ids[i:i + batch_size]
        try:
            result = supabase.table('state_rankings_view').select(
                'team_id_master, team_name, club_name, power_score_final, '
                'rank_in_cohort_final, sos_norm, offense_norm, defense_norm, '
                'age, games_played, state'
            ).in_('team_id_master', batch).eq('age', age_int).eq('gender', gender_code).execute()
            
            if result.data:
                for row in result.data:
                    teams_data[row['team_id_master']] = row
        except Exception as e:
            console.print(f"[yellow]Warning: Error fetching batch: {e}[/yellow]")
            continue
    
    console.print(f"[green]Found rankings for {len(teams_data)} teams[/green]")
    return teams_data


def evaluate_bracket_configuration(
    config: Dict[str, Dict[str, List[TournamentTeam]]],
    all_games: List[Game]
) -> Tuple[float, int]:
    """
    Evaluate a bracket configuration by predicting all matchups.
    Returns (average_goal_differential, blowout_count)
    Lower is better for both metrics.
    """
    all_predictions = []
    
    for bracket_name, groups in config.items():
        for group_name, teams in groups.items():
            if len(teams) >= 2:
                group_predictions = predict_matchups_in_bracket(teams, all_games)
                all_predictions.extend(group_predictions)
    
    if not all_predictions:
        return float('inf'), float('inf')
    
    avg_margin = statistics.mean([p.expected_margin for p in all_predictions])
    blowouts = sum(1 for p in all_predictions if p.is_blowout)
    
    return avg_margin, blowouts


def generate_candidate_configurations(
    teams: List[TournamentTeam],
    bracket_config: Dict[str, int],
    current_best: Optional[Dict[str, Dict[str, List[TournamentTeam]]]] = None,
    num_candidates: int = 50
) -> List[Dict[str, Dict[str, List[TournamentTeam]]]]:
    """
    Generate candidate bracket configurations using various strategies.
    Returns list of candidate configurations to evaluate.
    """
    candidates = []
    sorted_teams = sorted(teams, key=lambda t: t.power_score_final, reverse=True)
    
    # Strategy 1: Start with snake draft baseline
    if current_best is None:
        baseline = create_snake_draft_brackets(sorted_teams, bracket_config)
        candidates.append(baseline)
    
    # Strategy 2: Try swapping teams between groups within same bracket
    if current_best:
        for _ in range(num_candidates // 2):
            candidate = swap_teams_within_brackets(current_best.copy())
            candidates.append(candidate)
    
    # Strategy 3: Try swapping teams between brackets
    if current_best:
        for _ in range(num_candidates // 4):
            candidate = swap_teams_between_brackets(current_best.copy(), bracket_config)
            candidates.append(candidate)
    
    # Strategy 4: Try balanced power score distribution
    balanced = create_balanced_power_brackets(sorted_teams, bracket_config)
    candidates.append(balanced)
    
    return candidates


def create_snake_draft_brackets(
    sorted_teams: List[TournamentTeam],
    bracket_config: Dict[str, int]
) -> Dict[str, Dict[str, List[TournamentTeam]]]:
    """Create brackets using snake draft (baseline)"""
    brackets: Dict[str, List[TournamentTeam]] = {}
    for bracket_name in bracket_config.keys():
        brackets[bracket_name] = []
    
    bracket_names = list(bracket_config.keys())
    team_idx = 0
    
    while team_idx < len(sorted_teams):
        for bracket_name in bracket_names:
            if team_idx >= len(sorted_teams):
                break
            if len(brackets[bracket_name]) < bracket_config[bracket_name]:
                brackets[bracket_name].append(sorted_teams[team_idx])
                team_idx += 1
        
        if team_idx < len(sorted_teams):
            for bracket_name in reversed(bracket_names):
                if team_idx >= len(sorted_teams):
                    break
                if len(brackets[bracket_name]) < bracket_config[bracket_name]:
                    brackets[bracket_name].append(sorted_teams[team_idx])
                    team_idx += 1
        
        if all(len(brackets[name]) >= bracket_config[name] for name in bracket_names):
            break
    
    result: Dict[str, Dict[str, List[TournamentTeam]]] = {}
    for bracket_name, bracket_teams in brackets.items():
        num_teams = len(bracket_teams)
        if num_teams == 8:
            groups = create_optimal_groups(bracket_teams, 2, 4)
        elif num_teams == 6:
            groups = create_optimal_groups(bracket_teams, 2, 3)
        else:
            num_groups = 2
            per_group = num_teams // num_groups
            groups = create_optimal_groups(bracket_teams, num_groups, per_group)
        result[bracket_name] = groups
    
    return result


def swap_teams_within_brackets(
    config: Dict[str, Dict[str, List[TournamentTeam]]]
) -> Dict[str, Dict[str, List[TournamentTeam]]]:
    """Swap two random teams within the same bracket but different groups"""
    config = deepcopy_config(config)
    
    bracket_name = random.choice(list(config.keys()))
    groups = list(config[bracket_name].keys())
    
    if len(groups) >= 2:
        group_a = random.choice(groups)
        group_b = random.choice([g for g in groups if g != group_a])
        
        if config[bracket_name][group_a] and config[bracket_name][group_b]:
            team_a = random.choice(config[bracket_name][group_a])
            team_b = random.choice(config[bracket_name][group_b])
            
            # Swap
            config[bracket_name][group_a].remove(team_a)
            config[bracket_name][group_b].remove(team_b)
            config[bracket_name][group_a].append(team_b)
            config[bracket_name][group_b].append(team_a)
    
    return config


def swap_teams_between_brackets(
    config: Dict[str, Dict[str, List[TournamentTeam]]],
    bracket_config: Dict[str, int]
) -> Dict[str, Dict[str, List[TournamentTeam]]]:
    """Swap two random teams between different brackets"""
    config = deepcopy_config(config)
    
    bracket_names = list(config.keys())
    if len(bracket_names) < 2:
        return config
    
    bracket_a, bracket_b = random.sample(bracket_names, 2)
    
    # Get random groups
    groups_a = list(config[bracket_a].keys())
    groups_b = list(config[bracket_b].keys())
    
    if groups_a and groups_b:
        group_a = random.choice(groups_a)
        group_b = random.choice(groups_b)
        
        if config[bracket_a][group_a] and config[bracket_b][group_b]:
            team_a = random.choice(config[bracket_a][group_a])
            team_b = random.choice(config[bracket_b][group_b])
            
            # Check if swap maintains bracket sizes
            if (len(config[bracket_a][group_a]) <= 1 or 
                len(config[bracket_b][group_b]) <= 1):
                return config
            
            # Swap
            config[bracket_a][group_a].remove(team_a)
            config[bracket_b][group_b].remove(team_b)
            config[bracket_a][group_a].append(team_b)
            config[bracket_b][group_b].append(team_a)
    
    return config


def create_balanced_power_brackets(
    sorted_teams: List[TournamentTeam],
    bracket_config: Dict[str, int]
) -> Dict[str, Dict[str, List[TournamentTeam]]]:
    """Create brackets by balancing total power score across groups"""
    brackets: Dict[str, List[TournamentTeam]] = {}
    for bracket_name in bracket_config.keys():
        brackets[bracket_name] = []
    
    # Distribute teams to balance power scores
    bracket_names = list(bracket_config.keys())
    team_idx = 0
    
    while team_idx < len(sorted_teams):
        # Find bracket with lowest total power score that isn't full
        best_bracket = None
        min_power = float('inf')
        
        for bracket_name in bracket_names:
            if len(brackets[bracket_name]) < bracket_config[bracket_name]:
                total_power = sum(t.power_score_final for t in brackets[bracket_name])
                if total_power < min_power:
                    min_power = total_power
                    best_bracket = bracket_name
        
        if best_bracket and team_idx < len(sorted_teams):
            brackets[best_bracket].append(sorted_teams[team_idx])
            team_idx += 1
        else:
            break
    
    result: Dict[str, Dict[str, List[TournamentTeam]]] = {}
    for bracket_name, bracket_teams in brackets.items():
        num_teams = len(bracket_teams)
        if num_teams == 8:
            groups = balance_groups_by_power(bracket_teams, 2, 4)
        elif num_teams == 6:
            groups = balance_groups_by_power(bracket_teams, 2, 3)
        else:
            num_groups = 2
            per_group = num_teams // num_groups
            groups = balance_groups_by_power(bracket_teams, num_groups, per_group)
        result[bracket_name] = groups
    
    return result


def balance_groups_by_power(
    teams: List[TournamentTeam],
    num_groups: int,
    teams_per_group: int
) -> Dict[str, List[TournamentTeam]]:
    """Distribute teams to balance total power score across groups"""
    groups: Dict[str, List[TournamentTeam]] = {}
    group_powers = {}
    
    for i in range(num_groups):
        group_name = f"Group {chr(65 + i)}"
        groups[group_name] = []
        group_powers[group_name] = 0.0
    
    sorted_teams = sorted(teams, key=lambda t: t.power_score_final, reverse=True)
    
    for team in sorted_teams:
        # Find group with lowest total power that isn't full
        best_group = None
        min_power = float('inf')
        
        for group_name in groups.keys():
            if len(groups[group_name]) < teams_per_group:
                if group_powers[group_name] < min_power:
                    min_power = group_powers[group_name]
                    best_group = group_name
        
        if best_group:
            groups[best_group].append(team)
            group_powers[best_group] += team.power_score_final
    
    return groups


def deepcopy_config(config: Dict[str, Dict[str, List[TournamentTeam]]]) -> Dict[str, Dict[str, List[TournamentTeam]]]:
    """Deep copy a bracket configuration"""
    result = {}
    for bracket_name, groups in config.items():
        result[bracket_name] = {}
        for group_name, teams in groups.items():
            result[bracket_name][group_name] = teams.copy()
    return result


def create_optimal_brackets(
    teams: List[TournamentTeam],
    bracket_config: Dict[str, int] = None,
    all_games: List[Game] = None
) -> Dict[str, Dict[str, List[TournamentTeam]]]:
    """
    Create optimal brackets using prediction-based optimization.
    Tests multiple configurations and selects the one with lowest average goal differential.
    
    Args:
        teams: List of teams to distribute
        bracket_config: Dict mapping bracket names to team counts
        all_games: List of recent games for prediction (required for optimization)
    
    Returns:
        Dict mapping bracket names to groups within brackets
    """
    if not bracket_config:
        # Fallback to snake draft if no config provided
        sorted_teams = sorted(teams, key=lambda t: t.power_score_final, reverse=True)
        return create_snake_draft_brackets(sorted_teams, {"Default Bracket": len(teams)})
    
    if not all_games:
        # Fallback to snake draft if no games provided for prediction
        console.print("[yellow]Warning: No games provided, using snake draft instead of prediction-based optimization[/yellow]")
        sorted_teams = sorted(teams, key=lambda t: t.power_score_final, reverse=True)
        return create_snake_draft_brackets(sorted_teams, bracket_config)
    
    console.print("[cyan]Optimizing brackets using matchup predictions...[/cyan]")
    
    # Start with snake draft as baseline
    sorted_teams = sorted(teams, key=lambda t: t.power_score_final, reverse=True)
    best_config = create_snake_draft_brackets(sorted_teams, bracket_config)
    best_score, best_blowouts = evaluate_bracket_configuration(best_config, all_games)
    
    console.print(f"[dim]Baseline (snake draft): avg margin={best_score:.2f}, blowouts={best_blowouts}[/dim]")
    
    # Generate and evaluate candidates
    num_iterations = 30
    for iteration in range(num_iterations):
        candidates = generate_candidate_configurations(
            sorted_teams, 
            bracket_config, 
            current_best=best_config,
            num_candidates=10
        )
        
        for candidate in candidates:
            try:
                score, blowouts = evaluate_bracket_configuration(candidate, all_games)
                
                # Prefer lower average margin, tie-break with fewer blowouts
                if score < best_score or (score == best_score and blowouts < best_blowouts):
                    best_score = score
                    best_blowouts = blowouts
                    best_config = candidate
            except Exception as e:
                console.print(f"[yellow]Warning: Error evaluating candidate: {e}[/yellow]")
                continue
        
        if iteration % 10 == 0:
            console.print(f"[dim]Iteration {iteration}: best avg margin={best_score:.2f}, blowouts={best_blowouts}[/dim]")
    
    console.print(f"[green]Optimized: avg margin={best_score:.2f}, blowouts={best_blowouts}[/green]\n")
    
    return best_config


def create_optimal_groups(
    teams: List[TournamentTeam],
    num_groups: int,
    teams_per_group: int
) -> Dict[str, List[TournamentTeam]]:
    """Create optimal groups within a bracket using snake draft"""
    groups: Dict[str, List[TournamentTeam]] = {}
    for i in range(num_groups):
        groups[f"Group {chr(65 + i)}"] = []
    
    # Snake draft within bracket
    team_idx = 0
    for round_num in range(teams_per_group):
        # Forward direction
        for i in range(num_groups):
            if team_idx < len(teams):
                group_name = f"Group {chr(65 + i)}"
                groups[group_name].append(teams[team_idx])
                team_idx += 1
        
        # Reverse direction
        if team_idx < len(teams):
            for i in range(num_groups - 1, -1, -1):
                if team_idx < len(teams):
                    group_name = f"Group {chr(65 + i)}"
                    groups[group_name].append(teams[team_idx])
                    team_idx += 1
    
    return groups


def predict_matchups_in_bracket(
    teams: List[TournamentTeam],
    all_games: List[Game]
) -> List[MatchupPrediction]:
    """Predict all possible matchups in a bracket (round-robin)"""
    predictions = []
    
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            team_a = teams[i]
            team_b = teams[j]
            
            # Create TeamRanking objects for prediction
            team_a_ranking = TeamRanking(
                team_id_master=team_a.team_id_master,
                power_score_final=team_a.power_score_final,
                sos_norm=team_a.sos_norm or 0.5,
                offense_norm=team_a.offense_norm or 0.5,
                defense_norm=team_a.defense_norm or 0.5,
                age=team_a.age or 12,
                games_played=team_a.games_played
            )
            
            team_b_ranking = TeamRanking(
                team_id_master=team_b.team_id_master,
                power_score_final=team_b.power_score_final,
                sos_norm=team_b.sos_norm or 0.5,
                offense_norm=team_b.offense_norm or 0.5,
                defense_norm=team_b.defense_norm or 0.5,
                age=team_b.age or 12,
                games_played=team_b.games_played
            )
            
            # Run prediction
            try:
                prediction = predict_match(team_a_ranking, team_b_ranking, all_games)
                
                matchup = MatchupPrediction(
                    team_a=team_a,
                    team_b=team_b,
                    expected_margin=abs(prediction.expected_margin),
                    expected_score_a=prediction.expected_score['teamA'],
                    expected_score_b=prediction.expected_score['teamB'],
                    win_prob_a=prediction.win_probability_a,
                    is_blowout=abs(prediction.expected_margin) > 3.0
                )
                predictions.append(matchup)
            except Exception as e:
                console.print(f"[yellow]Warning: Could not predict {team_a.team_name} vs {team_b.team_name}: {e}[/yellow]")
                continue
    
    return predictions


def fetch_recent_games(supabase, team_ids: List[str], lookback_days: int = 90) -> List[Game]:
    """Fetch recent games for form calculation"""
    try:
        from datetime import datetime, timedelta
        cutoff_date = (datetime.now() - timedelta(days=lookback_days)).date().isoformat()
        
        result = supabase.table('games').select(
            'id, home_team_master_id, away_team_master_id, home_score, away_score, game_date'
        ).in_('home_team_master_id', team_ids).in_('away_team_master_id', team_ids).gte(
            'game_date', cutoff_date
        ).execute()
        
        games = []
        if result.data:
            for row in result.data:
                games.append(Game(
                    id=row['id'],
                    home_team_master_id=row.get('home_team_master_id'),
                    away_team_master_id=row.get('away_team_master_id'),
                    home_score=row.get('home_score'),
                    away_score=row.get('away_score'),
                    game_date=row['game_date']
                ))
        
        return games
    except Exception as e:
        console.print(f"[yellow]Warning: Could not fetch games: {e}[/yellow]")
        return []


def analyze_desert_super_cup(
    event_id: str = None,
    event_url: str = None,
    age_group: str = 'u12',
    gender: str = 'M',
    bracket_config: Dict[str, int] = None
):
    """
    Main analysis function for Desert Super Cup
    """
    if not event_id and not event_url:
        console.print("[bold red]Error: Must provide event_id or event_url[/bold red]")
        console.print("[yellow]Example: --event-id 40550 or --event-url 'https://www.gotsport.com/events/40550'[/yellow]")
        return
    
    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )
    
    # Step 1: Scrape teams from tournament
    console.print("\n[bold cyan]Step 1: Scraping teams from Desert Super Cup tournament...[/bold cyan]")
    
    scraper = GotSportEventScraper(supabase, 'gotsport')
    
    # Store brackets_with_groups for later use
    brackets_with_groups = {}
    
    # For U12B, use direct schedule URLs if event_id is 40550
    if event_id == '40550' and age_group.lower() == 'u12' and gender.upper() == 'M':
        console.print("[cyan]Using direct schedule URLs for U12B brackets...[/cyan]")
        schedule_urls = {
            "SUPER PRO - U12B": "https://system.gotsport.com/org_event/events/40550/schedules?group=341505",
            "SUPER ELITE - U12B": "https://system.gotsport.com/org_event/events/40550/schedules?group=341506",
            "SUPER BLACK - U12B": "https://system.gotsport.com/org_event/events/40550/schedules?group=451153"
        }
        
        brackets_with_groups = {}
        for bracket_name, schedule_url in schedule_urls.items():
            groups = scraper.extract_teams_by_group_from_schedule_page(bracket_name, schedule_url)
            if groups:
                brackets_with_groups[bracket_name] = groups
                total_teams = sum(len(teams) for teams in groups.values())
                console.print(f"  {bracket_name}: {total_teams} teams in {len(groups)} groups")
    
    try:
        # If we didn't get groups from direct URLs, try the normal method
        if not brackets_with_groups:
            # Try to get teams with group information from schedule pages
            if event_url:
                brackets_with_groups = scraper.list_event_teams_with_groups(event_url=event_url)
            elif event_id:
                brackets_with_groups = scraper.list_event_teams_with_groups(event_id=event_id)
            else:
                brackets_with_groups = {}
        
        # Store for later use in step 7
        globals()['brackets_with_groups'] = brackets_with_groups
        
        # Convert to flat structure for backward compatibility
        brackets_data = {}
        if brackets_with_groups:
            for bracket_name, groups in brackets_with_groups.items():
                # Flatten groups into single list
                all_teams = []
                for group_teams in groups.values():
                    all_teams.extend(group_teams)
                brackets_data[bracket_name] = all_teams
        else:
            # Fallback to regular method
            if event_url:
                brackets_data = scraper.list_event_teams(event_url=event_url)
            elif event_id:
                brackets_data = scraper.list_event_teams(event_id=event_id)
        
        if not brackets_data:
            console.print("[bold red]Error: Could not fetch tournament data[/bold red]")
            return
        
        console.print(f"[green]Found {len(brackets_data)} brackets[/green]")
        for bracket_name, teams in brackets_data.items():
            if brackets_with_groups and bracket_name in brackets_with_groups:
                groups_info = brackets_with_groups[bracket_name]
                console.print(f"  {bracket_name}: {len(teams)} teams in {len(groups_info)} groups")
                for group_name, group_teams in groups_info.items():
                    console.print(f"    {group_name}: {len(group_teams)} teams")
            else:
                console.print(f"  {bracket_name}: {len(teams)} teams")
        
    except Exception as e:
        console.print(f"[bold red]Error fetching tournament: {e}[/bold red]")
        return
    
    # Filter to U12B brackets only
    console.print(f"\n[cyan]Filtering to U12B teams...[/cyan]")
    u12b_brackets = {}
    for bracket_name, teams in brackets_data.items():
        # Check if this is a U12B bracket
        if 'U12B' in bracket_name.upper() or 'U12' in bracket_name.upper() and 'B' in bracket_name.upper():
            # Also check team ages
            u12_teams = []
            for team in teams:
                # Check if team is actually U12 (age_group or birth year)
                if team.age_group and ('12' in team.age_group or '2014' in team.team_name or '2014' in str(team.age_group)):
                    u12_teams.append(team)
                elif not team.age_group:
                    # If no age group, include it and filter later
                    u12_teams.append(team)
            
            if u12_teams:
                u12b_brackets[bracket_name] = u12_teams
    
    if not u12b_brackets:
        console.print("[yellow]No U12B brackets found. Showing all brackets for manual selection...[/yellow]")
        u12b_brackets = brackets_data
    
    console.print(f"[green]Found {len(u12b_brackets)} U12B brackets with {sum(len(t) for t in u12b_brackets.values())} teams[/green]\n")
    
    # Step 2: Find team_id_master for each team
    console.print("\n[bold cyan]Step 2: Matching teams to database...[/bold cyan]")
    
    all_team_ids = []
    bracket_teams_map: Dict[str, List[str]] = {}
    matched_count = 0
    unmatched_count = 0
    
    # Build provider_team_id -> team_id_master mapping as we match teams
    provider_to_master: Dict[str, str] = {}
    
    for bracket_name, event_teams in u12b_brackets.items():
        team_ids = []
        for event_team in event_teams:
            team_found = False
            # Try to find team_id_master from provider_team_id
            try:
                result = supabase.table('teams').select('team_id_master, team_name').eq(
                    'provider_team_id', event_team.team_id
                ).limit(1).execute()
                
                if result.data:
                    team_id = result.data[0]['team_id_master']
                    team_ids.append(team_id)
                    all_team_ids.append(team_id)
                    provider_to_master[event_team.team_id] = team_id
                    matched_count += 1
                    team_found = True
                    console.print(f"  [green]✓[/green] {event_team.team_name} (matched by ID)")
            except Exception as e:
                pass
            
            # If not found by ID, try exact name match (for U12 Boys)
            if not team_found:
                try:
                    # Clean team name - remove common prefixes
                    clean_name = event_team.team_name.strip()
                    
                    # Try exact match first
                    result = supabase.table('teams').select('team_id_master, team_name').eq(
                        'team_name', clean_name
                    ).eq('age_group', 'u12').eq('gender', 'Male').limit(1).execute()
                    
                    if result.data:
                        team_id = result.data[0]['team_id_master']
                        team_ids.append(team_id)
                        all_team_ids.append(team_id)
                        provider_to_master[event_team.team_id] = team_id
                        matched_count += 1
                        team_found = True
                        console.print(f"  [green]✓[/green] {event_team.team_name} (matched by exact name)")
                    else:
                        # Strategy 2: Try matching without club prefix - remove first 1-4 words
                        name_parts = clean_name.split()
                        for remove_count in [1, 2, 3, 4]:
                            if len(name_parts) > remove_count:
                                short_name = ' '.join(name_parts[remove_count:])
                                result = supabase.table('teams').select('team_id_master, team_name').eq(
                                    'team_name', short_name
                                ).eq('age_group', 'u12').eq('gender', 'Male').limit(1).execute()
                                
                                if result.data:
                                    team_id = result.data[0]['team_id_master']
                                    team_ids.append(team_id)
                                    all_team_ids.append(team_id)
                                    provider_to_master[event_team.team_id] = team_id
                                    matched_count += 1
                                    team_found = True
                                    console.print(f"  [green]✓[/green] {event_team.team_name} → {result.data[0]['team_name']} (no prefix)")
                                    break
                        
                        # Strategy 3: Partial match using key identifying words
                        if not team_found:
                            # Extract key words (usually last 3-6 words contain team name)
                            key_words = name_parts[-6:] if len(name_parts) >= 6 else name_parts
                            search_term = ' '.join(key_words)
                            
                            # Try ILIKE search
                            result = supabase.table('teams').select('team_id_master, team_name').ilike(
                                'team_name', f'%{search_term}%'
                            ).eq('age_group', 'u12').eq('gender', 'Male').limit(20).execute()
                            
                            if result.data:
                                # Find best match by scoring
                                best_match = None
                                best_score = 0
                                event_lower = clean_name.lower()
                                
                                for row in result.data:
                                    db_name = row['team_name'].lower()
                                    score = 0
                                    
                                    # Score based on matching key words
                                    for word in key_words:
                                        if len(word) > 2 and word.lower() in db_name:
                                            score += 1
                                    
                                    # Bonus for matching year/age indicators
                                    for indicator in ['2014', '2015', '14', '15', 'u12', 'b14', 'pre-ecnl', 'pre ecnl', 'premier', 'black', 'blue', 'green', 'red', 'gold']:
                                        if indicator in event_lower and indicator in db_name:
                                            score += 2
                                    
                                    # Bonus for matching club/academy names
                                    club_words = ['southeast', 'northwest', 'north', 'south', 'royals', 'halcones', 'sandsharks', 'dynamos', 'tuzos', 'playmaker', 'phoenix', 'scottsdale', 'rebels', 'classic', 'ccv', 'stars', 'azfc', 'select', 'drsc', 'fusion']
                                    for club_word in club_words:
                                        if club_word in event_lower and club_word in db_name:
                                            score += 1
                                    
                                    if score > best_score:
                                        best_score = score
                                        best_match = row
                                
                                if best_match and best_score >= 2:  # Require at least 2 matching elements
                                    team_id = best_match['team_id_master']
                                    team_ids.append(team_id)
                                    all_team_ids.append(team_id)
                                    provider_to_master[event_team.team_id] = team_id
                                    matched_count += 1
                                    team_found = True
                                    console.print(f"  [green]✓[/green] {event_team.team_name} → {best_match['team_name']} (partial)")
                        
                        # Strategy 4: Special cases (Inland Surf, etc.)
                        if not team_found and 'inland' in clean_name.lower() and 'surf' in clean_name.lower():
                            result = supabase.table('teams').select('team_id_master, team_name').ilike(
                                'team_name', '%inland%surf%'
                            ).eq('age_group', 'u12').eq('gender', 'Male').limit(10).execute()
                            
                            if result.data:
                                event_lower = clean_name.lower()
                                has_ea_in_event = 'ea' in event_lower or 'ea2' in event_lower or 'ea-' in event_lower
                                
                                best_match = None
                                for row in result.data:
                                    db_name = row['team_name'].lower()
                                    db_has_ea = 'ea' in db_name or 'ea-' in db_name or 'ea2' in db_name
                                    
                                    if has_ea_in_event and db_has_ea:
                                        best_match = row
                                        break
                                    elif not has_ea_in_event and not db_has_ea:
                                        best_match = row
                                
                                match_row = best_match or result.data[0]
                                team_id = match_row['team_id_master']
                                team_ids.append(team_id)
                                all_team_ids.append(team_id)
                                provider_to_master[event_team.team_id] = team_id
                                matched_count += 1
                                team_found = True
                                console.print(f"  [green]✓[/green] {event_team.team_name} → {match_row['team_name']} (special)")
                        
                        # Strategy 5: Try without age_group filter (in case it's stored differently)
                        if not team_found:
                            # Try matching just by name and gender, without age filter
                            result = supabase.table('teams').select('team_id_master, team_name, age_group').eq(
                                'team_name', clean_name
                            ).eq('gender', 'Male').limit(5).execute()
                            
                            if result.data:
                                # Check if any match is U12 or close
                                for row in result.data:
                                    age_grp = str(row.get('age_group', '')).lower()
                                    if 'u12' in age_grp or '12' in age_grp or '2014' in age_grp or '2015' in age_grp:
                                        team_id = row['team_id_master']
                                        team_ids.append(team_id)
                                        all_team_ids.append(team_id)
                                        provider_to_master[event_team.team_id] = team_id
                                        matched_count += 1
                                        team_found = True
                                        console.print(f"  [green]✓[/green] {event_team.team_name} → {row['team_name']} (no age filter)")
                                        break
                            
                            # Also try without prefix and without age filter
                            if not team_found:
                                for remove_count in [1, 2, 3, 4]:
                                    if len(name_parts) > remove_count:
                                        short_name = ' '.join(name_parts[remove_count:])
                                        result = supabase.table('teams').select('team_id_master, team_name, age_group').eq(
                                            'team_name', short_name
                                        ).eq('gender', 'Male').limit(5).execute()
                                        
                                        if result.data:
                                            for row in result.data:
                                                age_grp = str(row.get('age_group', '')).lower()
                                                if 'u12' in age_grp or '12' in age_grp or '2014' in age_grp or '2015' in age_grp:
                                                    team_id = row['team_id_master']
                                                    team_ids.append(team_id)
                                                    all_team_ids.append(team_id)
                                                    provider_to_master[event_team.team_id] = team_id
                                                    matched_count += 1
                                                    team_found = True
                                                    console.print(f"  [green]✓[/green] {event_team.team_name} → {row['team_name']} (no age filter, no prefix)")
                                                    break
                                            if team_found:
                                                break
                except Exception as e:
                    pass
            
            # Strategy 6: Handle teams playing up (e.g., 2015 Boys in U12 tournament)
            if not team_found:
                # Check if this is a 2015 team (U11 playing up to U12)
                if '2015' in clean_name or 'u11' in clean_name.lower():
                    # Try matching as U11 team
                    result = supabase.table('teams').select('team_id_master, team_name').eq(
                        'team_name', clean_name
                    ).eq('age_group', 'u11').eq('gender', 'Male').limit(1).execute()
                    
                    if result.data:
                        team_id = result.data[0]['team_id_master']
                        team_ids.append(team_id)
                        all_team_ids.append(team_id)
                        provider_to_master[event_team.team_id] = team_id
                        matched_count += 1
                        team_found = True
                        console.print(f"  [green]✓[/green] {event_team.team_name} → {result.data[0]['team_name']} (U11 playing up)")
                    else:
                        # Try without prefix as U11
                        for remove_count in [1, 2, 3, 4]:
                            if len(name_parts) > remove_count:
                                short_name = ' '.join(name_parts[remove_count:])
                                result = supabase.table('teams').select('team_id_master, team_name').eq(
                                    'team_name', short_name
                                ).eq('age_group', 'u11').eq('gender', 'Male').limit(1).execute()
                                
                                if result.data:
                                    team_id = result.data[0]['team_id_master']
                                    team_ids.append(team_id)
                                    all_team_ids.append(team_id)
                                    provider_to_master[event_team.team_id] = team_id
                                    matched_count += 1
                                    team_found = True
                                    console.print(f"  [green]✓[/green] {event_team.team_name} → {result.data[0]['team_name']} (U11 playing up, no prefix)")
                                    break
                        
                        # Try partial match for U11 teams
                        if not team_found:
                            key_words = name_parts[-6:] if len(name_parts) >= 6 else name_parts
                            search_term = ' '.join(key_words)
                            
                            result = supabase.table('teams').select('team_id_master, team_name').ilike(
                                'team_name', f'%{search_term}%'
                            ).eq('age_group', 'u11').eq('gender', 'Male').limit(20).execute()
                            
                            if result.data:
                                best_match = None
                                best_score = 0
                                event_lower = clean_name.lower()
                                
                                for row in result.data:
                                    db_name = row['team_name'].lower()
                                    score = 0
                                    
                                    for word in key_words:
                                        if len(word) > 2 and word.lower() in db_name:
                                            score += 1
                                    
                                    for indicator in ['2015', '15', 'u11', 'boys', 'black', 'red', 'blue', 'green', 'northwest', 'north', 'southeast', 'south']:
                                        if indicator in event_lower and indicator in db_name:
                                            score += 2
                                    
                                    if score > best_score:
                                        best_score = score
                                        best_match = row
                                
                                if best_match and best_score >= 2:
                                    team_id = best_match['team_id_master']
                                    team_ids.append(team_id)
                                    all_team_ids.append(team_id)
                                    provider_to_master[event_team.team_id] = team_id
                                    matched_count += 1
                                    team_found = True
                                    console.print(f"  [green]✓[/green] {event_team.team_name} → {best_match['team_name']} (U11 playing up, partial)")
            
            if not team_found:
                unmatched_count += 1
                console.print(f"  [yellow]Not found: {event_team.team_name} (ID: {event_team.team_id})[/yellow]")
        
        if team_ids:
            bracket_teams_map[bracket_name] = team_ids
    
    console.print(f"\n[green]Matched {matched_count} teams, {unmatched_count} not found[/green]\n")
    
    if not all_team_ids:
        console.print("[bold red]Error: Could not find any teams in database[/bold red]")
        return
    
    console.print(f"[green]Found {len(all_team_ids)} teams in database[/green]")
    
    # Step 3: Fetch rankings
    console.print("\n[bold cyan]Step 3: Fetching team rankings...[/bold cyan]")
    
    rankings_data = fetch_team_rankings(supabase, all_team_ids, age_group, gender)
    
    # Step 4: Build TournamentTeam objects
    console.print("\n[bold cyan]Step 4: Building team data structures...[/bold cyan]")
    
    tournament_teams: Dict[str, List[TournamentTeam]] = {}
    all_tournament_teams: List[TournamentTeam] = []
    
    # Create map of team_id_master -> event_team info (for later use)
    master_to_event_team = {}
    for bracket_name, event_teams in u12b_brackets.items():
        for event_team in event_teams:
            team_id_master = provider_to_master.get(event_team.team_id)
            if team_id_master:
                master_to_event_team[team_id_master] = (bracket_name, event_team)
    
    # Now build TournamentTeam objects using the matched team IDs
    for bracket_name, team_ids_list in bracket_teams_map.items():
        bracket_team_list = []
        for team_id in team_ids_list:
            if team_id in rankings_data:
                rank_data = rankings_data[team_id]
                # Get event team info
                event_bracket, event_team = master_to_event_team.get(team_id, (bracket_name, None))
                
                team = TournamentTeam(
                    team_id_master=team_id,
                    team_name=rank_data.get('team_name', event_team.team_name if event_team else 'Unknown'),
                    club_name=rank_data.get('club_name'),
                    bracket_name=bracket_name,  # Use actual bracket from tournament
                    power_score_final=rank_data.get('power_score_final', 0.5),
                    rank_in_cohort_final=rank_data.get('rank_in_cohort_final'),
                    sos_norm=rank_data.get('sos_norm'),
                    offense_norm=rank_data.get('offense_norm'),
                    defense_norm=rank_data.get('defense_norm'),
                    age=rank_data.get('age'),
                    games_played=rank_data.get('games_played', 0)
                )
                bracket_team_list.append(team)
                all_tournament_teams.append(team)
        
        if bracket_team_list:
            tournament_teams[bracket_name] = bracket_team_list
    
    if not tournament_teams:
        console.print("[bold red]Error: No teams with rankings found[/bold red]")
        return
    
    # Display teams found
    console.print("\n[bold cyan]Teams Found by Bracket:[/bold cyan]\n")
    for bracket_name, teams in tournament_teams.items():
        console.print(Panel(f"[bold]{bracket_name}[/bold] ({len(teams)} teams)", style="cyan"))
        table = Table(box=box.SIMPLE)
        table.add_column("Team Name", style="yellow")
        table.add_column("Power Score", style="cyan", justify="right")
        table.add_column("National Rank", style="green", justify="right")
        
        sorted_teams = sorted(teams, key=lambda t: t.power_score_final, reverse=True)
        for team in sorted_teams:
            table.add_row(
                team.team_name,
                f"{team.power_score_final:.3f}",
                f"#{team.rank_in_cohort_final}" if team.rank_in_cohort_final else "N/A"
            )
        console.print(table)
        console.print()
    
    # Step 5: Fetch recent games (needed for prediction-based optimization)
    console.print("\n[bold cyan]Step 5: Fetching recent games...[/bold cyan]")
    all_games = fetch_recent_games(supabase, all_team_ids)
    console.print(f"[green]Found {len(all_games)} recent games[/green]\n")
    
    # Step 6: Create optimal brackets using prediction-based optimization
    console.print("\n[bold cyan]Step 6: Creating optimal brackets...[/bold cyan]")
    
    # Use provided bracket config or infer from actual brackets
    if not bracket_config:
        # Infer bracket sizes from actual brackets
        bracket_config = {}
        for bracket_name, teams_list in tournament_teams.items():
            bracket_config[bracket_name] = len(teams_list)
    
    optimal_brackets = create_optimal_brackets(all_tournament_teams, bracket_config, all_games)
    
    # Step 7: Organize actual brackets into groups
    console.print("\n[bold cyan]Step 7: Organizing actual brackets into groups...[/bold cyan]\n")
    
    # Use group information from schedule pages if available
    actual_brackets_groups: Dict[str, Dict[str, List[TournamentTeam]]] = {}
    
    # Check if we have group information from schedule pages
    if brackets_with_groups:
        console.print("[green]Using actual group assignments from tournament schedule pages[/green]\n")
        
        # Create a map of team_id_master to TournamentTeam
        team_map = {t.team_id_master: t for t in all_tournament_teams}
        
        # Use the provider_to_master map we built earlier
        for bracket_name, groups in brackets_with_groups.items():
            # Normalize bracket name for matching
            normalized_bracket = bracket_name.upper().replace(' - ', ' ').replace('-', ' ')
            
            # Find matching bracket in tournament_teams
            matching_bracket = None
            for t_bracket in tournament_teams.keys():
                if normalized_bracket in t_bracket.upper() or t_bracket.upper() in normalized_bracket:
                    matching_bracket = t_bracket
                    break
            
            if not matching_bracket:
                matching_bracket = bracket_name if bracket_name in tournament_teams else None
            
            target_bracket = matching_bracket or bracket_name
            
            if target_bracket not in actual_brackets_groups:
                actual_brackets_groups[target_bracket] = {}
            
            for group_name, event_teams in groups.items():
                group_tournament_teams = []
                for event_team in event_teams:
                    # Use provider_to_master map to find team_id_master
                    team_id_master = provider_to_master.get(event_team.team_id)
                    
                    if team_id_master and team_id_master in team_map:
                        group_tournament_teams.append(team_map[team_id_master])
                
                if group_tournament_teams:
                    actual_brackets_groups[target_bracket][group_name] = group_tournament_teams
    else:
        # Fallback: Check if we need to split teams into multiple brackets
        # If all teams are in one bracket (like "U12B"), we need to manually split them
        # based on the tournament structure: Super Pro (8), Super Elite (6), Super Black (6)
        if len(tournament_teams) == 1 and len(all_tournament_teams) >= 17:
            console.print("[yellow]Note: All teams found in single bracket. Splitting into tournament structure...[/yellow]")
            sorted_all = sorted(all_tournament_teams, key=lambda t: t.power_score_final, reverse=True)
            
            # Split into 3 brackets: Top 8, Next 6, Next 6 (or remaining)
            super_pro = sorted_all[:8]
            super_elite = sorted_all[8:14] if len(sorted_all) >= 14 else sorted_all[8:]
            super_black = sorted_all[14:] if len(sorted_all) >= 14 else []
            
            # Organize each bracket into groups
            if super_pro:
                actual_brackets_groups["Super Pro U12B"] = {
                    "Group A": super_pro[:4],
                    "Group B": super_pro[4:]
                }
            if super_elite:
                actual_brackets_groups["Super Elite U12B"] = {
                    "Group A": super_elite[:3],
                    "Group B": super_elite[3:]
                }
            if super_black:
                actual_brackets_groups["Super Black U12B"] = {
                    "Group A": super_black[:3] if len(super_black) >= 3 else super_black[:len(super_black)//2],
                    "Group B": super_black[3:] if len(super_black) >= 3 else super_black[len(super_black)//2:]
                }
        else:
            # Normal case: teams already separated into brackets
            for bracket_name, teams in tournament_teams.items():
                num_teams = len(teams)
                sorted_teams = sorted(teams, key=lambda t: t.power_score_final, reverse=True)
                if num_teams == 8:
                    groups = {
                        "Group A": sorted_teams[:4],
                        "Group B": sorted_teams[4:]
                    }
                elif num_teams == 6:
                    groups = {
                        "Group A": sorted_teams[:3],
                        "Group B": sorted_teams[3:]
                    }
                else:
                    groups = {"Group A": sorted_teams}
                actual_brackets_groups[bracket_name] = groups
    
    # Step 8: Predict matchups
    console.print("\n[bold cyan]Step 8: Predicting matchups...[/bold cyan]\n")
    
    actual_predictions = []
    optimal_predictions = []
    
    total_groups = sum(len(groups) for groups in actual_brackets_groups.values())
    console.print(f"[cyan]Found {total_groups} groups in actual brackets[/cyan]")
    for bracket_name, groups in actual_brackets_groups.items():
        for group_name, teams in groups.items():
            console.print(f"  {bracket_name} {group_name}: {len(teams)} teams")
    
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("Predicting actual brackets...", total=total_groups)
        for bracket_name, groups in actual_brackets_groups.items():
            for group_name, teams in groups.items():
                if len(teams) >= 2:  # Need at least 2 teams for matchups
                    group_predictions = predict_matchups_in_bracket(teams, all_games)
                    actual_predictions.extend(group_predictions)
                progress.update(task, advance=1)
    
    total_groups = sum(len(groups) for groups in optimal_brackets.values())
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("Predicting optimal brackets...", total=total_groups)
        for bracket_name, groups in optimal_brackets.items():
            for group_name, teams in groups.items():
                group_predictions = predict_matchups_in_bracket(teams, all_games)
                optimal_predictions.extend(group_predictions)
                progress.update(task, advance=1)
    
    # Step 9: Display results
    console.print("\n[bold cyan]Step 9: Analysis Results[/bold cyan]\n")
    
    actual_margins = [p.expected_margin for p in actual_predictions]
    optimal_margins = [p.expected_margin for p in optimal_predictions]
    
    actual_blowouts = sum(1 for p in actual_predictions if p.is_blowout)
    optimal_blowouts = sum(1 for p in optimal_predictions if p.is_blowout)
    
    # Summary table
    summary_table = Table(title="Tournament Bracket Analysis Summary", box=box.ROUNDED)
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Actual Brackets", style="yellow")
    summary_table.add_column("Optimal Brackets", style="green")
    summary_table.add_column("Improvement", style="magenta")
    
    avg_actual = statistics.mean(actual_margins) if actual_margins else 0
    avg_optimal = statistics.mean(optimal_margins) if optimal_margins else 0
    improvement = avg_optimal - avg_actual  # Positive = optimal is better (lower differential)
    improvement_pct = (improvement / avg_actual * 100) if avg_actual > 0 else 0
    
    summary_table.add_row(
        "Average Goal Differential",
        f"{avg_actual:.2f}",
        f"{avg_optimal:.2f}",
        f"{improvement:.2f} ({abs(improvement_pct):.1f}% {'better' if improvement < 0 else 'worse'})" if avg_actual > 0 else "N/A"
    )
    
    summary_table.add_row(
        "Median Goal Differential",
        f"{statistics.median(actual_margins):.2f}" if actual_margins else "N/A",
        f"{statistics.median(optimal_margins):.2f}" if optimal_margins else "N/A",
        f"{statistics.median(actual_margins) - statistics.median(optimal_margins):.2f}" if actual_margins and optimal_margins else "N/A"
    )
    
    blowout_reduction = actual_blowouts - optimal_blowouts
    blowout_reduction_pct = (blowout_reduction / len(actual_predictions) * 100) if actual_predictions else 0
    
    summary_table.add_row(
        "Blowouts (>3 goal margin)",
        f"{actual_blowouts} ({actual_blowouts/len(actual_predictions)*100:.1f}%)" if actual_predictions else "0",
        f"{optimal_blowouts} ({optimal_blowouts/len(optimal_predictions)*100:.1f}%)" if optimal_predictions else "0",
        f"-{blowout_reduction} ({abs(blowout_reduction_pct):.1f}% {'reduction' if blowout_reduction > 0 else 'increase'})" if actual_predictions else "N/A"
    )
    
    summary_table.add_row(
        "Total Matchups",
        str(len(actual_predictions)),
        str(len(optimal_predictions)),
        ""
    )
    
    console.print(summary_table)
    
    # Add note about what we're comparing
    console.print("\n[yellow]⚠️  Important Note:[/yellow]")
    console.print("[yellow]The tournament page doesn't show detailed bracket/group assignments.")
    console.print("[yellow]'Actual Brackets' assumes teams were seeded by power score ranking")
    console.print("[yellow](top 8 → Super Pro, next 6 → Super Elite, next 6 → Super Black).")
    console.print("[yellow]This may not reflect the tournament's actual seeding method.\n")
    console.print("[cyan]The 'Optimal Brackets' use snake-draft seeding to balance strength")
    console.print("[cyan]across groups and minimize blowouts.\n")
    
    # Bracket comparisons
    console.print("\n[bold cyan]Bracket & Group Comparisons:[/bold cyan]\n")
    
    # Compare all brackets (both actual and optimal)
    all_bracket_names = set(list(actual_brackets_groups.keys()) + list(optimal_brackets.keys()))
    for bracket_name in sorted(all_bracket_names):
        actual_groups = actual_brackets_groups.get(bracket_name, {})
        optimal_groups = optimal_brackets.get(bracket_name, {})
        
        console.print(Panel(f"[bold]{bracket_name}[/bold]", style="cyan"))
        
        for group_name in ["Group A", "Group B"]:
            actual_teams = actual_groups.get(group_name, [])
            optimal_teams = optimal_groups.get(group_name, [])
            
            if not actual_teams and not optimal_teams:
                continue
            
            group_table = Table(title=f"{group_name}: Actual vs Optimal", box=box.SIMPLE)
            group_table.add_column("Actual Seeding", style="yellow", width=40)
            group_table.add_column("Power Score", style="cyan", justify="right")
            group_table.add_column("Optimal Seeding", style="green", width=40)
            group_table.add_column("Power Score", style="cyan", justify="right")
            
            max_len = max(len(actual_teams), len(optimal_teams))
            for i in range(max_len):
                actual_team = actual_teams[i] if i < len(actual_teams) else None
                optimal_team = optimal_teams[i] if i < len(optimal_teams) else None
                
                group_table.add_row(
                    actual_team.team_name if actual_team else "",
                    f"{actual_team.power_score_final:.3f}" if actual_team else "",
                    optimal_team.team_name if optimal_team else "",
                    f"{optimal_team.power_score_final:.3f}" if optimal_team else ""
                )
            
            console.print(group_table)
            console.print()
        
        # Show bracket-level statistics
        actual_bracket_team_ids = {t.team_id_master for teams in actual_groups.values() for t in teams}
        optimal_bracket_team_ids = {t.team_id_master for teams in optimal_groups.values() for t in teams}
        
        actual_bracket_predictions = [
            p for p in actual_predictions 
            if p.team_a.team_id_master in actual_bracket_team_ids and p.team_b.team_id_master in actual_bracket_team_ids
        ]
        optimal_bracket_predictions = [
            p for p in optimal_predictions
            if p.team_a.team_id_master in optimal_bracket_team_ids and p.team_b.team_id_master in optimal_bracket_team_ids
        ]
        
        if actual_bracket_predictions and optimal_bracket_predictions:
            actual_avg = statistics.mean([p.expected_margin for p in actual_bracket_predictions])
            optimal_avg = statistics.mean([p.expected_margin for p in optimal_bracket_predictions])
            
            stats_table = Table(box=box.SIMPLE)
            stats_table.add_column("Metric", style="cyan")
            stats_table.add_column("Actual", style="yellow", justify="right")
            stats_table.add_column("Optimal", style="green", justify="right")
            stats_table.add_column("Improvement", style="magenta", justify="right")
            
            stats_table.add_row(
                "Avg Goal Diff",
                f"{actual_avg:.2f}",
                f"{optimal_avg:.2f}",
                f"{actual_avg - optimal_avg:.2f}"
            )
            
            actual_blowouts = sum(1 for p in actual_bracket_predictions if p.is_blowout)
            optimal_blowouts = sum(1 for p in optimal_bracket_predictions if p.is_blowout)
            
            stats_table.add_row(
                "Blowouts",
                str(actual_blowouts),
                str(optimal_blowouts),
                f"-{actual_blowouts - optimal_blowouts}"
            )
            
            console.print(stats_table)
            console.print()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze Desert Super Cup tournament brackets")
    parser.add_argument("--event-id", type=str, help="GotSport event ID")
    parser.add_argument("--event-url", type=str, help="Full URL to GotSport event page")
    parser.add_argument("--age-group", type=str, default="u12", help="Age group (default: u12)")
    parser.add_argument("--gender", type=str, default="M", help="Gender: M or F (default: M)")
    parser.add_argument("--bracket-config", type=str, help="Bracket configuration: 'Super Pro U12B:8,Super Elite U12B:6,Super Black U12B:6'")
    
    args = parser.parse_args()
    
    # Parse bracket config if provided
    bracket_config = None
    if args.bracket_config:
        bracket_config = {}
        for item in args.bracket_config.split(','):
            name, count = item.split(':')
            bracket_config[name.strip()] = int(count.strip())
    
    # Default config for U12 Boys tournament
    if not bracket_config and args.age_group.lower() == 'u12' and args.gender.upper() == 'M':
        bracket_config = {
            "Super Pro U12B": 8,
            "Super Elite U12B": 6,
            "Super Black U12B": 6
        }
        console.print(f"[cyan]Using default bracket config: {bracket_config}[/cyan]")
    
    analyze_desert_super_cup(
        event_id=args.event_id,
        event_url=args.event_url,
        age_group=args.age_group,
        gender=args.gender,
        bracket_config=bracket_config
    )

