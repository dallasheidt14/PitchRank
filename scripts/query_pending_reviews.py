#!/usr/bin/env python3
"""
Query pending match reviews by age group, state (fuzzy), and gender.

Usage:
    python3 scripts/query_pending_reviews.py U12 CA Male
    python3 scripts/query_pending_reviews.py U14 AZ Female
    python3 scripts/query_pending_reviews.py --counts  # Show breakdown
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# State patterns for fuzzy matching on team names
STATE_PATTERNS = {
    'CA': ['Los Angeles', 'LA ', 'San Diego', 'San Jose', 'Sacramento', 'Fresno',
           'Oakland', 'Long Beach', 'Bakersfield', 'Anaheim', 'Santa ', 'Riverside',
           'Irvine', 'Chula Vista', 'Fremont', 'Huntington', 'Pasadena', 'Torrance',
           'Oceanside', 'Orange County', 'Bay Area', 'SoCal', 'NorCal', 'California',
           'Central Coast', 'Surf SC', 'Pateadores', 'Beach FC', 'Real So Cal',
           'LA Galaxy', 'LAFC', 'Albion SC', 'Legends FC', 'Strikers FC', 'Temecula',
           'Murrieta', 'Escondido', 'Carlsbad', 'Encinitas', 'Del Mar', 'La Jolla',
           'Stockton', 'Modesto', 'Visalia', 'Salinas', 'Ventura', 'Oxnard', 'Thousand Oaks'],
    'AZ': ['Phoenix', 'Arizona', 'Scottsdale', 'Tucson', 'Mesa', 'Chandler', 'Gilbert',
           'Glendale', 'Tempe', 'Peoria', 'Surprise', 'Goodyear', 'Flagstaff', 'Yuma',
           'SC del Sol', 'Sereno', 'Arsenal AZ', 'RSL AZ', 'FC Tucson', 'Kingman'],
    'TX': ['Texas', 'Houston', 'Dallas', 'Austin', 'San Antonio', 'Fort Worth', 'El Paso',
           'Arlington', 'Plano', 'Frisco', 'McKinney', 'Denton', 'Irving', 'Garland',
           'FC Dallas', 'Houston Dynamo', 'Solar SC', 'Texans SC', 'Lonestar SC'],
    'FL': ['Florida', 'Miami', 'Orlando', 'Tampa', 'Jacksonville', 'Fort Lauderdale',
           'Boca Raton', 'West Palm', 'Naples', 'Sarasota', 'Clearwater', 'Kissimmee',
           'Weston FC', 'Florida Elite', 'IMG Academy'],
    'NY': ['New York', 'Brooklyn', 'Manhattan', 'Queens', 'Bronx', 'Long Island',
           'Westchester', 'Buffalo', 'Rochester', 'Syracuse', 'Albany', 'Poughkeepsie',
           'NYSC', 'NYC FC', 'Red Bulls'],
    'NJ': ['New Jersey', 'Newark', 'Jersey City', 'Trenton', 'Edison', 'Princeton',
           'Cherry Hill', 'Morristown', 'PDA', 'TSF Academy', 'FC Delco'],
}

def get_counts(cur):
    """Show breakdown by age/gender."""
    cur.execute("""
        SELECT 
            UPPER(match_details->>'age_group') as age,
            match_details->>'gender' as gender,
            COUNT(*)
        FROM team_match_review_queue 
        WHERE status = 'pending'
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)
    print("\n=== Pending Reviews by Age/Gender ===")
    for row in cur.fetchall():
        print(f"  {row[0] or '?':4} {row[1] or '?':8}: {row[2]:5}")

def query_reviews(cur, age_group, state, gender, limit=50):
    """Query pending reviews with filters."""
    
    # Normalize inputs
    age_group = age_group.upper()
    state = state.upper()
    gender_filter = "('Male', 'Boys')" if gender.lower() in ('male', 'boys', 'm', 'b') else "('Female', 'Girls')"
    
    # Build state pattern clause
    patterns = STATE_PATTERNS.get(state, [state])  # Fall back to literal if unknown state
    pattern_clauses = [f"provider_team_name ILIKE '%{p}%'" for p in patterns]
    state_clause = ' OR '.join(pattern_clauses)
    
    query = f"""
        SELECT 
            provider_team_name,
            match_details->>'club_name' as club,
            confidence_score,
            id
        FROM team_match_review_queue 
        WHERE status = 'pending'
        AND UPPER(match_details->>'age_group') = '{age_group}'
        AND match_details->>'gender' IN {gender_filter}
        AND ({state_clause})
        ORDER BY provider_team_name
        LIMIT {limit}
    """
    
    cur.execute(query)
    rows = cur.fetchall()
    
    print(f"\n=== {age_group} {state} {gender} — {len(rows)} results (limit {limit}) ===\n")
    for i, row in enumerate(rows, 1):
        print(f"{i:3}. {row[0]}")
        if row[1]:
            print(f"     Club: {row[1]}")
    
    return rows

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    
    if sys.argv[1] == '--counts':
        get_counts(cur)
    elif len(sys.argv) >= 4:
        age_group = sys.argv[1]  # e.g., U12
        state = sys.argv[2]      # e.g., CA
        gender = sys.argv[3]     # e.g., Male
        limit = int(sys.argv[4]) if len(sys.argv) > 4 else 50
        query_reviews(cur, age_group, state, gender, limit)
    else:
        print("Usage: python3 query_pending_reviews.py U12 CA Male [limit]")
        print("       python3 query_pending_reviews.py --counts")
    
    conn.close()

if __name__ == '__main__':
    main()
