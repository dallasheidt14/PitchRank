"""
Audit club names in the database using the club normalizer.

This script:
1. Fetches all club names from the database
2. Normalizes them using the club normalizer
3. Identifies potential issues:
   - Multiple club names that normalize to the same club_id (potential duplicates)
   - Clubs with low confidence matches
   - Clubs that need review
   - Inconsistencies in naming
   - Acronyms/abbreviations vs full names
   - Missing/inconsistent FC/SC suffixes
   - "Academy" ambiguity
   - Missing brand tokens (SURF, PREMIER, UNITED, etc.)
   - Geography inconsistencies
   - Formatting/truncation artifacts
"""
import os
import sys
import re
from collections import defaultdict
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from supabase import create_client
from src.utils.club_normalizer import (
    normalize_to_club,
    group_by_club,
    get_matches_needing_review,
    normalize_club_name,
)

# Load environment
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)


# Common brand tokens that should be preserved
BRAND_TOKENS = {'surf', 'premier', 'united', 'soccer', 'academy', 'fc', 'sc', 'sa', 'ac', 'cf'}

# Common acronym patterns (all caps, 2-6 letters)
ACRONYM_PATTERN = re.compile(r'\b[A-Z]{2,6}\b')


def detect_acronym_vs_full_name(club_name: str, normalized: str) -> bool:
    """Detect if club name is an acronym that might match a full name"""
    # Check if original has acronym pattern
    has_acronym = bool(ACRONYM_PATTERN.search(club_name))
    # Check if normalized version is longer (suggesting expansion)
    normalized_words = len(normalized.split())
    original_words = len(club_name.split())
    return has_acronym and normalized_words > original_words


def detect_fc_sc_inconsistency(variations: list) -> bool:
    """Detect if variations differ only by FC/SC suffix"""
    normalized_vars = []
    for var in variations:
        # Normalize without stripping FC/SC
        norm = normalize_club_name(var, strip_suffixes=False)
        # Remove FC/SC for comparison
        norm_no_suffix = re.sub(r'\s+(fc|sc|sa|ac|cf|afc)\s*$', '', norm, flags=re.IGNORECASE)
        normalized_vars.append(norm_no_suffix)
    
    # If all normalized versions are the same, it's just FC/SC inconsistency
    if len(set(normalized_vars)) == 1 and len(variations) > 1:
        # Check if some have FC/SC and some don't
        has_suffix = any(re.search(r'\b(fc|sc|sa|ac|cf|afc)\b', v, re.IGNORECASE) for v in variations)
        no_suffix = any(not re.search(r'\b(fc|sc|sa|ac|cf|afc)\b', v, re.IGNORECASE) for v in variations)
        return has_suffix and no_suffix
    return False


def detect_academy_ambiguity(variations: list) -> dict:
    """Detect Academy ambiguity - sometimes added, sometimes removed"""
    results = {
        'academy_added': [],  # Variations where academy was added
        'academy_removed': [],  # Variations where academy was removed
        'has_academy': [],  # Variations that have academy
        'no_academy': []  # Variations without academy
    }
    
    for var in variations:
        has_academy = bool(re.search(r'\bacademy\b', var, re.IGNORECASE))
        norm = normalize_club_name(var)
        norm_has_academy = 'academy' in norm.lower()
        
        if has_academy:
            results['has_academy'].append(var)
        else:
            results['no_academy'].append(var)
        
        # Check if academy was added in normalization
        if not has_academy and norm_has_academy:
            results['academy_added'].append(var)
        # Check if academy was removed in normalization
        elif has_academy and not norm_has_academy:
            results['academy_removed'].append(var)
    
    return results


def detect_missing_brand_tokens(variations: list) -> dict:
    """Detect missing brand tokens (SURF, PREMIER, UNITED, SOCCER)"""
    brand_issues = defaultdict(list)
    
    # Get normalized version (should have brand tokens)
    normalized_samples = [normalize_club_name(v) for v in variations[:5]]
    normalized_combined = ' '.join(normalized_samples).lower()
    
    # Check which brand tokens appear in normalized but might be missing in originals
    for brand in BRAND_TOKENS:
        if brand in normalized_combined:
            # Find variations missing this brand token
            missing = [v for v in variations if brand not in v.lower()]
            if missing:
                brand_issues[brand.upper()] = missing
    
    return dict(brand_issues)


def detect_geography_inconsistencies(variations: list) -> dict:
    """Detect geography inconsistencies (city/state sometimes included)"""
    geo_issues = {
        'has_geography': [],
        'no_geography': [],
        'abbreviation_expansions': []  # PHX -> Phoenix, LA -> Los Angeles
    }
    
    # Common geography patterns
    state_codes = {'az', 'ca', 'tx', 'ny', 'fl', 'il', 'pa', 'oh', 'mi', 'nc', 'ga', 'nj', 'va', 'wa', 'ma', 'tn', 'in', 'mo', 'md', 'wi', 'co', 'mn', 'sc', 'al', 'la', 'ky', 'or', 'ok', 'ct', 'ia', 'ar', 'ut', 'nv', 'ms', 'ks', 'nm', 'ne', 'wv', 'id', 'hi', 'nh', 'me', 'mt', 'ri', 'de', 'sd', 'nd', 'ak', 'dc', 'vt', 'wy'}
    
    city_abbrevs = {
        'phx': 'phoenix', 'la': 'los angeles', 'nyc': 'new york city',
        'sf': 'san francisco', 'sd': 'san diego', 'kc': 'kansas city',
        'atl': 'atlanta', 'chi': 'chicago', 'dal': 'dallas', 'hou': 'houston'
    }
    
    for var in variations:
        var_lower = var.lower()
        has_state = any(f' {code}' in var_lower or f'-{code}' in var_lower for code in state_codes)
        has_city_abbrev = any(abbrev in var_lower for abbrev in city_abbrevs.keys())
        has_full_city = any(full in var_lower for full in city_abbrevs.values())
        
        if has_state or has_full_city:
            geo_issues['has_geography'].append(var)
        elif not has_state and not has_full_city:
            geo_issues['no_geography'].append(var)
        
        # Check for abbreviation expansions
        for abbrev, full in city_abbrevs.items():
            if abbrev in var_lower:
                geo_issues['abbreviation_expansions'].append((var, abbrev, full))
    
    return geo_issues


def detect_formatting_artifacts(club_name: str) -> list:
    """Detect formatting/truncation artifacts"""
    issues = []
    
    # Trailing ellipsis
    if club_name.endswith('...') or '...' in club_name:
        issues.append('trailing_ellipsis')
    
    # Parentheses/brackets differences
    if '(' in club_name or ')' in club_name or '[' in club_name or ']' in club_name:
        issues.append('parentheses_brackets')
    
    # Inconsistent separators
    if '-' in club_name and '/' in club_name:
        issues.append('mixed_separators')
    if '_' in club_name:
        issues.append('underscore_separator')
    
    # Multiple spaces
    if '  ' in club_name:
        issues.append('multiple_spaces')
    
    # Truncation patterns (U... or similar)
    if re.search(r'\b[uU]\d*\.\.\.', club_name):
        issues.append('truncation_pattern')
    
    return issues


def fetch_all_club_names():
    """Fetch all unique club names from the database"""
    print("Fetching club names from database...")
    
    all_clubs = []
    page_size = 1000
    offset = 0
    
    while True:
        result = supabase.table('teams').select(
            'club_name, team_name'
        ).not_.is_('club_name', 'null').range(offset, offset + page_size - 1).execute()
        
        if not result.data:
            break
        
        for team in result.data:
            club_name = team.get('club_name', '').strip()
            if club_name:
                all_clubs.append(club_name)
        
        offset += page_size
        
        if len(result.data) < page_size:
            break
    
    # Also get club names from team_name if club_name is missing
    offset = 0
    while True:
        result = supabase.table('teams').select(
            'team_name'
        ).is_('club_name', 'null').range(offset, offset + page_size - 1).execute()
        
        if not result.data:
            break
        
        for team in result.data:
            team_name = team.get('team_name', '').strip()
            if team_name:
                # Try to extract club name from team name
                # This is a simple heuristic - you might want to improve this
                all_clubs.append(team_name)
        
        offset += page_size
        
        if len(result.data) < page_size:
            break
    
    # Get unique club names
    unique_clubs = list(set(all_clubs))
    print(f"Found {len(unique_clubs)} unique club names\n")
    
    return unique_clubs


def audit_club_names(dry_run=True):
    """Run audit on club names"""
    print("=" * 80)
    print("CLUB NAMES AUDIT")
    print("=" * 80)
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}\n")
    
    # Fetch all club names
    club_names = fetch_all_club_names()
    
    if not club_names:
        print("No club names found in database")
        return
    
    # Normalize all club names
    print("Normalizing club names...")
    normalized_results = []
    for club_name in club_names:
        result = normalize_to_club(club_name)
        normalized_results.append((club_name, result))
    
    print(f"Normalized {len(normalized_results)} club names\n")
    
    # Group by club_id to find duplicates/variations
    print("=" * 80)
    print("1. CLUBS WITH MULTIPLE VARIATIONS")
    print("=" * 80)
    groups = group_by_club(club_names)
    
    # Find groups with multiple variations
    multi_variation_clubs = {k: v for k, v in groups.items() if len(v) > 1}
    
    if multi_variation_clubs:
        print(f"\nFound {len(multi_variation_clubs)} clubs with multiple name variations:\n")
        
        # Sort by number of variations (descending)
        sorted_clubs = sorted(multi_variation_clubs.items(), key=lambda x: len(x[1]), reverse=True)
        
        # Show top 20
        for i, (club_id, variations) in enumerate(sorted_clubs[:20], 1):
            # Get the normalized name for this club_id
            sample_result = normalize_to_club(variations[0])
            print(f"{i}. {sample_result.club_norm} (club_id: {club_id})")
            print(f"   Variations ({len(variations)}):")
            for var in sorted(variations)[:10]:  # Show first 10 variations
                print(f"     - {var}")
            if len(variations) > 10:
                print(f"     ... and {len(variations) - 10} more")
            print()
    else:
        print("No clubs with multiple variations found\n")
    
    # Find clubs needing review
    print("=" * 80)
    print("2. CLUBS NEEDING REVIEW")
    print("=" * 80)
    needs_review = get_matches_needing_review(club_names)
    
    if needs_review:
        print(f"\nFound {len(needs_review)} clubs needing review:\n")
        
        # Group by reason
        low_confidence = [r for r in needs_review if r.confidence < 0.9]
        not_canonical = [r for r in needs_review if not r.matched_canonical]
        
        print(f"  - Low confidence matches (< 0.9): {len(low_confidence)}")
        print(f"  - Not matched to canonical club: {len(not_canonical)}")
        print()
        
        # Show low confidence matches
        if low_confidence:
            print("Low confidence matches:")
            for i, result in enumerate(sorted(low_confidence, key=lambda x: x.confidence)[:20], 1):
                print(f"  {i}. '{result.original}'")
                print(f"     → {result.club_norm} (confidence: {result.confidence:.2f})")
                print()
        
        # Show some non-canonical matches
        if not_canonical:
            print("\nNon-canonical clubs (not in registry):")
            # Group by club_norm
            non_canonical_groups = defaultdict(list)
            for result in not_canonical:
                non_canonical_groups[result.club_norm].append(result.original)
            
            for i, (club_norm, originals) in enumerate(sorted(non_canonical_groups.items())[:20], 1):
                print(f"  {i}. {club_norm}")
                print(f"     Examples: {', '.join(originals[:5])}")
                if len(originals) > 5:
                    print(f"     ... and {len(originals) - 5} more")
                print()
    else:
        print("No clubs needing review\n")
    
    # Statistics
    print("=" * 80)
    print("3. STATISTICS")
    print("=" * 80)
    
    canonical_matches = sum(1 for _, result in normalized_results if result.matched_canonical)
    high_confidence = sum(1 for _, result in normalized_results if result.confidence >= 0.9)
    medium_confidence = sum(1 for _, result in normalized_results if 0.7 <= result.confidence < 0.9)
    low_confidence_count = sum(1 for _, result in normalized_results if result.confidence < 0.7)
    
    print(f"\nTotal unique club names: {len(club_names)}")
    print(f"Matched to canonical clubs: {canonical_matches} ({canonical_matches/len(club_names)*100:.1f}%)")
    print(f"High confidence (≥0.9): {high_confidence} ({high_confidence/len(club_names)*100:.1f}%)")
    print(f"Medium confidence (0.7-0.9): {medium_confidence} ({medium_confidence/len(club_names)*100:.1f}%)")
    print(f"Low confidence (<0.7): {low_confidence_count} ({low_confidence_count/len(club_names)*100:.1f}%)")
    print(f"Clubs with multiple variations: {len(multi_variation_clubs)}")
    print()
    
    # Detailed issue analysis
    print("=" * 80)
    print("4. DETAILED ISSUE ANALYSIS")
    print("=" * 80)
    
    # 1. Acronyms vs Full Names
    print("\n4.1 ACRONYMS / ABBREVIATIONS vs FULL NAMES")
    print("-" * 80)
    acronym_issues = []
    for club_name, result in normalized_results:
        if detect_acronym_vs_full_name(club_name, result.club_norm):
            acronym_issues.append((club_name, result.club_norm))
    
    if acronym_issues:
        print(f"\nFound {len(acronym_issues)} potential acronym → full name mappings:")
        for i, (original, normalized) in enumerate(acronym_issues[:20], 1):
            print(f"  {i}. {original} → {normalized}")
        if len(acronym_issues) > 20:
            print(f"  ... and {len(acronym_issues) - 20} more")
    else:
        print("\nNo obvious acronym issues detected")
    
    # 2. FC/SC Suffix Inconsistencies
    print("\n4.2 MISSING / INCONSISTENT FC/SC SUFFIXES")
    print("-" * 80)
    fc_sc_issues = []
    for club_id, variations in multi_variation_clubs.items():
        if detect_fc_sc_inconsistency(variations):
            fc_sc_issues.append((club_id, variations))
    
    if fc_sc_issues:
        print(f"\nFound {len(fc_sc_issues)} clubs with FC/SC suffix inconsistencies:")
        for i, (club_id, variations) in enumerate(fc_sc_issues[:15], 1):
            sample_result = normalize_to_club(variations[0])
            print(f"  {i}. {sample_result.club_norm} ({club_id})")
            print(f"     Examples: {', '.join(variations[:5])}")
            if len(variations) > 5:
                print(f"     ... and {len(variations) - 5} more")
        if len(fc_sc_issues) > 15:
            print(f"  ... and {len(fc_sc_issues) - 15} more clubs")
    else:
        print("\nNo FC/SC suffix inconsistencies detected")
    
    # 3. Academy Ambiguity
    print("\n4.3 ACADEMY AMBIGUITY")
    print("-" * 80)
    academy_issues_count = 0
    academy_examples = []
    for club_id, variations in list(multi_variation_clubs.items())[:50]:  # Check top 50
        academy_info = detect_academy_ambiguity(variations)
        if academy_info['academy_added'] or academy_info['academy_removed']:
            academy_issues_count += 1
            if len(academy_examples) < 10:
                sample_result = normalize_to_club(variations[0])
                academy_examples.append((sample_result.club_norm, academy_info))
    
    if academy_issues_count > 0:
        print(f"\nFound {academy_issues_count} clubs with Academy ambiguity:")
        for i, (club_norm, info) in enumerate(academy_examples[:10], 1):
            print(f"  {i}. {club_norm}")
            if info['academy_added']:
                print(f"     Academy ADDED in normalization: {len(info['academy_added'])} variations")
            if info['academy_removed']:
                print(f"     Academy REMOVED in normalization: {len(info['academy_removed'])} variations")
            if info['has_academy'] and info['no_academy']:
                print(f"     Mixed: {len(info['has_academy'])} with Academy, {len(info['no_academy'])} without")
    else:
        print("\nNo Academy ambiguity detected")
    
    # 4. Missing Brand Tokens
    print("\n4.4 MISSING BRAND TOKENS (SURF, PREMIER, UNITED, SOCCER)")
    print("-" * 80)
    brand_token_issues = defaultdict(int)
    brand_examples = defaultdict(list)
    for club_id, variations in list(multi_variation_clubs.items())[:50]:  # Check top 50
        missing_brands = detect_missing_brand_tokens(variations)
        for brand, missing_vars in missing_brands.items():
            brand_token_issues[brand] += len(missing_vars)
            if len(brand_examples[brand]) < 5:
                sample_result = normalize_to_club(variations[0])
                brand_examples[brand].append((sample_result.club_norm, missing_vars[:3]))
    
    if brand_token_issues:
        print(f"\nFound missing brand tokens:")
        for brand, count in sorted(brand_token_issues.items(), key=lambda x: x[1], reverse=True):
            print(f"  - {brand}: {count} variations missing this token")
            if brand in brand_examples:
                print(f"    Examples:")
                for club_norm, examples in brand_examples[brand]:
                    print(f"      {club_norm}: {', '.join(examples)}")
    else:
        print("\nNo missing brand token issues detected")
    
    # 5. Geography Inconsistencies
    print("\n4.5 GEOGRAPHY INCONSISTENCIES")
    print("-" * 80)
    geo_issues_count = 0
    geo_examples = []
    for club_id, variations in list(multi_variation_clubs.items())[:50]:  # Check top 50
        geo_info = detect_geography_inconsistencies(variations)
        if geo_info['has_geography'] and geo_info['no_geography']:
            geo_issues_count += 1
            if len(geo_examples) < 10:
                sample_result = normalize_to_club(variations[0])
                geo_examples.append((sample_result.club_norm, geo_info))
    
    if geo_issues_count > 0:
        print(f"\nFound {geo_issues_count} clubs with geography inconsistencies:")
        for i, (club_norm, info) in enumerate(geo_examples[:10], 1):
            print(f"  {i}. {club_norm}")
            print(f"     With geography: {len(info['has_geography'])} variations")
            print(f"     Without geography: {len(info['no_geography'])} variations")
            if info['abbreviation_expansions']:
                print(f"     Abbreviation expansions: {len(info['abbreviation_expansions'])}")
    else:
        print("\nNo geography inconsistencies detected")
    
    # 6. Formatting Artifacts
    print("\n4.6 FORMATTING / TRUNCATION ARTIFACTS")
    print("-" * 80)
    formatting_issues = defaultdict(list)
    for club_name in club_names:
        artifacts = detect_formatting_artifacts(club_name)
        for artifact in artifacts:
            formatting_issues[artifact].append(club_name)
    
    if formatting_issues:
        print(f"\nFound formatting artifacts:")
        for artifact_type, examples in sorted(formatting_issues.items(), key=lambda x: len(x[1]), reverse=True):
            print(f"  - {artifact_type}: {len(examples)} occurrences")
            if len(examples) <= 5:
                for ex in examples:
                    print(f"    • {ex}")
            else:
                for ex in examples[:5]:
                    print(f"    • {ex}")
                print(f"    ... and {len(examples) - 5} more")
    else:
        print("\nNo formatting artifacts detected")
    
    # Summary
    print("\n" + "=" * 80)
    print("5. SUMMARY")
    print("=" * 80)
    
    issues = []
    
    if multi_variation_clubs:
        total_variations = sum(len(v) for v in multi_variation_clubs.values())
        issues.append(f"  - {len(multi_variation_clubs)} clubs have {total_variations} total variations")
    
    if acronym_issues:
        issues.append(f"  - {len(acronym_issues)} potential acronym → full name mappings")
    
    if fc_sc_issues:
        issues.append(f"  - {len(fc_sc_issues)} clubs with FC/SC suffix inconsistencies")
    
    if academy_issues_count > 0:
        issues.append(f"  - {academy_issues_count} clubs with Academy ambiguity")
    
    if brand_token_issues:
        total_brand_issues = sum(brand_token_issues.values())
        issues.append(f"  - {total_brand_issues} variations missing brand tokens")
    
    if geo_issues_count > 0:
        issues.append(f"  - {geo_issues_count} clubs with geography inconsistencies")
    
    if formatting_issues:
        total_formatting = sum(len(v) for v in formatting_issues.values())
        issues.append(f"  - {total_formatting} club names with formatting artifacts")
    
    if low_confidence:
        issues.append(f"  - {len(low_confidence)} clubs have low confidence matches")
    
    if not_canonical:
        issues.append(f"  - {len(not_canonical)} clubs are not in canonical registry")
    
    if issues:
        print("\nPotential issues found:")
        for issue in issues:
            print(issue)
    else:
        print("\nNo major issues found!")
    
    print("\n" + "=" * 80)
    print("AUDIT COMPLETE")
    print("=" * 80)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Audit club names in the database')
    parser.add_argument(
        '--live',
        action='store_true',
        help='Run in live mode (default is dry run)'
    )
    
    args = parser.parse_args()
    
    audit_club_names(dry_run=not args.live)

