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
