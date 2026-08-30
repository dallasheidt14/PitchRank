"""Every stage of the hygiene chain reads the same GotSport payload the same way.

``unknown-opponent-hygiene-weekly.yml`` runs four scripts, each carrying its own
copy of a ``team_ranking_data/team_details`` resolver, and each comparing its
answer against another stage's. A payload read one way in one copy and another way
in the next is the failure this file exists to catch, so every case runs against
all four.

The recorded payload comes from team 742007. ``raise_for_status`` is load-bearing
rather than ceremonial: GotSport answers an unknown id with HTTP 404 and a valid
JSON body, which parses into an all-empty dict if the status is never checked.
"""

import subprocess
import sys
from pathlib import Path

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

import auto_match_unknown_opponents  # noqa: E402
import discover_teams_from_opponents  # noqa: E402
import due_diligence_unknown_opponents  # noqa: E402
import export_unknown_opponents  # noqa: E402

from src.utils import gotsport_team_details  # noqa: E402

TEAM_DETAILS = {
    "id": 742007,
    "name": "B12 ECNL RL",
    "club_name": "Seattle United",
    "city_state_country": "US",
    "website_url": "http://seattleunited.com/",
    "login_url": "",
    "primary_coach_name": None,
    "coach_names": ["Elias Ricord"],
    "primary_manager_name": None,
    "manager_names": ["Mark Thorrington"],
    "team_logo_url_full": "/system/organizations/logos/000/008/062/full/Seattle_United.png",
    "image": "/system/organizations/logos/000/008/062/icon/Seattle_United.png",
    "team_association": "WA",
    "display_gender": "Male",
    "display_age_group": "U15",
}

# Each stage names the same five facts differently. The value is what that stage
# must produce from the payload above; due diligence normalizes on the way through
# because it compares against stored rows, the other three carry the raw label.
EXPECTATIONS = [
    pytest.param(
        export_unknown_opponents,
        {
            "unknown_team_name": "B12 ECNL RL",
            "unknown_club_name": "Seattle United",
            "unknown_state": "WA",
            "unknown_age": "U15",
            "unknown_gender": "Male",
        },
        id="export",
    ),
    pytest.param(
        auto_match_unknown_opponents,
        {
            "unknown_team_name": "B12 ECNL RL",
            "unknown_club_name": "Seattle United",
            "unknown_state": "WA",
            "unknown_age": "U15",
            "unknown_gender": "Male",
        },
        id="auto_match",
    ),
    pytest.param(
        due_diligence_unknown_opponents,
        {
            "name": "B12 ECNL RL",
            "club_name": "Seattle United",
            "state": "WA",
            "age_group": "u15",
            "gender": "male",
        },
        id="due_diligence",
    ),
    pytest.param(
        gotsport_team_details,
        {
            "name": "B12 ECNL RL",
            "club_name": "Seattle United",
            "city_state_country": "US",
            "state_code": "WA",
            "age_group": "u15",
            "gender": "Male",
            "raw_age_group": "U15",
        },
        id="shared_module",
    ),
    pytest.param(
        discover_teams_from_opponents,
        {
            "name": "B12 ECNL RL",
            "club_name": "Seattle United",
            "state": "WA",
            "age": "U15",
            "gender": "Male",
            "city_state_country": "US",
        },
        id="discover",
    ),
]


# The shared module is imported, not executed, so it is not in this one.
SCRIPT_MODULES = [
    export_unknown_opponents,
    auto_match_unknown_opponents,
    due_diligence_unknown_opponents,
    discover_teams_from_opponents,
]


@pytest.mark.parametrize("module", SCRIPT_MODULES, ids=lambda m: m.__name__)
def test_the_script_still_imports_when_run_as_the_workflow_runs_it(module):
    """These four reach into src/ now, and `python3 scripts/x.py` puts scripts/ on
    sys.path rather than the repo root -- so the bootstrap each one adds is
    load-bearing in production and inert under pytest, which adds its own."""
    script = PROJECT_ROOT / "scripts" / f"{module.__name__}.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_a_late_resolution_reaches_the_aggregate_group():
    """The aggregate CSV is the only cohort source downstream reads, and a group
    keeps whatever its first game row resolved. A retry that succeeds on a later
    row has to land, or the retry only ever helps the detail CSV nothing reads."""
    groups = {}
    key = ("gotsport", "1", "742007", "home")

    export_unknown_opponents.ensure_group(groups, key, {})
    assert groups[key]["resolved_unknown"] == {}

    export_unknown_opponents.ensure_group(groups, key, {"unknown_age": "U15"})
    assert groups[key]["resolved_unknown"] == {"unknown_age": "U15"}


def test_a_resolved_group_is_not_overwritten_by_a_later_row():
    groups = {}
    key = ("gotsport", "1", "742007", "home")

    export_unknown_opponents.ensure_group(groups, key, {"unknown_age": "U15"})
    export_unknown_opponents.ensure_group(groups, key, {"unknown_age": "U99"})
    assert groups[key]["resolved_unknown"] == {"unknown_age": "U15"}
    assert len(groups) == 1


def _state_key(expected):
    for key in ("unknown_state", "state", "state_code"):
        if key in expected:
            return key
    raise AssertionError(f"no state key in {expected}")


class _FakeResponse:
    """Models requests.Response closely enough that raise_for_status can fire."""

    content = b"{}"

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for url", response=self)

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self._status_code = status_code
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return _FakeResponse(self._payload, self._status_code)


def _make_resolver(module):
    cls = getattr(module, "GotSportResolver", None) or module.TeamDetailsResolver
    return cls()


def _resolve(module, payload, status_code=200):
    resolver = _make_resolver(module)
    session = _FakeSession(payload, status_code)
    resolver.session = session
    return resolver.resolve("742007"), session


@pytest.mark.parametrize("module,expected", EXPECTATIONS)
def test_resolver_maps_the_recorded_payload(module, expected):
    resolved, _ = _resolve(module, TEAM_DETAILS)
    assert resolved == expected


@pytest.mark.parametrize("module,expected", EXPECTATIONS)
def test_cohort_and_gender_are_not_read_from_each_others_field(module, expected):
    """The copy-paste error four near-identical bodies invite."""
    swapped = dict(TEAM_DETAILS, display_age_group="Male", display_gender="U15")
    resolved, _ = _resolve(module, swapped)
    assert resolved != expected


@pytest.mark.parametrize("module,expected", EXPECTATIONS)
def test_a_missing_association_does_not_become_a_state(module, expected):
    """team_association is "" on real teams, and an unknown body must fail closed
    rather than be guessed onto a state board."""
    resolved, _ = _resolve(module, dict(TEAM_DETAILS, team_association=""))
    assert not resolved[_state_key(expected)]


@pytest.mark.parametrize("module,expected", EXPECTATIONS)
def test_can_resolves_to_california_north_not_canada(module, expected):
    resolved, _ = _resolve(module, dict(TEAM_DETAILS, team_association="CAN"))
    assert resolved[_state_key(expected)] == "CA"


@pytest.mark.parametrize("module,expected", EXPECTATIONS)
def test_the_lookup_is_cached_per_team_id(module, expected):
    resolver = _make_resolver(module)
    session = _FakeSession(TEAM_DETAILS)
    resolver.session = session
    resolver.resolve("742007")
    resolver.resolve("742007")
    assert len(session.calls) == 1


class _FailingThenWorkingSession:
    """GotSport's /api/v1 is CloudFront-fronted and answers a burst with 403."""

    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("403 Forbidden (CloudFront)")
        return _FakeResponse(self._payload)


@pytest.mark.parametrize("module,expected", EXPECTATIONS)
def test_a_transport_failure_is_not_cached_as_an_answer(module, expected):
    """Caching the empty result made one WAF block permanent for the run, and
    an empty resolve is indistinguishable from a team with no metadata -- which
    is what sends the caller back to the opponent's cohort."""
    resolver = _make_resolver(module)
    resolver.session = _FailingThenWorkingSession(TEAM_DETAILS)

    assert resolver.resolve("742007") == {}
    assert resolver.resolve("742007") == expected


@pytest.mark.parametrize("module,expected", EXPECTATIONS)
def test_a_404_body_is_never_parsed_as_a_team(module, expected):
    """GotSport answers an unknown id with HTTP 404 and a valid JSON body,
    {"message": "Can not find team"}. Without raise_for_status that body parses
    into an all-empty resolved dict and is cached as a resolved absence."""
    resolved, _ = _resolve(module, {"message": "Can not find team"}, status_code=404)
    assert resolved == {}


@pytest.mark.parametrize("module,expected", EXPECTATIONS)
def test_a_404_is_cached_because_it_is_a_permanent_answer(module, expected):
    resolver = _make_resolver(module)
    session = _FakeSession({"message": "Can not find team"}, status_code=404)
    resolver.session = session
    resolver.resolve("742007")
    resolver.resolve("742007")
    assert len(session.calls) == 1


@pytest.mark.parametrize("module,expected", EXPECTATIONS)
def test_a_server_error_body_is_never_parsed_as_a_team(module, expected):
    """A 5xx or WAF page can still carry a JSON body; raise_for_status is the
    only thing separating it from a payload."""
    resolved, _ = _resolve(module, dict(TEAM_DETAILS), status_code=503)
    assert resolved == {}
