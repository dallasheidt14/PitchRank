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

import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests
from requests.structures import CaseInsensitiveDict

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

    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = CaseInsensitiveDict(headers or {})

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for url", response=self)

    def json(self):
        return self._payload


class _FakeSession:
    """requests sends at get(), so that is where the URL, query and timeout are recorded."""

    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self._status_code = status_code
        self._headers = headers
        self.calls = []
        self.sent = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        self.sent.append((url, params, timeout))
        return _FakeResponse(self._payload, self._status_code, self._headers)


def _make_resolver(module, sleep=lambda _seconds: None):
    if module is gotsport_team_details:
        return module.TeamDetailsResolver()
    return module.GotSportResolver(pacer=gotsport_team_details.TeamDetailsPacer(cooldown_sec=300, sleep=sleep))


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
    """Raises a transport error on the first get(); a CloudFront 403 is the pacer's case (_ScriptedSession)."""

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
    """An empty resolve is indistinguishable from a team with no metadata, which sends the
    caller to the opponent's cohort, so a transport failure is not cached."""
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


# The shared module's TeamDetailsResolver takes no pacer, so it is not among these.
PACED_EXPECTATIONS = [p for p in EXPECTATIONS if p.values[0] in SCRIPT_MODULES]
CLOUDFRONT = {"Server": "CloudFront"}
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "unknown-opponent-hygiene-weekly.yml"
TIMEOUTS = {
    "export_unknown_opponents": 15,
    "auto_match_unknown_opponents": 15,
    "due_diligence_unknown_opponents": 20,
    "discover_teams_from_opponents": 15,
}


def _workflow_scripts_reading_team_details():
    names = dict.fromkeys(re.findall(r"python3 scripts/(\w+)\.py", WORKFLOW.read_text(encoding="utf-8")))
    readers = []
    for name in names:
        source = (PROJECT_ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8")
        if "team_ranking_data/team_details" in source or "gotsport_team_details" in source:
            readers.append(name)
    return readers


class _Sleeps(list):
    def __call__(self, seconds):
        self.append(seconds)


class _ScriptedSession:
    """Answers with each scripted response in turn, then repeats the last."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]


def test_every_script_the_weekly_job_runs_against_team_details_is_under_the_paced_tests():
    """Read from the workflow, so a stage that starts reading team_details fails here until it
    joins the tests below."""
    assert sorted(_workflow_scripts_reading_team_details()) == sorted(m.__name__ for m in SCRIPT_MODULES)
    assert {p.values[0] for p in PACED_EXPECTATIONS} == set(SCRIPT_MODULES)


@pytest.mark.parametrize("module", SCRIPT_MODULES, ids=lambda m: m.__name__)
def test_a_resolver_built_as_the_scripts_build_it_is_paced(module, monkeypatch):
    monkeypatch.delenv("GOTSPORT_WAF_COOLDOWN_SEC", raising=False)
    pacer = module.GotSportResolver().pacer
    assert (pacer.spacing_sec, pacer.cooldown_sec, pacer.sleep) == (3.0, 300, time.sleep)


def test_the_cooldown_can_be_set_from_the_environment(monkeypatch):
    monkeypatch.setenv("GOTSPORT_WAF_COOLDOWN_SEC", "45")
    assert gotsport_team_details.TeamDetailsPacer().cooldown_sec == 45


@pytest.mark.parametrize("module,expected", PACED_EXPECTATIONS)
def test_a_lookup_sends_the_team_id_to_team_details_with_a_timeout(module, expected):
    """Without a timeout, one stalled connection holds the weekly job until GitHub kills it."""
    resolver = _make_resolver(module)
    session = _FakeSession(TEAM_DETAILS)
    resolver.session = session

    resolver.resolve("742007")

    assert session.sent == [
        (
            "https://system.gotsport.com/api/v1/team_ranking_data/team_details",
            {"team_id": "742007"},
            TIMEOUTS[module.__name__],
        )
    ]


@pytest.mark.parametrize("module,expected", PACED_EXPECTATIONS)
def test_every_request_waits_its_spacing_first_and_a_cached_answer_does_not(module, expected):
    """Back-to-back lookups are what GotSport's per-IP burst limiter blocks: on 2026-11-10
    it refused every lookup after about the 1,100th of a run sent without a pause."""
    sleeps = _Sleeps()
    resolver = _make_resolver(module, sleep=sleeps)
    resolver.session = _FakeSession(TEAM_DETAILS)

    resolver.resolve("742007")
    resolver.resolve("742008")
    resolver.resolve("742007")

    assert sleeps == [3.0, 3.0]


@pytest.mark.parametrize("module,expected", PACED_EXPECTATIONS)
def test_a_cloudfront_block_is_waited_out_and_retried_once(module, expected):
    sleeps = _Sleeps()
    resolver = _make_resolver(module, sleep=sleeps)
    resolver.session = _ScriptedSession(_FakeResponse({}, 403, CLOUDFRONT), _FakeResponse(TEAM_DETAILS))

    assert resolver.resolve("742007") == expected
    assert sleeps == [3.0, 300, 3.0]


@pytest.mark.parametrize("module,expected", PACED_EXPECTATIONS)
def test_a_block_that_outlasts_the_wait_stops_every_later_lookup(module, expected):
    """Pressing on through a block prolongs it, so the rest of the run sends no more requests
    into it."""
    sleeps = _Sleeps()
    resolver = _make_resolver(module, sleep=sleeps)
    session = _ScriptedSession(_FakeResponse({}, 403, CLOUDFRONT))
    resolver.session = session

    assert resolver.resolve("742007") == {}
    assert resolver.resolve("742008") == {}
    assert len(session.calls) == 2
    assert sleeps == [3.0, 300, 3.0]


@pytest.mark.parametrize("module,expected", PACED_EXPECTATIONS)
def test_a_403_that_is_not_cloudfront_is_not_waited_out(module, expected):
    sleeps = _Sleeps()
    resolver = _make_resolver(module, sleep=sleeps)
    resolver.session = _ScriptedSession(_FakeResponse({}, 403), _FakeResponse(TEAM_DETAILS))

    assert resolver.resolve("742007") == {}
    assert sleeps == [3.0]
    assert resolver.resolve("742007") == expected


@pytest.mark.parametrize("status", [200, 404])
@pytest.mark.parametrize("module,expected", PACED_EXPECTATIONS)
def test_a_cloudfront_header_on_an_answer_is_not_a_block(module, expected, status):
    sleeps = _Sleeps()
    resolver = _make_resolver(module, sleep=sleeps)
    resolver.session = _FakeSession(TEAM_DETAILS, status, CLOUDFRONT)

    assert resolver.resolve("742007") == (expected if status == 200 else {})
    assert sleeps == [3.0]
    assert not resolver.pacer.stopped


def test_the_export_counts_an_id_it_never_read_and_drops_one_a_later_row_read():
    resolver = _make_resolver(export_unknown_opponents)
    resolver.session = _FailingThenWorkingSession(TEAM_DETAILS)

    resolver.resolve("742007")
    assert resolver.failed == {"742007"}
    resolver.resolve("742007")
    assert resolver.failed == set()
