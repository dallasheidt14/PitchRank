#!/usr/bin/env python3
"""
Audit the cohort-changing rewrites that normalize_team_names.py would perform.

The in-flight change to `normalize_team_names.normalize_team_name` renders a
team's age token FROM `teams.age_group` instead of from the name's own digits.
Most of those rewrites are cosmetic — the name already agreed with the column and
only its format changes. Some are not: the column names a different cohort than
the name does, so the rewrite changes what the name MEANS. Once written there is
nothing left to check it against, because the name was the only other record of
the team's age.

This script lists every one of those, with the evidence needed to decide which
side is right, and assigns each a verdict:

  club_fragment_eaten   The token about to be replaced is not an age at all —
                        it is a club founding year (1776 United, FC Impact 1854).
                        parse_age_gender has no lower bound on its bare-4-digit
                        branch. Always a bug; never write these.
  duplicate_age_token   The rewrite leaves two age tokens in the name.
  unusable_column       age_group is outside U6-U19, so no label can be rendered.
  band_column_conflict  The name states a two-year band, so it names its own
                        cohort and the rewrite takes the band's answer, not the
                        column's. These rows are therefore SAFE to write — they
                        are listed because the column disagrees, which makes
                        teams.age_group the side worth correcting.
  name_ahead            Column names a YOUNGER cohort than the name's birth year
                        allows. A birth year cannot age backwards, so the column
                        is the suspect side.
  wild_delta            The two sides differ by 3+ cohorts. One is corrupt.
  birth_year_overwritten  Name carries a birth year, column disagrees. The
                        rewrite DELETES a self-checking fact and substitutes one
                        that cannot be re-derived. The rows that need judgement.
  stale_u_age           Name carries a U-age from an earlier season and the
                        column has since rolled. The column is right and nothing
                        verifiable is lost.

Reads only. Makes no DB writes.
"""

from __future__ import annotations

import argparse
import collections
import csv
import os
import sys
from datetime import datetime
from typing import Optional

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "scripts"))

# The audit has to see the same env as the job it audits, and a worktree carries
# no .env of its own, so fall back to the main checkout's.
for _base in (_REPO, r"C:\PitchRank"):
    load_dotenv(os.path.join(_base, ".env.local"))
    load_dotenv(os.path.join(_base, ".env"))

from normalize_team_names import _cohort_label, _resolve_band, normalize_team_name  # noqa: E402

from src.utils.team_utils import CURRENT_YEAR, calculate_age_group_from_birth_year  # noqa: E402

# A 4-digit token is only a plausible birth year for a cohort that still plays.
# U19 is the oldest tracked cohort, so anything older than its birth year is a
# club founding year, an address, or a season label — not an age.
OLDEST_PLAUSIBLE_BIRTH_YEAR = CURRENT_YEAR - 19
YOUNGEST_PLAUSIBLE_BIRTH_YEAR = CURRENT_YEAR

def _has_band(name: str) -> bool:
    """Whether the raw name states a two-year band.

    Asks the normalizer rather than re-deriving it: the audit's job is to report
    what the rewrite will do, so a second band pattern here would eventually
    disagree with the one that does the rewriting.
    """
    return _resolve_band(name)[1] is not None


def _is_age_token(token: str) -> bool:
    """True for a normalizer-emitted age token: U## or a 4-digit year."""
    if not token:
        return False
    if token.startswith("U") and token[1:].isdigit() and 1 <= len(token[1:]) <= 2:
        return True
    return token.isdigit() and len(token) == 4


def _age_tokens(name: str) -> list:
    return [t for t in name.split() if _is_age_token(t)]


def _token_cohort(token: Optional[str]) -> Optional[str]:
    """The U-age a name's age token claims, under the current season."""
    if not token:
        return None
    if token.startswith("U"):
        age = int(token[1:])
        if age == 18:  # folded into U19, mirroring calculate_age_group_from_birth_year
            age = 19
        return f"U{age}"
    return calculate_age_group_from_birth_year(int(token))


def _cohort_num(label: Optional[str]) -> Optional[int]:
    return int(label[1:]) if label else None


def classify(row: dict) -> str:
    """Assign the verdict. Order matters — the first matching rule wins, and the
    bug classes come first so a broken rewrite is never filed as a judgement call.
    """
    if row["proposed_name"] == row["current_name"]:
        return "no_change"
    if row["age_group_column"] and not row["column_label"]:
        return "unusable_column"
    if row["name_token_kind"] == "birth_year" and not row["replaced_token_plausible"]:
        return "club_fragment_eaten"
    if row["duplicate_introduced"]:
        return "duplicate_age_token"

    delta = row["delta"]
    if delta is None or delta == 0:
        return "safe_format_only"
    # Ahead of the per-team classes deliberately: a band resolves its own cohort
    # from both of its birth years, so the disagreement here is the column's, and
    # none of the per-team questions below apply to it.
    if row["name_is_band"]:
        return "band_column_conflict"
    if abs(delta) >= 3:
        return "wild_delta"
    if row["name_token_kind"] == "birth_year":
        # A birth year is a fixed fact; a column younger than it is impossible.
        return "name_ahead" if delta < 0 else "birth_year_overwritten"
    return "stale_u_age" if delta > 0 else "name_ahead"


def load_teams(cur, include_deprecated: bool) -> list:
    where = "" if include_deprecated else "WHERE NOT is_deprecated"
    cur.execute(
        f"""
        SELECT t.id, t.team_id_master, t.team_name, t.club_name, t.team_name_original,
               t.age_group, t.birth_year, t.gender, t.state_code, t.league, t.distinction,
               t.is_deprecated, t.created_at, t.updated_at, p.code
        FROM teams t
        LEFT JOIN providers p ON p.id = t.provider_id
        {where}
        """
    )
    return cur.fetchall()


def build_rows(teams: list) -> list:
    """Run both normalizers over every team and describe the difference."""
    rows = []
    for (
        tid,
        master,
        name,
        club,
        original,
        age_group,
        birth_year,
        gender,
        state,
        league,
        distinction,
        deprecated,
        created,
        updated,
        provider,
    ) in teams:
        if not name:
            continue

        shipped = normalize_team_name(name, club)
        proposed = normalize_team_name(name, club, age_group)

        # The token the name itself carries is whatever the SHIPPED normalizer
        # emits — that path never consults the column, so it reports the name's
        # own claim rather than the one about to be written over it.
        shipped_tokens = _age_tokens(shipped)
        name_token = shipped_tokens[0] if shipped_tokens else None
        name_cohort = _token_cohort(name_token)
        column_label = _cohort_label(age_group)

        name_num, col_num = _cohort_num(name_cohort), _cohort_num(column_label)
        delta = col_num - name_num if (name_num and col_num) else None

        plausible = True
        kind = None
        if name_token:
            if name_token.startswith("U"):
                kind = "u_age"
            else:
                kind = "birth_year"
                plausible = (
                    OLDEST_PLAUSIBLE_BIRTH_YEAR <= int(name_token) <= YOUNGEST_PLAUSIBLE_BIRTH_YEAR
                )

        row = {
            "team_id": str(tid),
            "team_id_master": str(master) if master else "",
            "current_name": name,
            "proposed_name": proposed,
            "shipped_name": shipped,
            "name_age_token": name_token or "",
            "name_token_kind": kind or "",
            "name_implied_cohort": name_cohort or "",
            "age_group_column": age_group or "",
            "column_label": column_label or "",
            "delta": delta,
            "replaced_token_plausible": plausible,
            "name_is_band": _has_band(name),
            # A name that already carried two age tokens is not this change's
            # doing; only a duplicate the rewrite CREATES is a defect in it.
            "duplicate_introduced": len(_age_tokens(proposed)) > 1 and len(shipped_tokens) <= 1,
            "duplicate_pre_existing": len(shipped_tokens) > 1,
            "residual_age_tokens": " ".join(_age_tokens(proposed)[1:]),
            "birth_year_column": birth_year if birth_year is not None else "",
            "team_name_original": original or "",
            "club_name": club or "",
            "state_code": state or "",
            "gender": gender or "",
            "league": league or "",
            "distinction": distinction or "",
            "provider": provider or "",
            "is_deprecated": bool(deprecated),
            "created_at": created.date().isoformat() if created else "",
            "updated_at": updated.date().isoformat() if updated else "",
        }
        row["verdict"] = classify(row)
        rows.append(row)
    return rows


def attach_rollover(cur, rows: list) -> None:
    """What the column said before the Aug 2026 rollover moved every team up one."""
    cur.execute("SELECT to_regclass('public.teams_age_rollover_backup_2026')")
    if cur.fetchone()[0] is None:
        for row in rows:
            row["age_group_pre_rollover"] = ""
            row["rolled_once"] = ""
        return

    cur.execute("SELECT team_id_master, age_group FROM teams_age_rollover_backup_2026")
    prior = {str(m): a for m, a in cur.fetchall()}
    for row in rows:
        before = prior.get(row["team_id_master"], "")
        row["age_group_pre_rollover"] = before or ""
        now_num, before_num = _cohort_num(row["column_label"]), _cohort_num(_cohort_label(before))
        row["rolled_once"] = "" if not (now_num and before_num) else str(now_num == before_num + 1)


def attach_game_evidence(cur, rows: list, all_cohorts: dict, window_days: int) -> None:
    """Who the team actually played, which is the one signal independent of both
    the name and the column: an opponent's own NAME states a birth year that no
    hygiene job derived from this team's row.
    """
    targets = [r["team_id_master"] for r in rows if r["team_id_master"]]
    cur.execute("CREATE TEMP TABLE audit_targets (master uuid PRIMARY KEY) ON COMMIT DROP")
    cur.execute(
        "CREATE TEMP TABLE audit_cohorts"
        " (master uuid PRIMARY KEY, name_cohort text, col_cohort text, clean_cohort text)"
        " ON COMMIT DROP"
    )

    execute_values(
        cur,
        "INSERT INTO audit_targets (master) VALUES %s",
        [(m,) for m in dict.fromkeys(targets)],
        page_size=5000,
    )
    execute_values(
        cur,
        "INSERT INTO audit_cohorts (master, name_cohort, col_cohort, clean_cohort) VALUES %s",
        [(m, n, c, k) for m, (n, c, k) in all_cohorts.items()],
        page_size=5000,
    )

    cur.execute(
        f"""
        WITH sides AS (
            SELECT home_team_master_id AS tm, away_team_master_id AS opp,
                   game_date, division_name
            FROM games
            WHERE NOT COALESCE(is_excluded, false)
              AND game_date >= current_date - {window_days}
            UNION ALL
            SELECT away_team_master_id, home_team_master_id, game_date, division_name
            FROM games
            WHERE NOT COALESCE(is_excluded, false)
              AND game_date >= current_date - {window_days}
        )
        SELECT s.tm, count(*), max(s.game_date),
               mode() WITHIN GROUP (ORDER BY s.division_name)
        FROM sides s
        JOIN audit_targets t ON t.master = s.tm
        GROUP BY s.tm
        """
    )
    totals = {str(tm): (n, last, div) for tm, n, last, div in cur.fetchall()}

    cur.execute(
        f"""
        WITH sides AS (
            SELECT home_team_master_id AS tm, away_team_master_id AS opp FROM games
            WHERE NOT COALESCE(is_excluded, false) AND game_date >= current_date - {window_days}
            UNION ALL
            SELECT away_team_master_id, home_team_master_id FROM games
            WHERE NOT COALESCE(is_excluded, false) AND game_date >= current_date - {window_days}
        )
        SELECT s.tm, o.name_cohort, o.col_cohort, o.clean_cohort, count(*)
        FROM sides s
        JOIN audit_targets t ON t.master = s.tm
        JOIN audit_cohorts o ON o.master = s.opp
        GROUP BY s.tm, o.name_cohort, o.col_cohort, o.clean_cohort
        """
    )
    by_name = collections.defaultdict(collections.Counter)
    by_col = collections.defaultdict(collections.Counter)
    by_clean = collections.defaultdict(collections.Counter)
    for tm, name_cohort, col_cohort, clean_cohort, n in cur.fetchall():
        if name_cohort:
            by_name[str(tm)][name_cohort] += n
        if col_cohort:
            by_col[str(tm)][col_cohort] += n
        if clean_cohort:
            by_clean[str(tm)][clean_cohort] += n

    def _modal(counter):
        if not counter:
            return "", ""
        label, n = counter.most_common(1)[0]
        return label, f"{n / sum(counter.values()):.2f}"

    for row in rows:
        master = row["team_id_master"]
        n, last, division = totals.get(master, (0, None, None))
        row["games_in_window"] = n
        row["last_game"] = last.isoformat() if last else ""
        row["modal_division_name"] = division or ""
        row["opp_modal_name_cohort"], row["opp_modal_name_share"] = _modal(by_name.get(master))
        row["opp_modal_column_cohort"], row["opp_modal_column_share"] = _modal(by_col.get(master))
        clean = by_clean.get(master)
        row["opp_clean_cohort"], row["opp_clean_share"] = _modal(clean)
        row["opp_clean_games"] = sum(clean.values()) if clean else 0


def attach_rankings(cur, rows: list) -> None:
    cur.execute("SELECT team_id, status FROM rankings_full")
    ranked = {str(t): (s or "") for t, s in cur.fetchall()}
    for row in rows:
        status = ranked.get(row["team_id_master"])
        row["is_ranked"] = "True" if status is not None else "False"
        row["rank_status"] = status or ""


COLUMNS = [
    "verdict",
    "delta",
    "name_is_band",
    "team_id",
    "team_id_master",
    "current_name",
    "proposed_name",
    "shipped_name",
    "name_age_token",
    "name_token_kind",
    "name_implied_cohort",
    "age_group_column",
    "age_group_pre_rollover",
    "rolled_once",
    "birth_year_column",
    "opp_clean_cohort",
    "opp_clean_share",
    "opp_clean_games",
    "opp_modal_name_cohort",
    "opp_modal_name_share",
    "opp_modal_column_cohort",
    "opp_modal_column_share",
    "modal_division_name",
    "games_in_window",
    "last_game",
    "is_ranked",
    "rank_status",
    "residual_age_tokens",
    "duplicate_pre_existing",
    "team_name_original",
    "club_name",
    "league",
    "distinction",
    "state_code",
    "gender",
    "provider",
    "is_deprecated",
    "created_at",
    "updated_at",
]

# Verdicts that describe a rewrite nobody needs to adjudicate.
_UNREMARKABLE = {"no_change", "safe_format_only"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", help="CSV path (default: logs/name_age_disagreements_<date>.csv)")
    parser.add_argument(
        "--include-deprecated",
        action="store_true",
        help="Also audit deprecated teams (the weekly job's --all-teams scan reaches them)",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=365,
        help="Game window for opponent evidence (default: 365, matching the ranking window)",
    )
    parser.add_argument(
        "--all-rows", action="store_true", help="Write every team, not just the ones needing a decision"
    )
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set — this audit reads the full teams table and needs a direct connection.")

    out = args.out or os.path.join(
        _REPO, "logs", f"name_age_disagreements_{datetime.now().strftime('%Y%m%d')}.csv"
    )
    os.makedirs(os.path.dirname(out), exist_ok=True)

    print(
        f"Season year: {CURRENT_YEAR}  "
        f"(plausible birth years {OLDEST_PLAUSIBLE_BIRTH_YEAR}-{YOUNGEST_PLAUSIBLE_BIRTH_YEAR})"
    )

    conn = psycopg2.connect(database_url)
    with conn, conn.cursor() as cur:
        print("Loading teams...")
        teams = load_teams(cur, args.include_deprecated)
        print(f"  {len(teams):,} teams")

        rows = build_rows(teams)

        # Opponent evidence needs a cohort for EVERY team, not only the audited
        # ones — the opponents themselves are mostly teams the audit passes over.
        print("Loading cohorts for opponent lookup...")
        all_teams = teams if args.include_deprecated else load_teams(cur, True)
        all_cohorts = {}
        for t in all_teams:
            master, name, club, age_group = t[1], t[2], t[3], t[5]
            if not (master and name):
                continue
            tokens = _age_tokens(normalize_team_name(name, club))
            cohort = _token_cohort(tokens[0]) if tokens else None
            # A "clean" witness states one birth year and no band, so its cohort
            # is not itself an answer to the band question. Opponents that ARE
            # bands agree with each other by construction, which is why the
            # unfiltered opponent columns can look decisive and mean nothing.
            clean = tokens and not tokens[0].startswith("U") and not _has_band(name)
            all_cohorts[str(master)] = (cohort, _cohort_label(age_group), cohort if clean else None)

        audited = rows if args.all_rows else [r for r in rows if r["verdict"] not in _UNREMARKABLE]
        print(f"  {len(audited):,} rows need a decision")

        print("Attaching rollover history...")
        attach_rollover(cur, audited)
        print("Attaching game evidence...")
        attach_game_evidence(cur, audited, all_cohorts, args.window_days)
        print("Attaching ranking status...")
        attach_rankings(cur, audited)

    conn.close()

    order = {v: i for i, v in enumerate(
        ["club_fragment_eaten", "duplicate_age_token", "unusable_column",
         "birth_year_overwritten", "name_ahead", "wild_delta", "band_column_conflict",
         "stale_u_age", "safe_format_only", "no_change"]
    )}
    audited.sort(key=lambda r: (order.get(r["verdict"], 99), -abs(r["delta"] or 0), r["current_name"]))

    with open(out, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(audited)

    print(f"\nWrote {len(audited):,} rows to {out}\n")

    counts = collections.Counter(r["verdict"] for r in rows)
    ranked = collections.Counter(r["verdict"] for r in audited if r["is_ranked"] == "True")
    print(f"{'verdict':<24}{'teams':>10}{'ranked':>10}")
    print("-" * 44)
    for verdict, n in counts.most_common():
        print(f"{verdict:<24}{n:>10,}{ranked.get(verdict, 0):>10,}")
    print("-" * 44)
    print(f"{'TOTAL':<24}{sum(counts.values()):>10,}")


if __name__ == "__main__":
    main()
