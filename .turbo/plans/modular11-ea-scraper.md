# Modular11 EA Scraper (Step 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For one EA age group per run, scrape the Elite Academy League roster and every team's
season schedule from Modular11, pair the games by match number, and report which EA teams match
teams already in PitchRank. Nothing is written to the database.

**Architecture:** There are two standalone scripts. `scripts/scrape_modular11_ea.py` fetches the
public EA page, parses the embedded roster, pages through each team's schedule, and writes
`teams.csv` and `games.csv`. `scripts/match_modular11_ea_teams.py` reads `teams.csv` and live
`teams` rows read-only, then writes `match_report.csv`. A manual GitHub Action named "EA Scraper"
runs both for a chosen age and uploads the folder as an artifact.

**Tech Stack:** Python 3.11, `requests`, `beautifulsoup4`, `supabase-py`, pytest, and GitHub
Actions.

**Spec:** `.turbo/specs/modular11-ea-scraper.md`

## Global Constraints

- Tournament id `27`. Page `https://www.modular11.com/league-schedule/elite-academy-league`.
  Matches endpoint `https://www.modular11.com/public_schedule/league/get_matches`.
- Age codes: `20=u11, 17=u12, 21=u13, 22=u14, 33=u15, 14=u16, 15=u17, 26=u19`.
- Tiers: `EA`, `EA2`, `EA National`. National is never a team's name tier and never a tier marker.
- Pages are 1-indexed, and `open_page=0` silently returns page 1. Start at 1 and assert that the
  marker's current page equals the requested page.
- `No data available.` means zero games. Any other body without a `page out of` marker raises.
- The roster floor is 1,000 unique teams.
- Decode response bodies as UTF-8 from `.content`, never `.text`.
- No database writes, so no `--dry-run`. Do not touch the MLS NEXT spider,
  `src/models/modular11_matcher.py` or the `modular11-*.yml` workflows.
- Never propose a cross-tier link: an EA team never matches an `EA2` name, and the reverse holds
  too. HD, AD and MLS NEXT names, and existing `modular11` provider rows, are never candidates.
- The workflow is named exactly `EA Scraper`, with `workflow_dispatch` only.
- Lint: `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py`. Tests:
  `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`.

## Review Focus

1. **A club that has two teams at the same age** (Flyte SC vs Flyte SC Blue, academy 1408)
   playing each other. Both team ids must land on the correct sides. This is pinned in Task 3.
2. **A team with no games yet** (`No data available.`) must yield zero games, not crash the run.
   This is pinned in Task 2.
3. **The page-0 alias.** A loop starting at 0 reads page 1 twice and drops the last page. A
   test asserts that the requested `open_page` values are exactly `1..N`. Pinned in Task 2.
4. **Club branches** ("Colorado Rush" vs "Colorado Rush - COS"; `are_same_club` says they are the
   same club). One existing team claimed by two EA clubs must go to review, never to a confident
   link. Pinned in Task 5.
5. **A club name with non-ASCII characters** served without a charset must not mojibake. The fake
   session serves bytes and the test asserts a UTF-8 name. Pinned in Task 2.

## Branch setup (before Task 1)

The shared checkout is on an unrelated branch with uncommitted work. Do **not** stash or switch it.
Per the user's CLAUDE.md worktree exception, run:

```bash
cd /c/PitchRank && git fetch --all --prune
git worktree add ../pitchrank-ea-scraper -b feat/ea-scraper origin/main
cp .turbo/specs/modular11-ea-scraper.md ../pitchrank-ea-scraper/.turbo/specs/
cp .turbo/plans/modular11-ea-scraper.md ../pitchrank-ea-scraper/.turbo/plans/
```
 All work happens in
`C:\pitchrank-ea-scraper`. Root `.env` is needed only for the live smoke run in Task 7; copy it per
the fresh-worktree memory note and never commit it.

---

### Task 1: Roster parser

**Files:**
- Create: `scripts/scrape_modular11_ea.py`
- Create: `tests/fixtures/modular11_ea/ea_page.html` (live capture)
- Test: `tests/unit/test_scrape_modular11_ea_roster.py`

**Interfaces:**
- Produces: `ScrapeError(RuntimeError)`, `AGE_CODES: dict[str, str]`, `NAME_TIERS`,
  `RosterTeam` (frozen dataclass: `provider_team_id, academy_id, club_name, age_group,
  tiers: tuple[str, ...], regions: tuple[str, ...]`, property `name_tier -> str`), and
  `parse_roster(html: str, min_teams: int = MIN_ROSTER_TEAMS) -> list[RosterTeam]`.

- [ ] **Step 1: Capture the live page as a fixture**

```bash
mkdir -p tests/fixtures/modular11_ea
curl -sL -A "Mozilla/5.0" "https://www.modular11.com/league-schedule/elite-academy-league" -o tests/fixtures/modular11_ea/ea_page.html
grep -c "UID_team" tests/fixtures/modular11_ea/ea_page.html   # expect 1667ish
```

- [ ] **Step 2: Write the failing tests**

```python
"""The EA roster parser reads the page's embedded dependencies array."""

from pathlib import Path

import pytest

from scripts.scrape_modular11_ea import ScrapeError, parse_roster

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "modular11_ea" / "ea_page.html"


def _page() -> str:
    return FIXTURE.read_bytes().decode("utf-8")


def test_live_page_yields_every_team_once():
    teams = parse_roster(_page())
    ids = [t.provider_team_id for t in teams]
    assert len(ids) == len(set(ids))
    assert len(ids) == 1239  # count on capture day, 2026-10-04


def test_national_team_carries_both_tiers_and_is_named_ea():
    team = next(t for t in parse_roster(_page()) if t.provider_team_id == "7155")
    assert team.tiers == ("EA", "EA National")
    assert team.name_tier == "EA"
    assert team.age_group == "u13"
    assert team.academy_id == "1386"


def test_flyte_pair_are_two_teams_of_one_club():
    teams = {t.provider_team_id: t for t in parse_roster(_page())}
    assert teams["7343"].academy_id == teams["9176"].academy_id == "1408"
    assert teams["7343"].age_group == teams["9176"].age_group == "u13"


def test_missing_dependencies_raises():
    with pytest.raises(ScrapeError, match="dependencies"):
        parse_roster(_page().replace("dependencies:", "deps_gone:"))


def test_unknown_age_code_raises():
    html = _page().replace('"UID_age":"21"', '"UID_age":"99"', 1)
    with pytest.raises(ScrapeError, match="UID_age"):
        parse_roster(html)


def test_remapped_age_label_raises():
    # Code 21 still exists, but the page now labels it U12: our mapping is stale.
    html = _page().replace('value="21">U13', 'value="21">U12', 1)
    with pytest.raises(ScrapeError, match="UID_age"):
        parse_roster(html)


def test_unknown_academy_raises():
    html = _page().replace('"UID_academy":"1386"', '"UID_academy":"999999"', 1)
    with pytest.raises(ScrapeError, match="UID_academy"):
        parse_roster(html)


def test_below_floor_raises():
    with pytest.raises(ScrapeError, match="floor"):
        parse_roster(_page(), min_teams=5000)
```

Before running, open the fixture and confirm that the exact spellings used by the `replace`
calls are present (for example `value="21">U13` may carry whitespace). Adjust the needle to the
real text, not the parser.

- [ ] **Step 3: Run and confirm failure**

Run: `python -m pytest tests/unit/test_scrape_modular11_ea_roster.py -v`
Expected: FAIL with `ModuleNotFoundError: scripts.scrape_modular11_ea`.

- [ ] **Step 4: Implement**

```python
#!/usr/bin/env python3
"""Scrape one age group of the Modular11 Elite Academy League (EA): roster and games.

EA is Modular11 tournament 27, separate from the MLS NEXT spider. The public league page embeds
the whole roster as a ``dependencies:`` array; each team's season comes from ``get_matches``
filtered by ``team=<id>``. Writes ``<out-dir>/<age>/teams.csv`` and ``games.csv``. Read-only
against the database (it never touches it).

Usage:
    python scripts/scrape_modular11_ea.py --age u11
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from bs4 import BeautifulSoup

EA_PAGE_URL = "https://www.modular11.com/league-schedule/elite-academy-league"
MATCHES_URL = "https://www.modular11.com/public_schedule/league/get_matches"
TOURNAMENT_ID = "27"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PitchRank/1.0)"}
MIN_ROSTER_TEAMS = 1000
AGE_CODES = {"20": "u11", "17": "u12", "21": "u13", "22": "u14", "33": "u15", "14": "u16", "15": "u17", "26": "u19"}
NAME_TIERS = ("EA", "EA2")


class ScrapeError(RuntimeError):
    """The page or an API response no longer has the shape this scraper reads."""


@dataclass(frozen=True)
class RosterTeam:
    provider_team_id: str
    academy_id: str
    club_name: str
    age_group: str
    tiers: tuple[str, ...]
    regions: tuple[str, ...]

    @property
    def name_tier(self) -> str:
        return next(t for t in NAME_TIERS if t in self.tiers)


def _select_options(soup: BeautifulSoup, marker: str) -> dict[str, str]:
    select = soup.find("select", attrs={marker: True})
    if select is None:
        raise ScrapeError(f"page has no <select {marker}>")
    return {
        option["value"]: option.get_text(strip=True)
        for option in select.find_all("option")
        if option.get("value") not in (None, "0")
    }


def _dependencies(html: str) -> list[dict]:
    start = html.find("dependencies:")
    if start < 0:
        raise ScrapeError("page has no dependencies: array")
    try:
        rows, _ = json.JSONDecoder().raw_decode(html, html.index("[", start))
    except ValueError as exc:
        raise ScrapeError(f"dependencies: array does not parse: {exc}") from exc
    return rows


def parse_roster(html: str, min_teams: int = MIN_ROSTER_TEAMS) -> list[RosterTeam]:
    soup = BeautifulSoup(html, "html.parser")
    tables = {
        "UID_bracket": _select_options(soup, "js-brackets"),
        "UID_academy": _select_options(soup, "js-academy"),
        "UID_group": _select_options(soup, "js-groups"),
    }
    age_labels = _select_options(soup, "js-age")
    merged: dict[str, dict] = {}
    for row in _dependencies(html):
        team_id = str(row.get("UID_team"))
        for key, table in tables.items():
            if str(row.get(key)) not in table:
                raise ScrapeError(f"unknown {key} {row.get(key)!r} for team {team_id}")
        age_code = str(row.get("UID_age"))
        age = AGE_CODES.get(age_code)
        if age is None or age_labels.get(age_code) != age.upper():
            raise ScrapeError(f"unknown UID_age {age_code!r} (page label {age_labels.get(age_code)!r}) for team {team_id}")
        academy = str(row["UID_academy"])
        entry = merged.setdefault(team_id, {"academy": academy, "age": age, "tiers": set(), "regions": set()})
        if (entry["academy"], entry["age"]) != (academy, age):
            raise ScrapeError(f"team {team_id} listed under two clubs or ages")
        entry["tiers"].add(tables["UID_bracket"][str(row["UID_bracket"])])
        entry["regions"].add(tables["UID_group"][str(row["UID_group"])])
    if len(merged) < min_teams:
        raise ScrapeError(f"{len(merged)} teams is below the floor of {min_teams}")
    teams = []
    for team_id, entry in merged.items():
        if not entry["tiers"] & set(NAME_TIERS):
            raise ScrapeError(f"team {team_id} plays in neither EA nor EA2: {sorted(entry['tiers'])}")
        teams.append(
            RosterTeam(
                provider_team_id=team_id,
                academy_id=entry["academy"],
                club_name=tables["UID_academy"][entry["academy"]],
                age_group=entry["age"],
                tiers=tuple(sorted(entry["tiers"])),
                regions=tuple(sorted(entry["regions"])),
            )
        )
    return sorted(teams, key=lambda t: (t.age_group, t.club_name, t.provider_team_id))
```

- [ ] **Step 5: Run and confirm the tests pass.** Run the same command. Expected: 8 passed.
  Mutation check: change `age.upper()` to `age_labels.get(age_code)` and confirm that
  `test_remapped_age_label_raises` is among the failing tests. Revert, then delete `.pyc` per the
  stale-pyc memory note.

- [ ] **Step 6: Commit**

```bash
git add scripts/scrape_modular11_ea.py tests/unit/test_scrape_modular11_ea_roster.py tests/fixtures/modular11_ea/ea_page.html
git commit -m "Parse the Elite Academy League roster from Modular11's league page"
```

---

### Task 2: Schedule page parser and paging fetch

**Files:**
- Modify: `scripts/scrape_modular11_ea.py`
- Create: `tests/fixtures/modular11_ea/team_7343_p1.html` and `team_9176_p1.html` (live captures)
- Test: `tests/unit/test_scrape_modular11_ea_schedule.py`

**Interfaces:**
- Consumes: `ScrapeError`, `MATCHES_URL`, `TOURNAMENT_ID`, `HEADERS` from Task 1.
- Produces: `ScheduleRow` (frozen dataclass: `match_no, gender, game_date (YYYY-MM-DD), bracket,
  region, age_label, home_name, home_academy: str | None, away_name, away_academy: str | None,
  home_score: int | None, away_score: int | None`),
  `parse_schedule_page(html: str, expected_page: int) -> tuple[list[ScheduleRow], int]`,
  `fetch_team_schedule(session, team_id: str, start: str, end: str, delay: float = 1.0,
  sleep=time.sleep) -> list[ScheduleRow]`.

- [ ] **Step 1: Capture the fixtures**

```bash
for t in 7343 9176; do curl -s -A "Mozilla/5.0" "https://www.modular11.com/public_schedule/league/get_matches?open_page=1&academy=0&tournament=27&gender=0&age=0&brackets=&groups=&group=&match_number=0&status=all&match_type=2&schedule=0&team=$t&teamPlayer=0&location=0&as_referee=0&start_date=2026-08-01%2000:00:00&end_date=2027-07-31%2023:59:59" -o tests/fixtures/modular11_ea/team_${t}_p1.html; done
```

- [ ] **Step 2: Write the failing tests**

```python
"""EA schedule pages: row parsing, 1-indexed paging, empty schedules, UTF-8 bodies."""

from pathlib import Path

import pytest
import requests

from scripts.scrape_modular11_ea import MATCHES_URL, ScrapeError, fetch_team_schedule, parse_schedule_page

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "modular11_ea"
EMPTY = b" No data available. "


def _fixture(name: str) -> str:
    return (FIX / name).read_bytes().decode("utf-8")


class _Resp:
    def __init__(self, body: bytes, status: int = 200):
        self.content = body
        self.status_code = status

    @property
    def text(self):  # requests guesses ISO-8859-1 for a charset-less HTML body
        return self.content.decode("iso-8859-1")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class _Session:
    """Serves bodies by open_page and records url, params, headers and timeout of every call."""

    def __init__(self, pages: dict[int, bytes]):
        self.pages = pages
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": headers, "timeout": timeout})
        return _Resp(self.pages[int(params["open_page"])])  # KeyError on an unplanned page


def _paged(current: int, total: int, rows: str = "") -> bytes:
    return f"<div>{rows}</div><span>{current} page out of {total}</span>".encode("utf-8")


def test_parses_played_and_tbd_rows():
    rows, total = parse_schedule_page(_fixture("team_7343_p1.html"), expected_page=1)
    assert total == 1 and len(rows) == 20
    first = next(r for r in rows if r.match_no == "122957")
    assert (first.home_name, first.home_academy, first.away_academy) == ("FLYTE SC- Inland Empire", "1408", "101")
    assert (first.home_score, first.away_score) == (6, 0)
    assert first.game_date == "2026-09-12" and first.bracket == "EA" and first.gender == "MALE"
    later = next(r for r in rows if r.match_no == "123251")
    assert (later.home_score, later.away_score) == (None, None)


def test_intra_club_row_keeps_both_names():
    rows, _ = parse_schedule_page(_fixture("team_7343_p1.html"), expected_page=1)
    derby = next(r for r in rows if r.match_no == "123269")
    assert derby.home_academy == derby.away_academy == "1408"
    assert {derby.home_name, derby.away_name} == {"FLYTE SC Blue- Inland Empire", "FLYTE SC- Inland Empire"}


def test_no_data_is_zero_games():
    assert parse_schedule_page(EMPTY.decode(), expected_page=1) == ([], 0)


def test_markerless_body_raises():
    with pytest.raises(ScrapeError, match="page out of"):
        parse_schedule_page("<html>maintenance</html>", expected_page=1)


def test_wrong_current_page_raises():
    with pytest.raises(ScrapeError, match="asked for page 2"):
        parse_schedule_page(_paged(1, 3).decode(), expected_page=2)


def test_fetch_requests_pages_one_through_n_exactly():
    session = _Session({1: _paged(1, 3), 2: _paged(2, 3), 3: _paged(3, 3)})
    fetch_team_schedule(session, "7343", "2026-08-01 00:00:00", "2027-07-31 23:59:59", sleep=lambda s: None)
    assert [c["params"]["open_page"] for c in session.calls] == [1, 2, 3]
    call = session.calls[0]
    assert call["url"] == MATCHES_URL
    assert call["params"]["team"] == "7343" and call["params"]["tournament"] == "27"
    assert call["params"]["start_date"] == "2026-08-01 00:00:00"
    assert call["timeout"] == 30 and "User-Agent" in call["headers"]


def test_fetch_empty_team_makes_one_call():
    session = _Session({1: EMPTY})
    assert fetch_team_schedule(session, "1", "a", "b", sleep=lambda s: None) == []
    assert len(session.calls) == 1


def test_fetch_decodes_utf8_names():
    body = (FIX / "team_7343_p1.html").read_bytes().replace(b"ALBION SC San Diego", "Atlético SD".encode("utf-8"))
    session = _Session({1: body})
    rows = fetch_team_schedule(session, "7343", "a", "b", sleep=lambda s: None)
    assert any(r.away_name == "Atlético SD" for r in rows)
```

- [ ] **Step 3: Run and confirm failure.** Expected: ImportError for `ScheduleRow` and the others.

- [ ] **Step 4: Implement** by appending to `scripts/scrape_modular11_ea.py`, with these imports
  added at the top: `html as htmllib`, `re`, `time`, `datetime.date`.

```python
PAGE_RE = re.compile(r"(\d+)\s*page\s*out\s*of\s*(\d+)")
SCORE_RE = re.compile(r"^(\d+)\s*:\s*(\d+)$")
DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{2})")
CREST_RE = re.compile(r"/academy/(\d+)/")
NO_DATA = "No data available."


@dataclass(frozen=True)
class ScheduleRow:
    match_no: str
    gender: str
    game_date: str
    bracket: str
    region: str
    age_label: str
    home_name: str
    home_academy: str | None
    away_name: str
    away_academy: str | None
    home_score: int | None
    away_score: int | None


def _crest_academy(node) -> str | None:
    match = CREST_RE.search(node.get("style", ""))
    return match.group(1) if match else None


def _parse_row(row) -> ScheduleRow:
    cols = row.find_all("div", recursive=False)
    head = cols[0].get_text(" ", strip=True).split()
    date_match = DATE_RE.search(cols[1].get_text(" ", strip=True))
    names = [p.get("data-title", "").strip() for p in row.select(".container-first-team p, .container-second-team p")]
    crests = [_crest_academy(node) for node in row.select(".club-photo")]
    if len(head) < 2 or date_match is None or len(names) != 2 or len(crests) != 2:
        raise ScrapeError(f"unreadable match row: {row.get_text(' ', strip=True)[:120]}")
    mm, dd, yy = date_match.groups()
    score_node = row.select_one(".score-match-table")
    score_text = htmllib.unescape(score_node.get_text()).replace("\xa0", " ").strip() if score_node else ""
    score = SCORE_RE.match(score_text)
    return ScheduleRow(
        match_no=head[0],
        gender=head[1],
        game_date=date(2000 + int(yy), int(mm), int(dd)).isoformat(),
        bracket=row.get("js-match-bracket", ""),
        region=row.get("js-match-group", ""),
        age_label=cols[2].get_text(strip=True),
        home_name=names[0],
        home_academy=crests[0],
        away_name=names[1],
        away_academy=crests[1],
        home_score=int(score.group(1)) if score else None,
        away_score=int(score.group(2)) if score else None,
    )


def parse_schedule_page(html: str, expected_page: int) -> tuple[list[ScheduleRow], int]:
    marker = PAGE_RE.search(html)
    if marker is None:
        if NO_DATA in html:
            return [], 0
        raise ScrapeError("schedule response has no 'page out of' marker and no 'No data available.'")
    current, total = int(marker.group(1)), int(marker.group(2))
    if current != expected_page:
        raise ScrapeError(f"asked for page {expected_page}, got page {current} of {total}")
    soup = BeautifulSoup(html, "html.parser")
    return [_parse_row(r) for r in soup.select("div.table-content-row.hidden-xs")], total


def _match_params(team_id: str, page: int, start: str, end: str) -> dict:
    return {
        "open_page": page, "academy": 0, "tournament": TOURNAMENT_ID, "gender": 0, "age": 0,
        "brackets": "", "groups": "", "group": "", "match_number": 0, "status": "all",
        "match_type": 2, "schedule": 0, "team": team_id, "teamPlayer": 0, "location": 0,
        "as_referee": 0, "start_date": start, "end_date": end,
    }


def fetch_team_schedule(session, team_id: str, start: str, end: str, delay: float = 1.0, sleep=time.sleep) -> list[ScheduleRow]:
    """Every row of one team's season. Pages are 1-indexed: open_page=0 aliases page 1."""
    rows: list[ScheduleRow] = []
    page, total = 1, 1
    while page <= total:
        response = session.get(MATCHES_URL, params=_match_params(team_id, page, start, end), headers=HEADERS, timeout=30)
        response.raise_for_status()
        page_rows, total = parse_schedule_page(response.content.decode("utf-8"), expected_page=page)
        rows.extend(page_rows)
        page += 1
        sleep(delay)
    return rows
```

- [ ] **Step 5: Run and confirm the tests pass.** Expected: 8 passed. Then mutate each of the
  following one at a time and confirm the named test fails:
  `page, total = 1, 1` → `0, 1` (fails `..._one_through_n_exactly`);
  `.content.decode("utf-8")` → `.text` (fails `test_fetch_decodes_utf8_names`); and removing the
  `current != expected_page` check (fails `test_wrong_current_page_raises`).

- [ ] **Step 6: Commit**

```bash
git add scripts/scrape_modular11_ea.py tests/unit/test_scrape_modular11_ea_schedule.py tests/fixtures/modular11_ea/team_7343_p1.html tests/fixtures/modular11_ea/team_9176_p1.html
git commit -m "Read each EA team's season from Modular11, paging from 1"
```

---

### Task 3: Display names and game pairing

**Files:**
- Modify: `scripts/scrape_modular11_ea.py`
- Test: `tests/unit/test_scrape_modular11_ea_pairing.py`

**Interfaces:**
- Consumes: `RosterTeam`, `ScheduleRow`, `parse_roster`, `parse_schedule_page`.
- Produces: `team_display_name(team: RosterTeam, rows: list[ScheduleRow]) -> str`;
  `GameRow` (frozen dataclass: `match_no, game_date, age_group, bracket, region, home_team_id,
  away_team_id, home_name, away_name, home_academy, away_academy, home_score, away_score, status,
  pairing`), where `status` is `played` or `scheduled` and `pairing` is `both`, `one_sided` or
  `unresolved`; and
  `pair_games(teams: list[RosterTeam], schedules: dict[str, list[ScheduleRow]], age_group: str)
  -> list[GameRow]`.

- [ ] **Step 1: Write the failing tests** (they use the real fixtures from Tasks 1–2)

```python
"""Pairing by match number puts both team ids on the right sides, including an intra-club derby."""

from pathlib import Path

from scripts.scrape_modular11_ea import pair_games, parse_roster, parse_schedule_page, team_display_name

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "modular11_ea"


def _roster():
    return {t.provider_team_id: t for t in parse_roster((FIX / "ea_page.html").read_bytes().decode("utf-8"))}


def _rows(team_id):
    return parse_schedule_page((FIX / f"team_{team_id}_p1.html").read_bytes().decode("utf-8"), expected_page=1)[0]


def test_display_names_differ_within_one_club():
    roster = _roster()
    assert team_display_name(roster["7343"], _rows("7343")) == "FLYTE SC- Inland Empire"
    assert team_display_name(roster["9176"], _rows("9176")) == "FLYTE SC Blue- Inland Empire"


def test_display_name_falls_back_when_no_games():
    team = _roster()["7343"]
    assert team_display_name(team, []) == "FLYTE SC- Inland Empire U13 EA"  # academy 1408's page label


def test_derby_gets_both_ids_on_correct_sides():
    roster = _roster()
    games = pair_games([roster["7343"], roster["9176"]], {"7343": _rows("7343"), "9176": _rows("9176")}, "u13")
    derby = next(g for g in games if g.match_no == "123269")
    assert (derby.home_team_id, derby.away_team_id) == ("9176", "7343")
    assert derby.pairing == "both" and derby.status == "scheduled"


def test_opponent_outside_scrape_is_one_sided():
    roster = _roster()
    games = pair_games([roster["7343"]], {"7343": _rows("7343")}, "u13")
    first = next(g for g in games if g.match_no == "122957")
    assert (first.home_team_id, first.away_team_id, first.pairing) == ("7343", "", "one_sided")
    assert (first.home_score, first.away_score, first.status) == (6, 0, "played")


def test_each_match_appears_once():
    roster = _roster()
    games = pair_games([roster["7343"], roster["9176"]], {"7343": _rows("7343"), "9176": _rows("9176")}, "u13")
    assert len(games) == len({g.match_no for g in games}) == 39  # 20 + 20 - 1 shared derby
```

- [ ] **Step 2: Run and confirm failure.** Expected: ImportError.

- [ ] **Step 3: Implement** (add `from collections import Counter, defaultdict`)

```python
@dataclass(frozen=True)
class GameRow:
    match_no: str
    game_date: str
    age_group: str
    bracket: str
    region: str
    home_team_id: str
    away_team_id: str
    home_name: str
    away_name: str
    home_academy: str
    away_academy: str
    home_score: int | None
    away_score: int | None
    status: str
    pairing: str


def _sides(row: ScheduleRow):
    return (("home", row.home_name, row.home_academy), ("away", row.away_name, row.away_academy))


def team_display_name(team: RosterTeam, rows: list[ScheduleRow]) -> str:
    """The name this team plays under: its side in games against other clubs."""
    names = Counter()
    for row in rows:
        own = [name for _, name, academy in _sides(row) if academy == team.academy_id]
        if len(own) == 1:
            names[own[0]] += 1
    if names:
        return names.most_common(1)[0][0]
    return f"{team.club_name} {team.age_group.upper()} {team.name_tier}"


def _side_of(team: RosterTeam, display: str, row: ScheduleRow) -> str | None:
    by_academy = [side for side, _, academy in _sides(row) if academy == team.academy_id]
    if len(by_academy) == 1:
        return by_academy[0]
    pool = by_academy or [side for side, _, _ in _sides(row)]
    by_name = [side for side, name, _ in _sides(row) if side in pool and name == display]
    return by_name[0] if len(by_name) == 1 else None


def pair_games(teams: list[RosterTeam], schedules: dict[str, list[ScheduleRow]], age_group: str) -> list[GameRow]:
    by_id = {t.provider_team_id: t for t in teams}
    display = {tid: team_display_name(by_id[tid], rows) for tid, rows in schedules.items()}
    first_seen: dict[str, ScheduleRow] = {}
    claims: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"home": set(), "away": set()})
    for tid, rows in schedules.items():
        for row in rows:
            first_seen.setdefault(row.match_no, row)
            side = _side_of(by_id[tid], display[tid], row)
            if side:
                claims[row.match_no][side].add(tid)
    games = []
    for match_no, row in sorted(first_seen.items()):
        home, away = claims[match_no]["home"], claims[match_no]["away"]
        home_id = next(iter(home)) if len(home) == 1 else ""
        away_id = next(iter(away)) if len(away) == 1 else ""
        if len(home) > 1 or len(away) > 1 or not (home_id or away_id):
            pairing = "unresolved"
        else:
            pairing = "both" if home_id and away_id else "one_sided"
        games.append(
            GameRow(
                match_no=match_no, game_date=row.game_date, age_group=age_group, bracket=row.bracket,
                region=row.region, home_team_id=home_id, away_team_id=away_id, home_name=row.home_name,
                away_name=row.away_name, home_academy=row.home_academy or "", away_academy=row.away_academy or "",
                home_score=row.home_score, away_score=row.away_score,
                status="played" if row.home_score is not None else "scheduled", pairing=pairing,
            )
        )
    return games
```

- [ ] **Step 4: Run and confirm the tests pass.** Then mutate `_side_of` to return
  `by_academy[0]` whenever `by_academy` is non-empty. `test_derby_gets_both_ids_on_correct_sides`
  must fail. Revert.

- [ ] **Step 5: Commit**: `git add` the script and test, then
  `git commit -m "Pair EA games by match number so both team ids are known"`.

---

### Task 4: Scraper CLI

**Files:**
- Modify: `scripts/scrape_modular11_ea.py`
- Test: `tests/unit/test_scrape_modular11_ea_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `season_bounds(today: date) -> tuple[str, str]`;
  `run(age: str, out_dir: Path, session, today: date, delay: float = 1.0, sleep=time.sleep)
  -> dict[str, int]` with keys `teams, games, played, scheduled, one_sided, unresolved`;
  `main(argv: list[str] | None = None) -> int`.
  The files are `out_dir/<age>/teams.csv` (columns `provider_team_id, academy_id, club_name,
  display_name, age_group, tiers, regions, gender`) and `out_dir/<age>/games.csv` (the `GameRow`
  fields in declaration order).

- [ ] **Step 1: Write the failing tests.** Drive `run` end to end through a session that serves the
  EA page for `EA_PAGE_URL` and per-team bodies keyed by `params["team"]`. Two U13 teams get the
  real fixtures, and every other U13 team gets `No data available.`.

```python
"""run() drives page fetch → roster filter → per-team schedules → CSVs; failures leave no files."""

import csv
from datetime import date
from pathlib import Path

import pytest

from scripts import scrape_modular11_ea as ea

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "modular11_ea"


class _Resp:
    def __init__(self, body: bytes):
        self.content, self.status_code = body, 200

    def raise_for_status(self):
        pass


class _Session:
    def __init__(self, page: bytes):
        self.page, self.calls = page, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if url == ea.EA_PAGE_URL:
            return _Resp(self.page)
        path = FIX / f"team_{params['team']}_p1.html"
        return _Resp(path.read_bytes() if path.exists() else b"No data available.")


def test_season_bounds_rolls_on_aug_1():
    assert ea.season_bounds(date(2026, 7, 31)) == ("2025-08-01 00:00:00", "2026-07-31 23:59:59")
    assert ea.season_bounds(date(2026, 8, 1)) == ("2026-08-01 00:00:00", "2027-07-31 23:59:59")


def test_run_writes_one_age(tmp_path):
    session = _Session((FIX / "ea_page.html").read_bytes())
    counts = ea.run("u13", tmp_path, session, date(2026, 10, 4), sleep=lambda s: None)
    teams = list(csv.DictReader((tmp_path / "u13" / "teams.csv").open(encoding="utf-8")))
    assert {t["age_group"] for t in teams} == {"u13"}
    assert len(teams) == counts["teams"] == len([c for c in session.calls if c[0] == ea.MATCHES_URL])
    flyte = next(t for t in teams if t["provider_team_id"] == "9176")
    assert flyte["display_name"] == "FLYTE SC Blue- Inland Empire" and flyte["gender"] == "Male"
    games = list(csv.DictReader((tmp_path / "u13" / "games.csv").open(encoding="utf-8")))
    assert counts["games"] == len(games) == 39


def test_failure_exits_1_and_writes_nothing(tmp_path, monkeypatch):
    page = (FIX / "ea_page.html").read_bytes().replace(b"dependencies:", b"gone:")
    monkeypatch.setattr(ea, "_new_session", lambda: _Session(page))
    assert ea.main(["--age", "u13", "--out-dir", str(tmp_path)]) == 1
    assert not (tmp_path / "u13").exists()


def test_female_row_fails_the_run(tmp_path, monkeypatch):
    original = (FIX / "team_7343_p1.html").read_bytes()
    flipped = original.replace(b"MALE", b"FEMALE", 1)
    session = _Session((FIX / "ea_page.html").read_bytes())
    real_get = session.get

    def get(url, params=None, headers=None, timeout=None):
        if params and params.get("team") == "7343":
            session.calls.append((url, dict(params)))
            return _Resp(flipped)
        return real_get(url, params=params, headers=headers, timeout=timeout)

    session.get = get
    with pytest.raises(ea.ScrapeError, match="FEMALE"):
        ea.run("u13", tmp_path, session, date(2026, 10, 4), sleep=lambda s: None)
    assert not (tmp_path / "u13").exists()
```

`main` must build its session through a module-level `_new_session()`, so tests can replace it.

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement** (add `argparse`, `csv`, `sys`, `pathlib.Path`, `dataclasses.asdict`
  and `requests` imports).

```python
TEAM_COLUMNS = ["provider_team_id", "academy_id", "club_name", "display_name", "age_group", "tiers", "regions", "gender"]


def season_bounds(today: date) -> tuple[str, str]:
    year = today.year if today.month >= 8 else today.year - 1
    return f"{year}-08-01 00:00:00", f"{year + 1}-07-31 23:59:59"


def _new_session() -> requests.Session:
    return requests.Session()


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run(age: str, out_dir: Path, session, today: date, delay: float = 1.0, sleep=time.sleep) -> dict[str, int]:
    page = session.get(EA_PAGE_URL, headers=HEADERS, timeout=30)
    page.raise_for_status()
    teams = [t for t in parse_roster(page.content.decode("utf-8")) if t.age_group == age]
    if not teams:
        raise ScrapeError(f"the EA roster has no {age} teams")
    start, end = season_bounds(today)
    schedules = {t.provider_team_id: fetch_team_schedule(session, t.provider_team_id, start, end, delay, sleep) for t in teams}
    games = pair_games(teams, schedules, age)
    target = out_dir / age
    target.mkdir(parents=True, exist_ok=True)
    _write_csv(target / "teams.csv", TEAM_COLUMNS, [
        {
            "provider_team_id": t.provider_team_id, "academy_id": t.academy_id, "club_name": t.club_name,
            "display_name": team_display_name(t, schedules[t.provider_team_id]), "age_group": t.age_group,
            "tiers": ";".join(t.tiers), "regions": ";".join(t.regions), "gender": "Male",
        }
        for t in teams
    ])
    _write_csv(target / "games.csv", list(GameRow.__dataclass_fields__), [asdict(g) for g in games])
    return {
        "teams": len(teams), "games": len(games),
        "played": sum(g.status == "played" for g in games), "scheduled": sum(g.status == "scheduled" for g in games),
        "one_sided": sum(g.pairing == "one_sided" for g in games), "unresolved": sum(g.pairing == "unresolved" for g in games),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--age", required=True, choices=sorted(set(AGE_CODES.values())))
    parser.add_argument("--out-dir", type=Path, default=Path("data/modular11_ea"))
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between schedule requests")
    args = parser.parse_args(argv)
    try:
        counts = run(args.age, args.out_dir, _new_session(), date.today(), args.delay)
    except (ScrapeError, requests.RequestException) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(" ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Insert this into `run`, between building `schedules` and calling `pair_games`. The spec says to
assert boys-only rather than assume it; the `gender` column then holds the stored form, `Male`:

```python
    genders = {row.gender for rows in schedules.values() for row in rows}
    if genders - {"MALE"}:
        raise ScrapeError(f"EA rows with gender {sorted(genders - {'MALE'})}; this scraper assumes boys only")
```

- [ ] **Step 4: Run and confirm the tests pass**, then run ruff on the file.
- [ ] **Step 5: Commit**: `git commit -m "Add the EA scraper command: one age per run, CSVs only on success"`.

---

### Task 5: Match rules

**Files:**
- Create: `scripts/match_modular11_ea_teams.py`
- Test: `tests/unit/test_match_modular11_ea_rules.py`

**Interfaces:**
- Produces: `tier_marker(name: str) -> str | None`; `is_protected(name: str) -> bool`;
  `EaTeam` (frozen dataclass: `provider_team_id, club_name, display_name, age_group,
  tiers: frozenset[str]`); `ReportRow` (frozen dataclass: `ea: EaTeam, bucket: str, reason: str,
  candidates: tuple[dict, ...]`); and
  `classify(ea_teams: list[EaTeam], db_teams: list[dict]) -> list[ReportRow]`, where each
  `db_teams` dict has `team_id_master, team_name, club_name, state_code, provider_code`.
- Buckets: `confident`, `review`, `no_match`.

- [ ] **Step 1: Write the failing tests.** Use one fixture row per rule, each breaking exactly one
  condition.

```python
"""Same-club, same-age, same-tier rules for linking EA teams to existing ones."""

from scripts.match_modular11_ea_teams import EaTeam, classify, is_protected, tier_marker


def _ea(tid="1", club="Emerald City FC", tiers=("EA",)):
    return EaTeam(provider_team_id=tid, club_name=club, display_name=club, age_group="u13", tiers=frozenset(tiers))


def _db(tid, name, club="Emerald City FC"):
    return {"team_id_master": tid, "team_name": name, "club_name": club, "state_code": "WA", "provider_code": "gotsport"}


def test_tier_marker_whole_words():
    assert tier_marker("Emerald City 2014 EA") == "EA"
    assert tier_marker("Emerald City 2014 EA2") == "EA2"
    assert tier_marker("Seattle Sea Hawks 2014") is None
    assert tier_marker("Emerald City 2014 Team") is None


def test_protected_names():
    assert is_protected("Sparta 2014 HD") and is_protected("Sparta U13 AD") and is_protected("Sparta MLS NEXT")
    assert not is_protected("Sparta 2014 EA")


def test_single_tagged_candidate_is_confident():
    [row] = classify([_ea()], [_db("a", "Emerald City FC 2014 EA")])
    assert row.bucket == "confident" and [c["team_id_master"] for c in row.candidates] == ["a"]


def test_ea2_name_is_not_a_candidate_for_ea_team():
    [row] = classify([_ea()], [_db("a", "Emerald City FC 2014 EA2")])
    assert row.bucket == "no_match"


def test_ea_name_is_not_a_candidate_for_ea2_team():
    [row] = classify([_ea(tiers=("EA2",))], [_db("a", "Emerald City FC 2014 EA")])
    assert row.bucket == "no_match"


def test_two_tagged_candidates_go_to_review():
    [row] = classify([_ea()], [_db("a", "Emerald City FC 2014 EA"), _db("b", "Emerald City FC B14 EA")])
    assert row.bucket == "review" and len(row.candidates) == 2


def test_untagged_same_club_goes_to_review():
    [row] = classify([_ea()], [_db("a", "Emerald City FC 2014 Blue")])
    assert row.bucket == "review" and "no EA tier" in row.reason


def test_other_club_is_no_match():
    [row] = classify([_ea()], [_db("a", "Sparta Tacoma 2014 EA", club="Sparta Tacoma")])
    assert row.bucket == "no_match"


def test_candidate_claimed_by_two_ea_clubs_goes_to_review():
    # are_same_club treats a club and its branch as one; the shared claim must block a confident link.
    rush = _ea("1", club="Colorado Rush")
    cos = _ea("2", club="Colorado Rush - COS")
    rows = classify([rush, cos], [_db("a", "Colorado Rush 2014 EA", club="Colorado Rush")])
    assert {r.ea.provider_team_id: r.bucket for r in rows} == {"1": "review", "2": "review"}
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
"""Report which EA teams of one age match teams PitchRank already holds. Read-only.

A link is proposed only when the club, the age and the EA tier all agree: an EA team never
matches an EA2 name, and HD/AD/MLS NEXT names and modular11 rows are never candidates. This is
its own same-tier rule; it does not loosen ``has_protected_division``.

Usage:
    python scripts/match_modular11_ea_teams.py --age u11
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

from src.utils.club_normalizer import are_same_club

EA2_RE = re.compile(r"\bEA2\b", re.IGNORECASE)
EA_RE = re.compile(r"\bEA\b", re.IGNORECASE)
PROTECTED_RE = re.compile(r"\b(?:HD|AD|MLS\s*NEXT)\b", re.IGNORECASE)


def tier_marker(name: str) -> str | None:
    if EA2_RE.search(name):
        return "EA2"
    if EA_RE.search(name):
        return "EA"
    return None


def is_protected(name: str) -> bool:
    return bool(PROTECTED_RE.search(name))


@dataclass(frozen=True)
class EaTeam:
    provider_team_id: str
    club_name: str
    display_name: str
    age_group: str
    tiers: frozenset[str]


@dataclass(frozen=True)
class ReportRow:
    ea: EaTeam
    bucket: str
    reason: str
    candidates: tuple[dict, ...]


@lru_cache(maxsize=None)
def _same_club(ea_club: str, db_club: str) -> bool:
    return are_same_club(ea_club, db_club)


def _club_hits(ea: EaTeam, db_teams: list[dict]) -> list[dict]:
    return [d for d in db_teams if _same_club(ea.club_name, d.get("club_name") or d["team_name"])]


def classify(ea_teams: list[EaTeam], db_teams: list[dict]) -> list[ReportRow]:
    hits = {ea.provider_team_id: _club_hits(ea, db_teams) for ea in ea_teams}
    tagged = {
        ea.provider_team_id: [d for d in hits[ea.provider_team_id] if tier_marker(d["team_name"]) in ea.tiers]
        for ea in ea_teams
    }
    claims: dict[str, set[str]] = defaultdict(set)
    for ea_id, candidates in tagged.items():
        for candidate in candidates:
            claims[candidate["team_id_master"]].add(ea_id)
    rows = []
    for ea in ea_teams:
        mine = tagged[ea.provider_team_id]
        shared = sorted({other for c in mine for other in claims[c["team_id_master"]]} - {ea.provider_team_id})
        if len(mine) == 1 and not shared:
            rows.append(ReportRow(ea, "confident", "one same-club, same-age, same-tier team", tuple(mine)))
        elif mine:
            reason = f"{len(mine)} candidates" if len(mine) > 1 else f"candidate also fits EA team(s) {', '.join(shared)}"
            rows.append(ReportRow(ea, "review", reason, tuple(mine)))
        else:
            untagged = [d for d in hits[ea.provider_team_id] if tier_marker(d["team_name"]) is None]
            if untagged:
                rows.append(ReportRow(ea, "review", "club and age match, no EA tier in name", tuple(untagged)))
            else:
                rows.append(ReportRow(ea, "no_match", "", ()))
    return rows
```

- [ ] **Step 4: Run and confirm the tests pass.** Then mutate one conjunct at a time and confirm
  that the named test fails each time:
  - drop `and not shared` → `..._claimed_by_two_ea_clubs_...`
  - check `EA_RE` before `EA2_RE` → `test_tier_marker_whole_words`, `test_ea2_name_is_not_a_candidate_for_ea_team`
  - `in ea.tiers` → `is not None` → both cross-tier tests

- [ ] **Step 5: Commit**: `git commit -m "Add same-tier match rules for EA teams"`.

---

### Task 6: Match report command (fetch + CSV)

**Files:**
- Modify: `scripts/match_modular11_ea_teams.py`
- Test: `tests/unit/test_match_modular11_ea_report.py`

**Interfaces:**
- Consumes: `classify`, `EaTeam`, `is_protected`; and `teams.csv` from Task 4.
- Produces: `fetch_db_teams(sb, age_group: str) -> list[dict]`; `run(age: str, in_dir: Path, sb)
  -> dict[str, int]` with keys `confident, review, no_match`; `main(argv=None) -> int`; and the
  file `in_dir/<age>/match_report.csv` with columns `provider_team_id, club_name, display_name,
  tiers, bucket, reason, candidate_ids, candidate_names, candidate_clubs, candidate_providers,
  candidate_states`, where the lists are `|`-joined.

- [ ] **Step 1: Write the failing tests.** Copy `_Db` from
  `tests/unit/test_playmetrics_matcher_row_state.py` and adapt it. The double must record at
  `execute()` and must model ordered `.range()` paging: it returns slices of a row list and records
  each executed `(filters, order, range)`. Drive `run()` end to end.

```python
"""run() fetches live, same-age, male, non-protected, non-modular11 teams in ordered pages."""

import csv
from pathlib import Path

from scripts import match_modular11_ea_teams as m


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.order_by, self.window = db, table, [], None, None

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def or_(self, expr):
        # Honour only the exact live-row filter the implementation sends; anything else is refused.
        assert expr == "is_deprecated.is.null,is_deprecated.eq.false", f"unexpected or_ filter {expr!r}"
        self.filters.append(("live",))
        return self

    def order(self, col):
        self.order_by = col
        return self

    def range(self, lo, hi):
        self.window = (lo, hi)
        return self

    def execute(self):
        self.db.executed.append((self.table, list(self.filters), self.order_by, self.window))
        rows = [r for r in self.db.rows[self.table] if all(f[0] != "eq" or r.get(f[1]) == f[2] for f in self.filters)]
        if self.table == "teams":
            assert self.order_by == "team_id_master", "paging without a unique order skips rows"
            if ("live",) in self.filters:
                rows = [r for r in rows if r.get("is_deprecated") is not True]
            rows = sorted(rows, key=lambda r: r["team_id_master"])
            lo, hi = self.window
            rows = rows[lo : hi + 1]
        return type("R", (), {"data": rows})()


class _Db:
    def __init__(self, teams, providers):
        self.rows = {"teams": teams, "providers": providers}
        self.executed = []

    def table(self, name):
        return _Query(self, name)


GOT, M11 = "p-got", "p-m11"


def _team(tid, name, club="Emerald City FC", age="u13", gender="Male", provider=GOT, deprecated=None):
    return {"team_id_master": tid, "team_name": name, "club_name": club, "age_group": age, "gender": gender,
            "state_code": "WA", "provider_id": provider, "is_deprecated": deprecated}


def _write_teams_csv(tmp_path):
    folder = tmp_path / "u13"
    folder.mkdir()
    with (folder / "teams.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["provider_team_id", "academy_id", "club_name", "display_name", "age_group", "tiers", "regions", "gender"])
        w.writeheader()
        w.writerow({"provider_team_id": "1", "academy_id": "9", "club_name": "Emerald City FC", "display_name": "Emerald City FC",
                    "age_group": "u13", "tiers": "EA", "regions": "PACNW", "gender": "Male"})


def test_run_reports_only_eligible_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "PAGE_SIZE", 2)  # force several pages
    teams = [
        _team("a", "Emerald City FC 2014 EA"),
        _team("b", "Emerald City FC 2014 EA", deprecated=True),
        _team("c", "Emerald City FC U13 HD"),
        _team("d", "Emerald City FC 2014 EA", provider=M11),
        _team("e", "Emerald City FC 2014 EA", age="u12"),
        _team("f", "Emerald City FC 2014 EA", gender="Female"),
    ]
    db = _Db(teams, [{"id": GOT, "code": "gotsport"}, {"id": M11, "code": "modular11"}])
    _write_teams_csv(tmp_path)
    counts = m.run("u13", tmp_path, db)
    assert counts == {"confident": 1, "review": 0, "no_match": 0}
    [row] = list(csv.DictReader((tmp_path / "u13" / "match_report.csv").open(encoding="utf-8")))
    assert row["candidate_ids"] == "a" and row["candidate_providers"] == "gotsport"
    team_calls = [e for e in db.executed if e[0] == "teams"]
    assert len(team_calls) >= 2  # paged
```

The double drops deprecated rows only when the exact `or_` filter was sent, so removing
`.or_(...)` from the implementation leaves candidate `b` in and turns the row into a review.

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement** (append; add `argparse`, `csv`, `os`, `sys`, `Path`, `load_dotenv`
  and `create_client` imports, following the client setup in `scripts/enqueue_viewed_teams.py`).

```python
PAGE_SIZE = 1000
REPORT_COLUMNS = ["provider_team_id", "club_name", "display_name", "tiers", "bucket", "reason", "candidate_ids",
                  "candidate_names", "candidate_clubs", "candidate_providers", "candidate_states"]


def _provider_codes(sb) -> dict[str, str]:
    return {r["id"]: r["code"] for r in sb.table("providers").select("id, code").execute().data}


def fetch_db_teams(sb, age_group: str) -> list[dict]:
    codes = _provider_codes(sb)
    rows, offset = [], 0
    while True:
        page = (
            sb.table("teams")
            .select("team_id_master, team_name, club_name, state_code, provider_id, age_group, gender")
            .eq("age_group", age_group)
            .eq("gender", "Male")
            .or_("is_deprecated.is.null,is_deprecated.eq.false")
            .order("team_id_master")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
        )
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    eligible = []
    for row in rows:
        code = codes.get(row.get("provider_id"), "")
        if code == "modular11" or is_protected(row["team_name"]):
            continue
        eligible.append({**row, "provider_code": code})
    return eligible


def _load_ea_teams(path: Path) -> list[EaTeam]:
    with path.open(encoding="utf-8") as handle:
        return [
            EaTeam(r["provider_team_id"], r["club_name"], r["display_name"], r["age_group"],
                   frozenset(t for t in r["tiers"].split(";") if t != "EA National"))
            for r in csv.DictReader(handle)
        ]


def run(age: str, in_dir: Path, sb) -> dict[str, int]:
    ea_teams = _load_ea_teams(in_dir / age / "teams.csv")
    report = classify(ea_teams, fetch_db_teams(sb, age))
    with (in_dir / age / "match_report.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for row in report:
            writer.writerow({
                "provider_team_id": row.ea.provider_team_id, "club_name": row.ea.club_name,
                "display_name": row.ea.display_name, "tiers": ";".join(sorted(row.ea.tiers)),
                "bucket": row.bucket, "reason": row.reason,
                **{f"candidate_{k}s": "|".join(str(c.get(src) or "") for c in row.candidates)
                   for k, src in (("id", "team_id_master"), ("name", "team_name"), ("club", "club_name"),
                                  ("provider", "provider_code"), ("state", "state_code"))},
            })
    return {b: sum(r.bucket == b for r in report) for b in ("confident", "review", "no_match")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--age", required=True)
    parser.add_argument("--in-dir", type=Path, default=Path("data/modular11_ea"))
    args = parser.parse_args(argv)
    load_dotenv()
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        return 1
    counts = run(args.age, args.in_dir, create_client(url, key))
    print(" ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

The EA `tiers` loaded from CSV drop `EA National`, so the marker test checks against `EA`/`EA2`
only. Note that the `{f"candidate_{k}s"...}` keys produce `candidate_ids`, `candidate_names`,
`candidate_clubs`, `candidate_providers` and `candidate_states`, matching `REPORT_COLUMNS`.

- [ ] **Step 4: Run and confirm the tests pass.** Mutation checks: remove `.or_(...)`, so `b`
  appears and the test fails; remove `.order(...)`, so the double asserts; remove the
  `code == "modular11"` skip, so `d` appears and the row goes to review.
- [ ] **Step 5: Commit**: `git commit -m "Write the EA match report from live teams, read-only"`.

---

### Task 7: "EA Scraper" workflow and live U11 smoke run

**Files:**
- Create: `.github/workflows/ea-scraper.yml`

- [ ] **Step 1: Write the workflow** (mirrors `or-scraper.yml` setup and secrets)

```yaml
name: EA Scraper

on:
  workflow_dispatch:
    inputs:
      age:
        description: 'EA age group to scrape (one per run)'
        required: true
        type: choice
        options: [u11, u12, u13, u14, u15, u16, u17, u19]

concurrency:
  group: ea-scraper
  cancel-in-progress: false

jobs:
  scrape-ea:
    runs-on: ubuntu-latest
    timeout-minutes: 60
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

      - name: Scrape EA roster and games
        env:
          PYTHONPATH: ${{ github.workspace }}
          AGE: ${{ inputs.age }}
        run: |
          set -euo pipefail
          python scripts/scrape_modular11_ea.py --age "$AGE" | tee scrape_counts.txt

      - name: Build match report
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          PYTHONPATH: ${{ github.workspace }}
          AGE: ${{ inputs.age }}
        run: |
          set -euo pipefail
          python scripts/match_modular11_ea_teams.py --age "$AGE" | tee match_counts.txt

      - name: Upload EA output
        if: always()
        uses: actions/upload-artifact@v5
        with:
          name: ea-scraper-${{ inputs.age }}-${{ github.run_id }}
          path: data/modular11_ea/${{ inputs.age }}/
          retention-days: 30
          if-no-files-found: warn

      - name: Summary
        if: always()
        env:
          AGE: ${{ inputs.age }}
        run: |
          {
            echo "## EA Scraper — ${AGE}"
            echo "- Scrape: $(cat scrape_counts.txt 2>/dev/null || echo 'did not finish')"
            echo "- Match report: $(cat match_counts.txt 2>/dev/null || echo 'did not finish')"
          } >> "$GITHUB_STEP_SUMMARY"
```

- [ ] **Step 2: Run the workflow guard tests** that glob `.github/workflows/` (the pipefail and
  freeze-coverage suites, among others):
  `python -m pytest tests/ -k "workflow or pipefail or rollover or zenrows" -q`. Expected: pass.
  The scripts write no age groups, so nothing joins the freeze list yet. If a guard flags the
  new file, follow its message.

- [ ] **Step 3: Live U11 smoke run** (worktree, root `.env` copied):

```bash
python scripts/scrape_modular11_ea.py --age u11
python scripts/match_modular11_ea_teams.py --age u11
```

Expected: `teams=103` (unique U11 ids on 2026-10-04), `unresolved=0` or a handful, and a bucket
split is printed. Open
`games.csv` and `match_report.csv` and read 10 real rows of each, per the dry-run-output memory
note. A surprising rate is a finding to report, not to tune away.

- [ ] **Step 4: Commit the workflow, spec and plan**

```bash
git add .github/workflows/ea-scraper.yml .turbo/specs/modular11-ea-scraper.md .turbo/plans/modular11-ea-scraper.md
git commit -m "Add the EA Scraper workflow: one age per manual run, files only"
```

---

### Task 8: Finalize

- [ ] Run the full CI gate (`ruff` path list and pytest form from Global Constraints).
- [ ] Run `/finalize` per `.claude/rules/session-workflow.md`, then open the PR with
  `scripts/pr_wait.py --no-merge`. The user decides when to merge.
- [ ] Send the user the U11 `match_report.csv` bucket counts and the file, so they can review it
  before U12 and before any import step is planned.
