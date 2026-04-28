"""Pull pillar-content data for a target list of states.

For each state: total active teams, top clubs by team count, age-group breakdown,
and active leagues. Output is human-readable for drop-in use in MDX pillar drafts.
"""

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
env_local = REPO_ROOT / ".env.local"
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv(REPO_ROOT / ".env")

TARGET_STATES = ["NY", "VA", "MD"]


TOTAL_QUERY = """
SELECT t.state_code, COUNT(DISTINCT t.id) AS team_count
FROM teams t
JOIN rankings_full r ON t.team_id_master = r.team_id
WHERE t.state_code = ANY(%s)
  AND r.status = 'Active'
  AND t.is_deprecated = FALSE
GROUP BY t.state_code
ORDER BY t.state_code;
"""

CLUBS_QUERY = """
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
ORDER BY t.state_code, team_count DESC, avg_power DESC;
"""

AGE_GROUP_QUERY = """
SELECT t.state_code,
       t.age_group,
       COUNT(DISTINCT t.id) AS team_count
FROM teams t
JOIN rankings_full r ON t.team_id_master = r.team_id
WHERE t.state_code = ANY(%s)
  AND r.status = 'Active'
  AND t.is_deprecated = FALSE
  AND t.age_group IS NOT NULL
GROUP BY t.state_code, t.age_group
ORDER BY t.state_code, t.age_group;
"""


def main():
    states = sys.argv[1:] if len(sys.argv) > 1 else TARGET_STATES
    states = [s.upper() for s in states]

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    cur.execute(TOTAL_QUERY, (states,))
    totals = {row[0]: row[1] for row in cur.fetchall()}

    cur.execute(CLUBS_QUERY, (states,))
    clubs_by_state = {}
    for state, club, count, avg_p, top_p in cur.fetchall():
        clubs_by_state.setdefault(state, []).append(
            (club, count, float(avg_p), float(top_p))
        )

    cur.execute(AGE_GROUP_QUERY, (states,))
    ages_by_state = {}
    for state, age, count in cur.fetchall():
        ages_by_state.setdefault(state, []).append((age, count))

    cur.close()
    conn.close()

    for state in states:
        total = totals.get(state, 0)
        print(f"\n{'=' * 60}")
        print(f"{state} — {total:,} active teams")
        print('=' * 60)

        clubs = clubs_by_state.get(state, [])[:15]
        print(f"\nTop {len(clubs)} clubs by team count:")
        for club, count, avg_p, top_p in clubs:
            print(f"  {count:>3}t  avg={avg_p:>5.2f}  top={top_p:>5.2f}  {club}")

        ages = ages_by_state.get(state, [])
        print("\nAge group breakdown:")
        for age, count in ages:
            print(f"  {age:<6} {count:>5}")


if __name__ == "__main__":
    main()
