"""Pin the Seeding tab's GotSport event intake.

Every page of that walk is billed, so the assertions that matter most are the
ones guarding spend: which division limit each button asks for, that the runner
forwards it untouched, that the full-event button stays disabled until a probe
has actually read a division, and that a failure in the free lookups afterwards
cannot throw away the roster that was paid for.

``tournament_intake.st`` is replaced wholesale, the way the other tests of this
app's Streamlit-touching helpers do it. Two things that reach the filesystem are
replaced too, because both write where the operator keeps their own runs: the
scrape lock, which creates ``reports/gotsport__<id>__unknown/intake/.scrape.lock``
and would contend with a live scrape, and ``reports_dir`` itself, which the walk
writes its recovery file through.
"""

from __future__ import annotations

import contextlib
import json
import pathlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

import tournament_intake
from src.tournaments.event_roster_intake import to_seeding_rows
from src.tournaments.gotsport_event_roster import (
    EventRoster,
    EventRosterTeam,
    WafChallengeError,
)
from src.tournaments.roster_paste import ParsedRoster, RosterRow
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_run_store import SeedingRun

EVENT_URL = "https://system.gotsport.com/org_event/events/52975"
EVENT_LOCK_DIR = "gotsport__52975__unknown"


# -------- Streamlit double ------------------------------------------------


class _FakeSessionState(dict):
    """``st.session_state``, including every place it can raise a queued stop.

    ``SafeSessionState`` calls its yield callback at the top of ``__getitem__``,
    ``__setitem__``, ``__delitem__`` and ``__contains__`` — so a **read** is a
    stop point too, not only a write, and that callback raises from
    ``BaseException``. A double armed on writes alone lets the first statement of
    ``_scrape_still_running`` through, which is the read this change is built
    around.

    ``get`` is overridden explicitly. This subclasses ``dict``, whose ``get`` is
    a C-level method that does not dispatch to an overridden ``__getitem__``, so
    without it ``st.session_state.get(...)`` would stay unmodelled however
    faithful ``__getitem__`` became.

    ``sticky`` models a STOP rather than a RERUN: ``ScriptRequests`` returns a
    RERUN once and then resets to CONTINUE, while a STOP "remains stopped" and
    raises at every later yield point — which is why a walk's ``finally`` cannot
    be relied on to clear its own flag.
    """

    def __init__(self, raise_on_write: BaseException | None = None) -> None:
        super().__init__()
        dict.__setattr__(self, "_pending", raise_on_write)
        dict.__setattr__(self, "_sticky", False)

    def arm(self, error: BaseException, *, sticky: bool = False) -> None:
        """Queue a rerun, or with ``sticky`` a stop, as a mid-walk click does."""
        dict.__setattr__(self, "_pending", error)
        dict.__setattr__(self, "_sticky", sticky)

    def disarm(self) -> None:
        """Begin a fresh script run, which carries no queued stop of its own."""
        dict.__setattr__(self, "_pending", None)
        dict.__setattr__(self, "_sticky", False)

    def writes(self) -> list[str]:
        """The keys written, in order, so an ordering contract can be asserted."""
        return list(self.__dict__.get("_writes", []))

    def _yield(self) -> None:
        pending = self.__dict__.get("_pending")
        if pending is None:
            return
        if not self.__dict__.get("_sticky"):
            dict.__setattr__(self, "_pending", None)
        raise pending

    def __getitem__(self, key: str) -> Any:
        self._yield()
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        self._yield()
        return super().__contains__(key)

    def __delitem__(self, key: str) -> None:
        self._yield()
        super().__delitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setitem__(self, key: str, value: Any) -> None:
        self._yield()
        self.__dict__.setdefault("_writes", []).append(key)
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


class _FakeProgress:
    """``st.progress``, which the caller drives and then clears."""

    def __init__(self, log: list[str]) -> None:
        self._log = log

    def progress(self, _value: float, text: str = "") -> None:
        self._log.append(str(text))

    def empty(self) -> None:
        self._log.append("<cleared>")


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
        self.progress_texts: list[str] = []
        self.buttons: list[dict[str, Any]] = []
        self.metrics: list[tuple[str, Any]] = []
        self.downloads: list[str] = []
        self.download_payloads: list[Any] = []
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

    def progress(self, _value: float = 0.0, text: str = "") -> _FakeProgress:
        bar = _FakeProgress(self.progress_texts)
        bar.progress(_value, text=text)
        return bar

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

    def download_button(self, label: str, **kw: Any) -> bool:
        # Captures `data`, not just the label: the bytes are what the operator
        # opens in a spreadsheet, so a guard applied at the export boundary is
        # only observable here.
        self.downloads.append(str(label))
        self.download_payloads.append(kw.get("data"))
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


@pytest.fixture(autouse=True)
def _reports_under_tmp(monkeypatch, tmp_path):
    """Keep every test in this file out of the operator's own reports directory.

    A walk writes its recovery file through ``reports_dir()``, so a test that
    exercises the runner without redirecting it drops a fake event into
    ``reports/seeding/`` on every suite run, beside real saved runs. Autouse
    rather than part of ``app``: the protection should not depend on which
    fixture a future test happens to ask for.
    """
    monkeypatch.setattr(tournament_intake, "reports_dir", lambda: tmp_path)
    return tmp_path


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


def test_the_walk_never_creates_a_lock_directory_under_reports(app, tmp_path):
    """The lock is stubbed here; this fails loudly if a future edit unstubs it.

    Asserted against the redirected reports directory rather than the real one,
    because the real one legitimately holds a lock folder for any event the
    operator has actually scraped, and that has nothing to do with this walk.
    """
    scrape = _RecordingScrape()
    app.setattr(tournament_intake, "scrape_event_roster", scrape)
    _install(app, _FakeSt())

    _scrape(limit_groups=2)

    assert not (tmp_path / EVENT_LOCK_DIR).exists()
    assert tournament_intake.reports_dir() == tmp_path, "the redirect must be what we just checked"


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


def test_the_other_scrape_surfaces_flag_also_disables_both_buttons(app):
    """That surface shares this session key and still writes a bare ``True``.

    It takes a lock, but records no key here, so the flag is all this tab has to
    go on — and a walk running over there is still a reason not to start one.
    """
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


def test_a_full_walk_of_every_division_marks_the_event_complete(app):
    roster = _roster(_team(0), divisions_found=1, divisions_walked=1)
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(roster))
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


# -------- a walk that returned nothing must not leave the last one showing ---


def test_an_empty_walk_clears_the_previous_events_roster(app):
    """The probe now describes this event; the table must not still hold the last.

    Left alone, the zero-team caption for event B sits above event A's teams, and
    those teams can be saved or queued under B's name.
    """
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(_roster()))
    fake_st = _install(app, _FakeSt())
    fake_st.session_state._seeding_result = ("event A parsed", "event A resolved")
    fake_st.session_state._seeding_overrides = {0: {"team_id_master": "picked-for-event-a"}}
    fake_st.session_state._seeding_sheet_html = "<html>event A</html>"

    _scrape(limit_groups=2)

    assert fake_st.session_state._seeding_result is None
    assert fake_st.session_state._seeding_overrides == {}
    assert fake_st.session_state._seeding_sheet_html is None


# -------- completeness is the roster's answer, not a team count -------------


def test_a_walk_that_lost_a_division_is_not_complete(app):
    """Teams came back, but a division's table was unreadable, so more is owed.

    Marking it complete would retire the full-walk button for the session and
    leave no way to pick up the division that was missed.
    """
    roster = _roster(_team(0), divisions_found=40, divisions_walked=40, divisions_unreadable=1)
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(roster))
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=None)

    assert fake_st.session_state._seeding_event_probe["complete"] is False


def test_a_walk_that_read_everything_is_complete(app):
    roster = _roster(_team(0), divisions_found=1, divisions_walked=1)
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape(roster))
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=None)

    assert fake_st.session_state._seeding_event_probe["complete"] is True


# -------- the probe spends too, so it obeys the same gate -------------------


def test_the_probe_is_closed_once_the_event_has_been_walked_in_full(app):
    """A probe over a finished event replaces its roster with two divisions."""
    runs: list[dict[str, Any]] = []
    fake_st = _install(
        app,
        _FakeSt(buttons={"_seeding_event_probe_run": True}, text={"seeding_event_url": EVENT_URL}),
    )
    fake_st.session_state._seeding_event_probe = _probe(limit_groups=None, complete=True)
    app.setattr(tournament_intake, "_run_event_roster_scrape", lambda url, c, **kw: runs.append(kw))

    _render_controls()

    assert fake_st.button_by_key("_seeding_event_probe_run")["disabled"] is True
    assert runs == [], "a probe would overwrite the full roster this event already has"
    assert fake_st.errors


def test_a_partial_walk_cannot_overwrite_a_complete_recovery_file(app, tmp_path):
    """The guard the command-line scraper already applies to its roster file."""
    written: list[Any] = []
    app.setattr(tournament_intake, "reports_dir", lambda: tmp_path)
    app.setattr(tournament_intake, "write_json", lambda path, payload: written.append(payload))
    app.setattr(tournament_intake, "read_json", lambda _path: {"is_complete": True, "teams": [1, 2, 3]})
    _install(app, _FakeSt())

    tournament_intake._write_event_roster_recovery(_roster(_team(0), divisions_walked=2, divisions_found=40))

    assert written == [], "two cheap divisions replaced a walk someone paid for in full"


def test_a_complete_walk_does_replace_an_earlier_one(app, tmp_path):
    written: list[Any] = []
    app.setattr(tournament_intake, "reports_dir", lambda: tmp_path)
    app.setattr(tournament_intake, "write_json", lambda path, payload: written.append(payload))
    app.setattr(tournament_intake, "read_json", lambda _path: {"is_complete": True})
    _install(app, _FakeSt())

    tournament_intake._write_event_roster_recovery(_roster(_team(0), divisions_found=1, divisions_walked=1))

    assert len(written) == 1


def test_an_unreadable_recovery_file_does_not_block_the_walk_in_hand(app, tmp_path):
    written: list[Any] = []
    app.setattr(tournament_intake, "reports_dir", lambda: tmp_path)
    app.setattr(tournament_intake, "write_json", lambda path, payload: written.append(payload))

    def _corrupt(_path):
        raise ValueError("not json")

    app.setattr(tournament_intake, "read_json", _corrupt)
    _install(app, _FakeSt())

    tournament_intake._write_event_roster_recovery(_roster(_team(0), divisions_walked=2, divisions_found=40))

    assert len(written) == 1, "an unreadable file reads as absent; the walk in hand is what matters"


# -------- the suite keeps out of the operator's own reports directory ------


def test_a_walk_writes_its_recovery_file_under_the_tests_own_directory(app, tmp_path):
    """Fails if the reports redirect is removed, which is the regression to catch.

    Without it the runner writes a fake event into `reports/seeding/`, beside
    the operator's real saved runs, every time the suite runs.
    """
    app.setattr(tournament_intake, "scrape_event_roster", _RecordingScrape())
    _install(app, _FakeSt())

    _scrape(limit_groups=None)

    written = list(tmp_path.rglob("last_walk.json"))
    assert written, "the recovery write escaped the test's own directory"
    assert all(str(path).startswith(str(tmp_path)) for path in written)


def test_the_runner_resolves_reports_through_the_redirected_helper(app, tmp_path):
    """Pins the seam the redirect uses, so a direct path build is caught too."""
    assert tournament_intake.reports_dir() == tmp_path


# -------- the walk only pays for ages that can be ranked -------------------


def test_the_walk_asks_only_for_the_ages_pitchrank_boards(app):
    """Otherwise the app pays for team pages it can never rank or seed."""
    scrape = _RecordingScrape()
    app.setattr(tournament_intake, "scrape_event_roster", scrape)
    _install(app, _FakeSt())

    _scrape(limit_groups=None)

    assert scrape.calls[0]["wanted_cohorts"] == tournament_intake._RANKED_COHORTS


def test_the_boarded_ages_come_from_config_not_a_list_here():
    """Derived, so the set follows the August rollover instead of going stale."""
    from config.settings import AGE_GROUPS

    assert tournament_intake._RANKED_COHORTS == frozenset(AGE_GROUPS)
    assert "u9" not in tournament_intake._RANKED_COHORTS
    assert {"u10", "u19"} <= tournament_intake._RANKED_COHORTS


# -------- a walk the operator's next click killed --------------------------
#
# Streamlit's default `fastReruns` starts the new script run and stops the old
# one, so a click landing during the walk kills it at the first session-state
# write — every one of which comes after the pages were paid for. The lock the
# dying run held is released, the roster reaches only the recovery file, and the
# flag its `finally` would have cleared is never cleared.


_WALK_LOCK_KEY = tournament_intake.event_key("gotsport", "52975", None)


def _strand_a_walk(fake_st: _FakeSt) -> None:
    """Leave the session as a walk killed mid-run leaves it, and clear the render log.

    Both entries, because the flag alone is what the Backtest surface writes and
    the key is what says which lock to test.
    """
    fake_st.session_state._scrape_in_progress = True
    fake_st.session_state._seeding_scrape_lock_key = _WALK_LOCK_KEY
    fake_st.buttons.clear()


@contextlib.contextmanager
def _contended_lock(_key: str):
    raise tournament_intake._ScrapeLockContended("busy")
    yield  # pragma: no cover


def test_a_flag_left_by_a_killed_walk_does_not_disable_the_tab(app):
    """A flag its walk never cleared must not outlive the walk."""
    fake_st, _runs = _render(app, url=EVENT_URL, probe=_probe())
    _strand_a_walk(fake_st)
    _render_controls()

    assert fake_st.button_by_key("_seeding_event_probe_run")["disabled"] is False, (
        "a stuck flag would disable the tab for the rest of the session"
    )
    assert fake_st.session_state._scrape_in_progress is False
    assert fake_st.session_state._seeding_scrape_lock_key is None


def test_a_walk_still_holding_its_lock_keeps_the_buttons_disabled(app):
    app.setattr(tournament_intake, "_acquire_scrape_lock", _contended_lock)
    fake_st, _runs = _render(app, url=EVENT_URL, probe=_probe())
    _strand_a_walk(fake_st)
    _render_controls()

    assert fake_st.button_by_key("_seeding_event_probe_run")["disabled"] is True
    assert fake_st.session_state._seeding_scrape_lock_key == _WALK_LOCK_KEY


def test_the_roster_a_killed_walk_paid_for_can_be_reloaded_without_paying_again(app):
    tournament_intake._write_event_roster_recovery(_roster(_team(0), _team(1)), limit_groups=None)
    fake_st, runs = _render(app, url=EVENT_URL, probe=None, buttons={"_seeding_event_reload_walk": True})

    parsed, _resolved = fake_st.session_state._seeding_result
    assert [row.team_name_raw for row in parsed.rows] == ["Team 0", "Team 1"]
    assert runs == [], "reloading a walk already on disk must buy nothing"


def test_a_reloaded_walk_reports_the_counts_the_paid_walk_had(app):
    """Its own counters, not ones re-derived from a shortened payload.

    ``is_complete`` is a property over five counters, so a payload that keeps
    only two of them rebuilds a partial walk as a whole one — which locks both
    buttons and tells the operator an event is finished with.
    """
    tournament_intake._write_event_roster_recovery(
        _roster(_team(0), divisions_found=40, divisions_walked=40, divisions_unreadable=3),
        limit_groups=None,
    )
    fake_st, _runs = _render(app, url=EVENT_URL, probe=None, buttons={"_seeding_event_reload_walk": True})

    probe = fake_st.session_state._seeding_event_probe
    assert probe["divisions_found"] == 40
    assert probe["divisions_walked"] == 40
    assert probe["complete"] is False, "three divisions were unreadable"


def test_no_reload_is_offered_when_no_walk_was_ever_paid_for(app):
    fake_st, _runs = _render(app, url=EVENT_URL, probe=None)

    with pytest.raises(AssertionError):
        fake_st.button_by_key("_seeding_event_reload_walk")



def test_a_reloaded_walk_that_never_settled_is_not_called_complete(app):
    """A landing page that disagreed with itself may have hidden whole divisions."""
    tournament_intake._write_event_roster_recovery(
        _roster(_team(0), divisions_found=40, divisions_walked=40, divisions_stable=False),
        limit_groups=None,
    )
    fake_st, _runs = _render(app, url=EVENT_URL, probe=None, buttons={"_seeding_event_reload_walk": True})

    assert fake_st.session_state._seeding_event_probe["complete"] is False


def test_a_reloaded_probe_still_knows_it_was_a_probe(app):
    """Otherwise a two-division sample reloads as a whole event and prices nothing."""
    tournament_intake._write_event_roster_recovery(
        _roster(_team(0), divisions_found=40, divisions_walked=2), limit_groups=2
    )
    fake_st, _runs = _render(app, url=EVENT_URL, probe=None, buttons={"_seeding_event_reload_walk": True})

    assert fake_st.session_state._seeding_event_probe["limit_groups"] == 2


_REAL_ACQUIRE_SCRAPE_LOCK = tournament_intake._acquire_scrape_lock


def _write_payload(tmp_path: Path, payload: Any) -> None:
    path = tmp_path / "seeding" / "gotsport_52975" / "last_walk.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _legacy_payload(**overrides: Any) -> dict[str, Any]:
    """The shape the writer emitted before the extra counters existed."""
    return {
        "event_id": "52975",
        "is_complete": False,
        "divisions_found": 40,
        "divisions_walked": 2,
        "warnings": [],
        "teams": [asdict(_team(0))],
        **overrides,
    }


def test_the_walk_stores_the_key_of_the_lock_it_is_holding(app):
    """What the runner writes while the walk is in flight, which nothing else sees.

    Every other observation of these entries is made after the walk cleared them
    or is hand-set by the test, so a runner that stored a bare flag would leave
    the suite green while `_scrape_still_running` had no key to probe.
    """
    held: dict[str, Any] = {}

    def _capture(_event_id: str, **_kw: Any) -> EventRoster:
        held["flag"] = fake_st.session_state.get("_scrape_in_progress")
        held["key"] = fake_st.session_state.get("_seeding_scrape_lock_key")
        return _roster(_team(0))

    app.setattr(tournament_intake, "scrape_event_roster", _capture)
    fake_st = _install(app, _FakeSt())

    _scrape(limit_groups=None)

    assert held["flag"] is True
    assert held["key"] == tournament_intake.event_key("gotsport", "52975", None)


def test_a_held_lock_reads_as_running_and_a_released_one_does_not(app, tmp_path):
    """Exercises the real lock, not a double that raises on cue.

    A double that ignores its key cannot establish that the probe tests the right
    lock, that two independently opened handles conflict inside one process, or
    that the walk's own handle survives being probed.
    """
    app.setattr(tournament_intake, "_acquire_scrape_lock", _REAL_ACQUIRE_SCRAPE_LOCK)
    fake_st = _install(app, _FakeSt())
    _strand_a_walk(fake_st)

    with _REAL_ACQUIRE_SCRAPE_LOCK(_WALK_LOCK_KEY):
        assert tournament_intake._scrape_still_running() is True
        assert fake_st.session_state._scrape_in_progress is True, (
            "a live walk's flag is not this render's to clear"
        )

    assert tournament_intake._scrape_still_running() is False
    assert fake_st.session_state._scrape_in_progress is False


def test_a_walk_that_could_not_read_some_team_pages_reloads_as_incomplete(app):
    """The fifth ``is_complete`` conjunct, violated on its own."""
    tournament_intake._write_event_roster_recovery(
        _roster(_team(0), divisions_found=40, divisions_walked=40, teams_unreadable=2),
        limit_groups=None,
    )
    fake_st, _runs = _render(
        app, url=EVENT_URL, probe=None, buttons={"_seeding_event_reload_walk": True}
    )

    assert fake_st.session_state._seeding_event_probe["complete"] is False


def test_a_walk_written_before_the_counters_existed_is_refused(app, tmp_path):
    """Its own verdict disagrees with the one its counters rebuild.

    Defaulting the missing counters to their clean values turns a walk that lost
    a division into a whole one, which disables both buy buttons for the event
    and then writes that verdict back to disk permanently.
    """
    _write_payload(tmp_path, _legacy_payload(divisions_walked=40))

    assert tournament_intake._recovered_walk("52975") is None


def test_the_recovered_walk_is_filed_under_the_event_that_was_asked_for(app, tmp_path):
    """A payload naming another event must not name the directory written back to.

    ``_park_event_roster`` writes through ``roster.event_id``, and that is the one
    reports path built without the segment validation ``event_key`` applies.
    """
    _write_payload(tmp_path, _legacy_payload(event_id="../../../../tmp/escaped"))

    roster, _limit = tournament_intake._recovered_walk("52975")

    assert roster.event_id == "52975"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param([], id="not-a-mapping"),
        pytest.param({"teams": "Team 0"}, id="teams-not-a-list"),
        pytest.param({"teams": ["Team 0"]}, id="team-not-a-mapping"),
        pytest.param({"teams": [{"team_name": "Team 0"}]}, id="team-missing-fields"),
        pytest.param({"teams": [{"colour": "red"}]}, id="team-has-an-extra-field"),
        pytest.param({"teams": [], "divisions_found": "forty"}, id="counter-not-a-number"),
    ],
)
def test_a_payload_this_cannot_rebuild_faithfully_is_refused(app, tmp_path, payload):
    _write_payload(tmp_path, payload)

    assert tournament_intake._recovered_walk("52975") is None


def test_a_stable_flag_written_as_a_string_does_not_read_as_stable(app, tmp_path):
    """``"false"`` is truthy, and ``is not False`` is what let it through."""
    _write_payload(
        tmp_path,
        _legacy_payload(
            divisions_walked=40,
            divisions_unreadable=0,
            teams_unreadable=0,
            divisions_stable="false",
        ),
    )

    roster, _limit = tournament_intake._recovered_walk("52975")

    assert roster.divisions_stable is False
    assert roster.is_complete is False


def test_a_cohort_the_walk_could_never_have_produced_is_dropped(app, tmp_path):
    """The reload is the only path that can hand these fields anything else.

    ``_render_seeding_override`` prints the cohort without escaping it, on the
    strength of it having come from ``resolve_cohort``.
    """
    team = {
        **asdict(_team(0)),
        "age_group": "u14 [click](https://evil.example)",
        "gender": "Other",
    }
    _write_payload(tmp_path, _legacy_payload(teams=[team]))

    roster, _limit = tournament_intake._recovered_walk("52975")

    assert roster.teams[0].age_group == ""
    assert roster.teams[0].gender == ""


def test_the_offer_stops_once_the_tab_holds_the_walk(app):
    """The arm that turns the offer off, which no strict-inequality test reaches."""
    tournament_intake._write_event_roster_recovery(_roster(_team(0), _team(1)), limit_groups=None)
    fake_st, _runs = _render(
        app, url=EVENT_URL, probe=None, buttons={"_seeding_event_reload_walk": True}
    )
    fake_st.buttons.clear()

    _render_controls()

    with pytest.raises(AssertionError):
        fake_st.button_by_key("_seeding_event_reload_walk")


def test_the_reload_is_offered_while_a_probe_describes_the_walk_that_was_lost(app):
    """``_park_event_roster`` writes the probe before the roster, so they disagree.

    A stop landing in that gap leaves the counters describing the full walk with
    no roster parked; gating on the counters would withhold the offer exactly
    where it is needed.
    """
    tournament_intake._write_event_roster_recovery(
        _roster(*[_team(index) for index in range(12)]), limit_groups=None
    )
    fake_st, runs = _render(
        app, url=EVENT_URL, probe=_probe(teams=12), buttons={"_seeding_event_reload_walk": True}
    )

    parsed, _resolved = fake_st.session_state._seeding_result
    assert len(parsed.rows) == 12
    assert runs == []


def test_the_reload_cannot_be_clicked_while_a_walk_is_running(app):
    """Clicking it mid-walk kills the walk and parks the roster it replaced."""
    tournament_intake._write_event_roster_recovery(_roster(_team(0), _team(1)), limit_groups=None)
    app.setattr(tournament_intake, "_acquire_scrape_lock", _contended_lock)
    fake_st, _runs = _render(
        app, url=EVENT_URL, probe=None, buttons={"_seeding_event_reload_walk": True}
    )
    _strand_a_walk(fake_st)
    fake_st.session_state._seeding_result = None

    _render_controls()

    assert fake_st.button_by_key("_seeding_event_reload_walk")["disabled"] is True
    assert fake_st.session_state.get("_seeding_result") is None, (
        "a walk was in flight; nothing may be parked over it"
    )


def test_a_stop_the_walk_cannot_catch_leaves_its_own_flag_set(app, tmp_path):
    """The premise the whole recovery rests on, exercised rather than asserted.

    A STOP is not a RERUN: ``ScriptRequests`` hands a RERUN back once and resets
    to CONTINUE, while a STOP remains stopped and raises at every later yield
    point. So the ``finally`` that clears ``_scrape_in_progress`` raises too, and
    the flag the next render reads was never cleared by anyone.
    """
    app.setattr(tournament_intake, "write_json", lambda path, payload: None)
    fake_st = _install(app, _FakeSt())

    def _walk_then_the_operator_clicks(_event_id: str, **_kw: Any) -> EventRoster:
        fake_st.session_state.arm(_Rerun(), sticky=True)
        return _roster(_team(0))

    app.setattr(tournament_intake, "scrape_event_roster", _walk_then_the_operator_clicks)

    with contextlib.suppress(_Rerun):
        tournament_intake._run_event_roster_scrape(EVENT_URL, None, limit_groups=None)
    fake_st.session_state.disarm()

    assert fake_st.session_state.get("_scrape_in_progress") is True, (
        "the finally raised on its own write, so nothing cleared the flag"
    )
    assert fake_st.session_state.get("_seeding_scrape_lock_key") == _WALK_LOCK_KEY, (
        "and the key it named is what the next render has to probe"
    )


# -------- the reload gate must match the parked roster by event ------------


def _park_pasted_rows(fake_st: _FakeSt, count: int) -> None:
    """A pasted list, which belongs to no event at all."""
    rows = tuple(
        RosterRow(
            source_index=index,
            club_raw="Pasted FC",
            team_name_raw=f"Pasted {index}",
            state="TX",
            section_age_group="u13",
            section_gender="Male",
            team_name_stripped=f"Pasted {index}",
            has_star_marker=False,
            has_c_marker=False,
        )
        for index in range(count)
    )
    resolved = tuple(ResolvedTeam(source_index=index, status="unresolved") for index in range(count))
    fake_st.session_state._seeding_result = (ParsedRoster(rows=rows, warnings=()), resolved)


def test_a_bigger_pasted_roster_does_not_suppress_a_paid_walk(app):
    """The tab holding more rows is not the same thing as holding this walk.

    A pasted list belongs to no event, so its row count says nothing about
    whether the walk on disk has been seen. Counting rows alone leaves a paid
    roster unreachable behind an unrelated table.
    """
    tournament_intake._write_event_roster_recovery(
        _roster(*[_team(index) for index in range(12)]), limit_groups=None
    )
    fake_st = _install(app, _FakeSt(text={"seeding_event_url": EVENT_URL}, buttons={"_seeding_event_reload_walk": True}))
    _park_pasted_rows(fake_st, 40)

    _render_controls()

    parsed, _resolved = fake_st.session_state._seeding_result
    assert [row.team_name_raw for row in parsed.rows] == [f"Team {index}" for index in range(12)], (
        "the paid walk stayed unreachable behind a larger unrelated roster"
    )


def test_another_events_roster_does_not_suppress_this_ones(app, tmp_path):
    """Two events, one tab. The larger one must not answer for the smaller."""
    tournament_intake._write_event_roster_recovery(
        _roster(*[_team(index) for index in range(3)]), limit_groups=None
    )
    fake_st = _install(app, _FakeSt(text={"seeding_event_url": EVENT_URL}, buttons={"_seeding_event_reload_walk": True}))
    other = _roster(*[_team(index) for index in range(9)], event_id="49371")
    parsed_other, resolved_other = to_seeding_rows(other, {})
    tournament_intake._park_seeding_result((parsed_other, resolved_other), event_id="49371")

    _render_controls()

    parsed, _resolved = fake_st.session_state._seeding_result
    assert len(parsed.rows) == 3, "event 52975's own walk was suppressed by event 49371's"


def test_the_offer_still_stops_once_this_events_walk_is_parked(app):
    """The arm the gate exists for must survive the event scoping."""
    roster = _roster(_team(0), _team(1))
    tournament_intake._write_event_roster_recovery(roster, limit_groups=None)
    fake_st = _install(app, _FakeSt(text={"seeding_event_url": EVENT_URL}))
    parsed, resolved = to_seeding_rows(roster, {})
    tournament_intake._park_seeding_result((parsed, resolved), event_id="52975")

    _render_controls()

    with pytest.raises(AssertionError):
        fake_st.button_by_key("_seeding_event_reload_walk")


def test_every_parked_roster_write_goes_through_the_helper():
    """Derived, so a new writer that forgets the event id is caught here.

    A parallel session key kept in sync by hand is the shape that drifts: the
    gate then reads an event id belonging to a roster that has been replaced.
    """
    source = pathlib.Path(tournament_intake.__file__).read_text(encoding="utf-8")
    assignments = [
        line.strip()
        for line in source.splitlines()
        if "_seeding_result" in line and "=" in line.split("_seeding_result")[1][:3]
    ]
    stray = [
        line
        for line in assignments
        if "st.session_state._seeding_result" in line
        and "setdefault" not in line
        and line != "st.session_state._seeding_result = pair"  # the helper's own write
    ]

    assert stray == [], (
        "write the parked roster through _park_seeding_result so the event id "
        f"cannot drift from it: {stray}"
    )


def test_a_reloaded_saved_run_does_not_claim_to_be_this_events_walk(app):
    """A named run is a saved artifact, not this tab's walk of any event.

    Driven through `_load_seeding_run` rather than parked directly, so the event
    id that path actually writes is the thing under test.
    """
    tournament_intake._write_event_roster_recovery(_roster(_team(0), _team(1)), limit_groups=None)
    fake_st = _install(app, _FakeSt(text={"seeding_event_url": EVENT_URL}))
    parsed_saved, resolved_saved = to_seeding_rows(_roster(*[_team(i) for i in range(9)]), {})
    app.setattr(
        tournament_intake,
        "load_seeding_run_file",
        lambda _slug: SeedingRun(
            name="stx-cup-2026",
            rows=parsed_saved.rows,
            resolved=resolved_saved,
            overrides={},
            warnings=parsed_saved.warnings,
        ),
    )

    tournament_intake._load_seeding_run("stx-cup-2026")
    assert fake_st.session_state.get("_seeding_result_event_id") is None
    _render_controls()

    assert fake_st.button_by_key("_seeding_event_reload_walk")["disabled"] is False, (
        "a nine-row saved run answered for a two-team walk of this event"
    )


def test_the_paste_path_parks_a_roster_belonging_to_no_event(app):
    """Otherwise a pasted list suppresses the reload of the event in the box."""
    fake_st = _install(app, _FakeSt())
    app.setattr(tournament_intake, "resolve_roster", lambda rows, **_kw: tuple(
        ResolvedTeam(source_index=row.source_index, status="unresolved") for row in rows
    ))

    roster_text = "\n".join(
        [
            "Male U14",
            "Club\tTeam\tState",
            "Barcelona Soccer Club\tBarcelona SC 13B Aztecas\tTX",
        ]
    )
    tournament_intake._run_seeding_resolve(roster_text, None)

    parked, _resolved = fake_st.session_state._seeding_result
    assert parked.rows, "the paste path parked nothing, so this proves nothing"
    assert fake_st.session_state.get("_seeding_result_event_id") is None


def test_the_parked_roster_is_written_before_the_event_it_names(app):
    """A stop between the two writes must leave a stale id, never a stale roster.

    The other order claims a fresh roster for the previous event and withholds a
    reload; this order reads as "nothing parked for this event" and offers one
    that costs nothing to accept.
    """
    fake_st = _install(app, _FakeSt())
    parsed, resolved = to_seeding_rows(_roster(_team(0)), {})

    tournament_intake._park_seeding_result((parsed, resolved), event_id="52975")

    written = [key for key in fake_st.session_state.writes() if key.startswith("_seeding_result")]
    assert written == ["_seeding_result", "_seeding_result_event_id"]
