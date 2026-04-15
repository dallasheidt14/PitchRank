#!/usr/bin/env python3
"""
Emergency restore for rankings_full/current_rankings from ranking_history.

This is intended for outage recovery when a rankings run publishes an invalid
snapshot but ranking_history still contains the last good cohort/state ranks.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

sys.path.append(str(Path(__file__).parent.parent))

from src.rankings.constants import AGE_TO_ANCHOR


def _load_env() -> None:
    env_local = Path(".env.local")
    if env_local.exists():
        load_dotenv(env_local, override=True)
    else:
        load_dotenv()


def _anchor_for_age_group(age_group: str | None) -> float:
    if not age_group:
        return 1.0
    digits = "".join(ch for ch in str(age_group) if ch.isdigit())
    if not digits:
        return 1.0
    age = int(digits)
    if age == 18:
        age = 19
    return float(AGE_TO_ANCHOR.get(age, 1.0))


def _latest_good_snapshot_date(cur, explicit_snapshot_date: str | None) -> str:
    if explicit_snapshot_date:
        return explicit_snapshot_date

    cur.execute(
        """
        select snapshot_date::text
        from ranking_history
        where rank_in_cohort_final is not null
        group by snapshot_date
        order by snapshot_date desc
        limit 1
        """
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError("No usable ranking_history snapshot found")
    return row[0]


def _fetch_latest_good_rows(cur, snapshot_date: str):
    cur.execute(
        """
        with latest as (
            select distinct on (team_id)
                team_id,
                snapshot_date,
                created_at,
                age_group,
                gender,
                state_code,
                rank_in_cohort,
                rank_in_cohort_ml,
                rank_in_cohort_final,
                rank_in_state,
                power_score_final,
                powerscore_ml
            from ranking_history
            where snapshot_date = %s::date
              and rank_in_cohort_final is not null
              and power_score_final is not null
            order by team_id, created_at desc, id desc
        )
        select
            team_id::text,
            snapshot_date::text,
            created_at,
            age_group,
            gender,
            state_code,
            rank_in_cohort,
            rank_in_cohort_ml,
            rank_in_cohort_final,
            rank_in_state,
            power_score_final,
            powerscore_ml
        from latest
        order by team_id
        """,
        (snapshot_date,),
    )
    return cur.fetchall()


def restore(snapshot_date: str | None, execute: bool) -> int:
    _load_env()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")

    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            chosen_snapshot = _latest_good_snapshot_date(cur, snapshot_date)
            rows = _fetch_latest_good_rows(cur, chosen_snapshot)

            if not rows:
                raise RuntimeError(f"No ranking_history rows found for snapshot_date={chosen_snapshot}")

            rankings_full_rows = []
            current_rankings_rows = []
            for (
                team_id,
                _snapshot_date,
                created_at,
                age_group,
                gender,
                state_code,
                rank_in_cohort,
                rank_in_cohort_ml,
                rank_in_cohort_final,
                rank_in_state,
                power_score_final,
                powerscore_ml,
            ) in rows:
                anchor = _anchor_for_age_group(age_group)
                power_score_true = 0.0
                if power_score_final is not None and anchor > 0:
                    power_score_true = max(0.0, min(float(power_score_final) / anchor, 1.0))

                rankings_full_rows.append(
                    (
                        team_id,
                        age_group,
                        gender,
                        state_code,
                        "Active",
                        created_at,
                        created_at,
                        rank_in_cohort,
                        rank_in_cohort_ml,
                        rank_in_cohort_final,
                        rank_in_cohort_final,
                        rank_in_state,
                        float(power_score_true),
                        float(power_score_true),
                        float(power_score_final),
                        float(powerscore_ml) if powerscore_ml is not None else None,
                    )
                )
                current_rankings_rows.append(
                    (
                        team_id,
                        rank_in_cohort_final,
                        float(power_score_true),
                        rank_in_state,
                        created_at,
                    )
                )

            print(f"Snapshot date: {chosen_snapshot}")
            print(f"Rows to restore: {len(rows):,}")
            if not execute:
                print("Dry run only. Re-run with --execute to apply.")
                return len(rows)

            execute_values(
                cur,
                """
                insert into rankings_full (
                    team_id,
                    age_group,
                    gender,
                    state_code,
                    status,
                    last_game,
                    last_calculated,
                    rank_in_cohort,
                    rank_in_cohort_ml,
                    rank_in_cohort_final,
                    national_rank,
                    state_rank,
                    national_power_score,
                    power_score_true,
                    power_score_final,
                    powerscore_ml
                ) values %s
                on conflict (team_id) do update set
                    age_group = excluded.age_group,
                    gender = excluded.gender,
                    state_code = excluded.state_code,
                    status = excluded.status,
                    last_game = excluded.last_game,
                    last_calculated = excluded.last_calculated,
                    rank_in_cohort = excluded.rank_in_cohort,
                    rank_in_cohort_ml = excluded.rank_in_cohort_ml,
                    rank_in_cohort_final = excluded.rank_in_cohort_final,
                    national_rank = excluded.national_rank,
                    state_rank = excluded.state_rank,
                    national_power_score = excluded.national_power_score,
                    power_score_true = excluded.power_score_true,
                    power_score_final = excluded.power_score_final,
                    powerscore_ml = excluded.powerscore_ml
                """,
                rankings_full_rows,
                page_size=1000,
            )

            execute_values(
                cur,
                """
                insert into current_rankings (
                    team_id,
                    national_rank,
                    national_power_score,
                    state_rank,
                    last_calculated
                ) values %s
                on conflict (team_id) do update set
                    national_rank = excluded.national_rank,
                    national_power_score = excluded.national_power_score,
                    state_rank = excluded.state_rank,
                    last_calculated = excluded.last_calculated
                """,
                current_rankings_rows,
                page_size=1000,
            )

            conn.commit()
            print("Restore complete.")
            return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore rankings tables from the last good ranking_history snapshot")
    parser.add_argument("--snapshot-date", help="Snapshot date to restore (YYYY-MM-DD). Defaults to latest good snapshot.")
    parser.add_argument("--execute", action="store_true", help="Apply the restore. Without this flag, run as dry-run.")
    args = parser.parse_args()

    restore(snapshot_date=args.snapshot_date, execute=args.execute)


if __name__ == "__main__":
    main()
