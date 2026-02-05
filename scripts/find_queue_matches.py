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
    """Create Supabase client for GitHub Actions compatibility."""
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    
    return create_client(supabase_url, supabase_key)

def get_connection():
    """Get psycopg2 connection using Supabase pooler for GitHub Actions.
    
    GitHub Actions can't reach Supabase via IPv6 direct connection.
    We use the session mode pooler which provides IPv4 support.
    
    Priority order:
    1. SUPABASE_POOLER_URL (if set) - recommended for GitHub Actions
    2. DATABASE_URL (if contains pooler.supabase.com)
    3. DATABASE_URL (convert to pooler format if in GitHub Actions)
    4. DATABASE_URL (direct connection for local dev)
    """
    import psycopg2
    import re
    
    # Check for dedicated pooler URL first (best for GitHub Actions)
    pooler_url_env = os.getenv('SUPABASE_POOLER_URL')
    if pooler_url_env:
        print(f"🔗 Using SUPABASE_POOLER_URL")
        return psycopg2.connect(pooler_url_env)
    
    database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        raise ValueError("DATABASE_URL must be set")
    
    # Check if DATABASE_URL is already a pooler URL (contains pooler.supabase.com)
    if 'pooler.supabase.com' in database_url:
        print(f"🔗 Using Supabase pooler URL from DATABASE_URL")
        return psycopg2.connect(database_url)
    
    # Check if running in GitHub Actions
    is_github_actions = os.getenv('GITHUB_ACTIONS') == 'true'
    
    if is_github_actions:
        # Parse DATABASE_URL to extract project ref and password
        # From: postgresql://postgres:PASSWORD@db.PROJECT_REF.supabase.co:5432/postgres
        # To:   postgresql://postgres.PROJECT_REF:PASSWORD@aws-1-us-west-1.pooler.supabase.com:5432/postgres
        # 
        # NOTE: The pooler may require a different password than direct connection.
        # For best results, set SUPABASE_POOLER_URL secret in GitHub Actions.
        match = re.match(r'postgresql://postgres:([^@]+)@db\.([^.]+)\.supabase\.co:\d+/postgres', database_url)
        if match:
            password = match.group(1)
            project_ref = match.group(2)
            # Use session mode pooler (port 5432) with modified username format
            # Note: Region prefix is aws-1 for this project
            pooler_url = f"postgresql://postgres.{project_ref}:{password}@aws-1-us-west-1.pooler.supabase.com:5432/postgres"
            print(f"🔗 Using Supabase session pooler (IPv4) for GitHub Actions")
            print(f"   Project ref: {project_ref}")
            print(f"   ⚠️  Note: If connection fails, add SUPABASE_POOLER_URL secret to GitHub Actions")
            return psycopg2.connect(pooler_url)
        else:
            print(f"⚠️  Could not parse DATABASE_URL for pooler conversion, using as-is")
            return psycopg2.connect(database_url)
    
    # Local development - direct connection works fine
    print(f"🔗 Using direct database connection (local)")
    return psycopg2.connect(database_url)

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

# Common team colors and variants that indicate DIFFERENT teams
TEAM_COLORS = {'red', 'blue', 'white', 'black', 'gold', 'grey', 'gray', 'green', 
               'orange', 'purple', 'yellow', 'navy', 'maroon', 'silver', 'pink', 'sky'}

# Direction/location variants that indicate different teams
TEAM_DIRECTIONS = {'north', 'south', 'east', 'west', 'central'}

def extract_team_variant(name):
    """Extract team variant (color, direction, coach name, roman numeral) from team name.
    
    Teams like 'FC Dallas 2014 Blue' and 'FC Dallas 2014 Gold' are DIFFERENT teams.
    Also 'Select North' and 'Select South' are DIFFERENT teams.
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
    
    # Check for coach names in parentheses: "2014 (Holohan)"
    coach_match = re.search(r'\(([a-z]+)\)\s*$', name_lower)
    if coach_match:
        return coach_match.group(1)
    
    # Check for ALL CAPS words that look like coach/team names (4+ letters, not common words)
    # e.g., BRAULIO, MISA, EDSON in "FUTECA 2025 BRAULIO B2015"
    # Key: these are AFTER the year/age, identifying a specific team within the club
    common_words = {'ecnl', 'boys', 'girls', 'academy', 'united', 'elite', 'club', 'futbol', 
                    'soccer', 'youth', 'rush', 'surf', 'select', 'premier', 'gold', 'blue',
                    'white', 'black', 'grey', 'gray', 'green', 'maroon', 'navy', 'lafc', 'futeca',
                    'selection', 'fire', 'storm', 'rush', 'fusion'}
    
    # Look for a pattern like "2025 BRAULIO" or "2015 EDSON" - coach name after year
    coach_after_year = re.search(r'20\d{2}\s+([A-Z]{4,})\b', name)
    if coach_after_year:
        word = coach_after_year.group(1).lower()
        if word not in common_words:
            return word
    
    # Also check for mixed case names at end after age: "2014 Holohan" or "B2015 Chacon"
    name_parts = name.split()
    if len(name_parts) >= 2:
        last_part = name_parts[-1]
        # If last word is a proper name (capitalized, not a color/common word)
        if last_part[0].isupper() and last_part.lower() not in TEAM_COLORS and last_part.lower() not in common_words:
            if not re.match(r'^[BG]?\d+', last_part):  # Not an age
                return last_part.lower()
    
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

def find_best_match(queue_entry, cursor):
    """Find the best matching team for a queue entry."""
    name = queue_entry['provider_team_name']
    details = queue_entry['match_details'] or {}
    club_name = details.get('club_name', '')
    
    # Skip protected divisions - need manual review
    if has_protected_division(name):
        return None, 0.0, "protected_division"
    
    norm_name = normalize_team_name(name)
    age_group = extract_age_group(name, details)
    gender = extract_gender(name, details)
    queue_variant = extract_team_variant(name)
    
    # Build search query
    conditions = ["1=1"]
    params = []
    
    if gender:
        conditions.append("LOWER(gender) = %s")
        params.append(gender)
    
    if age_group:
        conditions.append("LOWER(age_group) = %s")
        params.append(age_group)
    
    # Search by club name first if available
    # Try to get state from club lookup
    state_code = None
    if club_name:
        cursor.execute('''
            SELECT DISTINCT state_code FROM teams 
            WHERE LOWER(club_name) = LOWER(%s) AND state_code IS NOT NULL
            LIMIT 1
        ''', (club_name,))
        state_row = cursor.fetchone()
        if state_row:
            state_code = state_row[0]
    
    if club_name:
        if state_code:
            # Match by club AND state for extra safety
            cursor.execute(f'''
                SELECT id, team_name, club_name, gender, age_group, state_code
                FROM teams
                WHERE LOWER(club_name) = LOWER(%s)
                  AND state_code = %s
                  AND {" AND ".join(conditions)}
                LIMIT 50
            ''', [club_name, state_code] + params)
        else:
            cursor.execute(f'''
                SELECT id, team_name, club_name, gender, age_group, state_code
                FROM teams
                WHERE LOWER(club_name) = LOWER(%s)
                  AND {" AND ".join(conditions)}
                LIMIT 50
            ''', [club_name] + params)
    else:
        # Fallback: search by normalized name similarity
        cursor.execute(f'''
            SELECT id, team_name, club_name, gender, age_group, state_code
            FROM teams
            WHERE {" AND ".join(conditions)}
            LIMIT 100
        ''', params)
    
    candidates = cursor.fetchall()
    
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
        team_norm = normalize_team_name(team[1])  # team_name
        team_lower = team[1].lower()
        team_variant = extract_team_variant(team[1])
        
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
        if club_name and team[2] and club_name.lower() == team[2].lower():
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
                'id': team[0],
                'team_name': team[1],
                'club_name': team[2],
                'gender': team[3],
                'age_group': team[4]
            }
    
    if best_score >= 0.7:
        return best_match, best_score, "fuzzy"
    
    return None, 0.0, "low_confidence"

def analyze_queue(limit=100, min_confidence=0.90):
    """Analyze queue entries and find matches."""
    from psycopg2.extras import RealDictCursor
    
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    search_cur = conn.cursor()
    
    # Get pending queue entries (skip recently analyzed ones that didn't match)
    cur.execute('''
        SELECT id, provider_id, provider_team_id, provider_team_name, 
               match_details, confidence_score
        FROM team_match_review_queue
        WHERE status = 'pending'
          AND (last_analyzed_at IS NULL OR last_analyzed_at < NOW() - INTERVAL '7 days')
        ORDER BY created_at
        LIMIT %s
    ''', (limit,))
    
    entries = cur.fetchall()
    
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
        
        match, score, method = find_best_match(entry, search_cur)
        
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
    analyzed_ids = [e[0] for e in entries]  # e[0] is the id
    if analyzed_ids:
        cur.execute('''
            UPDATE team_match_review_queue 
            SET last_analyzed_at = NOW()
            WHERE id = ANY(%s) AND status = 'pending'
        ''', (analyzed_ids,))
        conn.commit()
        print(f"  Marked {len(analyzed_ids)} entries as analyzed")
    
    conn.close()
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
    
    conn = get_connection()
    cur = conn.cursor()
    
    approved = 0
    failed = 0
    
    for r in candidates:
        q = r['queue_entry']
        m = r['match']
        
        try:
            if not dry_run:
                # Get provider UUID
                cur.execute('SELECT id FROM providers WHERE code = %s', (q['provider_id'],))
                provider_row = cur.fetchone()
                if not provider_row:
                    raise ValueError(f"Provider not found: {q['provider_id']}")
                provider_uuid = provider_row[0]
                
                # Cap score at 0.99 for alias table
                db_score = min(0.99, r['score'])
                
                # Create alias with correct column names
                cur.execute('''
                    INSERT INTO team_alias_map (team_id_master, provider_id, provider_team_id, 
                                                match_confidence, match_method, review_status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (provider_id, provider_team_id) DO NOTHING
                ''', (m['id'], provider_uuid, q['provider_team_id'], db_score, 'fuzzy_auto', 'approved'))
                
                # Update queue - don't update confidence_score (constraint requires 0.75-0.90)
                cur.execute('''
                    UPDATE team_match_review_queue 
                    SET status = 'approved',
                        suggested_master_team_id = %s,
                        reviewed_by = 'auto-merge-script',
                        reviewed_at = NOW()
                    WHERE id = %s
                ''', (m['id'], q['id']))
                
                conn.commit()
            
            approved += 1
            action = "Would merge" if dry_run else "Merged"
            print(f"  ✅ {action}: {q['provider_team_name']} → {m['team_name']} ({r['score']:.1%})")
            
        except Exception as e:
            failed += 1
            print(f"  ❌ Failed [{q['id']}]: {e}")
            if not dry_run:
                conn.rollback()
    
    conn.close()
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
    args = parser.parse_args()
    
    print("=" * 70)
    print("🔍 QUEUE MATCH FINDER")
    print("=" * 70)
    print(f"Analyzing up to {args.limit} queue entries...")
    print()
    
    results = analyze_queue(limit=args.limit)
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
