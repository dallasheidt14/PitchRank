#!/usr/bin/env python3
"""
Find matches for team_match_review_queue entries against current teams.

This script:
1. Pulls pending queue entries
2. Searches for matches in the teams table using fuzzy matching
3. Categorizes by match quality
4. Can auto-approve high-confidence matches

Usage:
    python3 scripts/find_queue_matches.py [--dry-run] [--limit 100] [--execute]
"""
import os
import sys
import argparse
import re
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from difflib import SequenceMatcher

load_dotenv(Path(__file__).parent.parent / '.env')

# Skip .env.local to avoid pooler connection issues in local dev
# (GitHub Actions will use the correct secrets)

def get_supabase():
    """Create Supabase client."""
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_KEY')
    
    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
    
    return create_client(supabase_url, supabase_key)

def normalize_team_name(name):
    """Normalize team name for matching."""
    if not name:
        return ""
    
    # Lowercase
    n = name.lower().strip()
    
    # Remove common suffixes/prefixes
    n = re.sub(r'\s*(ecnl|ecnl-rl|rl|pre-ecnl|mls next|ga|academy)\s*', ' ', n)
    n = re.sub(r'\s*-\s*', ' ', n)  # Replace dashes with spaces
    
    # Normalize age formats
    n = re.sub(r'\b(b|g)\s*(\d{2,4})\b', r'\2', n)  # B2014 -> 2014
    n = re.sub(r'\b(\d{2,4})\s*(b|g)\b', r'\1', n)  # 2014B -> 2014
    n = re.sub(r'\bu\s*(\d+)\b', r'u\1', n)  # U 14 -> u14
    
    # Remove extra whitespace
    n = ' '.join(n.split())
    
    return n

def extract_club_from_name(provider_team_name):
    """Extract club name from provider team name.
    
    Logic:
    1. Split on age/year patterns (2014, U14, B2014, etc.)
    2. Take the first part as club name
    3. Remove duplicate words (e.g., "Kingman SC Kingman SC" → "Kingman SC")
    4. Strip common suffixes (ECNL, RL, PRE, COMP)
    
    Examples:
        "FC Tampa Rangers FCTS 2015 Falcons" → "FC Tampa Rangers FCTS"
        "Phoenix Rising FC B2014 Black" → "Phoenix Rising FC"
        "Kingman SC Kingman SC U14" → "Kingman SC"
        "Real Salt Lake AZ ECNL 2014 Red" → "Real Salt Lake AZ"
    """
    if not provider_team_name:
        return None
    
    name = provider_team_name.strip()
    
    # Age/year patterns to split on (from team_name_normalizer.py)
    # Match: U14, U-14, 2014, B2014, 2014B, G2015, 15B, B15, etc.
    age_patterns = [
        r'\bU-?\d{1,2}\b',           # U14, U-14
        r'\b[BG]?\d{4}[BG]?\b',      # 2014, B2014, 2014B, G2015, 2015G
        r'\b[BG]\d{2}(?!\d)\b',      # B14, G15 (not followed by more digits)
        r'\b\d{2}[BG](?!\d)\b',      # 14B, 15G (not followed by more digits)
    ]
    
    # Find the earliest age pattern match
    earliest_pos = len(name)
    for pattern in age_patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if match and match.start() < earliest_pos:
            earliest_pos = match.start()
    
    # Extract club name before the age pattern
    if earliest_pos < len(name):
        club_name = name[:earliest_pos].strip()
    else:
        # No age pattern found, use whole name
        club_name = name
    
    # Remove common suffixes (case insensitive)
    suffixes = [
        r'\s+(ECNL-RL|ECNL RL|ECRL)\s*$',
        r'\s+ECNL\s*$',
        r'\s+RL\s*$',
        r'\s+PRE-ECNL\s*$',
        r'\s+PRE\s*$',
        r'\s+COMP\s*$',
        r'\s+GA\s*$',
        r'\s+MLS NEXT\s*$',
        r'\s+ACADEMY\s*$',
        r'\s+SELECT\s*$',
        r'\s+PREMIER\s*$',
        r'\s+ELITE\s*$',
    ]
    
    for suffix_pattern in suffixes:
        club_name = re.sub(suffix_pattern, '', club_name, flags=re.IGNORECASE)
    
    # Remove trailing hyphens, dots, and extra whitespace
    club_name = club_name.strip(' -.')
    
    # Remove duplicate words (e.g., "Kingman SC Kingman SC" → "Kingman SC")
    words = club_name.split()
    if len(words) >= 4:  # Only check if at least 4 words
        # Check if first half == second half
        mid = len(words) // 2
        first_half = ' '.join(words[:mid])
        second_half = ' '.join(words[mid:mid*2])
        if first_half.lower() == second_half.lower():
            club_name = first_half
    
    # Final cleanup
    club_name = ' '.join(club_name.split())
    
    # Don't return empty or too-short club names
    if not club_name or len(club_name) < 3:
        return None
    
    return club_name

# Common team colors and variants that indicate DIFFERENT teams
TEAM_COLORS = {'red', 'blue', 'white', 'black', 'gold', 'grey', 'gray', 'green', 
               'orange', 'purple', 'yellow', 'navy', 'maroon', 'silver', 'pink', 'sky'}

# Direction/location variants that indicate different teams
TEAM_DIRECTIONS = {'north', 'south', 'east', 'west', 'central'}

def extract_team_variant(name):
    """Extract team variant (color, direction, coach name, roman numeral) from team name.
    
    Teams like 'FC Dallas 2014 Blue' and 'FC Dallas 2014 Gold' are DIFFERENT teams.
    Also 'Select North' and 'Select South' are DIFFERENT teams.
    Coach names like 'Atletico Dallas 15G Riedell' and 'Atletico Dallas 15G Davis' are DIFFERENT teams.
    """
    if not name:
        return None
    
    name_lower = name.lower()
    words = name_lower.split()
    
    # Check for color ANYWHERE in name (not just at end)
    for word in words:
        word_clean = word.strip('-()[]')
        if word_clean in TEAM_COLORS:
            return word_clean
    
    # Check for direction variants (North, South, East, West, Central)
    for word in words:
        word_clean = word.strip('-()[]')
        if word_clean in TEAM_DIRECTIONS:
            return word_clean
    
    # Check for roman numerals or letter variants (I, II, III, A, B)
    roman_match = re.search(r'\b(i{1,3}|iv|v|vi{0,3})\b', name_lower)
    if roman_match:
        return roman_match.group(1)
    
    # === ENHANCED COACH NAME DETECTION ===
    # Coach names typically appear AFTER age/year but BEFORE regions/programs
    # Pattern: "Club [Age] [CoachName] (Region)" or "Club [Age] [CoachName] Region"
    # Examples: "15G Riedell (CTX)", "2015 Davis CTX", "2014 Thompson", "U14 Blanton"
    
    # Known non-coach words to filter out
    common_words = {'ecnl', 'boys', 'girls', 'academy', 'united', 'elite', 'club', 'futbol', 
                    'soccer', 'youth', 'rush', 'surf', 'select', 'premier', 'gold', 'blue',
                    'white', 'black', 'grey', 'gray', 'green', 'maroon', 'navy', 'lafc', 'futeca',
                    'selection', 'fire', 'storm', 'fusion', 'athletico', 'atletico', 'fc', 'sc',
                    'real', 'inter', 'sporting', 'united'}
    
    # Known region codes (3-letter abbreviations, typically in parens or at end)
    region_codes = {'ctx', 'phx', 'atx', 'dal', 'hou', 'san', 'sdg', 'sfv', 'oc', 'ie', 
                   'la', 'bay', 'nyc', 'nj', 'dmv', 'pnw', 'sea', 'pdx', 'slc', 'den',
                   'chi', 'stl', 'kc', 'min', 'det', 'cle', 'pit', 'atl', 'mia', 'orl',
                   'tam', 'ral', 'cha', 'dc', 'md', 'va', 'pa', 'ma', 'ct', 'ri', 'vt',
                   'nh', 'me', 'az', 'ca', 'tx', 'fl', 'ny', 'nj', 'ga', 'nc', 'sc', 
                   'co', 'ut', 'nv', 'wa', 'or', 'id', 'mt', 'wy', 'nm', 'ok', 'ks',
                   'ne', 'sd', 'nd', 'mn', 'wi', 'mi', 'il', 'in', 'oh', 'ky', 'tn',
                   'al', 'ms', 'la', 'ar', 'mo', 'ia', 'ecnl', 'rl', 'ga', 'ea', 'npl',
                   'usys', 'ayso', 'scdsl', 'dpl', 'mls', 'ussda', 'pre'}
    
    # Program/league names that aren't coach names
    program_names = {'aspire', 'rise', 'revolution', 'evolution', 'dynasty', 'legacy', 'impact',
                    'force', 'thunder', 'lightning', 'blaze', 'inferno', 'phoenix', 'predators',
                    'raptors', 'lions', 'tigers', 'bears', 'eagles', 'hawks', 'falcons', 'united',
                    'strikers', 'raiders', 'warriors', 'knights', 'spartans', 'titans', 'trojans'}
    
    # Find age/year position in the team name
    age_patterns = [
        r'\bU-?\d{1,2}\b',           # U14, U-14
        r'\b[BG]?\d{4}[BG]?\b',      # 2014, B2014, 2014B, G2015, 2015G
        r'\b[BG]\d{2}(?!\d)\b',      # B14, G15
        r'\b\d{2}[BG](?!\d)\b',      # 14B, 15G
    ]
    
    age_match = None
    age_end_pos = -1
    for pattern in age_patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            age_match = match
            age_end_pos = match.end()
            break
    
    if age_match and age_end_pos > 0:
        # Extract the part AFTER the age
        after_age = name[age_end_pos:].strip()
        
        # Remove region markers in parentheses first: "(CTX)" -> ""
        after_age_clean = re.sub(r'\s*\([^)]+\)\s*$', '', after_age).strip()
        
        # Split into words
        after_words = after_age_clean.split()
        
        # Look for coach name: first word after age that's not a region/program/common word
        for word in after_words:
            word_clean = word.strip('-()[].,').lower()
            
            # Skip if empty or too short
            if not word_clean or len(word_clean) < 3:
                continue
            
            # Skip if it's a known non-coach word
            if word_clean in common_words:
                continue
            if word_clean in region_codes:
                continue
            if word_clean in program_names:
                continue
            if word_clean in TEAM_COLORS:
                continue
            if word_clean in TEAM_DIRECTIONS:
                continue
            
            # Skip if it's clearly a number or age
            if word_clean.isdigit():
                continue
            if re.match(r'^[bug]?\d+', word_clean):
                continue
            
            # This looks like a coach name!
            return word_clean
    
    # Check for coach names in parentheses: "2014 (Holohan)" but NOT regions like "(CTX)"
    coach_match = re.search(r'\(([a-z]+)\)\s*$', name_lower)
    if coach_match:
        word = coach_match.group(1)
        # Only return if it's not a region code
        if word not in region_codes:
            return word
    
    # Fallback: Check for ALL CAPS words after year (legacy logic)
    coach_after_year = re.search(r'20\d{2}\s+([A-Z]{4,})\b', name)
    if coach_after_year:
        word = coach_after_year.group(1).lower()
        if word not in common_words and word not in region_codes and word not in program_names:
            return word
    
    # Fallback: Check for mixed case names at end after age
    name_parts = name.split()
    if len(name_parts) >= 2:
        last_part = name_parts[-1]
        last_clean = last_part.strip('()[]').lower()
        # If last word is a proper name (capitalized, not a color/common/region word)
        if (last_part[0].isupper() and 
            last_clean not in TEAM_COLORS and 
            last_clean not in common_words and
            last_clean not in region_codes and
            last_clean not in program_names and
            not re.match(r'^[BG]?\d+', last_part)):  # Not an age
            return last_clean
    
    return None

def extract_age_group(name, details):
    """Extract age group from name - ALWAYS parse from name first, metadata is unreliable."""
    name_lower = name.lower() if name else ""
    
    # Priority 1: U-age format (U13, U14, etc)
    match = re.search(r'\bu(\d+)\b', name_lower)
    if match:
        return f"u{match.group(1)}"
    
    # Priority 2: Birth year with gender prefix (G13, B2014, 2013G, etc)
    # G13/B13 = 2013 birth year, G2014/B2014 = 2014 birth year
    match = re.search(r'[bg](\d{2})(?!\d)', name_lower)  # G13, B14 (2-digit)
    if match:
        short_year = int(match.group(1))
        year = 2000 + short_year if short_year < 50 else 1900 + short_year
        age = 2026 - year
        return f"u{age}"
    
    match = re.search(r'[bg](20\d{2})', name_lower)  # G2013, B2014 (4-digit)
    if match:
        year = int(match.group(1))
        age = 2026 - year
        return f"u{age}"
    
    # Priority 3: Standalone 4-digit birth year
    match = re.search(r'\b(20\d{2})\b', name)
    if match:
        year = int(match.group(1))
        age = 2026 - year
        return f"u{age}"
    
    # Fallback: use metadata only if nothing found in name
    if details and details.get('age_group'):
        return details['age_group'].lower()
    
    return None

def extract_gender(name, details):
    """Extract gender from name or details."""
    if details and details.get('gender'):
        return details['gender'].lower()
    
    name_lower = name.lower()
    if ' g20' in name_lower or ' g1' in name_lower or 'girls' in name_lower:
        return 'female'
    if ' b20' in name_lower or ' b1' in name_lower or 'boys' in name_lower:
        return 'male'
    
    return None

def has_protected_division(name):
    """Check if team name contains AD, HD, or MLS NEXT - needs manual review."""
    if not name:
        return False
    name_upper = name.upper()
    # Check for division markers
    if ' AD' in name_upper or '_AD' in name_upper or '-AD' in name_upper:
        return True
    if ' HD' in name_upper or '_HD' in name_upper or '-HD' in name_upper:
        return True
    if 'MLS NEXT' in name_upper or 'MLSNEXT' in name_upper:
        return True
    if ' EA' in name_upper or '_EA' in name_upper:  # Elite Academy
        return True
    return False

def find_best_match(queue_entry, supabase):
    """Find the best matching team for a queue entry."""
    name = queue_entry['provider_team_name']
    details = queue_entry['match_details'] or {}
    club_name = details.get('club_name', '')
    
    # Skip protected divisions - need manual review
    if has_protected_division(name):
        return None, 0.0, "protected_division"
    
    # If club_name is empty, try to extract it from provider_team_name
    if not club_name:
        extracted_club = extract_club_from_name(name)
        if extracted_club:
            club_name = extracted_club
    
    norm_name = normalize_team_name(name)
    age_group = extract_age_group(name, details)
    gender = extract_gender(name, details)
    queue_variant = extract_team_variant(name)
    
    # Build Supabase query
    state_code = None
    if club_name:
        # Try to get state from club lookup
        state_result = supabase.table('teams').select('state_code').ilike('club_name', club_name).not_.is_('state_code', 'null').limit(1).execute()
        if state_result.data:
            state_code = state_result.data[0]['state_code']
    
    # Build the query with filters
    query = supabase.table('teams').select('team_id_master, team_name, club_name, gender, age_group, state_code')
    
    if club_name:
        query = query.ilike('club_name', club_name)
        if state_code:
            query = query.eq('state_code', state_code)
    
    if gender:
        query = query.ilike('gender', gender)
    
    if age_group:
        query = query.ilike('age_group', age_group)
    
    # Set limit based on whether we have club_name
    limit = 50 if club_name else 100
    result = query.limit(limit).execute()
    
    candidates = result.data if result.data else []
    
    if not candidates:
        return None, 0.0, "no_candidates"
    
    # Score each candidate
    best_match = None
    best_score = 0.0
    
    # Check for league markers in queue name
    name_lower = name.lower()
    has_rl = ' rl' in name_lower or '-rl' in name_lower or 'ecnl rl' in name_lower or 'ecnl-rl' in name_lower
    has_ecnl = 'ecnl' in name_lower and not has_rl
    has_pre_ecnl = 'pre-ecnl' in name_lower or 'pre ecnl' in name_lower
    
    for team in candidates:
        team_name = team['team_name']
        team_norm = normalize_team_name(team_name)
        team_lower = team_name.lower()
        team_variant = extract_team_variant(team_name)
        
        # CRITICAL: Variants must match EXACTLY
        # - Both have same variant: OK
        # - Both have no variant: OK  
        # - One has variant, other doesn't: SKIP (different teams)
        # - Both have different variants: SKIP (different teams)
        if queue_variant != team_variant:
            continue  # Variants don't match = different teams
        
        # Calculate similarity
        score = SequenceMatcher(None, norm_name, team_norm).ratio()
        
        # Boost if club name matches exactly
        if club_name and team.get('club_name') and club_name.lower() == team['club_name'].lower():
            score = min(1.0, score + 0.15)
        
        # League matching: penalize mismatches, boost matches
        team_has_rl = ' rl' in team_lower or '-rl' in team_lower or 'ecnl rl' in team_lower
        team_has_ecnl = 'ecnl' in team_lower and not team_has_rl
        
        if has_rl and team_has_rl:
            score = min(1.0, score + 0.05)  # Both RL
        elif has_ecnl and team_has_ecnl and not team_has_rl:
            score = min(1.0, score + 0.05)  # Both ECNL (not RL)
        elif has_rl != team_has_rl:
            score = max(0.0, score - 0.08)  # RL mismatch penalty
        
        if score > best_score:
            best_score = score
            best_match = {
                'id': team['team_id_master'],
                'team_name': team['team_name'],
                'club_name': team.get('club_name'),
                'gender': team.get('gender'),
                'age_group': team.get('age_group')
            }
    
    if best_score >= 0.7:
        return best_match, best_score, "fuzzy"
    
    return None, 0.0, "low_confidence"

def analyze_queue(limit=100, min_confidence=0.90, force=False):
    """Analyze queue entries and find matches.
    
    Args:
        limit: Max number of entries to analyze
        min_confidence: Minimum confidence score (unused, kept for compatibility)
        force: If True, ignore last_analyzed_at filter and reprocess all pending entries
    """
    supabase = get_supabase()
    
    # Get pending queue entries
    # If force=True, reprocess all pending entries (ignore last_analyzed_at)
    # Otherwise, skip recently analyzed ones that didn't match (7 day cooldown)
    query = supabase.table('team_match_review_queue').select('id, provider_id, provider_team_id, provider_team_name, match_details, confidence_score').eq('status', 'pending')
    
    if not force:
        # Filter for entries not analyzed in last 7 days
        query = query.or_('last_analyzed_at.is.null,last_analyzed_at.lt.now()-7days')
    
    result = query.order('created_at').limit(limit).execute()
    entries = result.data if result.data else []
    
    results = {
        'exact': [],      # 95%+ match
        'high': [],       # 90-94% match  
        'medium': [],     # 80-89% match
        'low': [],        # 70-79% match
        'no_match': []    # < 70% or no candidates
    }
    
    print(f"Analyzing {len(entries)} queue entries...")
    print()
    
    for i, entry in enumerate(entries):
        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(entries)}...")
        
        match, score, method = find_best_match(entry, supabase)
        
        result = {
            'queue_entry': entry,
            'match': match,
            'score': score,
            'method': method
        }
        
        if score >= 0.95:
            results['exact'].append(result)
        elif score >= 0.90:
            results['high'].append(result)
        elif score >= 0.80:
            results['medium'].append(result)
        elif score >= 0.70:
            results['low'].append(result)
        else:
            results['no_match'].append(result)
    
    # Mark ALL analyzed entries with timestamp so we skip them next run
    # (Only entries that don't get merged - merged ones change status to 'approved')
    analyzed_ids = [e['id'] for e in entries]
    if analyzed_ids:
        from datetime import datetime
        supabase.table('team_match_review_queue').update({
            'last_analyzed_at': datetime.utcnow().isoformat()
        }).in_('id', analyzed_ids).eq('status', 'pending').execute()
        print(f"  Marked {len(analyzed_ids)} entries as analyzed")
    
    return results

def display_results(results, verbose=False):
    """Display analysis results."""
    print("=" * 70)
    print("MATCH ANALYSIS RESULTS")
    print("=" * 70)
    print(f"✅ EXACT (95%+):    {len(results['exact']):>5} - Safe to auto-merge")
    print(f"🟢 HIGH (90-94%):   {len(results['high']):>5} - Likely safe")
    print(f"🟡 MEDIUM (80-89%): {len(results['medium']):>5} - Review recommended")
    print(f"🟠 LOW (70-79%):    {len(results['low']):>5} - Manual review needed")
    print(f"❌ NO MATCH:        {len(results['no_match']):>5} - Need to create new team")
    print()
    
    # Show exact matches
    if results['exact']:
        print("=" * 70)
        print("✅ EXACT MATCHES (Safe to auto-merge)")
        print("=" * 70)
        for r in results['exact'][:15]:
            q = r['queue_entry']
            m = r['match']
            print(f"  [{q['id']}] {q['provider_team_name']}")
            print(f"       → {m['team_name']} ({m['club_name']})")
            print(f"       Score: {r['score']:.1%} | {q['provider_id']}")
            print()
        
        if len(results['exact']) > 15:
            print(f"  ... and {len(results['exact']) - 15} more")
        print()
    
    # Show high matches
    if results['high'] and verbose:
        print("=" * 70)
        print("🟢 HIGH CONFIDENCE MATCHES")
        print("=" * 70)
        for r in results['high'][:10]:
            q = r['queue_entry']
            m = r['match']
            print(f"  [{q['id']}] {q['provider_team_name']}")
            print(f"       → {m['team_name']} ({m['club_name']})")
            print(f"       Score: {r['score']:.1%}")
            print()

def execute_merges(results, dry_run=True, min_confidence=0.95):
    """Execute auto-merges for high-confidence matches."""
    candidates = results['exact']
    if min_confidence < 0.95:
        candidates = candidates + results['high']
    
    if not candidates:
        print("No candidates to merge.")
        return 0, 0
    
    if dry_run:
        print(f"\n🔍 DRY RUN - Would merge {len(candidates)} entries\n")
    else:
        print(f"\n⚡ EXECUTING {len(candidates)} merges\n")
    
    supabase = get_supabase()
    
    approved = 0
    failed = 0
    
    for r in candidates:
        q = r['queue_entry']
        m = r['match']
        
        try:
            if not dry_run:
                # Get provider UUID
                provider_result = supabase.table('providers').select('id').eq('code', q['provider_id']).execute()
                if not provider_result.data:
                    raise ValueError(f"Provider not found: {q['provider_id']}")
                provider_uuid = provider_result.data[0]['id']
                
                # Cap score at 0.99 for alias table
                db_score = min(0.99, r['score'])
                
                # Create alias with correct column names
                supabase.table('team_alias_map').upsert({
                    'team_id_master': m['id'],
                    'provider_id': provider_uuid,
                    'provider_team_id': q['provider_team_id'],
                    'match_confidence': db_score,
                    'match_method': 'fuzzy_auto',
                    'review_status': 'approved'
                }, on_conflict='provider_id,provider_team_id').execute()
                
                # Update queue - don't update confidence_score (constraint requires 0.75-0.90)
                from datetime import datetime
                supabase.table('team_match_review_queue').update({
                    'status': 'approved',
                    'suggested_master_team_id': m['id'],
                    'reviewed_by': 'auto-merge-script',
                    'reviewed_at': datetime.utcnow().isoformat()
                }).eq('id', q['id']).execute()
            
            approved += 1
            action = "Would merge" if dry_run else "Merged"
            print(f"  ✅ {action}: {q['provider_team_name']} → {m['team_name']} ({r['score']:.1%})")
            
        except Exception as e:
            failed += 1
            print(f"  ❌ Failed [{q['id']}]: {e}")
    
    return approved, failed

def main():
    parser = argparse.ArgumentParser(description='Find matches for queue entries')
    parser.add_argument('--limit', type=int, default=200,
                        help='Max entries to analyze (default: 200)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show more details')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Show what would be merged (default)')
    parser.add_argument('--execute', action='store_true',
                        help='Actually execute merges')
    parser.add_argument('--include-high', action='store_true',
                        help='Include 90%+ matches in auto-merge (not just 95%+)')
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Skip confirmation prompt (for CI/automation)')
    parser.add_argument('--force', action='store_true',
                        help='Reprocess all pending entries (ignore last_analyzed_at filter)')
    args = parser.parse_args()
    
    print("=" * 70)
    print("🔍 QUEUE MATCH FINDER")
    print("=" * 70)
    print(f"Analyzing up to {args.limit} queue entries...")
    if args.force:
        print("⚡ FORCE mode: Reprocessing all pending entries")
    print()
    
    results = analyze_queue(limit=args.limit, force=args.force)
    display_results(results, verbose=args.verbose)
    
    # Execute if requested
    min_conf = 0.90 if args.include_high else 0.95
    
    if args.execute:
        total = len(results['exact'])
        if args.include_high:
            total += len(results['high'])
        
        if args.yes:
            print(f"\n⚠️  Auto-confirming merge of {total} entries (--yes flag)")
            approved, failed = execute_merges(results, dry_run=False, min_confidence=min_conf)
            print(f"\n✅ Approved: {approved}, ❌ Failed: {failed}")
        else:
            confirm = input(f"\n⚠️  Merge {total} entries? Type 'yes' to confirm: ")
            if confirm.lower() == 'yes':
                approved, failed = execute_merges(results, dry_run=False, min_confidence=min_conf)
                print(f"\n✅ Approved: {approved}, ❌ Failed: {failed}")
            else:
                print("Cancelled.")
    else:
        approved, _ = execute_merges(results, dry_run=True, min_confidence=min_conf)
        print(f"\n📊 DRY RUN: {approved} would be merged")
        print("\nTo execute, run with --execute")

if __name__ == '__main__':
    main()
