"""The Manual Team Edit games tab must show hidden games as hidden and keep them out of the record.

A superseded game stays in the games table with is_excluded set, and the site skips it. This tab lists
every row, so it marks hidden ones and leaves them out of the record; otherwise the stale copy reads as a
duplicate and the game counts twice.
dashboard.py is a Streamlit script that cannot be imported, so the scan is scoped to the tab's block.
"""

import re
from pathlib import Path


def _games_tab_block() -> str:
    source = (Path(__file__).resolve().parents[2] / "dashboard.py").read_text(encoding="utf-8")
    start = source.index("with games_tab:")
    end = source.index("st.dataframe(games_df", start)
    return source[start:end]


def _record_region(block: str) -> str:
    return block[block.index("wins = losses = draws = gf = ga = 0") : block.index("st.columns(4)")]


def test_both_game_queries_read_the_hidden_flag():
    block = _games_tab_block()

    assert block.count("'home_score, away_score, is_excluded'") == 2


def test_live_games_are_the_rows_not_flagged_hidden():
    block = _games_tab_block()

    assert "live_games = [g for g in all_games if not g.get('is_excluded')]" in block


def test_the_cap_applies_before_the_live_hidden_split():
    block = _games_tab_block()

    assert block.index("all_games = all_games[:50]") < block.index("live_games = [")


def test_the_count_message_reports_live_games_and_the_hidden_remainder():
    block = _games_tab_block()

    assert "hidden_count = len(all_games) - len(live_games)" in block
    assert 'hidden_note = f" (plus {hidden_count} hidden)" if hidden_count else ""' in block
    assert 'st.success(f"Found **{len(live_games)}** games{hidden_note}")' in block


def test_the_record_is_worked_out_from_the_live_games_only():
    record = _record_region(_games_tab_block())

    assert "for g in live_games:" in record
    assert "all_games" not in record


def test_unscored_fixtures_stay_out_of_the_record():
    record = _record_region(_games_tab_block())

    assert re.search(r"if home_score is None or away_score is None:\s*continue\b", record)
    assert "or 0" not in record


def test_the_table_lists_every_row_including_hidden_ones():
    block = _games_tab_block()
    table = block[block.index("games_df = pd.DataFrame(") :]

    assert re.search(r"for g in all_games\s*\]\)", table)
    assert "for g in live_games" not in table


def test_unscored_rows_get_no_result_in_the_table():
    block = _games_tab_block()
    table = block[block.index("games_df = pd.DataFrame(") :]

    assert "'—' if g.get('home_score') is None or g.get('away_score') is None" in table


def test_hidden_rows_are_marked_in_the_table():
    block = _games_tab_block()

    assert "'Hidden': 'hidden' if g.get('is_excluded') else ''" in block
