"""The rankings board tells parents how many games a rank takes; that number is the engine's own floor."""

import re
from pathlib import Path

from src.etl.glicko_config import GlickoConfig

_FRONTEND_CONSTANTS = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "constants.ts"


def test_board_games_threshold_matches_the_engine():
    declared = re.findall(
        r"^export const MIN_RANKED_GAMES = (\d+);$",
        _FRONTEND_CONSTANTS.read_text(encoding="utf-8"),
        re.MULTILINE,
    )

    assert len(declared) == 1
    assert int(declared[0]) == GlickoConfig().MIN_GAMES_PROVISIONAL
