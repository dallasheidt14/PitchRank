"""
Regression guard: the ranking input loader must filter NULL-score games.

Future-dated scheduled games are persisted with NULL scores per the
schedule-driven-scraping spec (Phase 1). If the loader ever loses its
NULL-score filter, those phantom rows will corrupt Glicko-2 ratings silently.
This test asserts both filter layers in `fetch_games_for_rankings` and
`supabase_to_v53e_format`.
"""
from __future__ import annotations

import inspect

from src.rankings.data_adapter import fetch_games_for_rankings, supabase_to_v53e_format


def test_ranking_loader_query_filters_null_scores():
    """
    The SQL query built in fetch_games_for_rankings must contain an explicit
    NULL-score predicate using supabase-py's .not_.is_() pattern.
    Verified at data_adapter.py:205-206.
    """
    source = inspect.getsource(fetch_games_for_rankings)
    assert (
        '.not_.is_("home_score", "null")' in source
        or ".not_.is_('home_score', 'null')" in source
        or "IS NOT NULL" in source
        or "is_not_null" in source.lower()
    ), (
        "fetch_games_for_rankings source does not contain a NULL home_score filter. "
        "This will allow scheduled (NULL-score) games into Glicko-2 input. "
        f"Source snippet:\n{source[:600]}..."
    )
    assert (
        '.not_.is_("away_score", "null")' in source
        or ".not_.is_('away_score', 'null')" in source
    ), (
        "fetch_games_for_rankings source does not contain a NULL away_score filter. "
        "This will allow scheduled (NULL-score) games into Glicko-2 input. "
        f"Source snippet:\n{source[:600]}..."
    )


def test_ranking_loader_date_upper_bound_excludes_future_games():
    """
    The SQL query must also cap game_date at today to exclude future-dated rows
    as a second line of defence against scheduled games leaking in.
    Verified at data_adapter.py:199-202.
    """
    source = inspect.getsource(fetch_games_for_rankings)
    assert (
        "today_date_str" in source and ".lte(" in source
    ), (
        "fetch_games_for_rankings no longer applies a game_date <= today upper bound. "
        "Future-dated games could enter rankings even if scores are non-NULL. "
        f"Source snippet:\n{source[:600]}..."
    )


def test_v53e_format_drops_null_score_rows():
    """
    supabase_to_v53e_format must call dropna on gf/ga columns so that any
    NULL-score rows that slip through the SQL query are discarded before
    they reach the Glicko-2 engine.
    Verified at data_adapter.py:589.
    """
    source = inspect.getsource(supabase_to_v53e_format)
    assert (
        'dropna(subset=["gf", "ga"])' in source
        or "dropna(subset=['gf', 'ga'])" in source
        or ('dropna' in source and '"gf"' in source and '"ga"' in source)
    ), (
        "supabase_to_v53e_format no longer calls dropna on [gf, ga] columns. "
        "NULL-score rows that bypass the SQL filter will silently corrupt Glicko-2. "
        f"Source snippet:\n{source[:600]}..."
    )
