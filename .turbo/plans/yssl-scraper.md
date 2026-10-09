# YSSL Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Monday, import YSSL's scored games, linking each YSSL team to its existing IL PitchRank team, or creating one when none fits.

**Architecture:** One driver, `scripts/import_yssl.py`, mirrors `scripts/import_athletes2events_event.py`. It walks clubs → teams → team pages, builds a roster, and registers each team through a matcher in a roster pass (link / review / create). It then writes the importer's CSV and hands it to `import_games_enhanced.py`, which resolves both sides through the aliases the roster pass wrote. The matcher is a thin subclass of `Athletes2EventsGameMatcher`, which already does club-gated, squad-gated, state-scoped matching. A reviewed club map translates YSSL's club spellings to PitchRank's.

**Tech Stack:** Python 3.11, requests, BeautifulSoup, supabase-py, pytest, GitHub Actions.

**Spec:** `.turbo/specs/yssl-scraper.md`

## Global Constraints

- Provider code `yssl`; provider row (`yssl`, `YSSL`, `https://www.yssl.org`).
- Every team's `state_code` is `IL`.
- Import scored games only. A row whose Result cell is empty is never imported.
- A team's age comes from the two-year band in its name (younger year names the band), converted with `calculate_age_group_from_band` against the wall-clock season. The division's U-age is used only when the name has no band. A band-named team that plays up is filed by its band (owner, 2026-09-18).
- Teams below U10 are left out with a reason. They have no board (same as Athletes2Events).
- Gender comes from the team code's 4th character: `M` → Male, `F` → Female, anything else → left out.
- Provider team id is the YSSL team code (`AACM121`), never `tea_id`.
- Requests are sequential, with a browser User-Agent and a random 1.0–2.0 s pause between fetches. A response with no declared charset is decoded as UTF-8.
- Dry run by default; `--execute` writes.
- Data in fixtures: replace every coach and contact name with `COACH NAME` before committing. The repo is public.
- Lint path: `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py`. Tests: `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`.

## Review Focus

1. **A game seen from only one side** (opponent's club not walked, e.g. a `--club` pilot). Expected: the game is still built from the one side, with home and away taken from its `H/A`. Pinned in Task 2.
2. **The two sides disagree** (score, date or opponents). Expected: the game is held back and named in problems, never imported with either version. Pinned in Task 2.
3. **A club code with no decided club-map row** (a club joins mid-season). Expected: its teams are left out with reason `club not in club map`, every other club still imports, and the run exits 1 so the workflow goes red. Pinned in Tasks 3 and 5.
4. **A changed game** (two dates, the second struck through). Expected: the first, un-struck date is the game date. Pinned in Task 1.
5. **A page that fails to load.** Expected: the run raises `ScrapeFetchError` and stops, rather than reading the page as a club or team with no games. Pinned in Task 2.

## File map

| File | Responsibility |
|---|---|
| `scripts/import_yssl.py` | Create. Fetch, parse, roster, register, CSV, import. |
| `scripts/propose_yssl_club_map.py` | Create. One-time: propose `config/yssl_club_map.csv` rows from YSSL clubs × PitchRank IL clubs. |
| `config/yssl_club_map.csv` | Create. Reviewed YSSL club → PitchRank club map. `data/` is gitignored, so it lives here. |
| `src/models/yssl_matcher.py` | Create. `YSSLGameMatcher(Athletes2EventsGameMatcher)`. |
| `src/etl/enhanced_pipeline.py` | Modify. Add the `yssl` branch beside `athletes2events` (~line 309). |
| `supabase/migrations/20261008120000_seed_yssl_provider.sql` | Create. Provider row. |
| `.github/workflows/yssl-scraper.yml` | Create. Weekly run. |
| `tests/fixtures/yssl/*.html` | Create. Saved pages with names scrubbed. |
| `tests/unit/test_import_yssl.py`, `tests/unit/test_yssl_matcher.py`, `tests/unit/test_propose_yssl_club_map.py` | Create. |
| `tests/unit/test_provider_matcher_dry_run.py`, `tests/unit/test_birth_year_guard_wiring.py`, `tests/unit/test_age_rollover_freeze_coverage.py` | Modify. Registries. |
| `CLAUDE.md`, `.claude/skills/scraper-patterns/SKILL.md` | Modify. Provider table, workflow table, freeze list, a YSSL pages section. |

---

### Task 0: Branch

- [ ] **Step 1:** In `C:\PitchRank`, `git status` shows unrelated staged/dirty work on `fix/fixture-score-fill`. Per the worktree rule's exception, create a worktree off `origin/main`:

```bash
git fetch --all --prune
git worktree add ../pitchrank-yssl -b feat/yssl-scraper origin/main
```

Set up `node_modules`/`.env` per memory `fresh-worktree-setup-on-pitchrank.md` (only `.env` is needed; this change has no frontend code). All paths below are relative to that worktree.

---

### Task 1: Page parsers

**Files:**
- Create: `scripts/import_yssl.py` (parsers only in this task)
- Create: `tests/fixtures/yssl/clublinks.html`, `club_AAC.html`, `club_BRB.html`, `team_130243.html`
- Test: `tests/unit/test_import_yssl.py`

**Interfaces — Produces:**
- `parse_club_list(html: str) -> List[str]`: sorted unique club codes.
- `parse_club_page(html: str) -> Tuple[str, List[Listing]]`: club display name and its team listings.
- `parse_team_games(html: str, team_code: str, season: int, source_url: str) -> Tuple[List[SideGame], List[str]]`: scored games seen from this team, plus problems.
- `game_date(month: int, day: int, season: int) -> date`
- dataclasses `Listing(tea_id, division, team_name, team_code)` and `SideGame(game_no, game_date, game_time, team_code, opponent_code, home_away, goals_for, goals_against, venue, source_url)`.

- [ ] **Step 1: Save fixtures.** Copy the four pages already downloaded to the session scratchpad `yssl/` folder (`clublinks.html`, `club_AAC.html`, `c_BRB.html` → `club_BRB.html`, `team_130243.html`), or re-download them with `curl -sL -A "Mozilla/5.0"`. Scrub personal names with a Python one-off (Write tool, not a heredoc). Replace the text of every `<a href="coachform.php...">…</a>` with `COACH NAME`, and on the team page also the `Team Contact`/`Head Coach`/`Assist Coach` values. Grep afterwards: `grep -c coachform tests/fixtures/yssl/*.html` stays non-zero (links kept), and every `coachform` link's text reads `COACH NAME` (`grep -oE 'coachform[^>]*>[^<]*<' tests/fixtures/yssl/*.html | grep -v "COACH NAME"` returns nothing).

- [ ] **Step 2: Write failing tests**

```python
"""Unit tests for the YSSL driver."""

from datetime import date
from pathlib import Path

import pytest

from scripts import import_yssl as yssl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "yssl"


def _fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestParseClubList:
    def test_reads_every_club_code(self):
        codes = yssl.parse_club_list(_fixture("clublinks.html"))
        assert len(codes) == 136
        assert codes[0] == "AAC"
        assert "FC1" in codes
        assert codes == sorted(set(codes))


class TestParseClubPage:
    def test_reads_club_name_and_teams(self):
        name, listings = yssl.parse_club_page(_fixture("club_AAC.html"))
        assert name == "AAC EAGLES CHICAGO"
        assert [(l.tea_id, l.division, l.team_name, l.team_code) for l in listings] == [
            ("130249", "U10/1", "AAC EAGLES CHICAGO 16/17 GOLD", "AACM101"),
            ("130250", "U10/5NW2", "AAC EAGLES CHICAGO 16/17 SILVER", "AACM102"),
            ("130243", "U12/1", "AAC EAGLES CHICAGO 14/15 GOLD", "AACM121"),
        ]

    def test_small_sided_division_label_is_kept_whole(self):
        _, listings = yssl.parse_club_page(_fixture("club_BRB.html"))
        assert any(l.division.startswith("U07-4V4") for l in listings)


class TestGameDate:
    @pytest.mark.parametrize(
        ("month", "day", "expected"),
        [(9, 13, date(2026, 9, 13)), (11, 1, date(2026, 11, 1)), (4, 10, date(2027, 4, 10))],
    )
    def test_fall_is_season_year_spring_is_next(self, month, day, expected):
        assert yssl.game_date(month, day, 2026) == expected


class TestParseTeamGames:
    def _games(self):
        return yssl.parse_team_games(_fixture("team_130243.html"), "AACM121", 2026, "https://www.yssl.org/team.php?tea_id=130243")

    def test_keeps_scored_games_only(self):
        games, problems = self._games()
        assert problems == []
        assert [g.game_no for g in games] == ["4267", "503", "1840", "3529", "1294"]

    def test_changed_game_uses_the_unstruck_date(self):
        games, _ = self._games()
        first = games[0]
        assert first.game_date == date(2026, 9, 13)
        assert first.game_time == "4:00pm"

    def test_score_is_from_this_teams_side(self):
        games, _ = self._games()
        g = {g.game_no: g for g in games}
        assert (g["4267"].home_away, g["4267"].opponent_code, g["4267"].goals_for, g["4267"].goals_against) == ("H", "ECLM121", 2, 3)
        assert (g["503"].home_away, g["503"].opponent_code, g["503"].goals_for, g["503"].goals_against) == ("A", "WZDM125", 2, 7)
        assert sum(x.goals_for for x in games) == 10  # page's GF
        assert sum(x.goals_against for x in games) == 34  # page's GA

    def test_venue_is_the_current_field(self):
        games, _ = self._games()
        assert games[0].venue == "HUNTINGTON CHASE"

    def test_no_games_table_is_a_problem_not_silence(self):
        games, problems = yssl.parse_team_games("<html><body>nothing</body></html>", "AACM121", 2026, "u")
        assert games == []
        assert problems == ["AACM121: games table not found"]
```

- [ ] **Step 3: Run** `python -m pytest tests/unit/test_import_yssl.py -v`. Expected: FAIL with `ImportError` (module missing).

- [ ] **Step 4: Implement the parsers** (top of `scripts/import_yssl.py`; header, imports and env loading mirror `import_athletes2events_event.py:1-90`)

```python
#!/usr/bin/env python3
"""Register YSSL's teams and import its scored games.

YSSL (Young Sportsmen's Soccer League, yssl.org) is a Chicago-area boys league.
Three public, server-rendered pages feed this script:

- ``clublinks.php`` links every club as ``club.php?clu_code=<CODE>``.
- ``club.php?clu_code=<CODE>`` names the club and lists its current-season
  teams: ``<division>&nbsp;<team name>`` linking ``team.php?tea_id=<n>``, then
  the team code (``AACM121``: club code, gender letter, U-age, squad index).
- ``team.php?tea_id=<n>`` carries the team's games. A changed game shows its
  current date first and the original struck through; ``Result`` is written
  from this team's side; an unplayed game has an empty ``Result``.

Every game appears on both teams' pages, so games are merged by YSSL game
number and checked for agreement. Only the current season is published.

The team code is the provider team id. It carries the U-age, so it changes
every Aug 1; the new code then re-matches by name onto the same PitchRank team.
YSSL abbreviates clubs (``ECLIPSE``) and splits some into branches (``RUSH
NORTH``), so ``config/yssl_club_map.csv`` translates each club code to the club
name PitchRank stores. A club with no decided row is left out and fails the run.

Dry run by default; ``--execute`` writes teams, aliases, review rows and games.

Usage:
    python scripts/import_yssl.py --days-back 14 [--club AAC --club ECL] [--execute]
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import random
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.markup import escape  # noqa: E402
from rich.table import Table  # noqa: E402

from config.settings import AGE_GROUPS  # noqa: E402
from src.models.yssl_matcher import YSSLGameMatcher  # noqa: E402
from src.utils.team_utils import (  # noqa: E402
    _soccer_season_year,
    calculate_age_group_from_band,
    extract_band_birth_year,
)
from src.utils.us_states import STATE_CODE_TO_NAME  # noqa: E402
from supabase import create_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
console = Console()

_env_local = Path(".env.local")
if _env_local.exists():
    load_dotenv(_env_local)
else:
    load_dotenv()

PROVIDER_CODE = "yssl"
BASE_URL = "https://www.yssl.org"
STATE_CODE = "IL"
OUTPUT_DIR = Path("data/raw/yssl")
CLUB_MAP_PATH = Path("config/yssl_club_map.csv")

_CLUB_LINK = re.compile(r"club\.php\?clu_code=([A-Z0-9]{2,5})\b")
_CLUB_NAME = re.compile(r"<b>Club</b></span>:\s*([^<]+?)\s*<br>", re.IGNORECASE)
_TEA_ID = re.compile(r"tea_id=(\d+)")
_TEA_NUM = re.compile(r"tea_num=([A-Z0-9]+)")
_SITE_DATE = re.compile(r"^[A-Za-z]{3}\s+(\d{1,2})/(\d{1,2})(?:\s+(\d{1,2}:\d{2}\s*[ap]m))?$", re.IGNORECASE)
_RESULT = re.compile(r"^(\d{1,2})\s*-\s*(\d{1,2})$")
_GAME_NO = re.compile(r"^(\d+)\*?$")
_GAMES_HEADER = ["Num", "Date/Time", "Opponent", "H/A", "Field", "Result"]


@dataclass
class Listing:
    tea_id: str
    division: str
    team_name: str
    team_code: str


@dataclass
class SideGame:
    game_no: str
    game_date: date
    game_time: str
    team_code: str
    opponent_code: str
    home_away: str
    goals_for: int
    goals_against: int
    venue: str
    source_url: str


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).replace("\xa0", " ").split())


def parse_club_list(html: str) -> List[str]:
    return sorted(set(_CLUB_LINK.findall(html)))


def parse_club_page(html: str) -> Tuple[str, List[Listing]]:
    found = _CLUB_NAME.search(html)
    club_name = " ".join(found.group(1).split()) if found else ""
    soup = BeautifulSoup(html, "html.parser")
    listings: List[Listing] = []
    for link in soup.select('a[href*="team.php?tea_id="]'):
        tea_id = _TEA_ID.search(link["href"]).group(1)
        division, _, team_name = link.get_text().partition("\xa0")
        cells = link.find_parent("tr").find_all("td")
        team_code = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        listings.append(Listing(tea_id, division.strip(), " ".join(team_name.split()), team_code))
    return club_name, listings


def game_date(month: int, day: int, season: int) -> date:
    """A fall date (Aug-Dec) is in the season's start year; a spring date in the next."""
    return date(season if month >= 8 else season + 1, month, day)


def _games_table(soup):
    for table in soup.find_all("table"):
        header = [th.get_text(strip=True) for th in table.find_all("th", recursive=True)][:6]
        if header == _GAMES_HEADER:
            return table
    return None


def parse_team_games(html: str, team_code: str, season: int, source_url: str) -> Tuple[List[SideGame], List[str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = _games_table(soup)
    if table is None:
        return [], [f"{team_code}: games table not found"]
    games: List[SideGame] = []
    problems: List[str] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        number = _GAME_NO.match(_text(cells[0]))
        result = _RESULT.match(_text(cells[5]))
        if not number or not result:
            continue  # header row, or a game not yet played
        for struck in cells[1].find_all("del") + cells[4].find_all("del"):
            struck.decompose()
        when = _SITE_DATE.match(_text(cells[1]))
        opponent = cells[2].find("a", href=_TEA_NUM)
        home_away = _text(cells[3])
        if not when or not opponent or home_away not in ("H", "A"):
            problems.append(f"{team_code} game {number.group(1)}: unreadable row")
            continue
        games.append(
            SideGame(
                game_no=number.group(1),
                game_date=game_date(int(when.group(1)), int(when.group(2)), season),
                game_time=(when.group(3) or "").replace(" ", ""),
                team_code=team_code,
                opponent_code=_TEA_NUM.search(opponent["href"]).group(1),
                home_away=home_away,
                goals_for=int(result.group(1)),
                goals_against=int(result.group(2)),
                venue=_text(cells[4]).removesuffix("[away]").strip(),
                source_url=source_url,
            )
        )
    return games, problems
```

If `_games_table` fails on the live page because `html.parser` nests the site's unclosed `<table>`, keep the header test and select the innermost matching table (`table.find_all("table")` empty). Then re-run the tests; never loosen the header match to just `"Num"`, because the Game Changes table also starts with `Num`.

- [ ] **Step 5: Run** `python -m pytest tests/unit/test_import_yssl.py -v`. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/import_yssl.py tests/unit/test_import_yssl.py tests/fixtures/yssl/
git commit -m "Parse YSSL club and team pages"
```

---

### Task 2: Collecting the league and merging both sides of each game

**Files:**
- Modify: `scripts/import_yssl.py`
- Test: `tests/unit/test_import_yssl.py`

**Interfaces:**
- Consumes: Task 1 parsers and dataclasses.
- Produces:
  - `ScrapeFetchError(RuntimeError)`, `make_session() -> requests.Session`, `_get(session, url) -> requests.Response` (copy `import_athletes2events_event.py:301-326` verbatim).
  - `Game(game_no, game_date, game_time, home_code, away_code, home_score, away_score, venue, source_url)`.
  - `merge_games(sides: List[SideGame]) -> Tuple[List[Game], List[str]]`.
  - `collect_league(fetch_html: Callable[[str], str], clubs: Optional[List[str]], season: int, pause: Callable[[], None] = lambda: None) -> Tuple[Dict[str, Tuple[str, List[Listing]]], List[SideGame], List[str]]`: returns `{club_code: (club_display_name, listings)}`, every scored side game, and problems.

- [ ] **Step 1: Write failing tests**

```python
def _side(no, team, opp, ha, gf, ga, day=date(2026, 9, 13)):
    return yssl.SideGame(no, day, "4:00pm", team, opp, ha, gf, ga, "FIELD", f"u/{team}")


class TestMergeGames:
    def test_two_agreeing_sides_make_one_game(self):
        games, problems = yssl.merge_games([_side("1", "AACM121", "ECLM121", "H", 2, 3), _side("1", "ECLM121", "AACM121", "A", 3, 2)])
        assert problems == []
        assert [(g.game_no, g.home_code, g.away_code, g.home_score, g.away_score) for g in games] == [("1", "AACM121", "ECLM121", 2, 3)]

    def test_one_side_is_enough(self):
        games, problems = yssl.merge_games([_side("7", "ECLM121", "AACM121", "A", 3, 2)])
        assert problems == []
        assert [(g.home_code, g.away_code, g.home_score, g.away_score) for g in games] == [("AACM121", "ECLM121", 2, 3)]

    @pytest.mark.parametrize(
        "other",
        [
            _side("1", "ECLM121", "AACM121", "A", 4, 2),  # score disagrees
            _side("1", "ECLM121", "AACM121", "A", 3, 2, day=date(2026, 9, 14)),  # date disagrees
            _side("1", "ECLM121", "PGSM121", "A", 3, 2),  # opponent disagrees
            _side("1", "ECLM121", "AACM121", "H", 3, 2),  # both home
        ],
    )
    def test_disagreeing_sides_hold_the_game(self, other):
        games, problems = yssl.merge_games([_side("1", "AACM121", "ECLM121", "H", 2, 3), other])
        assert games == []
        assert problems == ["game 1: the two teams' pages disagree"]

    def test_three_sides_hold_the_game(self):
        s = _side("1", "AACM121", "ECLM121", "H", 2, 3)
        games, problems = yssl.merge_games([s, _side("1", "ECLM121", "AACM121", "A", 3, 2), s])
        assert games == []
        assert problems == ["game 1: listed 3 times"]


class _Pages:
    def __init__(self, pages):
        self.pages = pages
        self.fetched = []

    def __call__(self, url):
        self.fetched.append(url)
        if url not in self.pages:
            raise yssl.ScrapeFetchError(f"HTTP 404 for {url}")
        return self.pages[url]


class TestCollectLeague:
    def _pages(self):
        return _Pages(
            {
                f"{yssl.BASE_URL}/clublinks.php": _fixture("clublinks.html"),
                f"{yssl.BASE_URL}/club.php?clu_code=AAC": _fixture("club_AAC.html"),
                f"{yssl.BASE_URL}/team.php?tea_id=130249": _fixture("team_130243.html").replace("AACM121", "AACM101"),
                f"{yssl.BASE_URL}/team.php?tea_id=130250": _fixture("team_130243.html").replace("AACM121", "AACM102"),
                f"{yssl.BASE_URL}/team.php?tea_id=130243": _fixture("team_130243.html"),
            }
        )

    def test_walks_only_the_named_clubs(self):
        pages = self._pages()
        clubs, sides, problems = yssl.collect_league(pages, ["AAC"], 2026)
        assert list(clubs) == ["AAC"]
        assert clubs["AAC"][0] == "AAC EAGLES CHICAGO"
        assert len(pages.fetched) == 5  # list, club, three teams
        assert {s.team_code for s in sides} == {"AACM101", "AACM102", "AACM121"}

    def test_a_named_club_not_on_the_list_is_a_problem(self):
        _, _, problems = yssl.collect_league(self._pages(), ["AAC", "ZZZ"], 2026)
        assert "club ZZZ is not on the club list" in problems

    def test_a_failed_page_stops_the_run(self):
        pages = self._pages()
        del pages.pages[f"{yssl.BASE_URL}/team.php?tea_id=130250"]
        with pytest.raises(yssl.ScrapeFetchError):
            yssl.collect_league(pages, ["AAC"], 2026)
```

- [ ] **Step 2: Run** `python -m pytest tests/unit/test_import_yssl.py -k "Merge or Collect" -v`. Expected: FAIL (`AttributeError: merge_games`).

- [ ] **Step 3: Implement**

```python
@dataclass
class Game:
    game_no: str
    game_date: date
    game_time: str
    home_code: str
    away_code: str
    home_score: int
    away_score: int
    venue: str
    source_url: str


def _as_home_view(side: SideGame) -> Tuple:
    if side.home_away == "H":
        return (side.team_code, side.opponent_code, side.goals_for, side.goals_against, side.game_date)
    return (side.opponent_code, side.team_code, side.goals_against, side.goals_for, side.game_date)


def merge_games(sides: List[SideGame]) -> Tuple[List[Game], List[str]]:
    """One game per YSSL game number; the two teams' pages must agree."""
    by_number: Dict[str, List[SideGame]] = {}
    for side in sides:
        by_number.setdefault(side.game_no, []).append(side)
    games: List[Game] = []
    problems: List[str] = []
    for game_no, seen in sorted(by_number.items(), key=lambda item: int(item[0])):
        if len(seen) > 2:
            problems.append(f"game {game_no}: listed {len(seen)} times")
            continue
        views = {_as_home_view(side) for side in seen}
        if len(views) != 1 or (len(seen) == 2 and seen[0].home_away == seen[1].home_away):
            problems.append(f"game {game_no}: the two teams' pages disagree")
            continue
        home_code, away_code, home_score, away_score, day = views.pop()
        first = seen[0]
        games.append(Game(game_no, day, first.game_time, home_code, away_code, home_score, away_score, first.venue, first.source_url))
    return games, problems


def collect_league(
    fetch_html: Callable[[str], str],
    clubs: Optional[List[str]],
    season: int,
    pause: Callable[[], None] = lambda: None,
) -> Tuple[Dict[str, Tuple[str, List[Listing]]], List[SideGame], List[str]]:
    listed = parse_club_list(fetch_html(f"{BASE_URL}/clublinks.php"))
    pause()
    problems = [f"club {code} is not on the club list" for code in (clubs or []) if code not in listed]
    wanted = [code for code in listed if not clubs or code in clubs]
    found: Dict[str, Tuple[str, List[Listing]]] = {}
    sides: List[SideGame] = []
    for code in wanted:
        found[code] = parse_club_page(fetch_html(f"{BASE_URL}/club.php?clu_code={code}"))
        pause()
        for listing in found[code][1]:
            url = f"{BASE_URL}/team.php?tea_id={listing.tea_id}"
            team_games, team_problems = parse_team_games(fetch_html(url), listing.team_code, season, url)
            pause()
            sides.extend(team_games)
            problems.extend(team_problems)
    return found, sides, problems
```

Also add `ScrapeFetchError`, `HEADERS`, `make_session` and `_get`, copied verbatim from `import_athletes2events_event.py:162-168` and `:301-326`.

- [ ] **Step 4: Run** the same command. Expected: PASS.

- [ ] **Step 5: Commit** `git add scripts/import_yssl.py tests/unit/test_import_yssl.py && git commit -m "Walk YSSL clubs and merge each game's two sides"`

---

### Task 3: Club map and roster

**Files:**
- Create: `scripts/propose_yssl_club_map.py`, `config/yssl_club_map.csv` (header only in this task)
- Modify: `scripts/import_yssl.py`
- Test: `tests/unit/test_import_yssl.py`, `tests/unit/test_propose_yssl_club_map.py`

**Interfaces:**
- Produces:
  - `ClubEntry(yssl_code, yssl_name, pitchrank_club_name, decided_by)`, `load_club_map(path: Path) -> Dict[str, ClubEntry]`: rows with a blank `decided_by` or blank `pitchrank_club_name` are **undecided** and omitted. A blank never means "no PitchRank club"; for a new club the owner writes the name to create it under.
  - `TeamRow(team_code, tea_id, team_name, division, club_code, club_as_written, club_name, age_group, age_source, gender, state_code="IL", skip_reason="")`.
  - `team_age(team_name: str, division: str, board_season: int) -> Tuple[Optional[str], str]`: `(age_group, source)`.
  - `build_roster(clubs: Dict[str, Tuple[str, List[Listing]]], club_map: Dict[str, ClubEntry], board_season: int) -> Tuple[List[TeamRow], List[TeamRow]]`: in scope, left out.
  - `propose_rows(yssl_clubs: List[Tuple[str, str]], pitchrank_clubs: List[str]) -> List[Dict]`.

- [ ] **Step 1: Write failing tests** (append to `test_import_yssl.py`)

```python
class TestTeamAge:
    @pytest.mark.parametrize(
        ("name", "division", "expected"),
        [
            ("AAC EAGLES CHICAGO 14/15 GOLD", "U12/1", ("u12", "band 14/15")),
            ("WCOB FC 2014/15 ACADEMY BLACK", "U12/3", ("u12", "band 2014/15")),
            ("BERBER CITY FC 12/13", "U14/5CITY", ("u14", "band 12/13")),
            ("EAGLES 13/14 PREMIER", "U14/1", ("u13", "band 13/14")),  # plays up: band wins
            ("EAGLES RED", "U11/2", ("u11", "division U11")),
            ("EAGLES RED", "U18/1", ("u19", "division U18")),
        ],
    )
    def test_band_first_then_division(self, name, division, expected):
        assert yssl.team_age(name, division, 2026) == expected

    @pytest.mark.parametrize(
        ("name", "division"),
        [("RUSH - WILMETTE WINGS 18/19B PREMIER", "U08-7V7/4N"), ("EAGLES", "U09/4S"), ("EAGLES", "")],
    )
    def test_no_board_is_none(self, name, division):
        assert yssl.team_age(name, division, 2026)[0] is None


def _club_map(**names):
    return {code: yssl.ClubEntry(code, code, name, "owner") for code, name in names.items()}


class TestBuildRoster:
    def test_maps_club_and_reads_gender_from_code(self):
        clubs = {"AAC": ("AAC EAGLES CHICAGO", [yssl.Listing("130243", "U12/1", "AAC EAGLES CHICAGO 14/15 GOLD", "AACM121")])}
        in_scope, left_out = yssl.build_roster(clubs, _club_map(AAC="AAC Eagles"), 2026)
        assert left_out == []
        row = in_scope[0]
        assert (row.team_code, row.club_name, row.club_as_written, row.age_group, row.gender, row.state_code) == (
            "AACM121", "AAC Eagles", "AAC EAGLES CHICAGO", "u12", "Male", "IL"
        )

    @pytest.mark.parametrize(
        ("listing", "club_map", "reason"),
        [
            (yssl.Listing("1", "U12/1", "X 14/15", "AACM121"), {}, "club AAC not in club map"),
            (yssl.Listing("1", "U12/1", "X 14/15", "AACX121"), _club_map(AAC="AAC Eagles"), "team code AACX121 names no gender"),
            (yssl.Listing("1", "U08-5V5/4S", "X 18/19", "AACM081"), _club_map(AAC="AAC Eagles"), "no U10-U19 board (band 18/19)"),
        ],
    )
    def test_left_out_with_reason(self, listing, club_map, reason):
        in_scope, left_out = yssl.build_roster({"AAC": ("AAC EAGLES CHICAGO", [listing])}, club_map, 2026)
        assert in_scope == []
        assert left_out[0].skip_reason == reason


class TestLoadClubMap:
    def test_undecided_rows_are_omitted(self, tmp_path):
        path = tmp_path / "map.csv"
        path.write_text(
            "yssl_code,yssl_name,pitchrank_club_name,decided_by,note\n"
            "AAC,AAC EAGLES CHICAGO,AAC Eagles,auto-exact,\n"
            "ECL,ECLIPSE,Eclipse Select Soccer Club,owner,\n"
            "RSN,RUSH NORTH,,,candidates: Chicago Rush Soccer Club\n"
            "XYZ,XYZ FC,Xyz FC,,\n",
            encoding="utf-8",
        )
        assert sorted(yssl.load_club_map(path)) == ["AAC", "ECL"]
```

And `tests/unit/test_propose_yssl_club_map.py`:

```python
from scripts import propose_yssl_club_map as p


def test_exact_after_normalizing_is_auto_decided():
    rows = p.propose_rows([("WZD", "WCOB FC"), ("BRB", "BERBER CITY FC")], ["Wcob FC", "Berber City FC", "Eclipse Select Soccer Club"])
    assert [(r["yssl_code"], r["pitchrank_club_name"], r["decided_by"]) for r in rows] == [
        ("BRB", "Berber City FC", "auto-exact"),
        ("WZD", "Wcob FC", "auto-exact"),
    ]


def test_anything_else_is_left_undecided_with_candidates():
    rows = p.propose_rows([("ECL", "ECLIPSE")], ["Eclipse Select Soccer Club", "Pegasus FC"])
    assert rows[0]["pitchrank_club_name"] == ""
    assert rows[0]["decided_by"] == ""
    assert rows[0]["note"].startswith("candidates: Eclipse Select Soccer Club")


def test_a_prefix_is_never_auto_decided():
    # Club branches are separate clubs: RUSH NORTH must not auto-map to Chicago Rush North Shore.
    rows = p.propose_rows([("RSN", "RUSH NORTH")], ["Chicago Rush North Shore", "Chicago Rush Soccer Club"])
    assert rows[0]["decided_by"] == ""
```

- [ ] **Step 2: Run** `python -m pytest tests/unit/test_import_yssl.py tests/unit/test_propose_yssl_club_map.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement in `import_yssl.py`**

```python
_DIVISION_AGE = re.compile(r"^U(\d{1,2})")
_TEAM_CODE = re.compile(r"^[A-Z0-9]{3}([A-Z])\d")
_GENDERS = {"M": "Male", "F": "Female"}
_BAND_TEXT = re.compile(r"\b(?:20)?\d{2}\s*[/-]\s*(?:20)?\d{2}")


@dataclass
class ClubEntry:
    yssl_code: str
    yssl_name: str
    pitchrank_club_name: str
    decided_by: str


@dataclass
class TeamRow:
    team_code: str
    tea_id: str
    team_name: str
    division: str
    club_code: str
    club_as_written: str
    club_name: Optional[str]
    age_group: Optional[str]
    age_source: str
    gender: Optional[str]
    state_code: str = STATE_CODE
    skip_reason: str = ""


def load_club_map(path: Path) -> Dict[str, ClubEntry]:
    """Decided rows only. A blank name or decider is undecided, never 'no club'."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {
        row["yssl_code"].strip(): ClubEntry(
            row["yssl_code"].strip(), row["yssl_name"].strip(), row["pitchrank_club_name"].strip(), row["decided_by"].strip()
        )
        for row in rows
        if row["pitchrank_club_name"].strip() and row["decided_by"].strip()
    }


def _board(label: Optional[str]) -> Optional[str]:
    if not label:
        return None
    cohort = "u19" if label.lower() == "u18" else label.lower()
    return cohort if cohort in AGE_GROUPS else None


def team_age(team_name: str, division: str, board_season: int) -> Tuple[Optional[str], str]:
    """The band in the name wins, even for a team playing up; the division only fills a nameless gap."""
    younger = extract_band_birth_year(team_name, board_season)
    if younger:
        band = _BAND_TEXT.search(team_name)
        source = f"band {band.group(0).replace(' ', '')}" if band else f"band {younger}"
        return _board(calculate_age_group_from_band(younger, board_season)), source
    age = _DIVISION_AGE.match(division or "")
    if age:
        return _board(f"U{int(age.group(1))}"), f"division U{int(age.group(1))}"
    return None, "no band in name and no division age"


def build_roster(
    clubs: Dict[str, Tuple[str, List[Listing]]], club_map: Dict[str, ClubEntry], board_season: int
) -> Tuple[List[TeamRow], List[TeamRow]]:
    in_scope: List[TeamRow] = []
    left_out: List[TeamRow] = []
    for club_code, (club_as_written, listings) in sorted(clubs.items()):
        entry = club_map.get(club_code)
        for listing in listings:
            age_group, age_source = team_age(listing.team_name, listing.division, board_season)
            code = _TEAM_CODE.match(listing.team_code)
            row = TeamRow(
                team_code=listing.team_code,
                tea_id=listing.tea_id,
                team_name=listing.team_name,
                division=listing.division,
                club_code=club_code,
                club_as_written=club_as_written,
                club_name=entry.pitchrank_club_name if entry else None,
                age_group=age_group,
                age_source=age_source,
                gender=_GENDERS.get(code.group(1)) if code else None,
            )
            if not entry:
                row.skip_reason = f"club {club_code} not in club map"
            elif not row.gender:
                row.skip_reason = f"team code {listing.team_code} names no gender"
            elif not age_group:
                row.skip_reason = f"no U10-U19 board ({age_source})"
            (left_out if row.skip_reason else in_scope).append(row)
    return in_scope, left_out
```

`team_age`'s source string must read `band 14/15` for the fixture. If `_BAND_TEXT` picks a different span on a test name, fix the regex rather than the expected value.

- [ ] **Step 4: Implement `scripts/propose_yssl_club_map.py`**

```python
#!/usr/bin/env python3
"""Propose config/yssl_club_map.csv: each YSSL club against PitchRank's IL clubs.

Only a name equal after normalizing is filled in (decided_by=auto-exact). Every
other club is left blank with up to three candidates in its note, for the owner:
club branches are separate clubs, so a shared prefix never decides a match.

Read-only against the database. Writes the proposal to --output (default
data/raw/yssl/club_map_proposal.csv); copy decided rows into the config file by hand.
"""

import argparse
import csv
import difflib
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402
from supabase import create_client  # noqa: E402

from scripts.import_yssl import BASE_URL, _get, make_session, parse_club_list, parse_club_page  # noqa: E402

COLUMNS = ["yssl_code", "yssl_name", "pitchrank_club_name", "decided_by", "note"]
_FILLER = {"fc", "sc", "soccer", "club", "futbol", "the"}


def _key(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    return " ".join(w for w in words if w not in _FILLER)


def propose_rows(yssl_clubs: List[Tuple[str, str]], pitchrank_clubs: List[str]) -> List[Dict]:
    by_key: Dict[str, str] = {}
    for club in sorted(set(pitchrank_clubs)):
        by_key.setdefault(_key(club), club)
    rows = []
    for code, name in sorted(yssl_clubs):
        exact = by_key.get(_key(name))
        candidates = difflib.get_close_matches(_key(name), list(by_key), n=3, cutoff=0.4)
        rows.append(
            {
                "yssl_code": code,
                "yssl_name": name,
                "pitchrank_club_name": exact or "",
                "decided_by": "auto-exact" if exact else "",
                "note": "" if exact else "candidates: " + "; ".join(by_key[c] for c in candidates),
            }
        )
    return rows


def il_club_names(supabase) -> List[str]:
    names, offset = set(), 0
    while True:
        page = (
            supabase.table("teams")
            .select("club_name")
            .eq("state_code", "IL")
            .eq("is_deprecated", False)
            .order("team_id_master")
            .range(offset, offset + 999)
            .execute()
        ).data or []
        names.update(r["club_name"] for r in page if r.get("club_name"))
        if len(page) < 1000:
            return sorted(names)
        offset += 1000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("data/raw/yssl/club_map_proposal.csv"))
    args = parser.parse_args()
    load_dotenv()
    supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    session = make_session()
    clubs = []
    for code in parse_club_list(_get(session, f"{BASE_URL}/clublinks.php").text):
        name, _ = parse_club_page(_get(session, f"{BASE_URL}/club.php?clu_code={code}").text)
        clubs.append((code, name))
    rows = propose_rows(clubs, il_club_names(supabase))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{sum(1 for r in rows if r['decided_by'])} of {len(rows)} clubs auto-decided -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

The club-page loop is sequential with no pause. Add `time.sleep(random.uniform(1.0, 2.0))` after each fetch, as in the driver.

Create `config/yssl_club_map.csv` holding only the header line `yssl_code,yssl_name,pitchrank_club_name,decided_by,note`. Task 7 fills it.

- [ ] **Step 5: Run** both test files. Expected: PASS.

- [ ] **Step 6: Commit** `git add scripts/import_yssl.py scripts/propose_yssl_club_map.py config/yssl_club_map.csv tests/unit/test_import_yssl.py tests/unit/test_propose_yssl_club_map.py && git commit -m "Map YSSL clubs to PitchRank clubs and build the YSSL roster"`

---

### Task 4: Matcher, provider row, pipeline branch

**Files:**
- Create: `src/models/yssl_matcher.py`, `supabase/migrations/20261008120000_seed_yssl_provider.sql`
- Modify: `src/etl/enhanced_pipeline.py` (after the `athletes2events` branch)
- Modify: `tests/unit/test_provider_matcher_dry_run.py`, `tests/unit/test_birth_year_guard_wiring.py`
- Test: `tests/unit/test_yssl_matcher.py`

**Interfaces:**
- Produces: `YSSLGameMatcher(supabase, provider_id=None, alias_cache=None, registration_mode=False, dry_run=False)`. `_match_team(...)` has exactly the signature and result keys of `Athletes2EventsGameMatcher._match_team` (`created`, `review`, `relinked`, `matched`, `team_id`, `method`, `confidence`). Its create hook keeps the full YSSL team name.

Why a subclass, and what it overrides: the Athletes2Events matcher already does what the spec asks. It gates on club (stored `club_name` or the club read from the candidate's name, with the written club stripped from both sides), gates on squad and tier, scopes to state plus null, ties to review, clamps review confidence, refuses two-squads-one-team inside a run, and gates every write on `dry_run`. Its create helper, though, strips the club prefix from the stored team name (`AAC EAGLES CHICAGO 14/15 GOLD` would be stored as `CHICAGO 14/15 GOLD` when the map says `AAC Eagles`). So the subclass replaces that one helper.

- [ ] **Step 1: Write failing tests** (`tests/unit/test_yssl_matcher.py`). Copy `_Query`/`_Db` from `tests/unit/test_athletes2events_matcher.py` (it records at `execute()`, applies `or_`, raises PGRST116 on a zero-row `.single()`, and enforces the review CHECK). Then:

```python
def _team(team_id, name, club, age="u12", state="IL"):
    return {"team_id_master": team_id, "team_name": name, "club_name": club, "age_group": age, "gender": "Male",
            "state_code": state, "is_deprecated": False}


def _match(db, name, club, written, code="AACM121", dry_run=False):
    matcher = YSSLGameMatcher(db, provider_id=PROVIDER, registration_mode=True, dry_run=dry_run)
    return matcher._match_team(PROVIDER, code, name, "u12", "Male", club, state_code="IL", written_club=written)


def test_links_existing_team_despite_band_spelling():
    db = _Db({"teams": [_team("t1", "AAC EAGLES CHICAGO 2014-15 GOLD", "AAC Eagles"),
                        _team("t2", "AAC EAGLES CHICAGO 2015 RED", "AAC Eagles")]})
    result = _match(db, "AAC EAGLES CHICAGO 14/15 GOLD", "AAC Eagles", "AAC EAGLES CHICAGO")
    assert (result["matched"], result["team_id"], result["created"]) == (True, "t1", False)


def test_different_squad_color_is_not_linked_and_creates():
    db = _Db({"teams": [_team("t2", "AAC EAGLES CHICAGO 2015 RED", "AAC Eagles")]})
    result = _match(db, "AAC EAGLES CHICAGO 14/15 GOLD", "AAC Eagles", "AAC EAGLES CHICAGO")
    assert result["created"] is True
    inserted = [p for (table, op, *_rest) in db.executed if table == "teams" and op == "insert" for p in [_rest[1]]]
    assert inserted[0]["team_name"] == "AAC EAGLES CHICAGO 14/15 GOLD"  # full name kept
    assert (inserted[0]["club_name"], inserted[0]["state_code"], inserted[0]["provider_team_id"]) == ("AAC Eagles", "IL", "AACM121")


def test_other_club_is_never_a_candidate():
    db = _Db({"teams": [_team("t9", "PEGASUS FC 14/15 GOLD", "Pegasus FC")]})
    result = _match(db, "AAC EAGLES CHICAGO 14/15 GOLD", "AAC Eagles", "AAC EAGLES CHICAGO")
    assert result["created"] is True


def test_dry_run_writes_nothing():
    db = _Db({"teams": []})
    _match(db, "AAC EAGLES CHICAGO 14/15 GOLD", "AAC Eagles", "AAC EAGLES CHICAGO", dry_run=True)
    assert [e for e in db.executed if e[1] != "select"] == []
```

Adjust the `inserted` unpacking to the `executed` tuple shape you copied: `(table, op, filters, payload, or_clauses, order_by, columns)`, so the payload is index 3.

- [ ] **Step 2: Run** `python -m pytest tests/unit/test_yssl_matcher.py -v`. Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `src/models/yssl_matcher.py`**

```python
"""YSSL game matcher (yssl.org, Chicago-area boys league).

YSSL teams are registered by a roster pass in ``scripts/import_yssl.py``, as
Athletes2Events teams are, and need the same matching: the club gate (the
driver passes PitchRank's club name from ``config/yssl_club_map.csv`` as
``club_name`` and YSSL's own spelling as ``written_club``), the squad and tier
gates, state scoping, and review for ties. So this reuses that matcher whole.

One thing differs. YSSL writes the club inside every team name under its own
spelling, so the Athletes2Events create helper's habit of cutting the club off
the front of the name would store ``CHICAGO 14/15 GOLD`` for ``AAC EAGLES
CHICAGO 14/15 GOLD`` whenever the two spellings share a prefix. A created YSSL
team keeps its full name.
"""

from typing import Optional, Tuple

from src.models.athletes2events_matcher import Athletes2EventsGameMatcher
from src.models.tournament_name_gates import is_boys
from src.utils.team_name_utils import resolve_distinction
from src.utils.us_states import STATE_CODE_TO_NAME


class YSSLGameMatcher(Athletes2EventsGameMatcher):
    def _create_new_athletes2events_team(
        self,
        team_name: str,
        club_name: Optional[str],
        age_group: str,
        gender: str,
        provider_id: Optional[str],
        provider_team_id: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """The base's create hook, keeping the full team name. A team already carrying this code is returned."""
        if provider_id and provider_team_id:
            try:
                existing = (
                    self.db.table("teams")
                    .select("team_id_master")
                    .eq("provider_id", provider_id)
                    .eq("provider_team_id", provider_team_id)
                    .single()
                    .execute()
                )
                if existing.data:
                    return existing.data["team_id_master"], False
            except Exception:
                # PGRST116 on a zero-row .single() is the normal path for a new team.
                pass

        team_id_master = self._new_team_id_master(provider_id, provider_team_id, team_name, age_group, gender)
        clean_team_name = " ".join(team_name.replace("\xa0", " ").split())
        team_data = {
            "team_id_master": team_id_master,
            "team_name": clean_team_name,
            "club_name": club_name or clean_team_name,
            "age_group": age_group.lower(),
            "gender": "Male" if is_boys(gender) else "Female",
            "state_code": state_code,
            "state": STATE_CODE_TO_NAME.get(state_code) if state_code else None,
            "provider_id": provider_id,
            "provider_team_id": provider_team_id,
            "distinction": resolve_distinction(clean_team_name, club_name, state_code),
        }
        if not self.dry_run:
            self.db.table("teams").insert(team_data).execute()
        return team_id_master, True
```

- [ ] **Step 4: Migration** `supabase/migrations/20261008120000_seed_yssl_provider.sql`:

```sql
-- Seed the yssl provider row (Young Sportsmen's Soccer League, Chicago area).
-- EnhancedETLPipeline raises ValueError when this row is absent, and
-- scripts/import_yssl.py refuses to run without it.
INSERT INTO providers (code, name, base_url)
VALUES ('yssl', 'YSSL', 'https://www.yssl.org')
ON CONFLICT (code) DO NOTHING;
```

Before naming the file, check that no migration on `origin/main` already uses that timestamp: `git ls-tree --name-only origin/main supabase/migrations/ | grep 202610081`.

- [ ] **Step 5: Pipeline branch.** In `src/etl/enhanced_pipeline.py`, directly after the `athletes2events` branch:

```python
        elif self.provider_code.lower() == "yssl":
            from src.models.yssl_matcher import YSSLGameMatcher

            # No registration_mode: only the roster pass in import_yssl.py creates YSSL teams.
            logger.info("Using YSSLGameMatcher (alias-only; teams come from the roster pass)")
            self.matcher = YSSLGameMatcher(
                self.supabase,
                provider_id=self.provider_id,
                alias_cache=self.alias_cache,
                dry_run=self.dry_run,
            )
```

- [ ] **Step 6: Registries.** In `tests/unit/test_provider_matcher_dry_run.py`, import `YSSLGameMatcher`, append `("yssl", YSSLGameMatcher)` to `AUTOCREATING_MATCHERS`, `("yssl", YSSLGameMatcher, "_create_new_athletes2events_team")` to the create-helper parametrize list, and `"yssl"` to `REGISTRATION_MATCHERS`. In `tests/unit/test_birth_year_guard_wiring.py`, append `("src.models.yssl_matcher", "YSSLGameMatcher")` to `_SUBCLASS_PATHS`.

- [ ] **Step 7: Run** `python -m pytest tests/unit/test_yssl_matcher.py tests/unit/test_provider_matcher_dry_run.py tests/unit/test_birth_year_guard_wiring.py -v`. Expected: PASS. Then mutate: delete `if not self.dry_run:` from the subclass, re-run, and confirm `test_dry_run_writes_nothing` **and** the registry's `yssl` create-helper case are among the failing test names. Restore and clear `__pycache__` (memory: `mutation-restore-leaves-stale-pyc.md`).

- [ ] **Step 8: Commit** `git add src/models/yssl_matcher.py src/etl/enhanced_pipeline.py supabase/migrations/20261008120000_seed_yssl_provider.sql tests/unit/test_yssl_matcher.py tests/unit/test_provider_matcher_dry_run.py tests/unit/test_birth_year_guard_wiring.py && git commit -m "Add the YSSL matcher and provider row"`

---

### Task 5: Driver — register, write CSV, import

**Files:**
- Modify: `scripts/import_yssl.py`
- Test: `tests/unit/test_import_yssl.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `main() -> int` (0 ok; 1 when any club was left out for lacking a map row, or setup failed; otherwise the importer's return code), and `build_csv_rows(games: List[Game], roster: List[TeamRow], outcomes: Dict[str, Outcome], days_back: int, today: date) -> Tuple[List[Dict], List[Game], List[Dict]]`.

Copy these from `import_athletes2events_event.py` with `a2e_team_id` renamed to `team_code` and `PROVIDER_CODE` meaning `yssl`. Keep their bodies and docstrings otherwise: `LINKED_OUTCOMES`, `Outcome`, `REQUIRED_COLUMNS`, `CROSS_AGE_COLUMNS`, `existing_aliases`, `register_teams`, `unsaved_links`, `pending_reviews`, `unsaved_reviews`, `shared_links`, `off_board_links`, `teams_by_id`, `_compute_result`, `write_csv`. `register_teams` passes `written_club=row.club_as_written`, `club_name=row.club_name`, `state_code=row.state_code`.

`REPORT_COLUMNS` for YSSL: `team_code, tea_id, team_name, club_code, club_as_written, club_name, division, age_group, age_source, gender, state_code, outcome, team_id_master, pitchrank_team_name, confidence, reason`.

- [ ] **Step 1: Write failing tests**

```python
def _row(code, age="u12"):
    return yssl.TeamRow(code, "1", f"TEAM {code} 14/15", "U12/1", code[:3], code[:3], code[:3], age, "band 14/15", "Male")


def _game(no, home, away, day=date(2026, 10, 3)):
    return yssl.Game(no, day, "10:00am", home, away, 2, 1, "FIELD", "https://www.yssl.org/team.php?tea_id=1")


class TestBuildCsvRows:
    def test_two_rows_per_linked_game_with_il_and_scores(self):
        outcomes = {c: yssl.Outcome("already_linked", f"m-{c}", 1.0) for c in ("AACM121", "ECLM121")}
        rows, held, _ = yssl.build_csv_rows([_game("4267", "AACM121", "ECLM121")], [_row("AACM121"), _row("ECLM121")], outcomes, 14, date(2026, 10, 7))
        assert held == []
        assert [(r["team_id"], r["opponent_id"], r["home_away"], r["goals_for"], r["goals_against"], r["state_code"], r["provider"]) for r in rows] == [
            ("AACM121", "ECLM121", "H", 2, 1, "IL", "yssl"),
            ("ECLM121", "AACM121", "A", 1, 2, "IL", "yssl"),
        ]

    def test_unlinked_team_holds_the_game(self):
        outcomes = {"AACM121": yssl.Outcome("already_linked", "m", 1.0), "ECLM121": yssl.Outcome("review")}
        rows, held, _ = yssl.build_csv_rows([_game("1", "AACM121", "ECLM121")], [_row("AACM121"), _row("ECLM121")], outcomes, 14, date(2026, 10, 7))
        assert rows == [] and [g.game_no for g in held] == ["1"]

    def test_opponent_outside_the_roster_holds_the_game(self):
        outcomes = {"AACM121": yssl.Outcome("already_linked", "m", 1.0)}
        rows, held, _ = yssl.build_csv_rows([_game("1", "AACM121", "ZZZM121")], [_row("AACM121")], outcomes, 14, date(2026, 10, 7))
        assert rows == [] and len(held) == 1

    def test_games_outside_the_window_are_dropped(self):
        outcomes = {c: yssl.Outcome("already_linked", f"m-{c}", 1.0) for c in ("AACM121", "ECLM121")}
        old = _game("1", "AACM121", "ECLM121", day=date(2026, 9, 1))
        rows, held, _ = yssl.build_csv_rows([old], [_row("AACM121"), _row("ECLM121")], outcomes, 14, date(2026, 10, 7))
        assert rows == [] and held == []
```

Then a `TestMain` class mirroring `test_import_athletes2events_event.py` `run_main` (lines 533-683): monkeypatch `collect_league`, `load_club_map`, `create_client` (providers table returns the `yssl` row), `YSSLGameMatcher` (a fake recording `_match_team` calls) and `subprocess.run`. Assert:
- a dry run constructs the matcher only with `dry_run=True`, never calls `subprocess.run`, and returns 0;
- `--execute` calls `subprocess.run` with `[sys.executable, "scripts/import_games_enhanced.py", <games csv>, "yssl"]`;
- a roster with one team left out for `club XYZ not in club map` returns **1** even when the import returns 0, and the games CSV still holds the other clubs' games;
- `--club AAC` is passed through to `collect_league` as `["AAC"]`.

- [ ] **Step 2: Run** `python -m pytest tests/unit/test_import_yssl.py -k "Csv or Main" -v`. Expected: FAIL.

- [ ] **Step 3: Implement `build_csv_rows`**: the A2E body, with these changes. Filter to `today - timedelta(days=days_back) <= game.game_date <= today` first. A game whose either code is missing from the roster or not in `LINKED_OUTCOMES` is held. `event_id` is `""`. `event_name` is `f"YSSL {season_label} - {home.division}"`, where `season_label` is `f"Fall {d.year}"` for a game in Aug–Dec and `f"Spring {d.year}"` otherwise. `schedule_id` is `f"yssl-{game.game_no}"`. `age_year` is `""`. `team_id_source` and `opponent_id_source` hold the codes. `state` is `STATE_CODE_TO_NAME["IL"]`.

- [ ] **Step 4: Implement `parse_args` and `main`**

```python
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--days-back", type=int, default=14, help="Import games dated within this many days (default 14)")
    p.add_argument("--club", action="append", default=None, help="Walk only this club code (repeatable; pilots)")
    p.add_argument("--club-map", type=Path, default=CLUB_MAP_PATH)
    p.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    p.add_argument("--delay-min", type=float, default=1.0)
    p.add_argument("--delay-max", type=float, default=2.0)
    p.add_argument("--execute", action="store_true", help="Write teams, aliases and games (default is a dry run)")
    return p.parse_args()
```

`main()` follows `import_athletes2events_event.main` line for line, with these differences:
- `season = _soccer_season_year()` is used both to date games and as the board season (YSSL publishes only the current season).
- Call `collect_league(lambda url: _get(session, url).text, args.club, season, pause)`, then `merge_games(sides)`, then `build_roster(clubs, load_club_map(args.club_map), season)`.
- The preview and writer matchers are `YSSLGameMatcher(..., registration_mode=True, ...)`.
- Files are `{stamp}_games.csv`, `{stamp}_cross_age.csv` and `{stamp}_teams.csv` under `args.output_dir`.
- The summary table is titled `YSSL` and adds the row `clubs not in club map` (a count of distinct `club_code` over left-out rows whose reason starts with `club `).
- At the end, `unmapped = …`; when non-zero, print them in red with `Add them to config/yssl_club_map.csv`. Then `rc = subprocess.run(...).returncode` when executing with records, and `return 1 if unmapped else rc`. In a dry run, return `1 if unmapped else 0`.
- Print one line `Games scraped: N` (memory `zenrows-402-makes-green-empty-runs.md`: operators read that line).

- [ ] **Step 5: Run** the full file `python -m pytest tests/unit/test_import_yssl.py -v`. Expected: PASS. Mutate the unmapped-club exit (`return rc`) and confirm the `TestMain` unmapped test is among the failures. Restore.

- [ ] **Step 6: Lint** `python -m ruff check scripts/import_yssl.py scripts/propose_yssl_club_map.py src/models/yssl_matcher.py`. Expected: clean.

- [ ] **Step 7: Commit** `git add scripts/import_yssl.py tests/unit/test_import_yssl.py && git commit -m "Register YSSL teams and import their scored games"`

---

### Task 6: Weekly workflow, freeze guard, docs

**Files:**
- Create: `.github/workflows/yssl-scraper.yml`
- Modify: `tests/unit/test_age_rollover_freeze_coverage.py`, `CLAUDE.md`, `.claude/skills/scraper-patterns/SKILL.md`

- [ ] **Step 1: Freeze guard first (failing).** Add `"import_yssl.py"` to `AGE_DERIVING_SCRIPTS` in `test_age_rollover_freeze_coverage.py`. It derives a cohort from the wall clock and writes only with `--execute`. Add `assert "yssl-scraper.yml" in workflows` to `test_the_scan_finds_the_known_writing_steps`. Run `python -m pytest tests/unit/test_age_rollover_freeze_coverage.py -v`. Expected: FAIL (workflow missing).

- [ ] **Step 2: Workflow**

```yaml
name: YSSL Scraper

on:
  schedule:
    # Monday 08:15 UTC: after the weekend's games, before data hygiene (11:00) and rankings (12:30).
    - cron: '15 8 * * 1'
  workflow_dispatch:
    inputs:
      days_back:
        description: 'Import games dated within this many days'
        required: false
        default: '14'
      clubs:
        description: 'Space-separated club codes to walk (blank = all)'
        required: false
        default: ''
      dry_run:
        description: 'Dry run (scrape and report, write nothing)'
        type: boolean
        required: false
        default: false

env:
  # Freezes team-creating imports across the Aug 1 age-group rollover; see CLAUDE.md.
  # Gates test == 'false' (not != 'true') so a renamed or deleted flag leaves the step skipped.
  AGE_ROLLOVER_FREEZE: 'false'

concurrency:
  group: yssl-scraper
  cancel-in-progress: false

jobs:
  scrape-yssl:
    runs-on: ubuntu-latest
    timeout-minutes: 90
    steps:
      - name: Checkout repository
        uses: actions/checkout@v5

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.lock

      - name: Scrape YSSL, register teams, import games
        if: ${{ env.AGE_ROLLOVER_FREEZE == 'false' }}
        env:
          PYTHONPATH: ${{ github.workspace }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
          DAYS_BACK_INPUT: ${{ github.event.inputs.days_back }}
          CLUBS_INPUT: ${{ github.event.inputs.clubs }}
          DRY_RUN_INPUT: ${{ github.event.inputs.dry_run }}
        run: |
          set -euo pipefail
          ARGS=(--days-back "${DAYS_BACK_INPUT:-14}")
          for club in ${CLUBS_INPUT:-}; do ARGS+=(--club "$club"); done
          if [ "${DRY_RUN_INPUT:-false}" != "true" ]; then ARGS+=(--execute); fi
          python scripts/import_yssl.py "${ARGS[@]}" | tee yssl_run.log
          GAMES=$(grep -oE 'Games scraped: [0-9]+' yssl_run.log | grep -oE '[0-9]+' || echo 0)
          MONTH=$(date -u +%m)
          # In season (Sep-Nov, Apr-Jun) a run that read zero scored games is a broken scrape, not a quiet week.
          if [ "$GAMES" = "0" ] && [[ "$MONTH" =~ ^(09|10|11|04|05|06)$ ]]; then
            echo "::error::YSSL run read zero scored games in season"
            exit 1
          fi

      - name: Upload CSVs
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: yssl-${{ github.run_id }}
          path: data/raw/yssl/
          if-no-files-found: ignore
```

Before finalizing, open `.github/workflows/ut-scraper.yml` on `origin/main` and match its secrets names, install line and `upload-artifact` version exactly. Where it differs from the block above, mirror it. Per memory `pipefail-kills-the-step-before-the-default.md`, the `GAMES=$(… || echo 0)` keeps a no-match grep from aborting the block. Keep it.

- [ ] **Step 3: Run** the freeze test again. Expected: PASS. Mutate the step's `if:` to `${{ always() }}` and confirm `test_writing_step_is_gated_on_the_freeze[yssl-scraper.yml-...]` is among the failures. Restore.

- [ ] **Step 4: Docs.**
  - `CLAUDE.md`: add YSSL to the Data Providers table (`| YSSL | yssl | HTML scraping, club → team pages | Chicago-area boys league, every team IL; weekly via yssl-scraper.yml |`). Add `yssl-scraper.yml` to the GitHub Actions table (`Mon 8:15 AM UTC | YSSL scrape + roster pass + import (scored games only)`). Add it to the `AGE_ROLLOVER_FREEZE` re-arm list and change "all ten" to "all eleven". Add it to "Three provider imports still stamp a state on team creation" and make that four, noting it is a provider constant with no `state_source`.
  - `.claude/skills/scraper-patterns/SKILL.md`: add a `## YSSL Pages` section with the page table from the spec, the "first date is current, struck date is original" rule, "Result is from this team's side", "team code is the provider id and changes every Aug 1", and "club map lives in `config/yssl_club_map.csv`; blank means undecided".
  - Check whether any CLAUDE.md docs test pins the provider or workflow table: `python -m pytest tests/ -k "claude_md or doc" -q`.

- [ ] **Step 5: Commit** `git add .github/workflows/yssl-scraper.yml tests/unit/test_age_rollover_freeze_coverage.py CLAUDE.md .claude/skills/scraper-patterns/SKILL.md && git commit -m "Run the YSSL import weekly behind the rollover freeze"`

---

### Task 7: Club map review, pilot, PR, backfill (operator steps, needs the owner)

- [ ] **Step 1:** Apply the provider migration to production (hand-applied, then `supabase migration repair --status applied 20261008120000`). Confirm with `select id, code from providers where code='yssl'`.
- [ ] **Step 2:** Run `python scripts/propose_yssl_club_map.py`. Pre-clear what the names alone settle (memory: `pre-clear-the-obvious-before-handing-a-review-list.md`). Hand the owner the remaining clubs as a file with a legend and one example per category: map to an existing club, or "new club, create as `<Name>`" (`approval-files-need-a-legend.md`). Rush branches are separate clubs unless the owner says otherwise.
- [ ] **Step 3:** Write the decided rows into `config/yssl_club_map.csv` (`decided_by` = `auto-exact` or `owner`). Commit.
- [ ] **Step 4:** Dry-run pilot: `python scripts/import_yssl.py --days-back 60 --club AAC --club ECL --club CHR --club AJX --club PGS`. Read the team report rows themselves, not just the counts (`dry-run-output-beats-code-review.md`): every `linked_existing` should be the same squad, and every `created` should have no existing twin. Report linked / review / created / conflict counts to the owner.
- [ ] **Step 5:** Run `/finalize` (tests, polish, review, commit). Then open the PR and run `python scripts/pr_wait.py --no-merge`. Merging is the owner's call.
- [ ] **Step 6:** After merge, run the backfill: `workflow_dispatch` with `days_back=70` (season began Aug 1) and `dry_run=true` first, then `false`. Verify from the data, not the run log: count `games` with the yssl provider id, and spot-check three teams' game counts against their YSSL pages (record lines such as `0-5-0`).
- [ ] **Step 7:** Close out. Note on the backlog entry about constant-state provenance that YSSL joins WA/OR/PlayMetrics. Clean up the worktree after merge.
