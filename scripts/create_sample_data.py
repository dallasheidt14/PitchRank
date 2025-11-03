"""Create sample data for testing and development"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import random
import uuid

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import track

sys.path.append(str(Path(__file__).parent.parent))
from config.settings import AGE_GROUPS

console = Console()
load_dotenv()


class SampleDataGenerator:
    """Generate sample teams, games, and aliases"""

    def __init__(self):
        self.supabase = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        )
        self.provider_id = None
        self.teams_created = []
        self.games_created = []

    def create_all(self, num_teams: int = 20, num_games_per_team: int = 15):
        """Create complete sample dataset"""
        console.print("[bold]Creating sample data...[/bold]")
        
        # Ensure provider exists
        self._ensure_provider()
        
        # Create teams
        console.print(f"\n[cyan]Creating {num_teams} teams...[/cyan]")
        self._create_teams(num_teams)
        
        # Create games
        console.print(f"\n[cyan]Creating games (up to {num_games_per_team} per team)...[/cyan]")
        self._create_games(num_games_per_team)
        
        # Create aliases
        console.print("\n[cyan]Creating team aliases...[/cyan]")
        self._create_aliases()
        
        console.print("\n[bold green]✅ Sample data creation complete![/bold green]")
        console.print(f"  - Teams: {len(self.teams_created)}")
        console.print(f"  - Games: {len(self.games_created)}")

    def _ensure_provider(self):
        """Ensure sample provider exists"""
        try:
            result = self.supabase.table('providers').select('id').eq(
                'code', 'sample'
            ).single().execute()
            
            if result.data:
                self.provider_id = result.data['id']
                return
        except Exception:
            pass
        
        # Create sample provider
        result = self.supabase.table('providers').insert({
            'code': 'sample',
            'name': 'Sample Data Provider',
            'base_url': 'https://sample.example.com',
            'created_at': datetime.now().isoformat()
        }).execute()
        
        self.provider_id = result.data[0]['id']

    def _create_teams(self, num_teams: int):
        """Create sample teams across age groups and genders"""
        clubs = [
            'Red Stars FC', 'Blue Eagles SC', 'Green Dragons',
            'Yellow Lions', 'Orange Tigers', 'Purple Panthers',
            'White Wolves', 'Black Bears', 'Silver Sharks',
            'Gold Falcons'
        ]
        
        states = ['CA', 'TX', 'FL', 'NY', 'IL', 'PA', 'OH', 'GA', 'NC', 'MI']
        
        age_groups = list(AGE_GROUPS.keys())
        genders = ['Male', 'Female']
        
        teams_to_create = []
        
        for i in range(num_teams):
            age_group = random.choice(age_groups)
            gender = random.choice(genders)
            club = random.choice(clubs)
            state = random.choice(states)
            
            # Generate team name
            team_number = random.randint(1, 99)
            team_name = f"{club} {age_group.upper()} {gender[0]}{team_number:02d}"
            
            teams_to_create.append({
                'team_id_master': str(uuid.uuid4()),
                'team_name': team_name,
                'provider_id': self.provider_id,
                'provider_team_id': f'SAMPLE_{uuid.uuid4().hex[:8]}',
                'age_group': age_group,
                'birth_year': AGE_GROUPS.get(age_group, {}).get('birth_year'),
                'gender': gender,
                'club_name': club,
                'state_code': state
            })
        
        # Insert teams
        for team_data in track(teams_to_create, description="Inserting teams"):
            try:
                result = self.supabase.table('teams').insert(team_data).execute()
                if result.data:
                    self.teams_created.append(result.data[0])
            except Exception as e:
                console.print(f"[yellow]Warning: Could not create team {team_data['team_name']}: {e}[/yellow]")

    def _create_games(self, num_games_per_team: int):
        """Create sample games between teams"""
        if len(self.teams_created) < 2:
            console.print("[yellow]Not enough teams to create games[/yellow]")
            return
        
        # Group teams by age group and gender for realistic matchups
        teams_by_group = {}
        for team in self.teams_created:
            key = (team['age_group'], team['gender'])
            if key not in teams_by_group:
                teams_by_group[key] = []
            teams_by_group[key].append(team)
        
        games_to_create = []
        start_date = datetime.now() - timedelta(days=365)
        
        for team in track(self.teams_created, description="Creating games"):
            # Get opponents from same age/gender group (or cross-age)
            age_group = team['age_group']
            gender = team['gender']
            
            # Potential opponents (same age/gender)
            if (age_group, gender) in teams_by_group:
                opponents = [
                    t for t in teams_by_group[(age_group, gender)]
                    if t['team_id_master'] != team['team_id_master']
                ]
            else:
                opponents = [t for t in self.teams_created if t['team_id_master'] != team['team_id_master']]
            
            if not opponents:
                continue
            
            # Create games for this team
            num_games = random.randint(5, num_games_per_team)
            
            for i in range(num_games):
                opponent = random.choice(opponents)
                game_date = start_date + timedelta(days=random.randint(0, 365))
                
                # Random score
                goals_for = random.randint(0, 5)
                goals_against = random.randint(0, 5)
                
                # Determine result
                if goals_for > goals_against:
                    result = 'W'
                elif goals_for < goals_against:
                    result = 'L'
                else:
                    result = 'D'
                
                # Determine home/away
                is_home = random.choice([True, False])
                
                game_data = {
                    'home_team_master_id': team['team_id_master'] if is_home else opponent['team_id_master'],
                    'away_team_master_id': opponent['team_id_master'] if is_home else team['team_id_master'],
                    'home_provider_id': team['provider_team_id'] if is_home else opponent['provider_team_id'],
                    'away_provider_id': opponent['provider_team_id'] if is_home else team['provider_team_id'],
                    'home_score': goals_for if is_home else goals_against,
                    'away_score': goals_against if is_home else goals_for,
                    'result': result,
                    'game_date': game_date.strftime('%Y-%m-%d'),
                    'provider_id': self.provider_id,
                    'scraped_at': datetime.now().isoformat()
                }
                
                games_to_create.append(game_data)
        
        # Insert games in batches
        batch_size = 100
        for i in track(range(0, len(games_to_create), batch_size), description="Inserting games"):
            batch = games_to_create[i:i + batch_size]
            try:
                result = self.supabase.table('games').insert(batch).execute()
                if result.data:
                    self.games_created.extend(result.data)
            except Exception as e:
                console.print(f"[yellow]Warning: Could not insert game batch: {e}[/yellow]")

    def _create_aliases(self):
        """Create alias map entries for all teams"""
        aliases_to_create = []
        
        for team in self.teams_created:
            alias_data = {
                'provider_id': self.provider_id,
                'provider_team_id': team['provider_team_id'],
                'team_id_master': team['team_id_master'],
                'match_method': 'sample_data',
                'match_confidence': 1.0,
                'review_status': 'approved'
            }
            aliases_to_create.append(alias_data)
        
        # Insert aliases
        batch_size = 50
        for i in range(0, len(aliases_to_create), batch_size):
            batch = aliases_to_create[i:i + batch_size]
            try:
                self.supabase.table('team_alias_map').insert(batch).execute()
            except Exception as e:
                console.print(f"[yellow]Warning: Could not insert aliases: {e}[/yellow]")


if __name__ == "__main__":
    num_teams = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    num_games = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    
    generator = SampleDataGenerator()
    generator.create_all(num_teams=num_teams, num_games_per_team=num_games)

