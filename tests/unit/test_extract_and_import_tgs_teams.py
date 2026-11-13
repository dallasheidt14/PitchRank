"""The TGS match step links a new TGS id to the existing team it names, or creates one.

It runs once, before the game import, over every shard's CSV. A team that already carries a TGS
id, directly or through a merge, never takes a second one, and a team two new ids both want
takes neither, so two squads cannot fuse into one team. A created team takes the age its own
name states, or the youngest division it played when the name states none. These drive ``main()`` end to end against a double that writes into its tables and
refuses what Postgres refuses.
"""

import csv
import re
import sys
from types import SimpleNamespace

import pytest

import scripts.enqueue_helpers as enqueue_helpers
import scripts.extract_and_import_tgs_teams as driver
from scripts.scrape_tgs_event import REQUIRED_COLUMNS
from src.utils.team_utils import CURRENT_YEAR

TGS = "tgs-provider-uuid"
GOTSPORT = "gotsport-provider-uuid"
CLUB = "Cascade Premier Soccer Club"
NAME = "Cascade Premier Soccer Club - B16/17"
OPPONENT_ID = "900"
MATCH_METHODS = {"auto", "manual", "import", "direct_id", "fuzzy_auto", "fuzzy_review"}


class _Query:
    """Applies its filters, writes into the table it names, and records every call at execute(),
    so a builder that is never executed changes nothing."""

    def __init__(self, db, table):
        self._db, self._table = db, table
        self._op, self._payload, self._columns = "select", None, None
        self._filters, self._negate = [], False
        self._order, self._range, self._limit, self._single = None, None, None, False

    def select(self, columns="*", *_a, **_k):
        self._columns = None if columns.strip() == "*" else [c.strip() for c in columns.split(",")]
        return self

    def insert(self, payload, *_a, **_k):
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload, *_a, **_k):
        self._op, self._payload = "update", payload
        return self

    @property
    def not_(self):
        self._negate = True
        return self

    def _filter(self, kind, field, value):
        self._filters.append((kind, field, value, self._negate))
        self._negate = False
        return self

    def eq(self, field, value):
        return self._filter("eq", field, value)

    def neq(self, field, value):
        return self._filter("neq", field, value)

    def like(self, field, value):
        return self._filter("like", field, value)

    def ilike(self, field, value):
        return self._filter("ilike", field, value)

    def in_(self, field, values):
        return self._filter("in", field, list(values))

    def is_(self, field, value):
        return self._filter("is", field, value)

    def order(self, field, *_a, **_k):
        self._order = field
        return self

    def range(self, start, end):
        # postgrest-py adds a second offset and limit rather than replacing the first, so a
        # builder reused for the next page asks for something else.
        if self._range is not None:
            raise AssertionError(f"range() called twice on one {self._table} builder")
        self._range = (start, end)
        return self

    def limit(self, count, *_a, **_k):
        self._limit = count
        return self

    def single(self):
        self._single = True
        return self

    def __getattr__(self, name):
        self._db.unmodeled.append(f"{self._table}.{name}")
        raise AttributeError(name)

    @staticmethod
    def _keeps(row, kind, field, value, negate):
        cell = row.get(field)
        if kind == "eq":
            hit = cell == value
        elif kind == "neq":
            hit = cell != value
        elif kind == "like":
            hit = re.fullmatch(re.escape(value).replace("%", ".*").replace("_", "."), str(cell or "")) is not None
        elif kind == "ilike":
            hit = str(cell or "").lower() == value.lower()
        elif kind == "in":
            hit = cell in value
        else:
            hit = cell is None if value == "null" else cell is (value == "true")
        return hit != negate

    def _matching(self):
        return [row for row in self._db.rows[self._table] if all(self._keeps(row, *f) for f in self._filters)]

    def execute(self):
        self._db.executed.append((self._table, self._op, self._payload))
        if self._op == "insert":
            self._db.insert(self._table, self._payload if isinstance(self._payload, list) else [self._payload])
            return SimpleNamespace(data=[])
        if self._op == "update":
            if self._table in self._db.fail_writes:
                raise RuntimeError("connection reset")
            for row in self._matching():
                row.update(self._payload)
            return SimpleNamespace(data=[])
        if self._db.fail_read and self._db.fail_read(self._table, self._columns, self._filters):
            raise RuntimeError("connection reset")
        rows = self._matching()
        if self._order:
            rows = sorted(rows, key=lambda row: row[self._order])
        if self._range:
            rows = rows[self._range[0] : self._range[1] + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        if self._columns:
            rows = [{column: row.get(column) for column in self._columns} for row in rows]
        if self._single:
            if len(rows) != 1:
                raise RuntimeError("PGRST116: JSON object requested, multiple (or no) rows returned")
            return SimpleNamespace(data=rows[0])
        return SimpleNamespace(data=rows)


class _DB:
    def __init__(self, teams=(), aliases=(), merges=(), broken=()):
        self.rows = {
            "providers": [{"id": TGS, "code": "tgs"}],
            "teams": [{"id": i, **team} for i, team in enumerate(teams, 1)],
            "team_alias_map": [{"id": i, **alias} for i, alias in enumerate(aliases, 1)],
            "team_merge_map": [dict(merge) for merge in merges],
            "team_match_review_queue": [],
        }
        self.broken = set(broken)
        self.executed, self.unmodeled = [], []
        # Tables whose inserts and updates raise, fields another writer gives each alias the
        # moment this run writes it, and a predicate on (table, columns, filters) for reads that raise.
        self.fail_writes, self.rewrite_alias, self.fail_read = set(), None, None

    def table(self, name):
        if name in self.broken:
            raise RuntimeError(f"{name} unavailable")
        return _Query(self, name)

    def insert(self, table, rows):
        """All rows or none, as one INSERT statement does."""
        if table in self.fail_writes:
            raise RuntimeError("connection reset")
        stored = self.rows[table]
        for i, row in enumerate(rows):
            if table in ("teams", "team_alias_map"):
                key = (row.get("provider_id"), row.get("provider_team_id"))
                if any((other.get("provider_id"), other.get("provider_team_id")) == key for other in stored + rows[:i]):
                    raise RuntimeError(f'duplicate key value violates unique constraint "{table}_provider_key" (23505)')
            if table == "team_alias_map":
                if not any(team["team_id_master"] == row["team_id_master"] for team in self.rows["teams"]):
                    raise RuntimeError('violates foreign key constraint "team_alias_map_team_id_master_fkey" (23503)')
                if row.get("match_method") not in MATCH_METHODS:
                    raise RuntimeError('new row violates check constraint "valid_match_type" (23514)')
        if table in ("teams", "team_alias_map"):
            last = max((row["id"] for row in stored), default=0)
            rows = [{"id": last + i, **row} for i, row in enumerate(rows, 1)]
        if table == "team_alias_map":
            rows = [{**row, **(self.rewrite_alias or {})} for row in rows]
        stored.extend(dict(row) for row in rows)

    def writes(self, table):
        return [payload for name, op, payload in self.executed if name == table and op != "select"]

    def alias_of(self, provider_team_id):
        return next((a for a in self.rows["team_alias_map"] if a["provider_team_id"] == provider_team_id), None)

    def team(self, team_id):
        return next(team for team in self.rows["teams"] if team["team_id_master"] == team_id)


def _team(
    team_id, name="Cascade Premier Soccer Club B16/17", provider=GOTSPORT, age="u10", deprecated=False, club=CLUB
):
    return {
        "team_id_master": team_id,
        "team_name": name,
        "team_name_original": None,
        "club_name": club,
        "age_group": age,
        "gender": "Male",
        "state_code": None,
        "state": None,
        "provider_id": provider,
        "provider_team_id": f"p-{team_id}",
        "is_deprecated": deprecated,
    }


def _alias(provider_team_id, team_id):
    return {
        "provider_id": TGS,
        "provider_team_id": provider_team_id,
        "team_id_master": team_id,
        "match_method": "direct_id",
        "match_confidence": 1.0,
        "review_status": "approved",
    }


def _db(teams=(), aliases=(), merges=(), broken=()):
    """The opponent every game names is already linked, so only the team under test is new."""
    opponent = _team("opponent", "Seattle United B16/17 Red", provider=TGS, club="Seattle United")
    return _DB([opponent, *teams], [_alias(OPPONENT_ID, "opponent"), *aliases], merges, broken)


def _game(team_id, team_name=NAME, name_age="u10", division="u10", gender="Boys", goals=("2", "1"), club=CLUB):
    return {
        "provider": "tgs",
        "team_id": team_id,
        "team_name": team_name,
        "club_name": club,
        "team_name_age": name_age,
        "opponent_id": OPPONENT_ID,
        "opponent_name": "Seattle United B16/17 Red",
        "opponent_club_name": "Seattle United",
        "opponent_name_age": "u10",
        "age_group": division,
        "gender": gender,
        "goals_for": goals[0],
        "goals_against": goals[1],
        "game_date": "2026-09-12",
    }


def _blank_club_team():
    """A team TGS id 601 already names, stored with no club, which the CSV's club would fill."""
    return _team("aliased-row", "Cascade Premier Soccer Club B2015", age="u12", club=None), _alias("601", "aliased-row")


def _run(monkeypatch, tmp_path, db, *shards, dry_run=False):
    paths = []
    for i, games in enumerate(shards):
        path = tmp_path / f"tgs_events_shard{i}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
            writer.writeheader()
            writer.writerows({column: game.get(column, "") for column in REQUIRED_COLUMNS} for game in games)
        paths.append(str(path))
    monkeypatch.setenv("SUPABASE_URL", "http://supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setattr(driver, "create_client", lambda url, key: db)
    monkeypatch.setattr(driver, "LOGS_DIR", tmp_path / "logs")
    argv = ["extract_and_import_tgs_teams.py", *paths, "tgs", *(["--dry-run"] if dry_run else [])]
    monkeypatch.setattr(sys, "argv", argv)
    return driver.main()


def _created_for(db, provider_team_id):
    """The team this run created for a TGS id, read through the id's own alias."""
    alias = db.alias_of(provider_team_id)
    assert alias is not None and alias["match_method"] == "direct_id"
    team = db.team(alias["team_id_master"])
    assert (team["provider_id"], team["provider_team_id"]) == (TGS, provider_team_id)
    return team


def _alias_target(db, provider_team_id):
    return db.alias_of(provider_team_id)["team_id_master"]


def _outcomes_file(tmp_path):
    (path,) = (tmp_path / "logs").glob("tgs_team_matches_*.csv")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_a_new_id_links_to_the_gotsport_team_its_name_matches(monkeypatch, tmp_path):
    db = _db(teams=[_team("gotsport-row")])

    assert _run(monkeypatch, tmp_path, db, [_game("501")]) == 0

    alias = db.alias_of("501")
    assert (alias["team_id_master"], alias["match_method"]) == ("gotsport-row", "fuzzy_auto")
    assert db.writes("teams") == []
    assert db.writes("team_match_review_queue") == []


def test_a_club_spelled_differently_still_finds_its_team_in_the_age_group(monkeypatch, tmp_path):
    """No row carries the CSV's club spelling, so the search reads the whole age group."""
    db = _db(teams=[_team("gotsport-row")])
    game = _game("501", "Cascade Premier SC - B16/17", club="Cascade Premier SC")

    assert _run(monkeypatch, tmp_path, db, [game]) == 0

    assert (_alias_target(db, "501"), db.alias_of("501")["match_method"]) == ("gotsport-row", "fuzzy_auto")


@pytest.mark.parametrize(
    "teams, aliases, merges",
    [
        # An approved TGS alias already names the matching team.
        ([_team("gotsport-row")], [_alias("777", "gotsport-row")], []),
        # The matching team began as a TGS row.
        ([_team("tgs-row", provider=TGS)], [], []),
        # A TGS alias names a row since merged into the matching team.
        (
            [_team("gotsport-row"), _team("merged-away", deprecated=True)],
            [_alias("779", "merged-away")],
            [{"deprecated_team_id": "merged-away", "canonical_team_id": "gotsport-row"}],
        ),
    ],
    ids=["by-alias", "by-tgs-row", "through-a-merge"],
)
def test_a_team_that_already_carries_a_tgs_id_is_not_given_a_second(monkeypatch, tmp_path, teams, aliases, merges):
    db = _db(teams=teams, aliases=aliases, merges=merges)

    assert _run(monkeypatch, tmp_path, db, [_game("501")]) == 0

    assert _created_for(db, "501")["age_group"] == "u10"
    assert db.writes("team_match_review_queue") == []


def test_a_claim_on_a_later_page_of_aliases_still_counts(monkeypatch, tmp_path):
    """Pages of two, so the alias naming the matching team arrives on the third page."""
    monkeypatch.setattr(enqueue_helpers, "PAGE_SIZE", 2)
    others = [
        _team(f"other-{i}", f"Seattle United B16/17 {color}", club="Seattle United")
        for i, color in enumerate(["Blue", "Gold", "White"])
    ]
    aliases = [_alias(f"70{i}", f"other-{i}") for i in range(3)] + [_alias("777", "gotsport-row")]
    db = _db(teams=[*others, _team("gotsport-row")], aliases=aliases)

    assert _run(monkeypatch, tmp_path, db, [_game("501")]) == 0

    _created_for(db, "501")


def test_a_merged_away_row_is_never_linked_to(monkeypatch, tmp_path):
    db = _db(teams=[_team("merged-away", deprecated=True)])

    assert _run(monkeypatch, tmp_path, db, [_game("501")]) == 0

    _created_for(db, "501")


def test_a_merged_away_row_is_not_found_in_the_whole_cohort_either(monkeypatch, tmp_path):
    """A club spelled differently matches no club row, so the search reads the whole age group."""
    db = _db(teams=[_team("merged-away", deprecated=True)])
    game = _game("501", "Cascade Premier SC - B16/17", club="Cascade Premier SC")

    assert _run(monkeypatch, tmp_path, db, [game]) == 0

    _created_for(db, "501")


def test_a_match_below_the_auto_link_score_creates_a_team(monkeypatch, tmp_path):
    db = _db(teams=[_team("near-miss", "Cascade Premier Soccer Club Boys 2016")])

    assert _run(monkeypatch, tmp_path, db, [_game("501")]) == 0

    _created_for(db, "501")


def test_a_team_two_new_ids_both_want_goes_to_neither(monkeypatch, tmp_path):
    db = _db(teams=[_team("gotsport-row")])

    assert _run(monkeypatch, tmp_path, db, [_game("501"), _game("502")]) == 0

    assert _created_for(db, "501")["team_id_master"] != _created_for(db, "502")["team_id_master"]


def test_every_shards_csv_is_matched_as_one_run(monkeypatch, tmp_path):
    db = _db(teams=[_team("gotsport-row")])

    assert _run(monkeypatch, tmp_path, db, [_game("501")], [_game("502")]) == 0

    _created_for(db, "501")
    _created_for(db, "502")


def test_a_team_is_searched_and_created_at_the_age_its_name_states(monkeypatch, tmp_path):
    """A B16/17 squad playing up in a U12 flight is a U10 team."""
    linked = _db(teams=[_team("u10-row")])
    assert _run(monkeypatch, tmp_path, linked, [_game("501", division="u12")]) == 0
    assert _alias_target(linked, "501") == "u10-row"

    created = _db()
    assert _run(monkeypatch, tmp_path, created, [_game("501", division="u12")]) == 0
    assert _created_for(created, "501")["age_group"] == "u10"


def test_a_lone_birth_year_read_two_ways_takes_the_younger_age(monkeypatch, tmp_path):
    """The scraper reads G2013 as u14 in a U12 flight and u13 in a U13 one; U13 is where it plays."""
    db = _db()
    name = "Cascade Premier Soccer Club - G2013"
    games = [
        _game("501", name, "u14", division="u12", gender="Girls"),
        _game("501", name, "u13", division="u13", gender="Girls"),
    ]

    assert _run(monkeypatch, tmp_path, db, games) == 0

    assert _created_for(db, "501")["age_group"] == "u13"


def test_readings_outside_the_latest_names_two_groups_get_no_team(monkeypatch, tmp_path, capsys):
    """An earlier row named B2015 reads u12; B2013, the latest name, fits only u13 and u14."""
    db = _db()
    games = [
        {**_game("501", "Cascade Premier Soccer Club - B2015", "u12", division="u14"), "game_date": "2026-09-05"},
        _game("501", "Cascade Premier Soccer Club - B2013", "u14", division="u14"),
    ]

    assert _run(monkeypatch, tmp_path, db, games) == 0

    assert db.alias_of("501") is None
    assert "skipped, name ages disagree" in capsys.readouterr().out


def test_a_float_formatted_id_is_read_as_the_import_reads_it(monkeypatch, tmp_path):
    """The import's CSV loaders read 501.0 as 501, so an alias on 501.0 would never be found."""
    db = _db()

    assert _run(monkeypatch, tmp_path, db, [_game("501.0")]) == 0

    _created_for(db, "501")


def test_a_name_read_as_two_ages_gets_no_team(monkeypatch, tmp_path, capsys):
    """Two flights from different seasons read one U-age two ways, and nothing says which is current."""
    db = _db()
    name = "Cascade Premier Soccer Club - BU11 Red"
    games = [_game("501", name, "u11", division="u11"), _game("501", name, "u12", division="u12")]

    assert _run(monkeypatch, tmp_path, db, games) == 0

    assert db.alias_of("501") is None
    assert "skipped, name ages disagree" in capsys.readouterr().out


def test_a_name_stating_no_age_takes_the_youngest_division_it_played(monkeypatch, tmp_path):
    db = _db()
    name = "Cascade Premier Black"
    games = [_game("501", name, "", division="u12"), _game("501", name, "", division="u13")]

    assert _run(monkeypatch, tmp_path, db, games) == 0

    assert _created_for(db, "501")["age_group"] == "u12"


@pytest.mark.parametrize("team_id", ["", "None"])
def test_a_placeholder_id_gets_no_team(monkeypatch, tmp_path, team_id):
    db = _db()

    assert _run(monkeypatch, tmp_path, db, [_game(team_id, "Winner Game 4", "")]) == 0

    assert db.writes("teams") == []
    assert db.writes("team_alias_map") == []


def test_a_team_with_no_scored_game_is_left_for_a_week_it_has_one(monkeypatch, tmp_path):
    db = _db()

    assert _run(monkeypatch, tmp_path, db, [_game("501", goals=("", "")), _game("502", goals=("", "0"))]) == 0

    assert db.alias_of("501") is None
    _created_for(db, "502")


def test_an_id_its_rows_give_two_genders_gets_no_team(monkeypatch, tmp_path, capsys):
    db = _db()

    assert _run(monkeypatch, tmp_path, db, [_game("501"), _game("501", gender="Girls")]) == 0

    assert db.alias_of("501") is None
    assert "skipped, rows disagree on gender" in capsys.readouterr().out


def test_a_tie_with_a_team_carrying_a_tgs_id_is_not_handed_to_its_twin(monkeypatch, tmp_path):
    """Equal scores, so only the claimed row winning the tie keeps the free twin from linking."""
    db = _db(teams=[_team("free-twin"), _team("tgs-row", provider=TGS)])

    assert _run(monkeypatch, tmp_path, db, [_game("501")]) == 0

    _created_for(db, "501")


def test_a_wrong_year_row_does_not_shadow_the_right_one(monkeypatch, tmp_path):
    """The wrong year outscores the right one, so only the skip lets the right one link."""
    wrong = _team("wrong-year", "Cascade Premier Soccer Club B2015", age="u11")
    right = _team("right-year", "Cascade Premier Soccer Club B16", age="u11")
    db = _db(teams=[wrong, right])

    assert _run(monkeypatch, tmp_path, db, [_game("501", "Cascade Premier Soccer Club - B2016", "u11", "u11")]) == 0

    assert _alias_target(db, "501") == "right-year"


def test_a_u19_name_stating_only_the_year_both_squads_share_is_not_linked(monkeypatch, tmp_path):
    """U19 holds two squads sharing one birth year, so a name stating only that year fits both."""
    shared = CURRENT_YEAR - 18
    band = _team("u19-band", f"Sparta FC {shared}/{(shared + 1) % 100:02d} Boys", age="u19", club="Sparta FC")
    db = _db(teams=[band])
    game = _game("501", f"Sparta FC {shared} Boys", "u19", "u19", club="Sparta FC")

    assert _run(monkeypatch, tmp_path, db, [game]) == 0

    _created_for(db, "501")


def test_a_row_whose_name_states_the_other_gender_is_not_linked(monkeypatch, tmp_path):
    db = _db(teams=[_team("girls-row", "Cascade Premier Soccer Club G16/17")])

    assert _run(monkeypatch, tmp_path, db, [_game("501")]) == 0

    _created_for(db, "501")


def test_an_id_already_aliased_is_left_as_it_is(monkeypatch, tmp_path):
    db = _db(teams=[_team("gotsport-row")])

    assert _run(monkeypatch, tmp_path, db, [_game("501")]) == 0
    assert _run(monkeypatch, tmp_path, db, [_game("501")]) == 0

    assert [alias["provider_team_id"] for alias in db.writes("team_alias_map")] == ["501"]


def test_an_already_aliased_team_with_no_club_takes_the_csvs(monkeypatch, tmp_path):
    team, alias = _blank_club_team()
    db = _db(teams=[team], aliases=[alias])

    assert _run(monkeypatch, tmp_path, db, [_game("601", "Cascade Premier Soccer Club - B2015", "u12", "u12")]) == 0

    assert db.writes("teams") == [{"club_name": CLUB}]
    assert db.team("aliased-row")["club_name"] == CLUB


def test_a_real_club_is_not_overwritten_by_tgs_spelling_it_differently(monkeypatch, tmp_path):
    """The first run links 501 across two spellings; the second sees an aliased team with a real club."""
    db = _db(teams=[_team("gotsport-row")])
    game = _game("501", "Cascade Premier SC - B16/17", club="Cascade Premier SC")

    assert _run(monkeypatch, tmp_path, db, [game]) == 0
    assert _run(monkeypatch, tmp_path, db, [game]) == 0

    assert _alias_target(db, "501") == "gotsport-row"
    assert db.writes("teams") == []
    assert db.team("gotsport-row")["club_name"] == CLUB


def test_a_placeholder_club_in_the_csv_is_never_written(monkeypatch, tmp_path):
    team, alias = _blank_club_team()
    db = _db(teams=[team], aliases=[alias])
    game = _game("601", "Cascade Premier Soccer Club - B2015", "u12", "u12", club="No Club Selection")

    assert _run(monkeypatch, tmp_path, db, [game]) == 0

    assert db.writes("teams") == []


def test_a_failed_merge_map_read_stops_before_anything_is_written(monkeypatch, tmp_path):
    """The club fill would write first if it ran before the merge map was read."""
    team, alias = _blank_club_team()
    db = _db(teams=[team, _team("gotsport-row")], aliases=[alias], broken=["team_merge_map"])
    games = [_game("501"), _game("601", "Cascade Premier Soccer Club - B2015", "u12", "u12")]

    with pytest.raises(SystemExit, match="Merge map failed to load"):
        _run(monkeypatch, tmp_path, db, games)

    assert db.writes("teams") == db.writes("team_alias_map") == []


def test_a_dry_run_writes_nothing_and_prints_what_it_would(monkeypatch, tmp_path, capsys):
    team, alias = _blank_club_team()
    db = _db(teams=[_team("gotsport-row"), team], aliases=[alias])
    games = [
        _game("501"),
        _game("502", "Cascade Premier Black", ""),
        _game("601", "Cascade Premier Soccer Club - B2015", "u12", "u12"),
    ]

    assert _run(monkeypatch, tmp_path, db, games, dry_run=True) == 0

    assert [payload for _, op, payload in db.executed if op != "select"] == []
    assert not (tmp_path / "logs").exists()
    out = capsys.readouterr().out
    assert "would fill the club on 1 teams" in out
    printed = list(csv.DictReader(out[out.index("provider_team_id,") :].splitlines()))
    assert [(row["provider_team_id"], row["outcome"]) for row in printed if row["outcome"]] == [
        ("501", "linked"),
        ("502", "created"),
    ]


def test_a_team_that_cannot_be_created_fails_the_step(monkeypatch, tmp_path):
    db = _db()
    db.fail_writes = {"teams"}

    assert _run(monkeypatch, tmp_path, db, [_game("501")]) == 1

    assert db.alias_of("501") is None
    assert [row["outcome"] for row in _outcomes_file(tmp_path)] == ["error: not created"]


@pytest.mark.parametrize(
    "fail_read",
    [
        lambda table, columns, filters: table == "teams" and any(f[:2] == ("ilike", "club_name") for f in filters),
        lambda table, columns, filters: table == "teams" and columns == ["team_name", "team_name_original", "gender"],
    ],
    ids=["club-candidates", "gender-guard"],
)
def test_a_failed_read_during_the_search_creates_nothing(monkeypatch, tmp_path, fail_read):
    """Read as "no match", the failure would create a duplicate of the team the search would have found."""
    db = _db(teams=[_team("gotsport-row")])
    db.fail_read = fail_read

    assert _run(monkeypatch, tmp_path, db, [_game("501")]) == 1

    assert db.alias_of("501") is None
    assert db.writes("teams") == []
    assert [row["outcome"] for row in _outcomes_file(tmp_path)] == ["error: search failed"]


def test_a_dry_run_reports_a_failed_search_as_the_real_run_would(monkeypatch, tmp_path, capsys):
    db = _db(teams=[_team("gotsport-row")])
    db.fail_read = lambda table, columns, filters: (
        table == "teams" and any(f[:2] == ("ilike", "club_name") for f in filters)
    )

    assert _run(monkeypatch, tmp_path, db, [_game("501")], dry_run=True) == 1

    assert [payload for _, op, payload in db.executed if op != "select"] == []
    assert "1 TGS ids could not be given a team" in capsys.readouterr().out


def test_a_team_held_by_the_gender_guard_passes_the_step(monkeypatch, tmp_path):
    """501's own TGS row states girls, so a boys game for 501 must not reuse it; that is a hold, not an error."""
    own_row = {
        **_team("tgs-girls", "Cascade Premier Soccer Club G16/17", provider=TGS),
        "gender": "Female",
        "provider_team_id": "501",
    }
    db = _db(teams=[own_row])

    assert _run(monkeypatch, tmp_path, db, [_game("501")]) == 0

    assert db.alias_of("501") is None
    assert [row["outcome"] for row in _outcomes_file(tmp_path)] == ["held: gender guard"]


def test_an_alias_write_that_fails_quietly_fails_the_step(monkeypatch, tmp_path):
    """_create_alias logs a failed insert and returns, so only reading the alias back catches it."""
    db = _db()
    db.fail_writes = {"team_alias_map"}

    assert _run(monkeypatch, tmp_path, db, [_game("501")]) == 1


@pytest.mark.parametrize(
    "teams, rewrite",
    [
        ([], {"team_id_master": "opponent"}),
        ([_team("gotsport-row")], {"match_method": "direct_id"}),
        ([_team("gotsport-row")], {"review_status": "pending"}),
    ],
    ids=["created-target", "linked-method", "linked-status"],
)
def test_an_alias_read_back_differing_in_any_field_fails_the_step(monkeypatch, tmp_path, teams, rewrite):
    """Another writer changes the alias as this run writes it, so an alias is there, just not this one."""
    db = _db(teams=teams)
    db.rewrite_alias = rewrite

    assert _run(monkeypatch, tmp_path, db, [_game("501")]) == 1


def test_a_name_carrying_markup_is_printed_as_text(monkeypatch, tmp_path, capsys):
    """Rich reads square brackets as markup, and a stray closing tag would raise after the writes."""
    name = "Cascade Premier Soccer Club - B16/17 [/]"
    db = _db(teams=[_team("gotsport-row")])

    assert _run(monkeypatch, tmp_path, db, [_game("501", name)]) == 0

    assert _alias_target(db, "501") == "gotsport-row"
    assert f"linked 501 {name!r}" in capsys.readouterr().out


def test_the_outcomes_file_defangs_a_name_a_spreadsheet_would_run(monkeypatch, tmp_path):
    db = _db()

    assert _run(monkeypatch, tmp_path, db, [_game("501", "=HYPERLINK(1) B16/17")]) == 0

    assert [row["team_name"] for row in _outcomes_file(tmp_path)] == ["'=HYPERLINK(1) B16/17"]


def test_every_call_the_step_makes_is_modeled(monkeypatch, tmp_path):
    db = _db(teams=[_team("gotsport-row")])

    _run(monkeypatch, tmp_path, db, [_game("501"), _game("502", "Cascade Premier Black", "")])

    assert db.unmodeled == []
