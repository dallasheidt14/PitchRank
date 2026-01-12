"""
Modular11-specific team matcher with ultra-conservative fuzzy matching.

This matcher is completely isolated from the main GameHistoryMatcher to ensure
Modular11-specific logic doesn't affect GotSport or other providers.

Key features:
- Alias-first: Once mapped, no fuzzy matching
- Ultra-conservative thresholds: 0.93 minimum, 0.07 gap requirement
- Age-strict, gender-strict, division-aware
- Birth-year aware: U13-U18 teams prioritize candidates with correct birth year (2010 for U16, 2013 for U13, etc.)
- Token overlap requirement
- Creates new teams when no confident match found
"""
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from difflib import SequenceMatcher
import logging
import uuid
import string
import time
import re
from dataclasses import dataclass

from supabase import Client
from config.settings import MATCHING_CONFIG

# Import base matcher for shared functionality
from src.models.game_matcher import GameHistoryMatcher, GAME_UID_NAMESPACE

logger = logging.getLogger(__name__)


# Modular11-specific thresholds (much stricter than GotSport)
MODULAR11_MIN_CONFIDENCE = 0.93  # vs 0.90 for GotSport
MODULAR11_MIN_GAP = 0.07  # Gap between best and second-best
MODULAR11_DIVISION_MATCH_BONUS = 0.05
MODULAR11_DIVISION_MISMATCH_PENALTY = 0.10

# Major tokens for token overlap requirement
MAJOR_TOKENS = {
    'galaxy', 'strikers', 'ideasport', 'flames', 'rsl', 'rapids', 'united',
    'city', 'fc', 'sc', 'academy', 'mutiny', 'chargers', 'surf', 'revolution',
    'fire', 'dynamo', 'timbers', 'sounders', 'whitecaps', 'impact', 'crew',
    'union', 'redbulls', 'republic', 'real', 'athletic', 'sporting', 'inter'
}


@dataclass
class Modular11MatchResult:
    """Result from Modular11 fuzzy matching"""
    team_id_master: str
    confidence: float
    division_match: bool
    token_overlap: bool


class Modular11GameMatcher(GameHistoryMatcher):
    """
    Modular11-specific team matcher with ultra-conservative fuzzy matching.
    
    Key differences from base matcher:
    1. ALWAYS validates age_group before accepting any match
    2. Alias-first: If alias exists, return immediately (no fuzzy)
    3. Ultra-conservative fuzzy matching (0.93 threshold, 0.07 gap)
    4. Division-aware matching (HD vs AD)
    5. Token overlap requirement
    6. Creates new teams when no confident match found
    """
    
    def __init__(self, supabase: Client, provider_id: Optional[str] = None, alias_cache: Optional[Dict] = None, debug: bool = False, summary_only: bool = False):
        """Initialize Modular11 matcher with same interface as base matcher"""
        super().__init__(supabase, provider_id=provider_id, alias_cache=alias_cache)
        self.debug = debug
        self.summary_only = summary_only
        self.summary = {
            "processed": 0,
            "alias_matches": 0,
            "fuzzy_matches": 0,
            "fuzzy_rejected": 0,
            "new_teams": 0,
            "review_queue": 0,
            "by_age": {},  # example: {"u16": {"matched": 5, "new": 3}}
            "fuzzy_details": [],   # list of dicts containing accepted fuzzy matches
            "fuzzy_reject_details": [],  # list of dicts for rejected matches
            "new_team_details": [],  # list of dicts
            "review_entries": []  # list of dicts
        }
        logger.info("Initialized Modular11GameMatcher with ultra-conservative fuzzy matching")
        
        # Club name synonym dictionary for improved token matching
        self.CLUB_SYNONYMS = {
            "sc": ["soccer club", "soccerclub", "sc"],
            "fc": ["football club", "futbol club", "soccer club", "footballclub", "futbolclub", "fc"],
            "sa": ["soccer academy", "socceracademy", "sa"],
            "acad": ["academy"],
            "acad.": ["academy"],
            "academy": ["acad", "sa"],
            "mls next": ["mlsnext", "next"],
            "surf": ["surf sc", "surf soccer"],
            "united": ["utd", "united"],
        }
    
    def _dlog(self, message: str):
        """Debug logging helper - prints only when self.debug=True and summary_only=False"""
        if self.debug and not self.summary_only:
            logger.info(f"[MOD11 DEBUG] {message}")
    
    def _init_age_tracking(self, age_group: str):
        """Initialize age-group tracking if not exists"""
        age_key = age_group.lower() if age_group else 'unknown'
        if age_key not in self.summary["by_age"]:
            self.summary["by_age"][age_key] = {"matched": 0, "new": 0}
    
    def _birth_year_from_age_group(self, age_group: str) -> Optional[int]:
        """
        Convert age group (e.g., 'u16', 'U14') to birth year.
        
        Birth year mapping (as used in team names):
        - U13 → 2013
        - U14 → 2012
        - U15 → 2011
        - U16 → 2010
        - U17 → 2009
        - U18 → 2008
        
        Returns None if age_group is invalid or out of range.
        """
        if not age_group:
            return None
        
        # Extract numeric age from age_group (e.g., 'u16' -> 16, 'U14' -> 14)
        age_str = age_group.lower().replace('u', '').strip()
        try:
            age = int(age_str)
        except (ValueError, TypeError):
            return None
        
        # Validate age range (U13-U18)
        if age < 13 or age > 18:
            return None
        
        # Map age to birth year (as used in team names)
        # U13 = 2013, U14 = 2012, U15 = 2011, U16 = 2010, U17 = 2009, U18 = 2008
        birth_year_map = {
            13: 2013,
            14: 2012,
            15: 2011,
            16: 2010,
            17: 2009,
            18: 2008
        }
        
        return birth_year_map.get(age)
    
    def _candidate_birth_year_tokens(self, birth_year: int) -> List[str]:
        """
        Generate list of acceptable birth year tokens for matching.
        
        Examples for birth_year=2009:
        ['2009', '09', 'b09', '09b', '(09)', '-09', '_09', ' 09 ']
        
        Returns list of lowercase tokens to search for in team names.
        """
        if not birth_year or birth_year < 2000 or birth_year > 2015:
            return []
        
        # Extract 2-digit year (e.g., 2009 -> '09')
        year_2digit = str(birth_year)[-2:]
        year_4digit = str(birth_year)
        
        tokens = [
            year_4digit,           # '2009'
            year_2digit,           # '09'
            f'b{year_2digit}',     # 'b09'
            f'{year_2digit}b',     # '09b'
            f'({year_2digit})',    # '(09)'
            f'-{year_2digit}',     # '-09'
            f'_{year_2digit}',     # '_09'
            f' {year_2digit} ',    # ' 09 '
            f' {year_2digit}',     # ' 09'
            f'{year_2digit} ',     # '09 '
        ]
        
        return [token.lower() for token in tokens]
    
    def _contains_birth_year(self, name: str, tokens: List[str]) -> bool:
        """
        Check if team name contains any of the birth year tokens.
        
        Args:
            name: Team name to search
            tokens: List of birth year tokens to look for
        
        Returns:
            True if any token is found in the name (case-insensitive)
        """
        if not name or not tokens:
            return False
        
        name_lower = name.lower()
        return any(token in name_lower for token in tokens)
    
    def _expand_synonyms(self, name: str) -> List[str]:
        """
        Takes an input team name and returns an expanded token set
        including synonyms. Improves fuzzy match token overlap.
        
        Args:
            name: Team name to expand
        
        Returns:
            List of tokens including original tokens and synonyms
        """
        if not name:
            return []
        
        # Split name into tokens (lowercase)
        tokens = re.split(r"[ \-_.,()]+", name.lower())
        tokens = [t.strip() for t in tokens if t.strip()]  # Remove empty tokens
        
        # Start with original tokens
        expanded = set(tokens)
        
        # Add synonyms for each token
        for token in tokens:
            if token in self.CLUB_SYNONYMS:
                for syn in self.CLUB_SYNONYMS[token]:
                    expanded.add(syn)
        
        return list(expanded)
    
    def _normalize_club_terms(self, name: str) -> str:
        """
        Normalize club terms in team names before similarity scoring.
        
        Replaces abbreviations with full terms:
        - ' sc ' → ' soccer club '
        - ' fc ' → ' football club '
        - ' sa ' → ' soccer academy '
        
        Args:
            name: Team name to normalize
        
        Returns:
            Normalized name string
        """
        if not name:
            return ""
        
        lower = name.lower()
        replacements = {
            " sc ": " soccer club ",
            " fc ": " football club ",
            " sa ": " soccer academy ",
        }
        
        for k, v in replacements.items():
            lower = lower.replace(k, v)
        
        return lower
    
    def _contains_wrong_birth_year(self, name: str, correct_birth_year: int) -> bool:
        """
        Check if team name contains a birth year that's different from the expected one.
        
        This is used for HARD FILTER - reject candidates with wrong birth years.
        
        Args:
            name: Team name to search
            correct_birth_year: The expected birth year (e.g., 2009 for U16)
        
        Returns:
            True if name contains a different birth year (2008, 2010, 2011, 2012, etc.)
        """
        if not name or not correct_birth_year:
            return False
        
        name_lower = name.lower()
        
        # Check for any 4-digit year between 2000-2015 (reasonable range)
        year_pattern = r'\b(20[0-1][0-9])\b'
        found_years = re.findall(year_pattern, name_lower)
        
        if found_years:
            for year_str in found_years:
                year = int(year_str)
                if year != correct_birth_year and 2000 <= year <= 2015:
                    return True  # Found a different birth year
        
        # Also check for 2-digit years (e.g., '08', '10', '11', '12')
        # Extract 2-digit from correct birth year
        correct_2digit = str(correct_birth_year)[-2:]
        # Look for 2-digit years that could be birth years (avoid matching random numbers)
        # Pattern: b08, 08b, (08), -08, _08, or standalone 08 in context
        year_2digit_pattern = r'\b([0-9]{2})\b'
        found_2digit = re.findall(year_2digit_pattern, name_lower)
        
        if found_2digit:
            for digit_str in found_2digit:
                # Check if it's a reasonable birth year (08-15 for 2008-2015)
                if digit_str.isdigit():
                    digit_int = int(digit_str)
                    if 8 <= digit_int <= 15:  # Reasonable range
                        # Convert to 4-digit year (assume 2000s)
                        potential_year = 2000 + digit_int
                        if potential_year != correct_birth_year:
                            return True  # Found a different birth year
        
        return False  # No wrong birth year found
    
    def print_summary(self):
        """Print clean summary of match decisions (only when debug=True or summary_only=True)"""
        # Always print summary if we have data, regardless of debug mode
        # (summary_only mode suppresses per-team logs but still shows summary)
        if not self.debug and not self.summary_only:
            return
        
        print("\n" + "=" * 60)
        print("MODULAR11 MATCH SUMMARY")
        print("=" * 60)
        print(f"Total Teams Processed: {self.summary['processed']}")
        print(f"Alias Matches: {self.summary['alias_matches']}")
        print(f"Fuzzy Matches Accepted: {self.summary['fuzzy_matches']}")
        print(f"Fuzzy Matches Rejected: {self.summary['fuzzy_rejected']}")
        print(f"New Teams Created: {self.summary['new_teams']}")
        print(f"Review Queue Entries: {self.summary['review_queue']}")
        
        if self.summary['by_age']:
            print("\nAGE BREAKDOWN:")
            for age in sorted(self.summary['by_age'].keys()):
                stats = self.summary['by_age'][age]
                print(f"  {age}: {stats['matched']} matched, {stats['new']} new")
        
        if self.summary['fuzzy_details']:
            print("\n" + "=" * 60)
            print("FUZZY MATCHES (Accepted) - Detailed Breakdown")
            print("=" * 60)
            for i, detail in enumerate(self.summary['fuzzy_details'], 1):
                print(f"\n{i}. {detail['incoming']} → {detail['matched_team']}")
                print(f"   Age: {detail['age']}, Division: {detail['division'] or 'N/A'}")
                print(f"   Score: {detail['score']:.4f} (threshold: 0.93) ✅")
                print(f"   Gap: {detail['gap']:.4f} (threshold: 0.07) ✅")
                print(f"   ─" * 30)
        
        if self.summary['fuzzy_reject_details']:
            print("\n" + "=" * 60)
            print("FUZZY MATCHES (Rejected) - Detailed Breakdown")
            print("=" * 60)
            for i, detail in enumerate(self.summary['fuzzy_reject_details'], 1):
                print(f"\n{i}. {detail['incoming']}")
                print(f"   Age: {detail['age']}, Division: {detail['division'] or 'N/A'}")
                print(f"   Rejection Reason: {detail['reason']}")
                print(f"\n   Top Candidates:")
                if detail.get('top_candidates'):
                    for idx, candidate in enumerate(detail['top_candidates'][:3], 1):
                        div_info = f" (div: {candidate.get('division', 'N/A')})" if candidate.get('division') else ""
                        print(f"   {idx}. {candidate['team_name']}{div_info}")
                        score_status = "PASS" if candidate['score'] >= 0.93 else "FAIL"
                        print(f"       Score: {candidate['score']:.4f} [{score_status}] (need >= 0.93)")
                        div_status = "PASS" if candidate['division_match'] else "FAIL"
                        print(f"       Division Match: [{div_status}]")
                        token_status = "PASS" if candidate['token_overlap'] else "FAIL"
                        print(f"       Token Overlap: [{token_status}]")
                        if idx == 1 and detail.get('second_team'):
                            gap_status = "PASS" if detail['score_gap'] >= 0.07 else "FAIL"
                            print(f"       Gap to 2nd: {detail['score_gap']:.4f} [{gap_status}] (need >= 0.07)")
                        print()
                print(f"   ─" * 30)
        
        if self.summary['new_team_details']:
            print("\nNEW TEAMS CREATED:")
            for detail in self.summary['new_team_details']:
                print(f"  {detail['incoming']} -> {detail['clean_name']} "
                      f"(id: {detail['team_id']}, age: {detail['age']}, div: {detail['division'] or 'N/A'})")
        
        if self.summary['review_entries']:
            print("\nREVIEW QUEUE ENTRIES:")
            for entry in self.summary['review_entries']:
                suggestions_str = ", ".join(entry['suggestions'][:3]) if entry['suggestions'] else "none"
                print(f"  {entry['incoming']} (age: {entry['age']}, div: {entry['division'] or 'N/A'})")
                if suggestions_str:
                    print(f"    Suggestions: {suggestions_str}")
        
        print("=" * 60 + "\n")
    
    def _match_team(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_name: Optional[str],
        age_group: Optional[str],
        gender: Optional[str],
        club_name: Optional[str] = None,
        division: Optional[str] = None  # NEW: HD or AD
    ) -> Dict:
        """
        Match a team using Modular11-specific ultra-conservative logic.
        
        Strategy:
        1. Alias lookup (ALWAYS FIRST) - if alias exists, return immediately
        2. Modular11 fuzzy match (if no alias) - ultra-conservative thresholds
        3. Create new team (if no confident match)
        
        Returns:
            Dict with:
            - matched: bool
            - team_id: str if matched
            - method: str ('alias', 'fuzzy_auto', 'import', None)
            - confidence: float (0.0-1.0)
        """
        # Extract division if not provided (try to get from context)
        if not division:
            # Try to extract from team_name if it ends with HD/AD
            if team_name:
                division = self._extract_division_from_name(team_name)
        
        # Log incoming team info
        self._dlog(f"Incoming team: {team_name} (age={age_group}, gender={gender}, division={division}, provider_team_id={provider_team_id})")
        
        # Track processed teams
        self.summary["processed"] += 1
        if age_group:
            self._init_age_tracking(age_group)
        
        # Strategy 1: Alias lookup (ALWAYS FIRST - no fuzzy if alias exists)
        if provider_team_id:
            self._dlog(f"Checking alias for provider_team_id={provider_team_id}, division={division}")
            alias_match = self._match_by_provider_id(provider_id, provider_team_id, age_group, gender, division)
            if alias_match:
                # Get team details for logging
                team_id_master = alias_match['team_id_master']
                try:
                    team_result = self.db.table('teams').select('team_name, age_group, gender').eq('team_id_master', team_id_master).single().execute()
                    if team_result.data:
                        team_name_db = team_result.data.get('team_name', 'Unknown')
                        team_age = team_result.data.get('age_group', 'Unknown')
                        team_gender = team_result.data.get('gender', 'Unknown')
                        match_type = alias_match.get('match_method', 'provider_id')
                        self._dlog(f"Alias found: provider_team_id={provider_team_id} maps to team_id_master={team_id_master}")
                        self._dlog(f"Alias info: team_name={team_name_db}, age={team_age}, gender={team_gender}, match_method={match_type}")
                        
                        # Validate age group
                        if age_group and team_age:
                            age_normalized = age_group.lower()
                            team_age_normalized = team_age.lower()
                            if age_normalized != team_age_normalized:
                                self._dlog(f"Alias rejected: age mismatch (incoming {age_group} vs team {team_age})")
                                alias_match = None
                            else:
                                self._dlog(f"Alias accepted: age match confirmed ({age_group})")
                except Exception as e:
                    self._dlog(f"Error fetching team details for alias validation: {e}")
                
                if alias_match:
                    # Alias found and validated - return immediately (NO fuzzy matching)
                    match_type = alias_match.get('match_method', 'provider_id')
                    team_id_master = alias_match['team_id_master']
                    try:
                        team_result = self.db.table('teams').select('team_name').eq('team_id_master', team_id_master).single().execute()
                        final_team_name = team_result.data.get('team_name', 'Unknown') if team_result.data else 'Unknown'
                    except:
                        final_team_name = 'Unknown'
                    self._dlog(f"FINAL DECISION: alias -> {final_team_name} ({team_id_master})")
                    
                    # Track alias match in summary
                    self.summary["alias_matches"] += 1
                    if age_group:
                        age_key = age_group.lower()
                        self._init_age_tracking(age_group)
                        self.summary["by_age"][age_key]["matched"] += 1
                    
                    return {
                        'matched': True,
                        'team_id': team_id_master,
                        'method': 'alias' if match_type != 'direct_id' else 'direct_id',
                        'confidence': 1.0
                    }
            else:
                self._dlog(f"No alias found for provider_team_id={provider_team_id}")
        
        # Strategy 2: Modular11-specific fuzzy match (only if no alias)
        fuzzy_match = None
        if team_name and age_group and gender:
            fuzzy_match = self.fuzzy_match_modular11_team(
                incoming_name=team_name,
                age_group=age_group,
                gender=gender,
                division=division,
                club_name=club_name
            )
            
            if fuzzy_match:
                # High-confidence match found - create alias and return
                self._create_modular11_alias(
                    provider_id=provider_id,
                    provider_team_id=provider_team_id,
                    team_id_master=fuzzy_match.team_id_master,
                    match_method='fuzzy_auto',
                    confidence=fuzzy_match.confidence,
                    division=division,
                    age_group=age_group
                )
                try:
                    team_result = self.db.table('teams').select('team_name').eq('team_id_master', fuzzy_match.team_id_master).single().execute()
                    final_team_name = team_result.data.get('team_name', 'Unknown') if team_result.data else 'Unknown'
                except:
                    final_team_name = 'Unknown'
                self._dlog(f"FINAL DECISION: fuzzy_auto -> matched {final_team_name} ({fuzzy_match.team_id_master})")
                return {
                    'matched': True,
                    'team_id': fuzzy_match.team_id_master,
                    'method': 'fuzzy_auto',
                    'confidence': fuzzy_match.confidence
                }
            else:
                self._dlog("Fuzzy match did not find confident match")
        
        # Strategy 3: No confident match - create new team
        if team_name and age_group and gender:
            # Generate provider_team_id if not provided (for teams table requirement)
            # Include division in hash to prevent HD/AD collisions
            if not provider_team_id:
                import hashlib
                division_str = division or ''
                provider_team_id = hashlib.md5(f"{team_name}_{age_group}_{gender}_{division_str}".encode()).hexdigest()[:16]
            
            new_team_id = self._create_new_modular11_team(
                team_name=team_name,
                club_name=club_name,
                age_group=age_group,
                gender=gender,
                provider_id=provider_id,
                provider_team_id=provider_team_id,
                division=division
            )
            
            # Get clean name for tracking (from _create_new_modular11_team logic)
            clean_name = team_name or 'Unknown'
            if team_name:
                # Normalize similar to _create_new_modular11_team
                clean_name = team_name.strip()
                if clean_name.upper().endswith(' HD') or clean_name.upper().endswith(' AD'):
                    clean_name = clean_name[:-3].strip()
            
            # Track new team creation (only if this is actually a new team, not a duplicate)
            # Check if we've already tracked this team_id to avoid double-counting
            if not any(detail.get("team_id") == new_team_id for detail in self.summary["new_team_details"]):
                self.summary["new_teams"] += 1
                self.summary["new_team_details"].append({
                    "incoming": team_name or 'Unknown',
                    "clean_name": clean_name,
                    "team_id": new_team_id,
                    "age": age_group,
                    "division": division
                })
                if age_group:
                    age_key = age_group.lower()
                    self._init_age_tracking(age_group)
                    self.summary["by_age"][age_key]["new"] += 1
            
            # Create alias for new team
            # NOTE: Pass base provider_team_id (raw club_id) - alias creation will build aliased format
            self._create_modular11_alias(
                provider_id=provider_id,
                provider_team_id=provider_team_id,  # Base club_id - alias will build {club_id}_{age}_{division}
                team_id_master=new_team_id,
                match_method='direct_id',  # Direct provider ID mapping (like TGS/GotSport)
                confidence=1.0,  # New team = 100% confidence
                division=division,
                age_group=age_group
            )

            # NOTE: Successfully created teams should NOT be added to review queue
            # Review queue is only for teams that couldn't be matched/created automatically
            
            clean_name = team_name or 'Unknown'
            self._dlog(f"FINAL DECISION: new team created -> {clean_name} ({new_team_id})")
            return {
                'matched': True,
                'team_id': new_team_id,
                'method': 'import',  # Must match database enum, not 'new_team'
                'confidence': 1.0
            }
        
        # Fallback: ALWAYS create team (never return None)
        # This should rarely be hit, but ensures no blocking
        if team_name and age_group and gender:
            # Generate provider_team_id if not provided
            # Include division in hash to prevent HD/AD collisions
            if not provider_team_id:
                import hashlib
                division_str = division or ''
                provider_team_id = hashlib.md5(f"{team_name}_{age_group}_{gender}_{division_str}".encode()).hexdigest()[:16]
            
            new_team_id = self._create_new_modular11_team(
                team_name=team_name,
                club_name=club_name,
                age_group=age_group,
                gender=gender,
                provider_id=provider_id,
                provider_team_id=provider_team_id,
                division=division
            )
            
            # Create alias with age_group for unique identification
            # NOTE: Pass base provider_team_id (raw club_id) - alias creation will build aliased format
            self._create_modular11_alias(
                provider_id=provider_id,
                provider_team_id=provider_team_id,  # Base club_id - alias will build {club_id}_{age}_{division}
                team_id_master=new_team_id,
                match_method='direct_id',  # Direct provider ID mapping
                confidence=1.0,
                division=division,
                age_group=age_group
            )
            
            # Track in summary (only if this is actually a new team, not a duplicate)
            # Check if we've already tracked this team_id to avoid double-counting
            clean_name = team_name or 'Unknown'
            if team_name:
                clean_name = team_name.strip()
                if clean_name.upper().endswith(' HD') or clean_name.upper().endswith(' AD'):
                    clean_name = clean_name[:-3].strip()
            
            if not any(detail.get("team_id") == new_team_id for detail in self.summary["new_team_details"]):
                self.summary["new_teams"] += 1
                self.summary["new_team_details"].append({
                    "incoming": team_name or 'Unknown',
                    "clean_name": clean_name,
                    "team_id": new_team_id,
                    "age": age_group,
                    "division": division
                })
                if age_group:
                    age_key = age_group.lower()
                    self._init_age_tracking(age_group)
                    self.summary["by_age"][age_key]["new"] += 1
            
            # NOTE: Successfully created teams should NOT be added to review queue
            # Review queue is only for teams that couldn't be matched/created automatically
            
            clean_name = team_name or 'Unknown'
            self._dlog(f"FINAL DECISION: new team created (fallback) -> {clean_name} ({new_team_id})")
            return {
                'matched': True,
                'team_id': new_team_id,
                'method': 'import',  # Must match database enum
                'confidence': 1.0
            }
        else:
            # Only return None if we truly can't create (missing required fields)
            logger.warning(f"[Modular11] Cannot create team - missing required fields: name={team_name}, age={age_group}, gender={gender}")
            return {
                'matched': False,
                'team_id': None,
                'method': None,
                'confidence': 0.0
            }
    
    def fuzzy_match_modular11_team(
        self,
        incoming_name: str,
        age_group: str,
        gender: str,
        division: Optional[str],
        club_name: Optional[str] = None
    ) -> Optional[Modular11MatchResult]:
        """
        Ultra-conservative fuzzy matching for Modular11 teams.
        
        Requirements:
        - best_score >= 0.93
        - (best_score - second_best_score) >= 0.07
        - Token overlap exists
        - Division matches or absent (not conflicting)
        
        Returns Modular11MatchResult if confident match found, None otherwise.
        """
        try:
            # Normalize age_group to lowercase (DB uses 'u13', source may have 'U13')
            age_group_normalized = age_group.lower() if age_group else age_group
            
            self._dlog(f"Running fuzzy match for: {incoming_name}")
            
            # Compute birth year from age group
            birth_year = self._birth_year_from_age_group(age_group)
            birth_year_tokens = []
            if birth_year:
                birth_year_tokens = self._candidate_birth_year_tokens(birth_year)
                self._dlog(f"[BY] Incoming {incoming_name} expects birth year {birth_year} (tokens: {birth_year_tokens[:3]}...)")
            else:
                self._dlog(f"[BY] Could not determine birth year from age_group={age_group}")
            
            # Get candidate teams (strict age/gender filter)
            result = self.db.table('teams').select(
                'team_id_master, team_name, club_name, age_group, gender, state_code'
            ).eq('age_group', age_group_normalized).eq('gender', gender).execute()
            
            if not result.data:
                self._dlog(f"No candidates found for {incoming_name} ({age_group}, {gender})")
                logger.debug(f"[Modular11] No candidates found for {incoming_name} ({age_group}, {gender})")
                return None
            
            self._dlog(f"Found {len(result.data)} candidate teams (age={age_group_normalized}, gender={gender})")
            
            # Get division info from aliases for candidates
            # Use the provider_id from initialization (Modular11 provider UUID)
            provider_id_for_division = self._cached_provider_id or self._get_provider_id('modular11')
            candidate_divisions = self._get_candidate_divisions(
                [t['team_id_master'] for t in result.data],
                provider_id_for_division
            )
            
            # Score all candidates
            scored_candidates = []
            for team in result.data:
                team_id = team['team_id_master']
                candidate_division = candidate_divisions.get(team_id)
                cand_name = team.get('team_name', '')
                cand_age = team.get('age_group', '')
                cand_gender = team.get('gender', '')
                
                # Normalize names for similarity scoring (expand abbreviations)
                normalized_incoming = self._normalize_club_terms(incoming_name)
                normalized_candidate = self._normalize_club_terms(cand_name)
                
                # Calculate base similarity using normalized names
                provider_team = {
                    'team_name': normalized_incoming,
                    'club_name': club_name,
                    'age_group': age_group,
                    'state_code': None
                }
                candidate = {
                    'team_name': normalized_candidate,
                    'club_name': team.get('club_name'),
                    'age_group': cand_age,
                    'state_code': team.get('state_code')
                }
                
                base_score = self._calculate_match_score(provider_team, candidate)
                
                # Check token overlap with synonym expansion
                incoming_tokens = self._expand_synonyms(incoming_name)
                candidate_tokens = self._expand_synonyms(cand_name)
                token_intersection = set(incoming_tokens) & set(candidate_tokens)
                has_overlap = len(token_intersection) > 0
                
                self._dlog(f"[SYN] Tokens for incoming '{incoming_name}': {incoming_tokens[:10]}")
                self._dlog(f"[SYN] Tokens for candidate '{cand_name}': {candidate_tokens[:10]}")
                self._dlog(f"[SYN] Overlap={has_overlap} (intersection: {list(token_intersection)[:5]})")
                
                if not has_overlap:
                    self._dlog(f"Candidate: {cand_name} | Age={cand_age} | Score={base_score:.4f} | TokenOverlap=False (REJECTED)")
                    logger.debug(
                        f"[Modular11] No token overlap: '{incoming_name}' vs '{cand_name}'"
                    )
                    continue  # Skip candidates without token overlap
                
                # Add small bonus for synonym overlap
                if has_overlap:
                    base_score += 0.03  # Small safe boost for synonym overlap
                    self._dlog(f"[SYN] Synonym overlap bonus: +0.03")
                
                # Apply birth year scoring (HARD FILTER for wrong birth years)
                birth_year_match = False
                birth_year_adjustment = 0.0
                if birth_year and birth_year_tokens:
                    # HARD FILTER: Reject candidates with WRONG birth year (e.g., 2010 when expecting 2009)
                    contains_wrong_birth_year = self._contains_wrong_birth_year(cand_name, birth_year)
                    if contains_wrong_birth_year:
                        self._dlog(f"[BY] Candidate {cand_name} contains WRONG birth year (expecting {birth_year}), REJECTED")
                        logger.debug(
                            f"[Modular11] Wrong birth year: '{incoming_name}' (expects {birth_year}) vs '{cand_name}'"
                        )
                        continue  # Skip candidate - wrong birth year
                    
                    # Check if candidate contains CORRECT birth year
                    contains_birth_year = self._contains_birth_year(cand_name, birth_year_tokens)
                    birth_year_match = contains_birth_year
                    
                    if contains_birth_year:
                        birth_year_adjustment = 0.05  # Bonus for correct birth year
                        base_score += birth_year_adjustment
                        self._dlog(f"[BY] Candidate {cand_name} contains birth year {birth_year}, score_adj=+0.05")
                    else:
                        # Candidate has no birth year - apply penalty but still consider
                        birth_year_adjustment = -0.10  # Penalty for missing birth year
                        base_score += birth_year_adjustment
                        self._dlog(f"[BY] Candidate {cand_name} MISSING birth year {birth_year} tokens, score_adj=-0.10")
                elif birth_year and not birth_year_tokens:
                    # Birth year determined but no tokens generated (shouldn't happen, but safe)
                    self._dlog(f"[BY] Warning: birth_year={birth_year} but no tokens generated")
                
                # Apply division bonus/penalty
                division_match = False
                division_adjustment = 0.0
                if division and candidate_division:
                    if division.upper() == candidate_division.upper():
                        division_match = True
                        division_adjustment = MODULAR11_DIVISION_MATCH_BONUS
                        base_score += division_adjustment
                    else:
                        division_adjustment = -MODULAR11_DIVISION_MISMATCH_PENALTY
                        base_score += division_adjustment
                elif not division and not candidate_division:
                    # Both absent - neutral
                    division_match = True
                elif division or candidate_division:
                    # One has division, other doesn't - slight penalty but not fatal
                    division_adjustment = -0.02
                    base_score += division_adjustment
                
                # Clamp score to [0, 1]
                final_score = max(0.0, min(1.0, base_score))
                
                self._dlog(
                    f"Candidate: {cand_name} | Age={cand_age} | Gender={cand_gender} | "
                    f"RawScore={base_score - division_adjustment - birth_year_adjustment:.4f} | "
                    f"TokenOverlap={has_overlap} | "
                    f"BirthYearMatch={birth_year_match} | BirthYearAdj={birth_year_adjustment:+.4f} | "
                    f"DivisionAdjustment={division_adjustment:+.4f} | ScoreAfterAdjustments={final_score:.4f} | "
                    f"DivisionMatch={division_match}"
                )
                
                scored_candidates.append({
                    'team_id_master': team_id,
                    'team_name': cand_name,
                    'score': final_score,
                    'division_match': division_match,
                    'token_overlap': has_overlap,
                    'birth_year_match': birth_year_match
                })
            
            if not scored_candidates:
                self._dlog(f"No candidates with token overlap for {incoming_name}")
                logger.debug(f"[Modular11] No candidates with token overlap for {incoming_name}")
                return None
            
            # Sort by score (descending)
            scored_candidates.sort(key=lambda x: x['score'], reverse=True)
            
            best = scored_candidates[0]
            second_best_score = scored_candidates[1]['score'] if len(scored_candidates) > 1 else 0.0
            score_gap = best['score'] - second_best_score
            
            self._dlog(f"Best match score={best['score']:.4f}, second best={second_best_score:.4f}, gap={score_gap:.4f}")
            
            # Apply ultra-conservative thresholds
            # Auto-approve if score >= 0.93, gap >= 0.07, and token overlap exists
            # Division mismatch is no longer a hard requirement (still affects scoring via bonus/penalty)
            if (best['score'] >= MODULAR11_MIN_CONFIDENCE and
                score_gap >= MODULAR11_MIN_GAP and
                best['token_overlap']):
                
                self._dlog(f"Fuzzy match ACCEPTED: {incoming_name} -> {best['team_name']} (score: {best['score']:.4f}, gap: {score_gap:.4f})")
                logger.info(
                    f"[Modular11] High-confidence match: {incoming_name} → {best['team_name']} "
                    f"(score: {best['score']:.3f}, gap: {score_gap:.3f})"
                )
                
                # Track fuzzy match accepted
                self.summary["fuzzy_matches"] += 1
                self.summary["fuzzy_details"].append({
                    "incoming": incoming_name,
                    "matched_team": best['team_name'],
                    "score": best['score'],
                    "gap": score_gap,
                    "age": age_group,
                    "division": division
                })
                if age_group:
                    age_key = age_group.lower()
                    self._init_age_tracking(age_group)
                    self.summary["by_age"][age_key]["matched"] += 1
                
                return Modular11MatchResult(
                    team_id_master=best['team_id_master'],
                    confidence=best['score'],
                    division_match=best['division_match'],
                    token_overlap=best['token_overlap']
                )
            else:
                # Log exact rejection reason
                reasons = []
                if best['score'] < MODULAR11_MIN_CONFIDENCE:
                    reasons.append(f"score < {MODULAR11_MIN_CONFIDENCE} required minimum (got {best['score']:.4f})")
                if score_gap < MODULAR11_MIN_GAP:
                    reasons.append(f"score gap too small (need >= {MODULAR11_MIN_GAP}, got {score_gap:.4f})")
                if not best['token_overlap']:
                    reasons.append("no token overlap")
                # Division mismatch is no longer a rejection reason - it only affects scoring
                
                rejection_reason = " | ".join(reasons) if reasons else "unknown reason"
                self._dlog(f"Reject fuzzy match: {rejection_reason}")
                
                # Track fuzzy match rejected
                self.summary["fuzzy_rejected"] += 1
                
                # Get top 3 candidates for detailed reporting
                # Use existing candidate_divisions data (already fetched above)
                top_candidates = []
                for i, candidate in enumerate(scored_candidates[:3]):
                    candidate_division = candidate_divisions.get(candidate['team_id_master'])
                    
                    top_candidates.append({
                        "team_name": candidate['team_name'],
                        "score": candidate['score'],
                        "division": candidate_division,
                        "division_match": candidate.get('division_match', False),
                        "token_overlap": candidate.get('token_overlap', False)
                    })
                
                self.summary["fuzzy_reject_details"].append({
                    "incoming": incoming_name,
                    "reason": rejection_reason,
                    "best_score": best['score'],
                    "best_team": best['team_name'],
                    "best_division_match": best.get('division_match', False),
                    "best_token_overlap": best.get('token_overlap', False),
                    "second_score": second_best_score,
                    "second_team": scored_candidates[1]['team_name'] if len(scored_candidates) > 1 else None,
                    "score_gap": score_gap,
                    "age": age_group,
                    "division": division,
                    "top_candidates": top_candidates
                })
                
                logger.debug(
                    f"[Modular11] Match rejected for {incoming_name}: "
                    f"score={best['score']:.3f} (need >= {MODULAR11_MIN_CONFIDENCE}), "
                    f"gap={score_gap:.3f} (need >= {MODULAR11_MIN_GAP})"
                )
                return None
            
        except Exception as e:
            logger.error(f"[Modular11] Fuzzy match error: {e}")
            return None
    
    def _has_token_overlap(self, name1: str, name2: str) -> bool:
        """
        Check if two team names share at least one major token.
        
        This prevents false matches between unrelated teams that happen to have
        high similarity scores but no actual club/team name overlap.
        """
        def extract_tokens(name: str) -> set:
            """Extract normalized tokens from team name"""
            if not name:
                return set()
            
            # Normalize: lowercase, remove punctuation, split
            normalized = name.lower().strip()
            normalized = re.sub(r'[^\w\s]', ' ', normalized)
            tokens = set(normalized.split())
            
            # Remove common stop words
            stop_words = {'u13', 'u14', 'u15', 'u16', 'u17', 'u18', 'hd', 'ad', 'mls', 'next', 'boys', 'girls'}
            tokens = tokens - stop_words
            
            return tokens
        
        tokens1 = extract_tokens(name1)
        tokens2 = extract_tokens(name2)
        
        # Check for major token overlap
        overlap = tokens1 & tokens2
        
        # If any overlapping token is a "major token", return True
        for token in overlap:
            if token in MAJOR_TOKENS or len(token) >= 4:  # Major token or substantial word
                return True
        
        # Also check if any major token from either name appears in the other
        for major_token in MAJOR_TOKENS:
            if major_token in name1.lower() and major_token in name2.lower():
                return True
        
        return False
    
    def _get_candidate_divisions(
        self,
        team_ids: List[str],
        provider_id: Optional[str]
    ) -> Dict[str, Optional[str]]:
        """
        Get division (HD/AD) for candidate teams from their Modular11 aliases.
        
        Returns dict mapping team_id_master -> division (or None)
        """
        if not provider_id or not team_ids:
            return {}
        
        try:
            # Query team_alias_map for division info
            result = self.db.table('team_alias_map').select(
                'team_id_master, division'
            ).eq('provider_id', provider_id).in_(
                'team_id_master', team_ids
            ).execute()
            
            divisions = {}
            for row in result.data:
                divisions[row['team_id_master']] = row.get('division')
            
            return divisions
        except Exception as e:
            logger.debug(f"[Modular11] Error fetching candidate divisions: {e}")
            return {}
    
    def _extract_division_from_name(self, team_name: str) -> Optional[str]:
        """
        Extract division (HD/AD) from team name.
        
        Modular11 team names often end with " HD" or " AD".
        """
        if not team_name:
            return None
        
        team_name_upper = team_name.upper().strip()
        if team_name_upper.endswith(' HD'):
            return 'HD'
        elif team_name_upper.endswith(' AD'):
            return 'AD'
        
        return None
    
    def _build_aliased_provider_team_id(
        self,
        base_provider_team_id: str,
        age_group: Optional[str] = None,
        division: Optional[str] = None
    ) -> str:
        """
        Build aliased provider_team_id format: {club_id}_{age}_{division}
        
        For Modular11, the same club_id is used for all age groups/divisions,
        so we need to create unique identifiers by appending age and division.
        
        Examples:
        - base="564", age="U13", division="HD" -> "564_U13_HD"
        - base="564", age="U13", division=None -> "564_U13"
        - base="564", age=None, division=None -> "564"
        - base="564", age="u13", division="hd" -> "564_U13_HD" (normalized)
        - base="564", age="13", division=None -> "564_U13" (adds U prefix)
        
        Edge cases handled:
        - Empty/None base_provider_team_id: Returns empty string
        - Empty/None age_group: Skips age suffix
        - Empty/None/invalid division: Skips division suffix
        - Whitespace in age_group: Stripped before processing
        - Case variations: Normalized to uppercase
        
        Args:
            base_provider_team_id: Raw club_id from Modular11 (e.g., "564")
            age_group: Age group (e.g., "U13", "u13", "13", " u13 ")
            division: Division (e.g., "HD", "AD", "hd", "ad")
            
        Returns:
            Aliased provider_team_id string
        """
        # Handle empty/None base_provider_team_id
        if not base_provider_team_id:
            return ''
        
        # Strip whitespace from base
        base_provider_team_id = str(base_provider_team_id).strip()
        if not base_provider_team_id:
            return ''
        
        aliased_id = base_provider_team_id
        suffix_parts = []
        
        # Add age group suffix (CRITICAL: same club ID used for all ages)
        if age_group:
            # Strip whitespace and normalize
            age_group = str(age_group).strip()
            if age_group:
                # Normalize age format: handle "U13", "u13", "13", " u13 ", etc.
                age_lower = age_group.lower()
                if age_lower.startswith('u'):
                    # Already has U prefix (e.g., "U13", "u13") - just uppercase
                    age_normalized = age_group.upper()
                else:
                    # No U prefix (e.g., "13") - add it
                    age_normalized = f"U{age_group.upper()}"
                
                suffix_parts.append(age_normalized)
        
        # Add division suffix (HD/AD)
        if division:
            # Strip whitespace and normalize
            division = str(division).strip().upper()
            if division in ('HD', 'AD'):
                suffix_parts.append(division)
        
        # Build final aliased ID
        if suffix_parts:
            aliased_id = f"{base_provider_team_id}_{'_'.join(suffix_parts)}"
        
        return aliased_id
    
    def _get_fuzzy_suggestions(
        self,
        incoming_name: str,
        age_group: str,
        gender: str,
        division: Optional[str],
        club_name: Optional[str],
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get top fuzzy match suggestions (even if below threshold) for review queue.
        """
        try:
            age_group_normalized = age_group.lower() if age_group else age_group
            
            result = self.db.table('teams').select(
                'team_id_master, team_name, club_name, age_group, gender'
            ).eq('age_group', age_group_normalized).eq('gender', gender).limit(50).execute()
            
            suggestions = []
            for team in result.data:
                provider_team = {
                    'team_name': incoming_name,
                    'club_name': club_name,
                    'age_group': age_group
                }
                candidate = {
                    'team_name': team.get('team_name', ''),
                    'club_name': team.get('club_name'),
                    'age_group': team.get('age_group', '')
                }
                
                score = self._calculate_match_score(provider_team, candidate)
                has_overlap = self._has_token_overlap(incoming_name, team.get('team_name', ''))
                
                if has_overlap:  # Only include suggestions with token overlap
                    suggestions.append({
                        'team_id_master': team['team_id_master'],
                        'team_name': team.get('team_name', ''),
                        'confidence': score
                    })
            
            # Sort and return top N
            suggestions.sort(key=lambda x: x['confidence'], reverse=True)
            return suggestions[:limit]
            
        except Exception as e:
            logger.debug(f"[Modular11] Error getting fuzzy suggestions: {e}")
            return []
    
    def _create_new_modular11_team(
        self,
        team_name: str,
        club_name: Optional[str],
        age_group: str,
        gender: str,
        provider_id: Optional[str],
        provider_team_id: Optional[str] = None,
        division: Optional[str] = None
    ) -> str:
        """
        Create a new team in the teams table for Modular11.
        
        CRITICAL: For Modular11, provider_team_id must use the aliased format
        {club_id}_{age}_{division} (e.g., "564_U13_HD") to ensure uniqueness
        since the same club_id is used for all age groups/divisions.
        
        If a team with the same provider_id and provider_team_id already exists,
        return that team's ID instead of creating a duplicate.
        
        Returns the team_id_master UUID.
        """
        try:
            # provider_team_id is REQUIRED (NOT NULL constraint)
            # If not provided, generate a hash-based one
            if not provider_team_id:
                import hashlib
                division_str = division or ''
                base_provider_team_id = hashlib.md5(f"{team_name}_{age_group}_{gender}_{division_str}".encode()).hexdigest()[:16]
            else:
                # Use provided provider_team_id as base (raw club_id)
                base_provider_team_id = provider_team_id
            
            # CRITICAL: Build aliased provider_team_id format: {club_id}_{age}_{division}
            # This ensures teams.provider_team_id matches team_alias_map.provider_team_id
            aliased_provider_team_id = self._build_aliased_provider_team_id(
                base_provider_team_id=base_provider_team_id,
                age_group=age_group,
                division=division
            )
            
            self._dlog(
                f"Team creation: base_provider_team_id={base_provider_team_id}, "
                f"aliased_provider_team_id={aliased_provider_team_id}"
            )
            
            # Check if team with this provider_id + aliased_provider_team_id already exists
            if provider_id:
                try:
                    existing = self.db.table('teams').select('team_id_master').eq(
                        'provider_id', provider_id
                    ).eq('provider_team_id', aliased_provider_team_id).single().execute()
                    
                    if existing.data:
                        logger.debug(
                            f"[Modular11] Team with provider_team_id {aliased_provider_team_id} already exists, "
                            f"using existing team {existing.data['team_id_master']}"
                        )
                        return existing.data['team_id_master']
                except Exception:
                    # No existing team found, continue to create new one
                    pass
            
            # Generate new UUID
            team_id_master = str(uuid.uuid4())
            
            # Normalize age_group
            age_group_normalized = age_group.lower() if age_group else age_group
            
            # Normalize gender
            gender_normalized = 'Male' if gender.upper() in ('M', 'MALE', 'BOYS') else 'Female'
            
            # Clean team name (remove HD/AD suffix if present for storage)
            clean_team_name = team_name
            if team_name.upper().endswith(' HD') or team_name.upper().endswith(' AD'):
                clean_team_name = team_name[:-3].strip()
            
            # Insert new team with ALIASED provider_team_id
            team_data = {
                'team_id_master': team_id_master,
                'team_name': clean_team_name,
                'club_name': club_name or clean_team_name,
                'age_group': age_group_normalized,
                'gender': gender_normalized,
                'provider_id': provider_id,  # Required for Modular11 teams
                'provider_team_id': aliased_provider_team_id,  # Use aliased format: {club_id}_{age}_{division}
                'created_at': datetime.utcnow().isoformat() + 'Z'
            }
            
            self.db.table('teams').insert(team_data).execute()
            
            self._dlog(
                f"Creating NEW Modular11 team: {clean_team_name} "
                f"({age_group_normalized}, {gender_normalized}, division={division}, "
                f"provider_team_id={aliased_provider_team_id})"
            )
            logger.info(
                f"[Modular11] Created new team: {clean_team_name} ({age_group_normalized}, {gender_normalized}) "
                f"with provider_team_id={aliased_provider_team_id}"
            )
            
            return team_id_master
            
        except Exception as e:
            # If duplicate key error, try to find existing team
            if 'duplicate key' in str(e).lower() or '23505' in str(e):
                logger.debug(f"[Modular11] Duplicate key error, looking up existing team: {e}")
                if provider_id:
                    # Rebuild aliased_provider_team_id for lookup (same format as what we tried to insert)
                    try:
                        # Determine base_provider_team_id
                        if not provider_team_id:
                            import hashlib
                            division_str = division or ''
                            base_provider_team_id = hashlib.md5(f"{team_name}_{age_group}_{gender}_{division_str}".encode()).hexdigest()[:16]
                        else:
                            base_provider_team_id = provider_team_id
                        
                        # Build aliased format
                        aliased_provider_team_id = self._build_aliased_provider_team_id(
                            base_provider_team_id=base_provider_team_id,
                            age_group=age_group,
                            division=division
                        )
                        
                        existing = self.db.table('teams').select('team_id_master').eq(
                            'provider_id', provider_id
                        ).eq('provider_team_id', aliased_provider_team_id).single().execute()
                        
                        if existing.data:
                            logger.info(
                                f"[Modular11] Found existing team with provider_team_id {aliased_provider_team_id}, "
                                f"using {existing.data['team_id_master']}"
                            )
                            return existing.data['team_id_master']
                    except Exception as lookup_error:
                        logger.error(f"[Modular11] Error looking up existing team: {lookup_error}")
            
            logger.error(f"[Modular11] Error creating new team: {e}")
            raise
    
    def _create_modular11_alias(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_id_master: str,
        match_method: str,
        confidence: float,
        division: Optional[str],
        age_group: Optional[str] = None
    ):
        """
        Create or update team alias map entry with division and age information.

        For MLS NEXT teams, this method creates age+division suffixed provider_team_id
        entries (e.g., "391_U16_HD", "391_U16_AD") to allow separate aliases for:
        - Different age groups (U13, U14, U15, U16, U17) with same club ID
        - Different divisions (HD, AD) within each age group

        This is necessary because Modular11 uses the same club/academy ID for ALL
        teams regardless of age group or division.

        CRITICAL: This method receives the BASE provider_team_id (raw club_id) and
        builds the aliased format. The team's provider_team_id should also use this
        same aliased format to ensure consistency.

        Note: team_name and gender are NOT stored in team_alias_map schema.
        """
        try:
            # provider_team_id is REQUIRED (NOT NULL constraint)
            if not provider_team_id:
                raise ValueError("provider_team_id is required for alias creation")

            # Build the aliased provider_team_id with age and division suffixes
            # Format: {club_id}_{age_group}_{division} e.g., "391_U16_AD"
            # This ensures each club+age+division combination has a unique alias
            # Use the helper function to ensure consistency with team creation
            aliased_provider_team_id = self._build_aliased_provider_team_id(
                base_provider_team_id=provider_team_id,
                age_group=age_group,
                division=division
            )
            
            self._dlog(f"Creating alias: base={provider_team_id}, aliased={aliased_provider_team_id}")

            # Check if alias already exists
            query = self.db.table('team_alias_map').select('id').eq(
                'provider_id', provider_id
            ).eq('provider_team_id', aliased_provider_team_id)
            
            existing = query.execute()

            # team_alias_map schema: id, provider_id, provider_team_id, team_id_master,
            # match_confidence, match_method, review_status, created_at, division
            # NOTE: Does NOT have team_name, age_group, or gender columns
            alias_data = {
                'provider_id': provider_id,
                'provider_team_id': aliased_provider_team_id,  # Use division-suffixed ID
                'team_id_master': team_id_master,
                'match_method': match_method,
                'match_confidence': confidence,
                'review_status': 'approved',
                'division': division,  # Store division (HD/AD) for reference
                'created_at': datetime.utcnow().isoformat() + 'Z'
            }

            if existing.data:
                # Update existing
                self.db.table('team_alias_map').update(alias_data).eq(
                    'id', existing.data[0]['id']
                ).execute()
            else:
                # Create new
                self.db.table('team_alias_map').insert(alias_data).execute()

            self._dlog(
                f"Creating alias -> provider_team_id={aliased_provider_team_id} "
                f"maps to team_id_master={team_id_master} (method={match_method}, division={division})"
            )
            logger.debug(
                f"[Modular11] Created/updated alias: {aliased_provider_team_id} → {team_id_master} "
                f"(method: {match_method}, division: {division})"
            )
                
        except Exception as e:
            logger.error(f"[Modular11] Error creating alias: {e}")
            raise
    
    def _enqueue_modular11_review_with_suggestions(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        provider_team_name: str,
        age_group: str,
        gender: str,
        division: Optional[str],
        suggested_master_team_id: Optional[str],
        candidates: List[Dict[str, Any]]
    ):
        """
        Add entry to team_match_review_queue with fuzzy match suggestions.
        """
        try:
            # Get provider code (team_match_review_queue uses VARCHAR provider_id)
            provider_result = self.db.table('providers').select('code').eq('id', provider_id).single().execute()
            provider_code = provider_result.data['code'] if provider_result.data else None
            
            if not provider_code:
                logger.warning(f"[Modular11] Could not find provider code for {provider_id}")
                return
            
            review_entry = {
                'provider_id': provider_code,  # VARCHAR code, not UUID
                'provider_team_id': str(provider_team_id) if provider_team_id else None,
                'provider_team_name': provider_team_name,
                'suggested_master_team_id': suggested_master_team_id,
                'confidence_score': 0.75,  # DB constraint requires >= 0.75
                'match_details': {
                    'age_group': age_group,
                    'gender': gender,
                    'division': division,
                    'match_method': 'import',  # Consistent with team_alias_map match_method
                    'candidates': candidates  # Top fuzzy suggestions
                },
                'status': 'pending'
            }
            
            # Check if entry already exists
            existing = self.db.table('team_match_review_queue').select('id').eq(
                'provider_id', provider_code
            ).eq('provider_team_id', str(provider_team_id)).eq('status', 'pending').execute()
            
            if not existing.data:
                self.db.table('team_match_review_queue').insert(review_entry).execute()
                
                # Track review queue entry
                self.summary["review_queue"] += 1
                self.summary["review_entries"].append({
                    "incoming": provider_team_name,
                    "suggestions": [c.get('team_name', 'Unknown') for c in candidates[:5]],  # top 5
                    "age": age_group,
                    "division": division
                })
                
                logger.info(
                    f"[Modular11] Created review queue entry for {provider_team_name} "
                    f"with {len(candidates)} suggestions"
                )
        except Exception as e:
            logger.error(f"[Modular11] Error creating review queue entry: {e}")
    
    def match_game_history(self, game_data: Dict) -> Dict:
        """
        Override match_game_history to extract and pass division for Modular11.
        
        Extracts mls_division from game_data and passes it to _match_team calls.
        This ensures division-aware matching for both home and away teams.
        """
        # Enable debug mode if this is a dry run OR if summary_only is enabled
        # (summary_only mode tracks summary data but suppresses per-team logs)
        if game_data.get("dry_run") is True or self.summary_only:
            self.debug = True
            # If summary_only is True, we still track summary but don't log per-team messages
        
        # Extract division from game_data (mls_division field from CSV)
        division = game_data.get('mls_division') or game_data.get('division')
        
        # If division not in game_data, try to extract from team names
        if not division:
            team_name = game_data.get('team_name') or game_data.get('home_team_name')
            if team_name:
                division = self._extract_division_from_name(team_name)
        
        # Store division in game_data so _match_team can access it
        # We'll extract it in _match_team override
        if division:
            game_data['_modular11_division'] = division
        
        # Get provider ID
        provider_id = self._get_provider_id(game_data.get('provider'))
        
        # Initialize variables for both code paths
        home_provider_id = ''
        away_provider_id = ''
        home_score = None
        away_score = None
        
        # Check if game is already transformed (has home_team_id/away_team_id)
        if 'home_team_id' in game_data and 'away_team_id' in game_data:
            # Already transformed - use directly
            home_provider_id_raw = game_data.get('home_provider_id') or game_data.get('home_team_id', '')
            away_provider_id_raw = game_data.get('away_provider_id') or game_data.get('away_team_id', '')
            try:
                home_provider_id = str(int(float(home_provider_id_raw))) if home_provider_id_raw and str(home_provider_id_raw).strip() else ''
            except (ValueError, TypeError):
                home_provider_id = str(home_provider_id_raw).strip() if home_provider_id_raw else ''
            try:
                away_provider_id = str(int(float(away_provider_id_raw))) if away_provider_id_raw and str(away_provider_id_raw).strip() else ''
            except (ValueError, TypeError):
                away_provider_id = str(away_provider_id_raw).strip() if away_provider_id_raw else ''
            
            # Extract division for home and away teams (may differ)
            home_division = division or self._extract_division_from_name(game_data.get('home_team_name', ''))
            away_division = division or self._extract_division_from_name(game_data.get('away_team_name', ''))
            
            # Match home team
            home_match = self._match_team(
                provider_id=provider_id,
                provider_team_id=home_provider_id,
                team_name=game_data.get('home_team_name'),
                age_group=game_data.get('age_group'),
                gender=game_data.get('gender'),
                club_name=game_data.get('home_club_name') or game_data.get('club_name'),
                division=home_division
            )
            
            # Match away team
            away_match = self._match_team(
                provider_id=provider_id,
                provider_team_id=away_provider_id,
                team_name=game_data.get('away_team_name'),
                age_group=game_data.get('age_group'),
                gender=game_data.get('gender'),
                club_name=game_data.get('away_club_name') or game_data.get('opponent_club_name'),
                division=away_division
            )
            
            home_team_master_id = home_match.get('team_id')
            away_team_master_id = away_match.get('team_id')
            home_score = game_data.get('home_score')
            away_score = game_data.get('away_score')
            # home_provider_id and away_provider_id already set above
            
        else:
            # Source format - transform and match
            # Extract division for team and opponent (may differ)
            team_division = division or self._extract_division_from_name(game_data.get('team_name', ''))
            opponent_division = division or self._extract_division_from_name(game_data.get('opponent_name', ''))
            
            # Match team
            team_match = self._match_team(
                provider_id=provider_id,
                provider_team_id=game_data.get('team_id'),
                team_name=game_data.get('team_name'),
                age_group=game_data.get('age_group'),
                gender=game_data.get('gender'),
                club_name=game_data.get('club_name') or game_data.get('team_club_name'),
                division=team_division
            )
            
            # Match opponent
            opponent_match = self._match_team(
                provider_id=provider_id,
                provider_team_id=game_data.get('opponent_id'),
                team_name=game_data.get('opponent_name'),
                age_group=game_data.get('age_group'),
                gender=game_data.get('gender'),
                club_name=game_data.get('opponent_club_name'),
                division=opponent_division
            )
            
            # Determine home/away teams based on home_away flag
            home_away = game_data.get('home_away', 'H').upper()
            
            # Extract team_id and opponent_id, converting floats to strings if needed
            team_id_raw = game_data.get('team_id', '')
            opponent_id_raw = game_data.get('opponent_id', '')
            
            try:
                team_id = str(int(float(team_id_raw))) if team_id_raw and str(team_id_raw).strip() else ''
            except (ValueError, TypeError):
                team_id = str(team_id_raw).strip() if team_id_raw else ''
            try:
                opponent_id = str(int(float(opponent_id_raw))) if opponent_id_raw and str(opponent_id_raw).strip() else ''
            except (ValueError, TypeError):
                opponent_id = str(opponent_id_raw).strip() if opponent_id_raw else ''
            
            if home_away == 'H':
                home_team_master_id = team_match.get('team_id')
                away_team_master_id = opponent_match.get('team_id')
                home_provider_id = team_id
                away_provider_id = opponent_id
                home_score = game_data.get('goals_for')
                away_score = game_data.get('goals_against')
            else:
                home_team_master_id = opponent_match.get('team_id')
                away_team_master_id = team_match.get('team_id')
                home_provider_id = opponent_id
                away_provider_id = team_id
                home_score = game_data.get('goals_against')
                away_score = game_data.get('goals_for')
        
        # CRITICAL: Validate age groups match between home and away teams
        # This prevents age mismatches (e.g., U13 vs U16 games)
        match_status = None  # Initialize before age validation
        
        # Log team matching results for debugging
        game_uid_debug = game_data.get('game_uid', 'N/A')
        logger.debug(
            f"[Modular11] Team matching results for game {game_uid_debug}: "
            f"home_team_master_id={home_team_master_id}, away_team_master_id={away_team_master_id}, "
            f"home_provider_id={home_provider_id}, away_provider_id={away_provider_id}"
        )
        
        if home_team_master_id and away_team_master_id:
            try:
                home_team_result = self.db.table('teams').select('age_group, gender, team_name').eq('team_id_master', home_team_master_id).single().execute()
                away_team_result = self.db.table('teams').select('age_group, gender, team_name').eq('team_id_master', away_team_master_id).single().execute()
                
                if home_team_result.data and away_team_result.data:
                    home_age = home_team_result.data.get('age_group', '').lower() if home_team_result.data.get('age_group') else None
                    away_age = away_team_result.data.get('age_group', '').lower() if away_team_result.data.get('age_group') else None
                    home_team_name = home_team_result.data.get('team_name', 'Unknown')
                    away_team_name = away_team_result.data.get('team_name', 'Unknown')
                    
                    logger.debug(
                        f"[Modular11] Age validation for game {game_uid_debug}: "
                        f"home={home_team_name} ({home_age}), away={away_team_name} ({away_age})"
                    )
                    
                    if home_age and away_age:
                        try:
                            home_age_num = int(home_age.replace('u', '').replace('U', ''))
                            away_age_num = int(away_age.replace('u', '').replace('U', ''))
                            age_diff = abs(home_age_num - away_age_num)
                            
                            logger.debug(
                                f"[Modular11] Age difference for game {game_uid_debug}: "
                                f"{home_age_num} vs {away_age_num} = {age_diff} years"
                            )
                            
                            # Age mismatch if difference >= 2 years
                            if age_diff >= 2:
                                logger.warning(
                                    f"[Modular11] AGE MISMATCH DETECTED: "
                                    f"{home_team_name} ({home_age}) vs "
                                    f"{away_team_name} ({away_age}) - "
                                    f"Age difference: {age_diff} years - "
                                    f"Game UID: {game_uid_debug} - "
                                    f"REJECTING GAME"
                                )
                                # Reject the game by setting match_status to 'failed'
                                match_status = 'failed'
                                home_team_master_id = None
                                away_team_master_id = None
                            else:
                                logger.debug(
                                    f"[Modular11] Age validation PASSED for game {game_uid_debug}: "
                                    f"Age difference {age_diff} < 2 years"
                                )
                        except (ValueError, AttributeError) as e:
                            logger.debug(
                                f"[Modular11] Age parsing failed for game {game_uid_debug}: {e} - "
                                f"Allowing game (home_age={home_age}, away_age={away_age})"
                            )
                            pass  # If age parsing fails, allow the game (better safe than sorry)
                    else:
                        logger.debug(
                            f"[Modular11] Age validation SKIPPED for game {game_uid_debug}: "
                            f"Missing age data (home_age={home_age}, away_age={away_age})"
                        )
                else:
                    logger.warning(
                        f"[Modular11] Could not fetch team data for age validation: "
                        f"game {game_uid_debug}, home_id={home_team_master_id}, away_id={away_team_master_id}"
                    )
            except Exception as e:
                logger.error(
                    f"[Modular11] Error validating age groups for game {game_uid_debug}: {e}"
                )
                # If validation fails, allow the game (don't block on validation errors)
        else:
            logger.debug(
                f"[Modular11] Age validation SKIPPED for game {game_uid_debug}: "
                f"Missing team master IDs (home={home_team_master_id}, away={away_team_master_id})"
            )
        
        # Determine overall match status
        # NOTE: Don't overwrite 'failed' status if age validation already set it
        if match_status != 'failed':
            if home_team_master_id and away_team_master_id:
                match_status = 'matched'
                logger.debug(
                    f"[Modular11] Game {game_uid_debug} MATCHED: "
                    f"Both teams found (home={home_team_master_id}, away={away_team_master_id})"
                )
            elif home_team_master_id or away_team_master_id:
                match_status = 'partial'
                logger.debug(
                    f"[Modular11] Game {game_uid_debug} PARTIAL MATCH: "
                    f"home={home_team_master_id}, away={away_team_master_id}"
                )
            else:
                match_status = 'failed'
                logger.warning(
                    f"[Modular11] Game {game_uid_debug} FAILED: "
                    f"No teams matched (home={home_team_master_id}, away={away_team_master_id})"
                )
        else:
            logger.warning(
                f"[Modular11] Game {game_uid_debug} FAILED: "
                f"Age validation rejected the game"
            )
        
        # Generate game UID if missing
        if not game_data.get('game_uid'):
            provider_code = game_data.get('provider', '')
            game_uid = self.generate_game_uid(
                provider=provider_code,
                game_date=game_data.get('game_date', ''),
                team1_id=home_provider_id or game_data.get('team_id', ''),
                team2_id=away_provider_id or game_data.get('opponent_id', '')
            )
        else:
            game_uid = game_data.get('game_uid')
        
        # Build game record
        try:
            home_provider_id_final = str(int(float(home_provider_id))) if home_provider_id and str(home_provider_id).strip() else ''
        except (ValueError, TypeError):
            home_provider_id_final = str(home_provider_id).strip() if home_provider_id else ''
        try:
            away_provider_id_final = str(int(float(away_provider_id))) if away_provider_id and str(away_provider_id).strip() else ''
        except (ValueError, TypeError):
            away_provider_id_final = str(away_provider_id).strip() if away_provider_id else ''
        
        game_record = {
            'game_uid': game_uid,
            'home_team_master_id': home_team_master_id,
            'away_team_master_id': away_team_master_id,
            'home_provider_id': home_provider_id_final,
            'away_provider_id': away_provider_id_final,
            'team_id': game_data.get('team_id', ''),
            'opponent_id': game_data.get('opponent_id', ''),
            'home_score': home_score,
            'away_score': away_score,
            'result': game_data.get('result'),
            'game_date': game_data.get('game_date'),
            'competition': game_data.get('competition'),
            'division_name': game_data.get('division_name'),
            'event_name': game_data.get('event_name'),
            'venue': game_data.get('venue'),
            'provider_id': provider_id,
            'source_url': game_data.get('source_url'),
            'scraped_at': game_data.get('scraped_at'),
            'match_status': match_status,
            'raw_data': game_data
        }
        
        return game_record
    
    def _match_by_provider_id(
        self,
        provider_id: str,
        provider_team_id: str,
        age_group: Optional[str] = None,
        gender: Optional[str] = None,
        division: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Match by exact provider ID with MANDATORY age_group validation.

        CRITICAL: For Modular11, the same provider_team_id (club ID) is used
        for multiple age groups. We MUST validate age_group to prevent
        cross-age matches (e.g., U16 games matching to U13 teams).

        Alias lookup priority (most specific to least specific):
        1. {id}_{age}_{division} (e.g., "391_U16_AD") - new format
        2. {id}_{division} (e.g., "391_AD") - backwards compatible
        3. {id} (e.g., "391") - original format

        This allows gradual migration from old aliases while new imports
        create properly suffixed aliases.
        """
        if not provider_team_id:
            return None

        team_id_str = str(provider_team_id)

        # Build list of alias formats to try (most specific first)
        team_ids_to_try = []

        # Normalize age format
        age_normalized = None
        if age_group:
            age_normalized = age_group.upper() if age_group.lower().startswith('u') else f"U{age_group}"

        # 1. Try full suffix: {id}_{age}_{division} (e.g., "391_U16_AD")
        if age_normalized and division and division.upper() in ('HD', 'AD'):
            team_ids_to_try.append(f"{team_id_str}_{age_normalized}_{division.upper()}")

        # 2. Try age-only suffix: {id}_{age} (e.g., "391_U16")
        if age_normalized:
            team_ids_to_try.append(f"{team_id_str}_{age_normalized}")

        # 3. Try division-only suffix: {id}_{division} (e.g., "391_AD") - backwards compatible
        if division and division.upper() in ('HD', 'AD'):
            team_ids_to_try.append(f"{team_id_str}_{division.upper()}")

        # 4. Always fall back to original ID
        team_ids_to_try.append(team_id_str)
        
        # Check cache first (if available) - try division-suffixed IDs first
        for try_id in team_ids_to_try:
            if self.alias_cache and try_id in self.alias_cache:
                cached = self.alias_cache[try_id]
                team_id_master = cached['team_id_master']

                # MODULAR11: ALWAYS validate age_group if provided
                if age_group:
                    if not self._validate_team_age_group(team_id_master, age_group, gender):
                        # Get team details for logging
                        try:
                            team_result = self.db.table('teams').select('team_name, age_group, gender').eq('team_id_master', team_id_master).single().execute()
                            if team_result.data:
                                team_age = team_result.data.get('age_group', 'Unknown')
                                team_gender = team_result.data.get('gender', 'Unknown')
                                self._dlog(f"Alias rejected: age mismatch (incoming {age_group} vs team {team_age})")
                            else:
                                self._dlog(f"Alias rejected: age mismatch (incoming {age_group} vs team Unknown)")
                        except:
                            self._dlog(f"Alias rejected: age mismatch (incoming {age_group})")
                        logger.debug(
                            f"[Modular11] Provider ID {try_id} matched to team {team_id_master} "
                            f"but age_group mismatch (game: {age_group}, team: ?). Rejecting match."
                        )
                        continue  # Try next ID instead of returning None

                # Prefer direct_id matches
                if cached.get('match_method') == 'direct_id':
                    self._dlog(f"Cache hit: {try_id} -> {team_id_master} (direct_id)")
                    return {
                        'team_id_master': team_id_master,
                        'review_status': cached.get('review_status', 'approved'),
                        'match_method': 'direct_id'
                    }
                # Fallback to any cached match
                self._dlog(f"Cache hit: {try_id} -> {team_id_master}")
                return {
                    'team_id_master': team_id_master,
                    'review_status': cached.get('review_status', 'approved'),
                    'match_method': cached.get('match_method')
                }
        
        # Tier 1: Direct ID match (from team importer) - try division-suffixed IDs first
        for try_id in team_ids_to_try:
            try:
                result = self.db.table('team_alias_map').select(
                    'team_id_master, review_status, match_method'
                ).eq('provider_id', provider_id).eq(
                    'provider_team_id', try_id
                ).eq('match_method', 'direct_id').eq(
                    'review_status', 'approved'
                ).single().execute()

                if result.data:
                    team_id_master = result.data['team_id_master']
                    # MODULAR11: ALWAYS validate age_group if provided
                    if age_group:
                        if not self._validate_team_age_group(team_id_master, age_group, gender):
                            # Get team details for logging
                            try:
                                team_result = self.db.table('teams').select('team_name, age_group, gender').eq('team_id_master', team_id_master).single().execute()
                                if team_result.data:
                                    team_age = team_result.data.get('age_group', 'Unknown')
                                    team_gender = team_result.data.get('gender', 'Unknown')
                                    self._dlog(f"Alias rejected: age mismatch (incoming {age_group} vs team {team_age})")
                                else:
                                    self._dlog(f"Alias rejected: age mismatch (incoming {age_group} vs team Unknown)")
                            except:
                                self._dlog(f"Alias rejected: age mismatch (incoming {age_group})")
                            logger.debug(
                                f"[Modular11] Provider ID {try_id} matched to team {team_id_master} "
                                f"but age_group mismatch (game: {age_group}). Rejecting match."
                            )
                            continue  # Try next ID
                    self._dlog(f"Tier 1 match: {try_id} -> {team_id_master} (direct_id)")
                    return result.data
            except Exception as e:
                logger.debug(f"No direct_id match found for {try_id}: {e}")
        
        # Tier 2: Any approved alias map entry (fallback) - try division-suffixed IDs first
        for try_id in team_ids_to_try:
            try:
                result = self.db.table('team_alias_map').select(
                    'team_id_master, review_status, match_method'
                ).eq('provider_id', provider_id).eq(
                    'provider_team_id', try_id
                ).eq('review_status', 'approved').single().execute()

                if result.data:
                    team_id_master = result.data['team_id_master']
                    # MODULAR11: ALWAYS validate age_group if provided
                    if age_group:
                        if not self._validate_team_age_group(team_id_master, age_group, gender):
                            # Get team details for logging
                            try:
                                team_result = self.db.table('teams').select('team_name, age_group, gender').eq('team_id_master', team_id_master).single().execute()
                                if team_result.data:
                                    team_age = team_result.data.get('age_group', 'Unknown')
                                    team_gender = team_result.data.get('gender', 'Unknown')
                                    self._dlog(f"Alias rejected: age mismatch (incoming {age_group} vs team {team_age})")
                                else:
                                    self._dlog(f"Alias rejected: age mismatch (incoming {age_group} vs team Unknown)")
                            except:
                                self._dlog(f"Alias rejected: age mismatch (incoming {age_group})")
                            logger.debug(
                                f"[Modular11] Provider ID {try_id} matched to team {team_id_master} "
                                f"but age_group mismatch (game: {age_group}). Rejecting match."
                            )
                            continue  # Try next ID
                    self._dlog(f"Tier 2 match: {try_id} -> {team_id_master}")
                    return result.data
            except Exception as e:
                logger.debug(f"No alias map match found for {try_id}: {e}")
        return None
    
    def _validate_team_age_group(
        self, 
        team_id_master: str, 
        expected_age_group: str, 
        expected_gender: Optional[str] = None
    ) -> bool:
        """
        Validate that a master team's age_group matches the expected age_group.
        
        This is CRITICAL for Modular11 because the same provider_team_id (club ID)
        is used for all age groups. Without this validation, U16 games would
        incorrectly match to U13 teams.
        """
        try:
            # Normalize age_group for comparison (U13 vs u13)
            expected_age_normalized = expected_age_group.lower() if expected_age_group else None
            
            # Get team's age_group from database
            team_result = self.db.table('teams').select(
                'age_group, gender'
            ).eq('team_id_master', team_id_master).single().execute()
            
            if not team_result.data:
                logger.warning(f"[Modular11] Team {team_id_master} not found in database")
                return False
            
            team_age = team_result.data.get('age_group', '').lower() if team_result.data.get('age_group') else None
            team_gender = team_result.data.get('gender')
            
            # Check age_group match
            if expected_age_normalized and team_age:
                if expected_age_normalized != team_age:
                    logger.debug(
                        f"[Modular11] Age mismatch: game expects {expected_age_group}, "
                        f"team has {team_result.data.get('age_group')}"
                    )
                    return False
            
            # Check gender match if provided
            if expected_gender and team_gender:
                if expected_gender != team_gender:
                    logger.debug(
                        f"[Modular11] Gender mismatch: game expects {expected_gender}, "
                        f"team has {team_gender}"
                    )
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"[Modular11] Error validating team age_group: {e}")
            # On error, be conservative and reject the match
            return False
