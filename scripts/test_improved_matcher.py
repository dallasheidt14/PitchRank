#!/usr/bin/env python3
"""
Test IMPROVED matcher logic against approved matches.

Improvements over current game_matcher:
1. Extract club name from team_name if club_name is empty
2. Better age normalization (B08/07 → 2008 birth year → U17)
3. Filter by age group FIRST, then fuzzy match on name
4. Use our existing team_name_normalizer patterns

Compare results to baseline (0% accuracy) to measure improvement.
"""

import sys
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from difflib import SequenceMatcher

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from supabase import create_client
from config.settings import SUPABASE_URL, SUPABASE_KEY

# Birth year to age group mapping (for 2026 season)
BIRTH_YEAR_TO_AGE = {
    2008: 'u17', 2009: 'u17',  # U17 = 2008-2009
    2010: 'u16',
    2011: 'u15',
    2012: 'u14',
    2013: 'u13',
    2014: 'u12',
    2015: 'u11',
    2016: 'u10',
}

def extract_birth_year(text: str) -> Optional[int]:
    """Extract birth year from team name patterns like B08/07, G2014, 14B, etc."""
    if not text:
        return None
    
    # Pattern: B08/07, G08/09 (two-digit years with slash)
    match = re.search(r'[BG](\d{2})/(\d{2})', text, re.I)
    if match:
        year = int(match.group(1))
        return 2000 + year if year < 50 else 1900 + year
    
    # Pattern: B08, G09 (single two-digit year after B/G)
    match = re.search(r'[BG](\d{2})(?!\d)', text, re.I)
    if match:
        year = int(match.group(1))
        return 2000 + year if year < 50 else 1900 + year
    
    # Pattern: 2014B, 2015G, B2014, G2015 (four-digit year)
    match = re.search(r'(?:^|[BG])?(20\d{2})[BG]?(?:$|\s)', text, re.I)
    if match:
        return int(match.group(1))
    
    # Pattern: 14B, 15G (two-digit at start/end)
    match = re.search(r'(?:^|\s)(\d{2})[BG](?:$|\s)', text, re.I)
    if match:
        year = int(match.group(1))
        if 6 <= year <= 20:  # Likely birth years 2006-2020
            return 2000 + year
    
    return None

def birth_year_to_age_group(birth_year: int) -> Optional[str]:
    """Convert birth year to age group."""
    return BIRTH_YEAR_TO_AGE.get(birth_year)

def extract_club_from_team_name(team_name: str) -> Tuple[str, str]:
    """
    Extract club name from team name.
    Returns (club_name, remaining_team_info)
    
    Patterns:
    - "Club Name - Team Details" → ("Club Name", "Team Details")
    - "Club Name Team Details" → ("Club Name", "Team Details") based on known patterns
    """
    if not team_name:
        return ('', '')
    
    # Pattern 1: Explicit separator " - "
    if ' - ' in team_name:
        parts = team_name.split(' - ', 1)
        return (parts[0].strip(), parts[1].strip() if len(parts) > 1 else '')
    
    # Pattern 2: Known club suffixes that mark end of club name
    club_suffixes = ['FC', 'SC', 'SA', 'CF', 'AC', 'United', 'City', 'Athletic', 'Academy']
    
    words = team_name.split()
    for i, word in enumerate(words):
        clean_word = word.rstrip(',').upper()
        if clean_word in [s.upper() for s in club_suffixes]:
            # Everything up to and including this word is the club
            club = ' '.join(words[:i+1])
            rest = ' '.join(words[i+1:])
            return (club.strip(), rest.strip())
    
    # Pattern 3: If team name contains age patterns, split there
    age_patterns = [
        r'\s+[BG]?\d{2}/\d{2}\s*',  # B08/07
        r'\s+[BG]20\d{2}\s*',        # B2014
        r'\s+20\d{2}[BG]\s*',        # 2014B
        r'\s+U\d{1,2}\s*',           # U14
        r'\s+\d{2}[BG]\s*',          # 14B
    ]
    
    for pattern in age_patterns:
        match = re.search(pattern, team_name, re.I)
        if match:
            club = team_name[:match.start()].strip()
            rest = team_name[match.start():].strip()
            return (club, rest)
    
    # Fallback: return full name as club
    return (team_name, '')

def normalize_age_group(age_str: str, team_name: str = '') -> Optional[str]:
    """Normalize age group to standard format (u10, u11, etc.)"""
    if not age_str and not team_name:
        return None
    
    # First try to extract birth year from team name
    birth_year = extract_birth_year(team_name)
    if birth_year:
        age = birth_year_to_age_group(birth_year)
        if age:
            return age
    
    # Normalize provided age_str
    if age_str:
        age_str = age_str.lower().strip()
        # Remove gender suffix
        age_str = re.sub(r'[bg]$', '', age_str)
        # Ensure 'u' prefix
        if not age_str.startswith('u'):
            age_str = 'u' + age_str
        # Normalize u9 → u09 style not needed, DB uses u10, u11, etc.
        return age_str
    
    return None

def normalize_for_comparison(name: str) -> str:
    """Normalize name for fuzzy comparison."""
    if not name:
        return ''
    name = name.lower().strip()
    # Remove punctuation
    name = re.sub(r'[^\w\s]', ' ', name)
    # Remove common suffixes
    for suffix in ['fc', 'sc', 'sa', 'academy', 'soccer club', 'football club']:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
    # Compress whitespace
    name = ' '.join(name.split())
    return name

def calculate_similarity(str1: str, str2: str) -> float:
    """Calculate string similarity."""
    s1 = normalize_for_comparison(str1)
    s2 = normalize_for_comparison(str2)
    if s1 == s2:
        return 1.0
    return SequenceMatcher(None, s1, s2).ratio()

class ImprovedMatcher:
    """Improved matcher with club extraction and age filtering."""
    
    def __init__(self, db):
        self.db = db
        self.fuzzy_threshold = 0.75
    
    def fuzzy_match_team(
        self,
        team_name: str,
        age_group: str,
        gender: str,
        club_name: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Improved fuzzy matching:
        1. Extract club from team_name if club_name empty
        2. Normalize age group (handle birth years)
        3. Filter candidates by age group FIRST
        4. Fuzzy match on club/team name
        """
        
        # Step 1: Extract club if missing
        if not club_name:
            club_name, _ = extract_club_from_team_name(team_name)
        
        # Step 2: Normalize age group (handle B08/07 → u17)
        normalized_age = normalize_age_group(age_group, team_name)
        if not normalized_age:
            return None
        
        # Step 3: Get candidates filtered by age group AND gender
        try:
            result = self.db.table('teams').select(
                'team_id_master, team_name, club_name, age_group, gender, state_code'
            ).eq('age_group', normalized_age).eq('gender', gender).execute()
            
            if not result.data:
                return None
            
            # Step 4: Score candidates by club name similarity
            best_match = None
            best_score = 0.0
            
            for team in result.data:
                candidate_club = team.get('club_name') or team.get('team_name', '')
                
                # Primary: club name similarity
                club_score = calculate_similarity(club_name, candidate_club)
                
                # Secondary: team name similarity
                team_score = calculate_similarity(team_name, team.get('team_name', ''))
                
                # Weight club more heavily since age is already filtered
                score = (club_score * 0.7) + (team_score * 0.3)
                
                if score > best_score and score >= self.fuzzy_threshold:
                    best_score = score
                    best_match = {
                        'team_id': team['team_id_master'],
                        'team_name': team['team_name'],
                        'club_name': team.get('club_name'),
                        'confidence': round(score, 3)
                    }
            
            return best_match
            
        except Exception as e:
            print(f"Error in fuzzy_match_team: {e}")
            return None


def run_test(limit: int = 25):
    """Run improved matcher against approved matches."""
    
    db = create_client(SUPABASE_URL, SUPABASE_KEY)
    matcher = ImprovedMatcher(db)
    
    # Load approved matches
    query = db.table('team_match_review_queue').select(
        'provider_team_name, match_details, suggested_master_team_id'
    ).eq('status', 'approved').not_.is_('suggested_master_team_id', 'null')
    
    if limit:
        query = query.limit(limit)
    
    result = query.execute()
    entries = result.data or []
    
    print(f"\n{'='*60}")
    print(f"IMPROVED MATCHER TEST")
    print(f"{'='*60}")
    print(f"Testing {len(entries)} approved matches\n")
    
    correct = 0
    wrong = 0
    no_match = 0
    
    wrong_examples = []
    correct_examples = []
    
    for entry in entries:
        team_name = entry.get('provider_team_name', '')
        details = entry.get('match_details', {}) or {}
        expected_id = entry.get('suggested_master_team_id')
        
        age_group = details.get('age_group', '')
        gender = details.get('gender', 'Male')
        club_name = details.get('club_name', '')
        
        # Normalize gender
        if gender in ['M', 'Boys', 'Male', 'male', 'boys']:
            gender = 'Male'
        else:
            gender = 'Female'
        
        match = matcher.fuzzy_match_team(team_name, age_group, gender, club_name)
        
        if match is None:
            no_match += 1
        elif match['team_id'] == expected_id:
            correct += 1
            if len(correct_examples) < 3:
                correct_examples.append({
                    'team_name': team_name,
                    'matched': match['team_name'],
                    'confidence': match['confidence']
                })
        else:
            wrong += 1
            if len(wrong_examples) < 3:
                wrong_examples.append({
                    'team_name': team_name,
                    'expected_id': expected_id,
                    'got_id': match['team_id'],
                    'got_name': match['team_name'],
                    'confidence': match['confidence']
                })
    
    total = correct + wrong + no_match
    accuracy = (correct / total * 100) if total > 0 else 0
    
    print(f"RESULTS:")
    print(f"  ✓ Correct:   {correct:3} ({correct/total*100:.1f}%)" if total else "  ✓ Correct:   0")
    print(f"  ✗ Wrong:     {wrong:3} ({wrong/total*100:.1f}%)" if total else "  ✗ Wrong:     0")
    print(f"  ∅ No match:  {no_match:3} ({no_match/total*100:.1f}%)" if total else "  ∅ No match:  0")
    print(f"\n{'='*60}")
    print(f"IMPROVED ACCURACY: {accuracy:.1f}%")
    print(f"{'='*60}")
    
    if correct_examples:
        print(f"\nSAMPLE CORRECT MATCHES:")
        for ex in correct_examples:
            print(f"  ✓ {ex['team_name'][:50]}")
            print(f"    → {ex['matched']} (conf: {ex['confidence']})")
    
    if wrong_examples:
        print(f"\nSAMPLE WRONG MATCHES:")
        for ex in wrong_examples:
            print(f"  ✗ {ex['team_name'][:50]}")
            print(f"    Expected: {ex['expected_id'][:8]}...")
            print(f"    Got:      {ex['got_name']} (conf: {ex['confidence']})")
    
    return accuracy

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=25)
    args = parser.parse_args()
    
    run_test(args.limit)
