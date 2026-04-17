"""Pull top clubs per state for SEO meta description curation.

For each target state, returns top clubs by team count + average PowerScore.
Output is human-curated into STATE_DESCRIPTIONS at frontend/app/rankings/[region]/page.tsx.

Note: rankings_full.team_id joins to teams.team_id_master, not teams.id.
"""

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv("C:/PitchRank/.env.local")

TARGET_STATES = [
    "VA", "OR", "LA", "AL", "MN", "AR", "WA", "OH", "KY", "NC",
    "NE", "KS", "MA", "CT", "ME", "UT", "ID", "MS", "AK", "OK",
]

QUERY = """
SELECT t.state_code,
       t.club_name,
       COUNT(DISTINCT t.id) AS team_count,
       AVG(r.power_score_final)::numeric(6,2) AS avg_power,
       MAX(r.power_score_final)::numeric(6,2) AS top_power
FROM teams t
JOIN rankings_full r ON t.team_id_master = r.team_id
WHERE t.state_code = ANY(%s)
  AND r.status = 'Active'
  AND t.club_name IS NOT NULL
  AND t.club_name <> ''
  AND t.is_deprecated = FALSE
GROUP BY t.state_code, t.club_name
HAVING COUNT(DISTINCT t.id) >= 3
ORDER BY t.state_code, team_count DESC, avg_power DESC
"""


def main():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute(QUERY, (TARGET_STATES,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    by_state = {}
    for state_code, club, count, avg_p, top_p in rows:
        by_state.setdefault(state_code, []).append((club, count, float(avg_p), float(top_p)))

    for state in TARGET_STATES:
        clubs = by_state.get(state, [])[:8]
        print(f"\n=== {state} ({len(by_state.get(state, []))} clubs >=3 active teams) ===")
        if not clubs:
            print("  (no qualifying clubs)")
            continue
        for club, count, avg_p, top_p in clubs:
            print(f"  {count:>3}t  avg={avg_p:>6.2f}  top={top_p:>6.2f}  {club}")


if __name__ == "__main__":
    main()
