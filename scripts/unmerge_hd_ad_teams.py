#!/usr/bin/env python3
"""
Un-merge teams that incorrectly have both HD and AD aliases.

HD (Higher Division) and AD (Academy Division) are DIFFERENT teams in MLS NEXT.
The FIRST alias created determines the original team's division.
"""
import os, sys, uuid, argparse
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv(Path(__file__).parent.parent / '.env')

def get_connection():
    return psycopg2.connect(os.getenv('DATABASE_URL'))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    
    conn = get_connection()
    cur = conn.cursor()
    
    # Find teams with both HD and AD, with timestamps
    cur.execute("""
        SELECT t.id, t.team_id_master, t.team_name, t.club_name, t.age_group, 
               t.gender, t.state_code, t.provider_id,
               array_agg(DISTINCT a.provider_team_id) FILTER (WHERE a.provider_team_id LIKE '%_HD%') as hd_aliases,
               array_agg(DISTINCT a.provider_team_id) FILTER (WHERE a.provider_team_id LIKE '%_AD%') as ad_aliases,
               (SELECT MIN(created_at) FROM team_alias_map 
                WHERE team_id_master = t.team_id_master AND provider_team_id LIKE '%_HD%') as hd_created,
               (SELECT MIN(created_at) FROM team_alias_map 
                WHERE team_id_master = t.team_id_master AND provider_team_id LIKE '%_AD%') as ad_created
        FROM teams t
        JOIN team_alias_map a ON t.team_id_master = a.team_id_master
        GROUP BY t.id, t.team_id_master, t.team_name, t.club_name, t.age_group, 
                 t.gender, t.state_code, t.provider_id
        HAVING bool_or(a.provider_team_id LIKE '%_HD%') AND bool_or(a.provider_team_id LIKE '%_AD%')
    """)
    
    teams = cur.fetchall()
    if args.limit:
        teams = teams[:args.limit]
    
    print(f"{'DRY RUN - ' if not args.execute else ''}UN-MERGE {len(teams)} TEAMS")
    print("=" * 70)
    
    for t in teams:
        tid, master_id, name, club, age, gender, state, prov_id, hd_aliases, ad_aliases, hd_created, ad_created = t
        
        # Which was first?
        hd_first = hd_created < ad_created if (hd_created and ad_created) else True
        
        base_name = name.replace(' HD', '').replace(' AD', '').strip()
        
        if hd_first:
            keep_name = f"{base_name} HD"
            new_name = f"{base_name} AD"
            move_aliases = ad_aliases
            first = "HD"
        else:
            keep_name = f"{base_name} AD" 
            new_name = f"{base_name} HD"
            move_aliases = hd_aliases
            first = "AD"
        
        print(f"\n{club} | {name}")
        print(f"  First created: {first} → Keep as: {keep_name}")
        print(f"  Split off new: {new_name} (aliases: {move_aliases})")
        
        if args.execute:
            new_id = str(uuid.uuid4())
            new_master = str(uuid.uuid4())
            
            # Rename original
            cur.execute("UPDATE teams SET team_name = %s WHERE id = %s", (keep_name, tid))
            
            # Create new team
            cur.execute("""
                INSERT INTO teams (id, team_id_master, team_name, club_name, age_group, gender, state_code, provider_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (new_id, new_master, new_name, club, age, gender, state, prov_id))
            
            # Move aliases
            for alias in move_aliases:
                cur.execute("UPDATE team_alias_map SET team_id_master = %s WHERE provider_team_id = %s AND team_id_master = %s",
                           (new_master, alias, master_id))
            
            # Update games
            cur.execute("UPDATE games SET home_team_master_id = %s WHERE home_provider_id = ANY(%s) AND home_team_master_id = %s",
                       (new_master, move_aliases, master_id))
            cur.execute("UPDATE games SET away_team_master_id = %s WHERE away_provider_id = ANY(%s) AND away_team_master_id = %s",
                       (new_master, move_aliases, master_id))
            
            print(f"  ✅ Done")
    
    if args.execute:
        conn.commit()
        print(f"\n✅ Un-merged {len(teams)} teams")
    else:
        print(f"\n📊 Would un-merge {len(teams)} teams. Run with --execute")
    
    conn.close()

if __name__ == '__main__':
    main()
