"""Pin the Seeding tab's GotSport event intake.

Every page of that walk is billed, so the assertions that matter most are the
ones guarding spend: which division limit each button asks for, that the runner
forwards it untouched, that the full-event button stays disabled until a probe
has actually read a division, and that a failure in the free lookups afterwards
cannot throw away the roster that was paid for.

``tournament_intake.st`` is replaced wholesale, the way the other tests of this
app's Streamlit-touching helpers do it. The scrape lock is replaced too: the
real one creates ``reports/gotsport__<id>__unknown/intake/.scrape.lock`` and
would either mutate the operator's own storage or contend with a live scrape.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pytest

import tournament_intake
from src.tournaments.gotsport_event_roster import (
    EventRoster,
    EventRosterTeam,
    WafChallengeError,
)
from src.tournaments.storage import reports_dir

EVENT_URL = "https://system.gotsport.com/org_event/events/52975"
EVENT_LOCK_DIR = "gotsport__52975__unknown"


# -------- Streamlit double ------------------------------------------------


class _FakeSessionState(dict):
    """``st.session_state``, including that a write is a yield point.

    Streamlit checks for a queued rerun before every write and raises it from
    ``BaseException``. ``raise_on_write`` models that: a plain dict would let
    every write through and hide an ordering that loses a paid walk.
    """

    def __init__(self, raise_on_write: BaseException | None = None) -> None:
        super().__init__()
        dict.__setattr__(self, "_raise_on_write", raise_on_write)

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def arm(self, error: BaseException) -> None:
        """Queue a rerun, as an operator clicking mid-walk does."""
        dict.__setattr__(self, "_raise_on_write", error)

    def __setitem__(self, key: str, value: Any) -> None:
        pending = self.__dict__.get("_raise_on_write")
        if pending is not None:
            dict.__setattr__(self, "_raise_on_write", None)
            raise pending
        super().__setitem__(key, value)

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


class _Rerun(BaseException):
    """What ``st.rerun`` raises.

    Derived from ``BaseException``, as Streamlit's own ``RerunException`` is, so
    that a handler catching ``Exception`` cannot swallow it. A double that raised
    an ordinary ``Exception`` here would let code pass that production stops.
    """


class _FakeSpinner:
    """``st.spinner``, including that its cleanup is a script-thread yield point.

    ``raise_on_exit`` models a rerun queued while the walk was running: real
    Streamlit surfaces it when the spinner's message is cleared, which is after
    the walk has been paid for and before anything the caller does next.
    """

    def __init__(self, log: list[tuple[str, str]], text: str, raise_on_exit: BaseException | None) -> None:
        self._log = log
        self._text = text
        self._raise_on_exit = raise_on_exit

    def __enter__(self) -> _FakeSpinner:
        self._log.append(("enter", self._text))
        return self

    def __exit__(self, *_exc: Any) -> bool:
        self._log.append(("exit", self._text))
        if self._raise_on_exit is not None:
            raise self._raise_on_exit
        return False


class _FakeColumn:
    """A column, which Streamlit also lets a caller write through directly."""

    def __init__(self, owner: _FakeSt | None = None) -> None:
        self._owner = owner

    def __enter__(self) -> _FakeColumn:
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False

    def metric(self, label: str, value: Any, **_kw: Any) -> None:
        if self._owner is not None:
            self._owner.metrics.append((str(label), value))


class _FakeSt:
    def __init__(
        self,
        *,
        buttons: dict[str, bool] | None = None,
        text: dict[str, str] | None = None,
        spinner_raises: BaseException | None = None,
        session_state_raises: BaseException | None = None,
    ) -> None:
        self.session_state = _FakeSessionState(session_state_raises)
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.captions: list[str] = []
        self.successes: list[str] = []
        self.markdowns: list[str] = []
        self.spinners: list[tuple[str, str]] = []
        self.buttons: list[dict[str, Any]] = []
        self.metrics: list[tuple[str, Any]] = []
        self.downloads: list[str] = []
        self.dataframes = 0
        self.reruns = 0
        self._button_returns = buttons or {}
        self._text_returns = text or {}
        self._spinner_raises = spinner_raises

    def error(self, message: str) -> None:
        self.errors.append(str(message))

    def warning(self, message: str) -> None:
        self.warnings.append(str(message))

    def info(self, message: str) -> None:
        self.infos.append(str(message))

    def caption(self, message: str) -> None:
        self.captions.append(str(message))

    def success(self, message: str) -> None:
        self.successes.append(str(message))

    def markdown(self, message: str, **_kw: Any) -> None:
        self.markdowns.append(str(message))

    def spinner(self, text: str = "") -> _FakeSpinner:
        return _FakeSpinner(self.spinners, str(text), self._spinner_raises)

    def rerun(self) -> None:
        self.reruns += 1
        raise _Rerun()

    def text_input(self, _label: str, **kw: Any) -> str:
        return self._text_returns.get(kw.get("key"), "")

    def button(self, label: str, **kw: Any) -> bool:
        self.buttons.append({"label": label, **kw})
        return self._button_returns.get(kw.get("key"), False)

    def columns(self, spec: Any, **_kw: Any) -> list[_FakeColumn]:
        count = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        return [_FakeColumn(self) for _ in range(count)]

    def container(self, **_kw: Any) -> _FakeColumn:
        return _FakeColumn(self)

    def text_area(self, _label: str, **kw: Any) -> str:
        return self._text_returns.get(kw.get("key"), "")

    def metric(self, label: str, value: Any, **_kw: Any) -> None:
        self.metrics.append((str(label), value))

    def dataframe(self, *_a: Any, **_kw: Any) -> None:
        self.dataframes += 1

    def download_button(self, label: str, **_kw: Any) -> bool:
        self.downloads.append(str(label))
        return False

    def button_by_key(self, key: str) -> dict[str, Any]:
        for call in self.buttons:
            if call.get("key") == key:
                return call
        raise AssertionError(f"no button rendered with key {key!r}")


# -------- fixtures --------------------------------------------------------


def _team(index: int, **overrides: Any) -> EventRosterTeam:
    return EventRosterTeam(
        **{
            "source_index": index,
            "group_id": "77",
            "division_label": "U-13 BOYS GOLD",
            "age_group": "u13",
            "gender": "Male",
            "team_name": f"Team {index}",
            "registration_id": str(4200000 + index),
            "provider_team_id": None,
            **overrides,
        }
    )


def _roster(*teams: EventRosterTeam, **overrides: Any) -> EventRoster:
    return EventRoster(
        **{
            "event_id": "52975",
            "teams": teams,
            "warnings": (),
            "divisions_found": 40,
            "divisions_walked": 2,
            **overrides,
        }
    )


class _RecordingScrape:
    """Stands in for ``scrape_event_roster`` and records how it was called."""

    def __init__(self, roster: EventRoster | None = None, raises: BaseException | None = None) -> None:
        self.roster = roster if roster is not None else _roster(_team(0))
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    def __call__(self, event_id: str, **kwargs: Any) -> EventRoster:
        self.calls.append({"event_id": event_id, **kwargs})
        if self.raises is not None:
            raise self.raises
        return self.roster


@contextlib.contextmanager
def _no_lock(_key: str):
    yield


@pytest.fixture
def app(monkeypatch):
    """``tournament_intake`` with its Streamlit surface and scrape lock replaced."""
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    monkeypatch.setattr(tournament_intake, "_acquire_scrape_lock", _no_lock)
    monkeypatch.setattr(tournament_intake, "make_zenrows_fetcher", lambda *_a, **_kw: (lambda url: ""))
    monkeypatch.setattr(tournament_intake, "_autosave_seeding_run", _autosave_must_not_run)
    monkeypatch.setattr(tournament_intake, "resolve_master_ids", lambda teams, **_kw: ({}, []))
    monkeypatch.setattr(tournament_intake, "search_gotsport_teams", lambda *_a, **_kw: [])
    monkeypatch.setattr(tournament_intake, "_seeding_provider_id_lookup", lambda _client: (lambda _pid: None))
    monkeypatch.setattr(tournament_intake, "make_exact_name_lookup", lambda _client: (lambda *_a: []))
    return monkeypatch


def _autosave_must_not_run() -> None:
    raise AssertionError("this path saves only when the operator presses Save")


def _install(monkeypatch, fake_st: _FakeSt) -> _FakeSt:
    monkeypatch.setattr(tournament_intake, "st", fake_st)
    return fake_st


def _scrape(url: str = EVENT_URL, client: Any = None, *, limit_groups: int | None) -> None:
    """Run the walk the way Streamlit does: a rerun ends the script run."""
    with contextlib.suppress(_Rerun):
        tournament_intake._run_event_roster_scrape(url, client, limit_groups=limit_groups)


def _render_controls(client: Any = None) -> None:
    with contextlib.suppress(_Rerun):
        tournament_intake._render_seeding_event_scrape(client)


# -------- the runner's paid arguments -------------------------------------


def test_the_runner_forwards_the_division_limit_and_the_worker_count(app):
    scrape = _RecordingScrape()
    app.setattr(tournament_intake, "scrape_event_roster", scrape)
    _install(app, _FakeSt())

    _scrape(limit_groups=2)

    assert scrape.calls[0]["event_id"] == "52975"
    assert scrape.calls[0]["limit_groups"] == 2
    assert scrape.calls[0]["max_workers"] == 8, "the scraper defaults to serial, which walks an event for hours"


def test_the_runner_forwards_a_full_walk_as_no_limit(app):
    scrape = _RecordingScrape()
    app.setattr(tournament_intake, "scrape_event_roster", scrape)
    _install(app, _FakeSt())

    _scrape(limit_groups=None)

    assert scrape.calls[0]["limit_groups"] is None


def test_the_walk_never_creates_a_lock_directory_under_reports(app, monkeypatch):
    """The lock is stubbed here; this fails loudly if a future edit unstubs it."""
    scrape = _RecordingScrape()
    app.setattr(tournament_intake, "scrape_event_roster", scrape)
    _install(app, _FakeSt())

    _scrape(limit_groups=2)

    assert not (reports_dir() / EVENT_LOCK_DIR).exists()


# -------- guards before any money is spent --------------------------------


def test_a_missing_api_key_returns_before_a_fetcher_is_built(app):
    app.delenv("ZENROWS_API_KEY", raising=False)
    built: list[Any] = []
    app.setattr(tournament_intake, "make_zenrows_fetcher", lambda *a, **kw: built.append(a) or (lambda url: ""))
    scrape = _RecordingScrape()
    app.setattr(tournament_intake, "scrape_event_roster", scrape)
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=2)

    assert built == []
    assert scrape.calls == []
    assert any("ZENROWS_API_KEY" in message for message in fake_st.errors)


def test_an_unreadable_url_returns_before_the_walk(app):
    scrape = _RecordingScrape()
    app.setattr(tournament_intake, "scrape_event_roster", scrape)
    fake_st = _install(app, _FakeSt())

    _scrape("https://example.com/not-an-event", limit_groups=2)

    assert scrape.calls == []
    assert fake_st.errors


def test_an_event_publishing_no_teams_warns_and_parks_nothing(app):
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(_roster()))
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=2)

    assert fake_st.warnings
    assert fake_st.session_state.get("_seeding_result") is None
    assert fake_st.session_state["_seeding_event_probe"]["divisions_walked"] == 2


# -------- failures during the walk ----------------------------------------


def test_a_bot_challenge_is_reported_as_a_block(app):
    app.setattr(
        tournament_intake,
        "scrape_event_roster",
        _RecordingScrape(raises=WafChallengeError("challenged")),
    )
    fake_st = _install(app, _FakeSt())
    fake_st.session_state._scrape_in_progress = True

    _scrape(limit_groups=2)

    assert any("bot challenge" in message for message in fake_st.errors)
    assert fake_st.session_state._scrape_in_progress is False
    assert ("exit", "Walking the event...") in fake_st.spinners


def test_an_ordinary_failure_is_not_reported_as_a_block(app):
    app.setattr(
        tournament_intake,
        "scrape_event_roster",
        _RecordingScrape(raises=RuntimeError("ZenRows gave up")),
    )
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=2)

    assert any("ZenRows gave up" in message for message in fake_st.errors)
    assert not any("bot challenge" in message for message in fake_st.errors), (
        "WafChallengeError subclasses RuntimeError, so a generic handler would swallow the blocked-run wording"
    )
    assert fake_st.session_state._scrape_in_progress is False
    assert ("exit", "Walking the event...") in fake_st.spinners


def test_a_contended_lock_is_reported_and_nothing_is_parked(app):
    @contextlib.contextmanager
    def _contended(_key: str):
        raise tournament_intake._ScrapeLockContended("busy")
        yield  # pragma: no cover

    app.setattr(tournament_intake, "_acquire_scrape_lock", _contended)
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape())
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=2)

    assert any("another tab" in message for message in fake_st.errors)
    assert fake_st.session_state.get("_seeding_result") is None


# -------- what the walk produces ------------------------------------------


def test_a_linked_team_lands_as_a_resolved_row(app):
    app.setattr(
        tournament_intake,
        "scrape_event_roster",
        _RecordingScrape(_roster(_team(0, provider_team_id="521426"))),
    )
    app.setattr(
        tournament_intake,
        "resolve_master_ids",
        lambda teams, **_kw: ({"521426": "uuid-a"}, []),
    )
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=None)

    parsed, resolved = fake_st.session_state._seeding_result
    assert parsed.rows[0].team_name_raw == "Team 0"
    assert resolved[0].status == "gotsport_id"
    assert resolved[0].team_id_master == "uuid-a"
    assert fake_st.session_state._seeding_overrides == {}


def test_an_unlinked_team_goes_through_the_free_name_lookups(app):
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(_roster(_team(0), _team(1))))
    searched: list[tuple[Any, ...]] = []
    id_lookups: list[str] = []
    name_lookups: list[tuple[str, str, str]] = []

    app.setattr(
        tournament_intake,
        "search_gotsport_teams",
        lambda *args, **kw: searched.append(args) or [],
    )
    app.setattr(
        tournament_intake,
        "_seeding_provider_id_lookup",
        lambda _client: (lambda pid: id_lookups.append(pid) or None),
    )
    app.setattr(
        tournament_intake,
        "make_exact_name_lookup",
        lambda _client: (lambda name, age, gender: name_lookups.append((name, age, gender)) or ["uuid-b"]),
    )
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=None)

    _parsed, resolved = fake_st.session_state._seeding_result
    assert searched, "a team with no provider id takes the GotSport name search"
    assert name_lookups, "and then the exact-name pass"
    assert [item.source_index for item in resolved] == [0, 1]
    assert resolved[0].status == "exact_name"
    assert resolved[0].team_id_master == "uuid-b"
    assert fake_st.session_state._seeding_resolution_failed is False


def test_a_lookup_failure_leaves_the_paid_roster_parked(app):
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(_roster(_team(0), _team(1))))

    def _explode(_client):
        raise TypeError("supabase transport blew up in a way no named handler covers")

    app.setattr(tournament_intake, "_seeding_provider_id_lookup", _explode)
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=None)

    parsed, resolved = fake_st.session_state._seeding_result
    assert len(parsed.rows) == 2, "the roster is the paid artifact and must survive a free-pass failure"
    assert len(resolved) == 2
    assert fake_st.session_state._seeding_resolution_failed is True, (
        "the flag is what offers the free retry on the next run"
    )


def test_the_scrape_clears_the_cached_sheet_but_not_the_open_run_marker(app):
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape())
    fake_st = _install(app, _FakeSt())
    fake_st.session_state._seeding_sheet_html = "<html>old event</html>"
    fake_st.session_state._seeding_loaded_slug = "stx-cup-2026"

    _scrape(limit_groups=None)

    assert fake_st.session_state._seeding_sheet_html is None
    assert fake_st.session_state._seeding_loaded_slug == "stx-cup-2026", (
        "clearing this makes the resume selector reload its run over the fresh scrape"
    )


def test_the_scrape_does_not_save_the_run(app):
    """``_autosave_seeding_run`` is stubbed to raise, so any call fails here."""
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape())
    _install(app, _FakeSt())

    _scrape(limit_groups=None)


# -------- the render boundary and its spend gate --------------------------


def _render(monkeypatch, *, url: str, probe: dict[str, Any] | None, buttons: dict[str, bool] | None = None):
    runs: list[dict[str, Any]] = []
    fake_st = _install(monkeypatch, _FakeSt(buttons=buttons, text={"seeding_event_url": url}))
    if probe is not None:
        fake_st.session_state._seeding_event_probe = probe
    monkeypatch.setattr(
        tournament_intake,
        "_run_event_roster_scrape",
        lambda url, client, **kw: runs.append({"url": url, **kw}),
    )
    _render_controls()
    return fake_st, runs


def _probe(**overrides: Any) -> dict[str, Any]:
    return {
        "url": EVENT_URL,
        "limit_groups": 2,
        "divisions_found": 40,
        "divisions_walked": 2,
        "teams": 11,
        "linked": 8,
        **overrides,
    }


def test_the_full_event_button_is_disabled_until_something_has_been_probed(app):
    fake_st, runs = _render(app, url=EVENT_URL, probe=None)

    assert fake_st.button_by_key("_seeding_event_full_run")["disabled"] is True
    assert runs == []


def test_a_probe_of_a_different_event_does_not_unlock_this_one(app):
    fake_st, _runs = _render(app, url=EVENT_URL, probe=_probe(url="https://system.gotsport.com/org_event/events/1"))

    assert fake_st.button_by_key("_seeding_event_full_run")["disabled"] is True


def test_a_probe_that_read_no_division_does_not_unlock_the_full_event(app):
    fake_st, _runs = _render(app, url=EVENT_URL, probe=_probe(divisions_walked=0, teams=0, linked=0))

    assert fake_st.button_by_key("_seeding_event_full_run")["disabled"] is True
    assert not any("$" in caption for caption in fake_st.captions), (
        "two divisions of nothing is not a sample to price an event from"
    )


def test_a_matching_probe_unlocks_the_full_event_and_prices_it(app):
    fake_st, _runs = _render(app, url=EVENT_URL, probe=_probe())

    assert fake_st.button_by_key("_seeding_event_full_run")["disabled"] is False
    assert any("$" in caption for caption in fake_st.captions)


def test_the_probe_button_asks_for_two_divisions(app):
    _fake_st, runs = _render(app, url=EVENT_URL, probe=None, buttons={"_seeding_event_probe_run": True})

    assert runs == [{"url": EVENT_URL, "limit_groups": 2}]


def test_the_full_button_asks_for_the_whole_event(app):
    _fake_st, runs = _render(
        app,
        url=EVENT_URL,
        probe=_probe(),
        buttons={"_seeding_event_full_run": True},
    )

    assert runs == [{"url": EVENT_URL, "limit_groups": None}]


def test_neither_button_runs_without_a_url(app):
    fake_st, runs = _render(app, url="", probe=None)

    assert fake_st.button_by_key("_seeding_event_probe_run")["disabled"] is True
    assert fake_st.button_by_key("_seeding_event_full_run")["disabled"] is True
    assert runs == []


def test_a_scrape_already_running_disables_both_buttons(app):
    fake_st = _install(app, _FakeSt(text={"seeding_event_url": EVENT_URL}))
    fake_st.session_state._scrape_in_progress = True

    _render_controls()

    assert fake_st.button_by_key("_seeding_event_probe_run")["disabled"] is True
    assert fake_st.button_by_key("_seeding_event_full_run")["disabled"] is True


def test_a_missing_api_key_is_flagged_at_the_control(app):
    app.delenv("ZENROWS_API_KEY", raising=False)
    fake_st, _runs = _render(app, url=EVENT_URL, probe=None)

    assert any("ZENROWS_API_KEY" in message for message in fake_st.infos)


def test_a_failed_lookup_offers_a_free_retry(app):
    retries: list[Any] = []
    fake_st = _install(app, _FakeSt(buttons={"_seeding_retry_lookup": True}, text={"seeding_event_url": EVENT_URL}))
    fake_st.session_state._seeding_resolution_failed = True
    fake_st.session_state._seeding_result = ("parsed", "resolved")
    app.setattr(
        tournament_intake,
        "_run_seeding_name_lookup",
        lambda parsed, resolved, client: retries.append((parsed, resolved)),
    )

    _render_controls()

    assert retries == [("parsed", "resolved")]


def test_no_retry_is_offered_while_the_lookups_are_healthy(app):
    fake_st, _runs = _render(app, url=EVENT_URL, probe=_probe())

    assert all(call.get("key") != "_seeding_retry_lookup" for call in fake_st.buttons)


# -------- the price the operator decides on -------------------------------


def test_the_caption_prices_the_whole_event_not_the_sample():
    """40 divisions at the sampled 5.5 teams each, plus a landing page.

    Pricing the two divisions actually walked instead would quote about a
    nineteenth of the real bill, on the one number the operator has when
    authorizing the spend.
    """
    caption = tournament_intake._seeding_probe_caption(_probe(divisions_found=40, divisions_walked=2, teams=11))

    pages = 1 + 40 + 40 * 11 / 2
    low = pages * 0.5 * tournament_intake._SEEDING_EVENT_PAGE_COST_USD
    high = pages * 1.5 * tournament_intake._SEEDING_EVENT_PAGE_COST_USD
    assert f"{tournament_intake._money(low)}-{tournament_intake._money(high)}" in caption
    assert low < high, "the range reads low to high"


def test_a_probe_that_found_no_team_prices_nothing():
    """Divisions with no schedule posted yet are the normal seeding-time state."""
    caption = tournament_intake._seeding_probe_caption(_probe(divisions_walked=2, teams=0, linked=0))

    assert "$" not in caption
    assert "not enough to price" in caption


def test_a_full_walk_quotes_no_further_cost():
    caption = tournament_intake._seeding_probe_caption(
        _probe(limit_groups=None, divisions_walked=40, teams=220)
    )

    assert "$" not in caption, "the whole event has already been walked"


def test_the_probe_price_is_the_arithmetic_it_claims_to_be():
    """Written out rather than derived, so a wrong page count fails here.

    A landing page, then each probed division's own page, then one page per team
    in them — priced across the teams-per-division spread the constant records.
    """
    low, high = tournament_intake._seeding_probe_price()

    assert low == pytest.approx((1 + 2 * (1 + 3.0)) * 0.004)
    assert high == pytest.approx((1 + 2 * (1 + 9.0)) * 0.004)


def test_the_probe_buttons_label_carries_that_price(app):
    fake_st, _runs = _render(app, url=EVENT_URL, probe=None)
    label = fake_st.button_by_key("_seeding_event_probe_run")["label"]
    low, high = tournament_intake._seeding_probe_price()

    assert f"{tournament_intake._SEEDING_EVENT_PROBE_DIVISIONS} divisions" in label
    assert f"{tournament_intake._money(low)}-{tournament_intake._money(high)}" in label


def test_a_price_is_written_so_streamlit_does_not_read_it_as_maths():
    """`$` opens inline LaTeX in the Markdown every Streamlit message renders as.

    Unescaped, `$0.04-$0.08` reaches the operator as maths symbols — caught in a
    browser, because an assertion on the string we build cannot see it.
    """
    assert tournament_intake._money(0.04) == chr(92) + "$0.04"


@pytest.mark.parametrize(
    "text",
    [
        "Check 2 divisions",
        "The whole event looks like",
    ],
)
def test_no_money_surface_emits_a_bare_dollar(app, text):
    """Both controls that state a cost go through the same escaping."""
    fake_st, _runs = _render(app, url=EVENT_URL, probe=_probe())
    rendered = [call["label"] for call in fake_st.buttons] + list(fake_st.captions)
    matching = [line for line in rendered if text in line]

    assert matching, f"nothing on the page said {text!r}"
    for line in matching:
        for index, char in enumerate(line):
            if char == "$":
                assert index and line[index - 1] == chr(92), f"unescaped dollar in {line!r}"


# -------- saving is the operator's step, and it must be honest ------------


def test_the_save_button_writes_the_run_and_says_so(monkeypatch):
    saved: list[bool] = []
    fake_st = _install(monkeypatch, _FakeSt(buttons={"_seeding_save_run": True}))
    fake_st.session_state["seeding_event_name"] = "STX Cup 2026"
    monkeypatch.setattr(tournament_intake, "_autosave_seeding_run", lambda: saved.append(True) or True)

    tournament_intake._render_seeding_save()

    assert saved == [True], "the button must actually reach the writer"
    assert fake_st.successes


def test_the_save_button_stays_quiet_when_the_write_failed(monkeypatch):
    """``_autosave_seeding_run`` warns and returns False; a success beside that lies."""
    fake_st = _install(monkeypatch, _FakeSt(buttons={"_seeding_save_run": True}))
    fake_st.session_state["seeding_event_name"] = "STX Cup 2026"
    monkeypatch.setattr(tournament_intake, "_autosave_seeding_run", lambda: False)

    tournament_intake._render_seeding_save()

    assert fake_st.successes == []


def test_an_unnamed_run_is_told_to_name_itself_rather_than_offered_a_save(monkeypatch):
    fake_st = _install(monkeypatch, _FakeSt())

    tournament_intake._render_seeding_save()

    assert fake_st.infos
    assert all(call.get("key") != "_seeding_save_run" for call in fake_st.buttons)


# -------- the gate at the moment of spending ------------------------------


def test_editing_the_url_after_a_probe_does_not_buy_the_new_event(app):
    """`disabled` is a render hint; Streamlit still returns the click.

    The operator probes one event, edits the box to another and clicks the
    full-event button in the same run. The button was enabled when it was drawn,
    so the trigger arrives alongside the new URL — and a full walk of an unpriced
    event is the single most expensive thing this tab can do.
    """
    other_url = "https://system.gotsport.com/org_event/events/52980"
    runs: list[dict[str, Any]] = []
    fake_st = _install(
        app,
        _FakeSt(buttons={"_seeding_event_full_run": True}, text={"seeding_event_url": other_url}),
    )
    fake_st.session_state._seeding_event_probe = _probe()
    app.setattr(
        tournament_intake,
        "_run_event_roster_scrape",
        lambda url, client, **kw: runs.append({"url": url, **kw}),
    )

    _render_controls()

    assert runs == [], "a walk was launched for an event no probe ever priced"
    assert fake_st.errors, "and the operator was not told why nothing happened"


def test_a_probe_of_the_same_url_still_buys_the_full_event(app):
    """The negative twin: the gate must not refuse a legitimately priced event."""
    runs: list[dict[str, Any]] = []
    fake_st = _install(
        app,
        _FakeSt(buttons={"_seeding_event_full_run": True}, text={"seeding_event_url": EVENT_URL}),
    )
    fake_st.session_state._seeding_event_probe = _probe()
    app.setattr(
        tournament_intake,
        "_run_event_roster_scrape",
        lambda url, client, **kw: runs.append({"url": url, **kw}),
    )

    _render_controls()

    assert runs == [{"url": EVENT_URL, "limit_groups": None}]
    assert fake_st.errors == []


def test_a_rerun_during_the_walk_cannot_discard_the_paid_roster(app):
    """A queued rerun surfaces when the spinner clears, after the pages are bought.

    Streamlit raises it from ``BaseException``, so no handler in the runner can
    catch it — the roster has to be in session state before the spinner exits or
    the walk is paid for and thrown away.
    """
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(_roster(_team(0), _team(1))))
    fake_st = _install(app, _FakeSt(spinner_raises=_Rerun()))

    _scrape(limit_groups=None)

    parsed, resolved = fake_st.session_state._seeding_result
    assert len(parsed.rows) == 2
    assert len(resolved) == 2
    assert fake_st.session_state._seeding_event_probe["teams"] == 2
    assert fake_st.session_state._scrape_in_progress is False


def test_a_completed_walk_reruns_so_its_own_price_and_gate_are_drawn(app):
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape())
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=2)

    assert fake_st.reruns == 1, (
        "without this the full-event button stays greyed out and the price caption "
        "is missing in the very run that paid for them"
    )


def test_a_failed_walk_does_not_rerun_over_its_own_error(app):
    app.setattr(
        tournament_intake,
        "scrape_event_roster",
        _RecordingScrape(raises=RuntimeError("ZenRows gave up")),
    )
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=2)

    assert fake_st.reruns == 0
    assert fake_st.errors


# -------- what the runner asks the database for ---------------------------


def test_the_walk_resolves_master_ids_against_the_app_client_and_keeps_its_warnings(app):
    """The kwargs are the call: without them resolution runs against no database.

    Every scraped team would then land unresolved, the paid walk's direct-id
    advantage would quietly degrade to name matching, and the warning explaining
    why would never reach the page.
    """
    calls: list[dict[str, Any]] = []
    client = object()

    def _recording(teams, **kwargs):
        calls.append({"teams": len(teams), **kwargs})
        return {"521426": "uuid-a"}, ["No Supabase credentials"]

    roster = _roster(_team(0, provider_team_id="521426"))
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(roster))
    app.setattr(tournament_intake, "resolve_master_ids", _recording)
    fake_st = _install(app, _FakeSt())

    _scrape(client=client, limit_groups=None)

    assert calls[0]["enabled"] is True
    assert calls[0]["client_factory"]("url", "key") is client, "the app's own client must be the one used"
    parsed, _resolved = fake_st.session_state._seeding_result
    assert parsed.warnings[0] == "No Supabase credentials", (
        "the resolver's warnings are the only signal that credentials failed"
    )


def test_the_free_name_pass_is_throttled(app):
    """The GotSport search is a public endpoint belonging to someone else."""
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(_roster(_team(0), _team(1))))
    passed: list[float] = []

    def _recording_resolve(parsed, resolved, **kwargs):
        passed.append(kwargs["delay_seconds"])
        return tuple(resolved)

    app.setattr(tournament_intake, "resolve_unlinked", _recording_resolve)
    _install(app, _FakeSt())

    _scrape(limit_groups=None)

    assert passed == [tournament_intake._SEEDING_LOOKUP_DELAY_SECONDS]
    assert passed[0] > 0


def test_a_new_scrape_drops_the_previous_events_manual_fixes(app):
    """Overrides key on ``source_index``, so a stale one lands on an unrelated team."""
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(_roster(_team(0), _team(1))))
    fake_st = _install(app, _FakeSt())
    fake_st.session_state._seeding_overrides = {0: {"team_id_master": "from-the-last-event"}}

    _scrape(limit_groups=None)

    assert fake_st.session_state._seeding_overrides == {}


# -------- provider text does not get to author the page -------------------


def test_a_division_label_cannot_put_a_link_in_front_of_the_operator(monkeypatch):
    """Streamlit renders messages as Markdown; organizers choose division names."""
    from src.tournaments.roster_paste import ParsedRoster

    fake_st = _install(monkeypatch, _FakeSt())
    hostile = "Division [Session expired - sign in](https://not-gotsport.example/login) names no single board"

    tournament_intake._render_seeding_warnings(ParsedRoster(rows=(), warnings=(hostile,)))

    assert fake_st.warnings, "the warning must still be shown"
    assert "](" not in fake_st.warnings[0], "a live link reached the operator"
    assert "Session expired" in fake_st.warnings[0], "and the text itself is still readable"


def test_an_ordinary_division_label_is_left_readable(monkeypatch):
    from src.tournaments.roster_paste import ParsedRoster

    fake_st = _install(monkeypatch, _FakeSt())
    plain = "Division U-13 BOYS GOLD / Silver names no single board"

    tournament_intake._render_seeding_warnings(ParsedRoster(rows=(), warnings=(plain,)))

    assert fake_st.warnings == [plain]


def test_every_seeding_id_lookup_resolves_merges(monkeypatch):
    """An approved alias can name a team that was later merged away.

    ``make_provider_id_lookup``'s alias fallback filters on approval, not on
    liveness, so without a resolver a deprecated id reaches the scrape queue and
    the cohort sheet. Every intake goes through one helper so they cannot drift
    apart on it.
    """
    seen: list[Any] = []
    monkeypatch.setattr(tournament_intake, "_seeding_merge_resolver", lambda client: "the-resolver")
    monkeypatch.setattr(
        tournament_intake,
        "make_provider_id_lookup",
        lambda client, resolver=None: seen.append(resolver) or (lambda _pid: None),
    )

    tournament_intake._seeding_provider_id_lookup(object())

    assert seen == ["the-resolver"], "the lookup was built without merge resolution"


def test_no_seeding_lookup_bypasses_the_merge_resolving_helper():
    """Derived from the source, so another call site cannot be added unguarded."""
    source = Path(tournament_intake.__file__).read_text(encoding="utf-8")
    bare = [
        line.strip()
        for line in source.splitlines()
        if "make_provider_id_lookup(" in line
        and "_seeding_provider_id_lookup" not in line
        and "_seeding_merge_resolver(" not in line
        and "def " not in line
        and "import" not in line
    ]

    assert bare == [], f"these call the raw lookup instead of the merge-resolving helper: {bare}"


# -------- the merge resolver, and what it must never serve -----------------


def test_the_seeding_resolver_is_a_loaded_merge_resolver(monkeypatch):
    """The producer, not just the wiring.

    A test that only pins forwarding stays green when this function returns
    nothing, and a lookup built with no resolver hands back deprecated ids.
    """
    loaded: list[str] = []

    class _Resolver:
        version = "ok"

        def __init__(self, client):
            self.client = client

        def load_merge_map(self):
            loaded.append("loaded")

    monkeypatch.setattr(tournament_intake, "MergeResolver", _Resolver)
    client = object()

    resolver = tournament_intake._seeding_merge_resolver.__wrapped__(client)

    assert isinstance(resolver, _Resolver)
    assert resolver.client is client
    assert loaded == ["loaded"], "an unloaded resolver resolves nothing"


def test_a_resolver_whose_merge_map_failed_is_not_reused():
    """``load_merge_map`` swallows its own failure, so this is the only signal.

    Without it the cache serves a resolver that resolves nothing for its whole
    lifetime, and every seeding lookup silently stops applying merges.
    """
    failed = type("R", (), {"version": "error"})()
    healthy = type("R", (), {"version": "abc123"})()

    assert tournament_intake._merge_map_loaded(failed) is False
    assert tournament_intake._merge_map_loaded(healthy) is True


def test_the_resolver_cache_validates_what_it_serves():
    """Pinned at the decorator: ``ttl`` alone would keep a failed load for 10 minutes."""
    import inspect

    source = inspect.getsource(tournament_intake)
    assert "@st.cache_resource(ttl=600, validate=_merge_map_loaded)" in source


def test_the_walk_resolves_ids_through_the_same_cached_resolver(app):
    """Otherwise the walk loads a second merge map, inside the paid spinner."""
    seen: dict[str, Any] = {}

    def _recording(teams, **kwargs):
        seen.update(kwargs)
        return {}, []

    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape())
    app.setattr(tournament_intake, "resolve_master_ids", _recording)
    app.setattr(tournament_intake, "_seeding_merge_resolver", lambda _c: "the-cached-resolver")
    app.setattr(tournament_intake, "_seeding_provider_id_lookup", lambda _c: "the-shared-lookup")
    _install(app, _FakeSt())

    _scrape(limit_groups=2)

    assert seen["resolver_factory"](None) == "the-cached-resolver"
    assert seen["lookup_factory"](None, None) == "the-shared-lookup"


# -------- the recovery file the walk writes before anything else ----------


def test_the_walk_writes_a_recovery_file_before_touching_session_state(app, tmp_path):
    """The roster reaches disk before the work that derives from it."""
    written: list[tuple[Any, dict[str, Any]]] = []
    app.setattr(tournament_intake, "write_json", lambda path, payload: written.append((path, payload)))
    app.setattr(tournament_intake, "reports_dir", lambda: tmp_path)
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(_roster(_team(0), _team(1))))
    _install(app, _FakeSt(spinner_raises=_Rerun()))

    _scrape(limit_groups=None)

    assert written, "the paid roster reached no durable store"
    path, payload = written[0]
    assert path == tmp_path / "seeding" / "gotsport_52975" / "last_walk.json"
    assert len(payload["teams"]) == 2
    assert payload["event_id"] == "52975"
    assert [team["team_name"] for team in payload["teams"]] == ["Team 0", "Team 1"]


def test_a_recovery_write_that_fails_does_not_cost_the_walk(app):
    """The backup must never outrank the thing it is backing up."""

    def _explode(*_a, **_kw):
        raise OSError("disk full")

    app.setattr(tournament_intake, "write_json", _explode)
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(_roster(_team(0))))
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=None)

    parsed, _resolved = fake_st.session_state._seeding_result
    assert len(parsed.rows) == 1


# -------- an event already walked is not for sale again -------------------


def test_a_fully_walked_event_cannot_be_bought_twice(app):
    """A second click queued during the walk arrives once the first run ends."""
    runs: list[dict[str, Any]] = []
    fake_st = _install(
        app,
        _FakeSt(buttons={"_seeding_event_full_run": True}, text={"seeding_event_url": EVENT_URL}),
    )
    fake_st.session_state._seeding_event_probe = _probe(limit_groups=None, complete=True)
    app.setattr(tournament_intake, "_run_event_roster_scrape", lambda url, c, **kw: runs.append(kw))

    _render_controls()

    assert fake_st.button_by_key("_seeding_event_full_run")["disabled"] is True
    assert runs == [], "the event was walked in full already; buying it again is pure waste"
    assert fake_st.errors


def test_a_probed_but_unwalked_event_is_still_for_sale(app):
    runs: list[dict[str, Any]] = []
    fake_st = _install(
        app,
        _FakeSt(buttons={"_seeding_event_full_run": True}, text={"seeding_event_url": EVENT_URL}),
    )
    fake_st.session_state._seeding_event_probe = _probe(complete=False)
    app.setattr(tournament_intake, "_run_event_roster_scrape", lambda url, c, **kw: runs.append(kw))

    _render_controls()

    assert fake_st.button_by_key("_seeding_event_full_run")["disabled"] is False
    assert runs == [{"limit_groups": None}]


def test_a_full_walk_marks_the_event_complete(app):
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape())
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=None)

    assert fake_st.session_state._seeding_event_probe["complete"] is True


def test_a_probe_does_not_mark_the_event_complete(app):
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape())
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=2)

    assert fake_st.session_state._seeding_event_probe["complete"] is False


# -------- a probe that found nothing still redraws its own controls -------


def test_a_probe_that_found_no_teams_still_reruns(app):
    """Without it the operator sees a greyed-out button and re-clicks the paid probe."""
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(_roster()))
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=2)

    assert fake_st.reruns == 1
    assert fake_st.warnings


# -------- the name pass is pending until it commits -----------------------


def test_the_name_pass_is_marked_pending_until_it_commits(app):
    """A rerun inside the lookup spinner would otherwise leave no retry offered."""
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(_roster(_team(0))))
    seen: list[bool] = []

    def _recording_lookup(parsed, resolved, client):
        seen.append(tournament_intake.st.session_state._seeding_resolution_failed)

    app.setattr(tournament_intake, "_run_seeding_name_lookup", _recording_lookup)
    _install(app, _FakeSt())

    _scrape(limit_groups=None)

    assert seen == [True], "the flag must already be set when the free pass starts"


# -------- the tab actually wires its parts together -----------------------


def test_the_seeding_tab_renders_the_event_intake_and_the_warnings(monkeypatch):
    """Every helper is tested alone; these are the lines that join them to the app."""
    import pandas as pd

    from src.tournaments.roster_paste import ParsedRoster, RosterRow
    from src.tournaments.roster_resolver import ResolvedTeam

    called: list[str] = []
    row = RosterRow(
        source_index=0,
        club_raw="",
        team_name_raw="Team 0",
        state="",
        section_age_group="u13",
        section_gender="Male",
        team_name_stripped="Team 0",
        has_star_marker=False,
        has_c_marker=False,
    )
    parsed = ParsedRoster(rows=(row,), warnings=("a division named no board",))
    resolved = (ResolvedTeam(source_index=0, status="unresolved"),)

    fake_st = _install(monkeypatch, _FakeSt())
    fake_st.session_state._seeding_result = (parsed, resolved)
    fake_st.session_state._seeding_overrides = {}

    for name in (
        "_render_seeding_run_controls",
        "_render_seeding_event_scrape",
        "_render_seeding_warnings",
        "_render_seeding_save",
        "_render_seeding_enqueue",
        "_render_seeding_sheet",
        "_render_seeding_override",
    ):
        monkeypatch.setattr(
            tournament_intake, name, (lambda n: lambda *a, **kw: called.append(n))(name)
        )
    monkeypatch.setattr(
        tournament_intake,
        "_seeding_result_frame",
        lambda *a, **kw: pd.DataFrame({"Status": ["Not found"], "Team": ["Team 0"]}),
    )

    tournament_intake._render_seeding_tab(None)

    assert "_render_seeding_event_scrape" in called, "the GotSport event intake is not on the page"
    assert "_render_seeding_warnings" in called, "cohort and credential warnings never reach the operator"
    assert "_render_seeding_save" in called


# -------- saving happens only on a press ----------------------------------


def test_a_named_run_is_not_saved_until_the_button_is_pressed(monkeypatch):
    """Otherwise every rerun overwrites the stored run with whatever is loaded."""
    saved: list[str] = []
    fake_st = _install(monkeypatch, _FakeSt())
    fake_st.session_state["seeding_event_name"] = "STX Cup 2026"
    monkeypatch.setattr(tournament_intake, "_autosave_seeding_run", lambda: saved.append("wrote") or True)

    tournament_intake._render_seeding_save()

    assert saved == [], "a rerun with a named run must not write on its own"
    assert fake_st.successes == []


# -------- provider text, character by character ---------------------------


@pytest.mark.parametrize("char", ["\\", "`", "*", "_", "[", "]", "(", ")", "<", ">", "!"])
def test_every_markdown_character_is_escaped(char):
    assert tournament_intake._as_plain_text("A" + char + "B") == "A\\" + char + "B"


@pytest.mark.parametrize(
    "link", ["https://evil.example/x", "http://evil.example", "www.evil.example"]
)
def test_a_bare_address_is_shown_monospace_so_it_cannot_be_clicked(link):
    """Escaping cannot reach an autolink; a code span is what stops it."""
    rendered = tournament_intake._as_plain_text("Division " + link + " names no board")

    assert "`" + link + "`" in rendered


def test_ordinary_punctuation_in_a_division_label_survives():
    label = "U-13 BOYS GOLD / Silver, 9v9"

    assert tournament_intake._as_plain_text(label) == label


# -------- the caption's own numbers ---------------------------------------


def test_the_caption_reports_the_counts_it_was_given():
    caption = tournament_intake._seeding_probe_caption(
        _probe(divisions_found=40, divisions_walked=2, teams=11, linked=8)
    )

    assert "Walked 2 of 40 divisions" in caption
    assert "11 teams" in caption
    assert "8 carrying a GotSport id" in caption


# -------- the card an unlinked scraped team is reviewed on ----------------


def test_a_scraped_team_name_cannot_put_a_link_on_its_review_card(monkeypatch):
    """This card is where every team the walk could not link is read.

    ``html.escape`` is the wrong escaper here: Streamlit already blocks HTML at
    ``unsafe_allow_html=False``, and what it leaves untouched — ``!``, ``[``,
    ``]``, ``(``, ``)`` — is exactly the syntax that renders a link or an image.
    """
    from src.tournaments.roster_paste import RosterRow
    from src.tournaments.roster_resolver import ResolvedTeam

    fake_st = _install(monkeypatch, _FakeSt())
    row = RosterRow(
        source_index=0,
        club_raw="",
        team_name_raw="![](https://collect.example/beacon.png)",
        state="",
        section_age_group="u13",
        section_gender="Male",
        team_name_stripped="![](https://collect.example/beacon.png)",
        has_star_marker=False,
        has_c_marker=False,
    )

    tournament_intake._render_seeding_override(row, ResolvedTeam(source_index=0, status="unresolved"), None)

    heading = fake_st.markdowns[0]
    assert "](" not in heading, "an image or link reached the operator's review card"
    assert "collect.example" in heading, "the name itself must still be readable"


def test_the_candidates_line_cannot_carry_a_link_either(monkeypatch):
    """Candidate names come from the provider's own search results."""
    from src.tournaments.roster_paste import RosterRow
    from src.tournaments.roster_resolver import ResolvedTeam

    fake_st = _install(monkeypatch, _FakeSt())
    row = RosterRow(
        source_index=0,
        club_raw="",
        team_name_raw="Team 0",
        state="",
        section_age_group="u13",
        section_gender="Male",
        team_name_stripped="Team 0",
        has_star_marker=False,
        has_c_marker=False,
    )
    item = ResolvedTeam(
        source_index=0,
        status="review",
        candidates=({"team_name": "[Click here](https://evil.example)"},),
    )

    tournament_intake._render_seeding_override(row, item, None)

    assert fake_st.captions, "the candidates line should still be shown"
    assert "](" not in fake_st.captions[0]


def test_a_rerun_at_the_first_session_write_still_leaves_the_roster_on_disk(app, tmp_path):
    """The ordering the recovery file exists for.

    Streamlit checks for a queued rerun before every session-state write, so the
    first assignment in the parking step is itself a place the walk can stop.
    Anything the recovery write waits on — resolving ids, converting rows, the
    spinner ``st.cache_resource`` opens on a miss — is a page already paid for
    and about to be thrown away.
    """
    written: list[tuple[Any, dict[str, Any]]] = []
    app.setattr(tournament_intake, "write_json", lambda path, payload: written.append((path, payload)))
    app.setattr(tournament_intake, "reports_dir", lambda: tmp_path)
    fake_st = _install(app, _FakeSt())

    def _walk_then_the_operator_clicks(event_id, **_kw):
        fake_st.session_state.arm(_Rerun())
        return _roster(_team(0), _team(1))

    app.setattr(tournament_intake, "scrape_event_roster", _walk_then_the_operator_clicks)

    _scrape(limit_groups=None)

    assert written, "the walk was paid for and nothing survived the rerun"
    assert len(written[0][1]["teams"]) == 2


def test_the_recovery_write_precedes_the_id_resolution_it_does_not_need(app, tmp_path):
    """Resolution is free to redo; the walk is not, so it cannot go first."""
    order: list[str] = []
    app.setattr(
        tournament_intake,
        "write_json",
        lambda path, payload: order.append("recovery"),
    )
    app.setattr(tournament_intake, "reports_dir", lambda: tmp_path)
    app.setattr(
        tournament_intake,
        "resolve_master_ids",
        lambda teams, **_kw: (order.append("resolve"), ({}, []))[1],
    )
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape())
    _install(app, _FakeSt())

    _scrape(limit_groups=None)

    assert order == ["recovery", "resolve"]
