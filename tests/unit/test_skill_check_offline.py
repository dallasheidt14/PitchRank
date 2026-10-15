"""The stand-in, guards and runner the club and reconcile self-checks share. Each refusal here is one
PostgREST, or a real run, makes; a stand-in that accepted it would let a self-check pass on a request
production refuses, and a guard that let it through would let a self-check reach production."""

import asyncio
import http.client
import json
import multiprocessing
import os
import re
import socket
import subprocess
import sys
import types
import urllib.request
from pathlib import Path
from subprocess import Popen as PreBoundPopen
from unittest import mock

import httpx
import pytest
import requests
import yaml
from postgrest import SyncPostgrestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import repair_swapped_club_names as repair  # noqa: E402
from scripts import skill_check_offline  # noqa: E402
from scripts.skill_check_offline import (  # noqa: E402
    CREDENTIALS,
    Database,
    Refused,
    guarded,
    offline,
    run_checks,
    run_main,
    run_with_anon_key,
    step_is_off,
    workflow_steps,
)

COLUMNS = {"teams": ("team_id_master", "club_name", "state_code", "is_deprecated")}
MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
# Columns production holds that no migration creates. Each is checked to be still missing from them, so
# one a later migration adds has to leave this list.
OUTSIDE_MIGRATIONS = {("teams", "team_name_original")}
CONSTRAINTS = {"constraint", "primary", "unique", "foreign", "check", "exclude", "like"}
TABLE_NAME = r'(?:"?public"?\.)?"?\w+"?'
# A table statement where a statement starts: a file's start, after a semicolon, or after the BEGIN, THEN or
# ELSE that opens a block's statement. ALTER PUBLICATION ... DROP TABLE is none.
TABLE_STATEMENT = re.compile(
    r"(?is)(?:\A|;|\b(?:begin|then|else)\b)\s*(create|alter|drop)\s+table\s+(if\s+(?:not\s+)?exists\s+)?"
    rf"(?:only\s+)?({TABLE_NAME}(?:\s*,\s*{TABLE_NAME})*)"
)
GH = ["gh", "auth", "status"]
# Each audit event the interpreter raises to start a process: the arguments it raises it with, and the
# command guarded() records from them. Written out here rather than read from the guard, so the net below
# still stops an event the guard stops refusing.
PROCESS_START_EVENTS = {
    "subprocess.Popen": ((None, GH, None, None), GH),
    "os.system": (("gh auth status",), "gh auth status"),
    "os.spawn": ((0, "gh", GH, None), GH),
    "os.exec": (("gh", GH, None), GH),
    "os.posix_spawn": (("gh", GH, None), GH),
    "os.fork": ((), "os.fork"),
    "os.forkpty": ((), "os.forkpty"),
    "os.startfile": (("gh.exe", None), "gh.exe"),
    "_winapi.CreateProcess": (("gh.exe", "gh auth status", None), "gh.exe"),
}
NET_EVENTS = {
    *PROCESS_START_EVENTS,
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "socket.gethostbyaddr",
    "socket.getnameinfo",
}
LOOPBACK = ("127.0.0.1", "::1")
WINDOWS = sys.platform == "win32"
# A command as the subprocess.Popen audit event carries it: Windows has already joined it into one line.
STARTED = subprocess.list2cmdline if WINDOWS else list
PYTHON = [sys.executable, "-c", "pass"]
_netted = False


def _got_past(*args, **kwargs):
    raise AssertionError("got past guarded() to a real child process or socket")


def _audit_net(event, args):
    """The net under guarded()'s own audit hook, installed after it, so called only for an event the guard
    let through."""
    if _netted and (event in NET_EVENTS or (event == "socket.connect" and args[1][0] not in LOOPBACK)):
        raise AssertionError(f"got past guarded() to {event}")


sys.addaudithook(_audit_net)


class _NetPopen(subprocess.Popen):
    """NoChild's base under the net: the real Popen, its constructor a tripwire should NoChild ever call it."""

    def __init__(self, *args, **kwargs):
        _got_past()


class EarlyPopen(subprocess.Popen):
    """A tool's own Popen, subclassed when its module is imported, before any guard."""


def net_under_guards(monkeypatch, *modules):
    """A tripwire under each boundary guarded() refuses, its audit events included, and under each client
    builder of ``modules``, so a guard that lets anything through fails the test before it leaves."""
    monkeypatch.setattr(skill_check_offline, "_POPEN", _NetPopen)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _got_past)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _got_past)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _got_past)
    monkeypatch.setattr("supabase.create_client", _got_past)
    for module in modules:
        monkeypatch.setattr(module, "create_client", _got_past)
    monkeypatch.setattr(sys.modules[__name__], "_netted", True)


def drop_update_filter(monkeypatch, column, value=mock.ANY):
    """Every update a tool sends against the stand-in loses its equality filter ``column`` = ``value``:
    the break a write guard exists to catch."""
    eq = skill_check_offline._Request.eq

    def dropped(self, name, wanted):
        return self if self.kind == "update" and (column, value) == (name, wanted) else eq(self, name, wanted)

    monkeypatch.setattr(skill_check_offline._Request, "eq", dropped)


def _db(*clubs):
    teams = [
        {"team_id_master": f"t{n}", "club_name": club, "state_code": "AZ", "is_deprecated": False}
        for n, club in enumerate(clubs)
    ]
    return Database({"teams": teams}, COLUMNS, defaults={"teams": {"is_deprecated": False}})


def _tool(tmp_path, main, **attributes):
    """A module with a command line, as run_main runs a tool's."""
    tool = types.ModuleType("tool")
    tool.__file__ = str(tmp_path / "tool.py")
    tool.main = main
    for name, value in attributes.items():
        setattr(tool, name, value)
    return tool


@pytest.mark.parametrize(
    "build",
    [
        lambda t: t.select("club_name").update({"club_name": "x"}),
        lambda t: t.update({"club_name": "x"}).select("club_name"),
        lambda t: t.update({"club_name": "x"}).eq("team_id_master", "t0").order("team_id_master"),
        lambda t: t.update({"club_name": "x"}).range(0, 9),
        lambda t: t.update({"club_name": "x"}).limit(1),
        lambda t: t.insert({"club_name": "x"}).eq("team_id_master", "t0"),
        lambda t: t.insert({"club_name": "x"}).or_("nickname.eq.x"),
        lambda t: t.eq("team_id_master", "t0"),
        lambda t: t.or_("club_name.eq.x"),
        lambda t: t.execute(),
        lambda t: t.select("club_name").not_,
    ],
    ids=[
        "update after select",
        "select after update",
        "order an update",
        "page an update",
        "limit an update",
        "filter an insert",
        "or-filter an insert, its kind read before its columns",
        "filter a table",
        "or-filter a table",
        "execute a table",
        "an unmodelled builder",
    ],
)
def test_the_stand_in_refuses_a_builder_postgrest_refuses(build):
    with pytest.raises(AttributeError):
        build(_db("A").table("teams"))


LINK = ("p_game_id", "p_team_id_master")


def _with_link(rows=(), params=("p_game_id",), answer=lambda database, params: True):
    """A stand-in seeded with ``rows`` of teams and the function link_game_team, which takes ``params``."""
    return Database({"teams": list(rows)}, COLUMNS, {"link_game_team": params}, rpcs={"link_game_team": answer})


@pytest.mark.parametrize(
    "build",
    [
        lambda db: db.table("team_alias_map"),
        lambda db: db.table("teams").select("club_name,nickname"),
        lambda db: db.table("teams").update({"nickname": "x"}),
        lambda db: db.table("teams").insert({"nickname": "x"}),
        lambda db: db.table("teams").select("club_name").eq("nickname", "x"),
        lambda db: db.table("teams").select("club_name").or_("nickname.eq.x"),
        lambda db: db.table("teams").select("club_name").order("nickname"),
        lambda db: Database({"teams": []}, COLUMNS).table("teams").select("nickname"),
        lambda db: Database({"teams": []}, COLUMNS).table("teams").update({"nickname": "x"}),
        lambda db: db.table("teams").select("club_name").in_("team_id_master", [str(n) for n in range(101)]),
        lambda db: db.table("teams").select("club_name").is_("club_name", "not.null"),
        lambda db: db.table("teams").select("club_name").or_("club_name.ilike.x"),
        lambda db: db.table("teams").select("club_name", count="exact"),
        lambda db: db.rpc("apply_team_state", {}),
        lambda db: _with_link(params=LINK).rpc("link_game_team", {"p_game_id": "g1"}),
        lambda db: _with_link(params=LINK).rpc(
            "link_game_team", {"p_game_id": "g1", "p_team_id_master": "t", "p_x": 1}
        ),
        lambda db: _with_link(params=LINK).rpc("link_game_team", {"p_game_id": "g1", "p_team_id": "t"}),
        lambda db: Database({"teams": []}, {}),
        lambda db: Database({}, {}, rpcs={"link_game_team": lambda d, p: True}),
        lambda db: Database({"teams": [{"team_id_master": "t0", "nickname": "x"}]}, COLUMNS),
        lambda db: Database({"teams": []}, COLUMNS, defaults={"teams": {"nickname": "x"}}),
    ],
    ids=[
        "unseeded table",
        "unknown selected column",
        "unknown updated column",
        "unknown inserted column",
        "unknown filtered column",
        "unknown or_ column",
        "unknown ordered column",
        "unknown column selected from a table seeded empty",
        "unknown column updated on a table seeded empty",
        "in_ past the URI limit",
        "unmodelled is_",
        "unmodelled or_ term",
        "unmodelled select option",
        "unseeded function",
        "a call leaving out an argument",
        "a call adding an argument",
        "a call misnaming an argument",
        "a table seeded without its columns",
        "a function seeded without its arguments",
        "a seeded row holding an undeclared column",
        "a default for an undeclared column",
    ],
)
def test_the_stand_in_refuses_what_it_does_not_model(build):
    with pytest.raises(AssertionError):
        build(_db("A"))


def test_nothing_is_recorded_until_execute():
    db = _with_link([{"team_id_master": "t0", "club_name": "A", "state_code": "AZ", "is_deprecated": False}])
    seeded = [dict(row) for row in db.tables["teams"]]
    hooked = []
    db.before_write.append(hooked.append)

    db.table("teams").update({"club_name": "B"}).eq("team_id_master", "t0")
    db.table("teams").select("club_name").eq("team_id_master", "t0")
    db.table("teams").insert({"team_id_master": "t9", "club_name": "Z"})
    db.rpc("link_game_team", {"p_game_id": "g1"})

    assert db.writes == [] and db.reads == [] and hooked == [] and db.tables["teams"] == seeded


def test_a_seeded_row_holds_every_declared_column():
    db = Database({"teams": [{"team_id_master": "t0"}]}, COLUMNS)

    assert db.table("teams").select("*").execute().data == [
        {"team_id_master": "t0", "club_name": None, "state_code": None, "is_deprecated": None}
    ]


def test_an_update_lands_only_on_rows_matching_every_filter_and_returns_them():
    db = _db("A", "A", "B")
    done = db.table("teams").update({"club_name": "C"}).eq("club_name", "A").eq("team_id_master", "t1").execute()

    assert done.data == [{"team_id_master": "t1", "club_name": "C", "state_code": "AZ", "is_deprecated": False}]
    assert [row["club_name"] for row in db.tables["teams"]] == ["A", "C", "B"]
    assert db.updates() == [("teams", {"club_name": "C"}, [("club_name", "A"), ("team_id_master", "t1")])]
    assert db.writes[0]["matched"] == 1


def test_a_null_matches_only_is_null():
    db = _db("A", None)
    found = db.table("teams").select("team_id_master")

    assert found.eq("club_name", None).execute().data == []
    assert db.table("teams").select("team_id_master").neq("club_name", "A").execute().data == []
    assert db.table("teams").select("team_id_master").is_("club_name", "null").execute().data == [
        {"team_id_master": "t1"}
    ]


def test_ilike_reads_every_star_as_a_percent_sign_and_honours_escapes():
    db = _db("AxB", "A*B", "A%B", "a_b")

    def holders(pattern):
        return [
            r["club_name"] for r in db.table("teams").select("club_name").ilike("club_name", pattern).execute().data
        ]

    assert holders("a*b") == ["AxB", "A*B", "A%B", "a_b"]
    assert holders("a\\*b") == ["A%B"]
    assert holders("a\\_b") == ["a_b"]


def test_or_reads_equality_and_null_terms():
    db = _db("A", None, "")
    query = db.table("teams").select("team_id_master").or_("club_name.is.null,club_name.eq.")

    assert query.execute().data == [{"team_id_master": "t1"}, {"team_id_master": "t2"}]


def test_a_read_returns_copies_of_only_the_selected_columns():
    db = _db("A")
    row = db.table("teams").select("club_name").execute().data[0]
    row["club_name"] = "changed"

    assert row.keys() == {"club_name"} and db.row("teams", team_id_master="t0")["club_name"] == "A"


def test_an_unordered_page_comes_back_in_no_stable_order():
    db = _db("A", "B")

    def first():
        return db.table("teams").select("club_name").range(0, 0).execute().data

    assert (first(), first()) == ([{"club_name": "A"}], [{"club_name": "B"}])
    ordered = db.table("teams").select("club_name").order("club_name", desc=True).range(0, 0).execute().data
    assert ordered == [{"club_name": "B"}]


def test_order_takes_desc_only_by_name_and_sorts_by_each_ordering_in_turn():
    db = _db("B", "A", "B", None)

    with pytest.raises(TypeError):
        db.table("teams").select("club_name").order("club_name", True)
    rows = db.table("teams").select("team_id_master").order("club_name").order("team_id_master", desc=True)

    assert [row["team_id_master"] for row in rows.execute().data] == ["t1", "t2", "t0", "t3"]


@pytest.mark.parametrize(
    ("write", "error"),
    [
        (lambda db: db.table("teams").update({"club_name": float("nan")}).eq("team_id_master", "t0"), ValueError),
        (lambda db: db.table("teams").insert({"team_id_master": "t9", "club_name": {"A"}}), TypeError),
        (lambda db: db.rpc("link_game_team", {"p_game_id": Path("g1")}), TypeError),
    ],
    ids=["a NaN", "a set", "an object JSON has no form for"],
)
def test_a_body_json_cannot_encode_is_refused_at_execute_and_never_lands(write, error):
    db = _with_link([{"team_id_master": "t0", "club_name": "A"}])
    seeded = [dict(row) for row in db.tables["teams"]]

    with pytest.raises(error):
        write(db).execute()
    assert db.writes == [] and db.tables["teams"] == seeded


def test_an_insert_fills_the_table_defaults_and_each_write_hook_runs_first():
    db = _db("A")
    seen = []
    db.before_write.append(lambda record: seen.append((record["kind"], len(db.tables["teams"]))))

    db.table("teams").insert({"team_id_master": "t9", "club_name": "Z"}).execute()

    assert db.row("teams", team_id_master="t9") == {
        "team_id_master": "t9",
        "club_name": "Z",
        "state_code": None,
        "is_deprecated": False,
    }
    assert seen == [("insert", 1)]


def test_a_function_call_is_recorded_and_answered_by_its_seeded_handler():
    db = _with_link(answer=lambda database, params: [params["p_game_id"]])

    assert db.rpc("link_game_team", {"p_game_id": "g1"}).execute().data == ["g1"]
    assert db.writes == [{"kind": "rpc", "function": "link_game_team", "payload": {"p_game_id": "g1"}}]


def test_a_copy_shares_no_rows_and_no_records():
    db = _db("A")
    db.table("teams").update({"club_name": "B"}).eq("team_id_master", "t0").execute()
    copied = db.copy()
    copied.row("teams", team_id_master="t0")["club_name"] = "C"

    assert copied.writes == [] and db.row("teams", team_id_master="t0")["club_name"] == "B"


def test_drop_update_filter_drops_only_the_named_equality_and_only_from_updates(monkeypatch):
    db = _db("A", "B")
    drop_update_filter(monkeypatch, "club_name", "A")

    db.table("teams").update({"state_code": "NV"}).eq("club_name", "A").execute()

    assert db.updates() == [("teams", {"state_code": "NV"}, [])]
    assert db.table("teams").select("club_name").eq("club_name", "A").execute().data == [{"club_name": "A"}]
    db.table("teams").update({"state_code": "UT"}).eq("club_name", "B").execute()
    assert db.updates()[-1] == ("teams", {"state_code": "UT"}, [("club_name", "B")])


# --- the guards -----------------------------------------------------------------------------


def test_offline_blanks_credentials_and_hands_over_the_stand_in(monkeypatch):
    for name in CREDENTIALS:
        monkeypatch.setenv(name, "set-outside")
    db = _db("A")

    with offline(db, repair, argv=["repair_swapped_club_names.py"]):
        assert [os.environ[name] for name in CREDENTIALS] == [""] * len(CREDENTIALS)
        assert repair.get_supabase(require_service_role=True) is db and sys.argv == ["repair_swapped_club_names.py"]
        with pytest.raises(Refused, match="a real database client"):
            repair.create_client("https://offline.invalid", "key")
    assert os.environ["SUPABASE_URL"] == "set-outside"


def test_guarded_refuses_a_real_postgrest_request_at_httpx_s_transport(monkeypatch):
    net_under_guards(monkeypatch)

    with guarded(), pytest.raises(Refused, match="the network through httpx"):
        client = SyncPostgrestClient("https://offline.invalid/rest/v1", headers={"apikey": "anon"})
        client.from_("teams").select("team_id_master").execute()


def test_guarded_refuses_an_async_httpx_request_at_its_transport(monkeypatch):
    net_under_guards(monkeypatch)

    async def fetch():
        async with httpx.AsyncClient() as client:
            await client.get("https://offline.invalid/rest/v1/teams")

    with guarded(), pytest.raises(Refused, match="the network through httpx"):
        asyncio.run(fetch())


@pytest.mark.parametrize(
    "send",
    [
        lambda: requests.Session().send(requests.Request("GET", "https://offline.invalid/teams").prepare()),
        lambda: requests.get("https://offline.invalid/teams"),
    ],
    ids=["a prepared request sent", "a plain get"],
)
def test_guarded_refuses_a_requests_request_at_its_adapter(monkeypatch, send):
    net_under_guards(monkeypatch)

    with guarded(), pytest.raises(Refused, match="the network through requests"):
        send()


def test_guarded_refuses_a_child_process_and_records_its_command(monkeypatch):
    net_under_guards(monkeypatch)

    with guarded() as children, pytest.raises(Refused, match="a child process$"):
        subprocess.run(PYTHON, capture_output=True)
    assert children == [PYTHON]


def test_a_module_imported_under_guarded_can_still_subclass_popen_and_its_subclass_is_refused(monkeypatch):
    net_under_guards(monkeypatch)

    with guarded() as children:

        class Mine(subprocess.Popen):
            pass

        with pytest.raises(Refused, match="a child process$"):
            Mine(args=["gh", "auth", "status"])
    assert children == [["gh", "auth", "status"]]


def test_offline_records_each_child_process_refused_on_the_stand_in(monkeypatch):
    net_under_guards(monkeypatch)
    db = _db("A")

    with offline(db), pytest.raises(Refused):
        subprocess.check_output(["gh", "run", "view", "1", "--log"])
    assert db.children == [["gh", "run", "view", "1", "--log"]]


def _start_a_process_through_multiprocessing():
    multiprocessing.get_context("spawn" if WINDOWS else "fork").Process(target=print).start()


@pytest.mark.parametrize(
    ("start", "event", "command"),
    [
        (lambda: PreBoundPopen(PYTHON), "subprocess.Popen", STARTED(PYTHON)),
        (lambda: EarlyPopen(["gh", "auth", "status"]), "subprocess.Popen", STARTED(["gh", "auth", "status"])),
        (lambda: os.system("echo offline"), "os.system", "echo offline"),
        (
            lambda: os.spawnv(os.P_WAIT, sys.executable, PYTHON),
            "os.spawn" if WINDOWS else "os.fork",
            PYTHON if WINDOWS else "os.fork",
        ),
        (_start_a_process_through_multiprocessing, "_winapi.CreateProcess" if WINDOWS else "os.fork", mock.ANY),
    ],
    ids=[
        "a Popen bound before the guard",
        "a Popen subclass made before the guard",
        "os.system",
        "os.spawnv",
        "multiprocessing",
    ],
)
def test_guarded_refuses_each_way_of_starting_a_process_at_its_audit_event(monkeypatch, start, event, command):
    net_under_guards(monkeypatch)

    with guarded() as children, pytest.raises(Refused, match=f"a child process at {re.escape(event)}$"):
        start()
    assert children == [command]


@pytest.mark.parametrize("event", PROCESS_START_EVENTS)
def test_guarded_refuses_each_process_start_event_wherever_it_is_raised(monkeypatch, event):
    args, command = PROCESS_START_EVENTS[event]
    net_under_guards(monkeypatch)

    with guarded() as children, pytest.raises(Refused, match=f"a child process at {re.escape(event)}$"):
        sys.audit(event, *args)
    assert children == [command]


def _connect(address):
    with socket.socket() as sock:
        sock.connect(address)


@pytest.mark.parametrize(
    ("reach", "event"),
    [
        (lambda: urllib.request.urlopen("https://offline.invalid/", timeout=1), "socket.getaddrinfo"),
        (lambda: http.client.HTTPSConnection("offline.invalid", timeout=1).request("GET", "/"), "socket.getaddrinfo"),
        (lambda: socket.getaddrinfo("offline.invalid", 443), "socket.getaddrinfo"),
        (lambda: socket.gethostbyname("offline.invalid"), "socket.gethostbyname"),
        (lambda: socket.gethostbyaddr("192.0.2.1"), "socket.gethostbyaddr"),
        (lambda: socket.getnameinfo(("192.0.2.1", 80), 0), "socket.getnameinfo"),
        (lambda: _connect(("192.0.2.1", 443)), "socket.connect"),
    ],
    ids=[
        "urllib",
        "http.client",
        "a name lookup",
        "gethostbyname",
        "gethostbyaddr",
        "getnameinfo",
        "a connection to an address off this machine",
    ],
)
def test_guarded_refuses_each_way_of_reaching_the_network_at_its_audit_event(monkeypatch, reach, event):
    net_under_guards(monkeypatch)

    with guarded(), pytest.raises(Refused, match=f"the network at {re.escape(event)}$"):
        reach()


def test_guarded_still_lets_a_connection_to_this_machine_through(monkeypatch):
    net_under_guards(monkeypatch)

    with socket.create_server(("127.0.0.1", 0)) as server, socket.socket() as client, guarded():
        client.connect(server.getsockname())


def test_a_process_start_is_recorded_on_the_innermost_guard(monkeypatch):
    net_under_guards(monkeypatch)

    with guarded() as outer, guarded() as inner, pytest.raises(Refused):
        os.system("echo offline")
    assert (outer, inner) == ([], ["echo offline"])


@pytest.mark.parametrize(
    "event, args, recorded",
    [
        ("os.system", (b"echo offline",), "echo offline"),
        ("os.exec", (b"/bin/echo", [b"echo", b"offline"], None), ["echo", "offline"]),
    ],
    ids=["os.system-bytes", "os.exec-bytes"],
)
def test_a_command_posix_hands_over_as_bytes_is_recorded_as_text(monkeypatch, event, args, recorded):
    net_under_guards(monkeypatch)

    with guarded() as children, pytest.raises(Refused):
        sys.audit(event, *args)
    assert children == [recorded]


def test_the_audit_hook_refuses_nothing_outside_every_guard(monkeypatch):
    net_under_guards(monkeypatch)
    with pytest.raises(Refused), guarded():
        sys.audit("os.system", "echo offline")

    assert skill_check_offline._audit("os.system", ("echo offline",)) is None
    assert skill_check_offline._audit("socket.getaddrinfo", ("offline.invalid", 443, 0, 0, 0)) is None


def test_guarded_blanks_credentials_and_replaces_the_client_builder_only_of_the_modules_given(monkeypatch):
    from supabase import create_client

    for name in CREDENTIALS:
        monkeypatch.setenv(name, "set-outside")
    with guarded():
        assert repair.create_client is create_client and os.environ["SUPABASE_KEY"] == ""
    with guarded(repair):
        assert repair.create_client is not create_client


def test_offline_points_each_default_exports_folder_at_a_temporary_one(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    folders = []

    def main():
        folders.append(tool.EXPORTS_DIR)
        tool.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (tool.EXPORTS_DIR / "log.csv").write_text("written", encoding="utf-8")

    tool = _tool(tmp_path, main, EXPORTS_DIR=Path("data/exports"))
    run_main(_db("A"), tool)
    run_main(_db("A"), tool, exports=tmp_path / "given")

    assert not (tmp_path / "data").exists() and folders[0] != Path("data/exports")
    assert folders[1] == tmp_path / "given" and (tmp_path / "given" / "log.csv").is_file()
    assert tool.EXPORTS_DIR == Path("data/exports")


# --- the runners ----------------------------------------------------------------------------


def test_run_main_returns_the_exit_code_and_everything_printed(tmp_path):
    code, output = run_main(_db("A"), repair, "--no-such-flag")

    assert code == 2 and "unrecognized arguments: --no-such-flag" in output
    assert run_main(_db("A"), _tool(tmp_path, lambda: None)) == (0, "")


@pytest.mark.parametrize(
    ("code", "status", "printed"),
    [(None, 0, ""), (3, 3, ""), ("refusing", 1, "refusing\n")],
    ids=["no code", "a number", "a message"],
)
def test_run_main_reads_a_system_exit_as_python_does(tmp_path, code, status, printed):
    assert run_main(_db("A"), _tool(tmp_path, lambda: sys.exit(code))) == (status, printed)


def test_run_with_anon_key_sets_only_an_anon_key_and_records_each_client_built(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def main():
        print(sys.argv[1:], sorted(name for name in CREDENTIALS if name in os.environ))
        tool.create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        tool.EXPORTS.mkdir(parents=True, exist_ok=True)
        raise SystemExit("--execute needs SUPABASE_SERVICE_ROLE_KEY")

    tool = _tool(tmp_path, main, create_client=_got_past, load_env=_got_past, EXPORTS=Path("data/exports"))
    built, output = run_with_anon_key(tool, "--execute")

    assert built == 1 and not (tmp_path / "data").exists()
    assert output == "['--execute'] ['SUPABASE_KEY', 'SUPABASE_URL']\n--execute needs SUPABASE_SERVICE_ROLE_KEY\n"


def _run_checks(monkeypatch, capsys, *checks, argv=("--code-only",)):
    monkeypatch.setattr(sys, "argv", ["check.py", *argv])
    code = run_checks(list(checks), "A self-check", [("a claim no code settles", "why")])
    return code, capsys.readouterr().out


def test_run_checks_exits_1_when_an_assertion_fails_and_0_when_all_hold(monkeypatch, capsys):
    assert _run_checks(monkeypatch, capsys, lambda r: r.check("holds", True, ""))[0] == 0
    code, out = _run_checks(monkeypatch, capsys, lambda r: r.check("breaks", False, "why"))
    assert code == 1 and "FAIL  breaks" in out and "NOT VERIFIED" in out and "a claim no code settles" in out


def test_run_checks_reports_a_check_that_stops_and_runs_the_rest(monkeypatch, capsys):
    def stops(r):
        raise SystemExit("no saved run log")

    def holds(r):
        r.check("holds", True, "")

    code, out = _run_checks(monkeypatch, capsys, stops, holds)
    assert code == 1
    assert "FAIL  stops runs to the end" in out and "SystemExit: no saved run log" in out and "PASS  holds" in out


def test_run_checks_emits_the_assertions_and_the_notes_as_json(monkeypatch, capsys):
    code, out = _run_checks(monkeypatch, capsys, lambda r: r.check("holds", True, ""), argv=("--json",))

    assert code == 0 and json.loads(out) == {
        "assertions": [{"name": "holds", "ok": True, "detail": ""}],
        "unverified": [{"name": "a claim no code settles", "detail": "why"}],
    }


# --- workflow gates -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("job", "step", "off"),
    [
        ("", "", False),
        ("", "if: false", True),
        ("", "if: False", True),
        ("", "if: 'false'", True),
        ("", "if: ${{ false }}", True),
        ("", "if: ${{ false && github.event_name == 'schedule' }}", True),
        ("", "if: ${{ github.event_name == 'schedule' && (false) }}", True),
        ("", "if: ${{ github.event_name == 'schedule' && ((false)) }}", True),
        ("", "if: ${{ (github.event_name == 'schedule' || inputs.force) && false }}", True),
        ("", "if: ${{ github.event.inputs.mode == 'a || b' && false }}", True),
        ("", "if: ${{ false || github.event_name == 'schedule' }}", False),
        ("", "if: ${{ 'false' }}", False),
        ("", "if: ${{ !contains(github.event.inputs.skip_steps, ',1,') }}", False),
        ("if: false", "", True),
        ("if: ${{ false }}", "if: ${{ true }}", True),
    ],
    ids=[
        "no gate",
        "false",
        "False",
        "a quoted false",
        "false in an expression",
        "false && another term",
        "another term && (false)",
        "another term && ((false))",
        "a bracketed || && false",
        "a || inside a string && false",
        "false || another branch",
        "the string 'false', which GitHub reads as true",
        "a gate that can hold",
        "the job off",
        "the job off, the step on",
    ],
)
def test_step_is_off_reads_the_job_s_if_and_the_step_s(job, step, off):
    doc = yaml.safe_load(f"jobs:\n  clubs:\n    {job or 'name: clubs'}\n    steps:\n      - {step or 'name: s'}\n")

    assert [step_is_off(j, s) for j, s in workflow_steps(doc)] == [off]


def test_workflow_steps_walks_every_step_of_every_job():
    doc = {"jobs": {"a": {"steps": [{"name": "1"}, {"name": "2"}]}, "b": {"steps": [{"name": "3"}]}, "c": {}}}

    assert [(job is doc["jobs"]["b"], step["name"]) for job, step in workflow_steps(doc)] == [
        (False, "1"),
        (False, "2"),
        (True, "3"),
    ]


# --- what the self-checks declare -----------------------------------------------------------


def _sql(path: Path) -> str:
    """A migration less its comments, so a commented-out statement does not count."""
    text = re.sub(r"/\*.*?\*/", " ", path.read_text(encoding="utf-8"), flags=re.S)
    return re.sub(r"--[^\n]*", "", text)


def _scan(sql: str, start: int):
    """Each character from ``start`` outside a quoted string, with its index and its bracket depth."""
    depth, quoted = 0, False
    for i in range(start, len(sql)):
        char = sql[i]
        if char == "'":
            quoted = not quoted
        elif not quoted:
            depth += {"(": 1, ")": -1}.get(char, 0)
            yield i, char, depth


def _closing(sql: str, opening: int) -> int:
    return next(i for i, char, depth in _scan(sql, opening) if char == ")" and depth == 0)


def _parts(text: str) -> list[str]:
    """``text`` split on its top-level commas."""
    cuts = [i for i, char, depth in _scan(text, 0) if char == "," and depth == 0]
    return [text[a + 1 : b].strip() for a, b in zip([-1, *cuts], [*cuts, len(text)])]


def _name(word: str) -> str:
    return word.strip('"').lower()


def _table(name: str) -> str:
    """A table's name less its quotes and its public schema."""
    return _name(name.strip().split(".")[-1])


def _alter(columns: set, tables: dict, table: str, action: str) -> None:
    words = [_name(word) for word in action.split()]
    if not words or words[0] not in ("add", "drop", "rename"):
        return
    verb, rest = words[0], words[1:]
    if rest[:1] == ["to"]:
        tables[rest[1]] = tables.pop(table)
        return
    if not rest or rest[0] in CONSTRAINTS:
        return
    rest = rest[1:] if rest[0] == "column" else rest
    if rest[:3] == ["if", "not", "exists"]:
        rest = rest[3:]
    elif rest[:2] == ["if", "exists"]:
        rest = rest[2:]
    if verb == "add":
        columns.add(rest[0])
    elif verb == "drop":
        columns.discard(rest[0])
    else:
        columns.discard(rest[0])
        columns.add(rest[2])


def _schema(folder: Path) -> dict[str, set[str]]:
    """Each table's columns after every migration in ``folder``, oldest first: what CREATE TABLE gives it,
    and what each ALTER TABLE adds, drops or renames, and no table a DROP TABLE removed."""
    tables: dict[str, set[str]] = {}
    for path in sorted(folder.glob("*.sql")):
        sql = _sql(path)
        for match in TABLE_STATEMENT.finditer(sql):
            verb, guarded_by = match.group(1).lower(), match.group(2)
            names = [_table(name) for name in match.group(3).split(",")]
            table = names[0]
            if verb == "drop":
                for name in names:
                    tables.pop(name, None)
            elif verb == "create":
                opening = re.compile(r"\s*").match(sql, match.end()).end()
                if sql[opening : opening + 1] != "(" or (guarded_by and table in tables):
                    continue
                body = sql[opening + 1 : _closing(sql, opening)]
                tables[table] = {_name(part.split()[0]) for part in _parts(body) if part}
                tables[table] -= CONSTRAINTS
            elif table in tables:
                end = next((i for i, char, depth in _scan(sql, match.end()) if char == ";" and depth == 0), len(sql))
                for action in _parts(sql[match.end() : end]):
                    _alter(tables[table], tables, table, action)
    return tables


def _parameters(name: str, folder: Path) -> list[str]:
    """The argument names of ``name``'s newest definition across every migration in ``folder``, OUT
    arguments aside. A DROP FUNCTION after it leaves no definition."""
    pattern = re.compile(
        r"(?is)\b(create\s+(?:or\s+replace\s+)?|drop\s+)function\s+(?:if\s+exists\s+)?"
        rf'(?:"?public"?\.)?"?{re.escape(name)}"?\s*(?=[(;,]|\Z)'
    )
    found = None
    for path in sorted(folder.glob("*.sql")):
        sql = _sql(path)
        for match in pattern.finditer(sql):
            if match.group(1).lower().startswith("drop"):
                found = None
            elif sql[match.end() : match.end() + 1] == "(":
                found = sql[match.end() + 1 : _closing(sql, match.end())]
    assert found is not None, f"no migration defines {name}"
    names = []
    for part in _parts(found):
        words = part.split()
        if words and words[0].lower() in ("in", "inout", "variadic"):
            words = words[1:]
        if words and words[0].lower() != "out":
            names.append(_name(words[0]))
    return names


def _declared(monkeypatch, capsys) -> tuple[dict, dict]:
    """The columns and function arguments of every stand-in the two self-checks build, gathered while each
    runs whole."""
    import scripts.check_club_skill_assumptions as club
    import scripts.check_reconcile_skill_assumptions as reconcile

    columns, functions = {}, {}
    init = Database.__init__

    def recording(self, *args, **kwargs):
        init(self, *args, **kwargs)
        for table, names in self.columns.items():
            columns.setdefault(table, set()).update(names)
        for function, names in self.functions.items():
            functions.setdefault(function, set()).add(names)

    monkeypatch.setattr(Database, "__init__", recording)
    net_under_guards(monkeypatch)
    for checker in (club, reconcile):
        monkeypatch.setattr(sys, "argv", [Path(checker.__file__).name, "--json"])
        assert checker.main() == 0
    capsys.readouterr()
    return columns, functions


def test_the_self_checks_declare_only_columns_and_arguments_the_migrations_define(monkeypatch, capsys):
    columns, functions = _declared(monkeypatch, capsys)
    schema = _schema(MIGRATIONS)

    missing = sorted(
        (table, column)
        for table, names in columns.items()
        for column in names
        if column not in schema.get(table, set()) and (table, column) not in OUTSIDE_MIGRATIONS
    )
    assert {"teams", "games", "rankings_full"} <= set(columns) and missing == []
    assert set(functions) == {"apply_team_state", "link_game_team", "unlink_game_team"}
    assert {name: sorted(map(sorted, declared)) for name, declared in functions.items()} == {
        name: [sorted(_parameters(name, MIGRATIONS))] for name in functions
    }


def test_each_column_listed_outside_the_migrations_is_still_missing_from_them():
    schema = _schema(MIGRATIONS)

    assert [(table, column) for table, column in OUTSIDE_MIGRATIONS if column in schema.get(table, set())] == []
    assert {"state_source", "state_confidence", "is_deprecated"} <= schema["teams"]
    assert "is_excluded" in schema["games"]


SYNTHETIC_MIGRATIONS = {
    "20260101000000_create.sql": """
create table public.teams (
  team_id_master uuid primary key,
  club_name text,
  state_code text,
  gone_quoted text,
  gone_guarded text,
  constraint teams_once unique (team_id_master)
);
create table if not exists games (id uuid, home_team text);
create table spare (id uuid);
create table published (id uuid);
create table old_name (id uuid, note text);
create function public.link_game_team(p_game_id uuid, p_team uuid) returns void language sql as $$ select $$;
create function unlink_game_team(p_game_id uuid) returns void language sql as $$ select $$;
create function keep_me(p_old uuid) returns void language sql as $$ select $$;
""",
    "20260102000000_change.sql": """
-- undo: select 1; alter table teams drop column club_name;
/*
rollback:
  alter table teams add column rolled_back text;
  alter table teams drop column team_id_master;
*/
create table if not exists teams (only_column text);
alter table teams add column if not exists age_group text, add column gender text;
alter table "public"."teams" drop column "gone_quoted";
alter table teams drop column if exists gone_guarded;
alter table only public.teams rename column state_code to state;
alter table old_name rename to new_name;
alter publication supabase_realtime drop table published;
drop table if exists spare, "public"."games";
do $$ begin alter table teams add column from_begin text; end $$;
do $$ begin if false then null; else alter table teams add column from_else text; end if; end $$;
do $$ begin if true then alter table teams add column from_then text; end if; end $$;
create or replace function "public"."link_game_team"(p_game_id uuid, p_team_id_master uuid, p_is_home_team boolean)
returns void language sql as $$ select $$;
drop function if exists public.unlink_game_team(uuid);
drop function keep_me(uuid);
create function keep_me(in p_a uuid, out p_b uuid, inout p_c uuid, variadic p_d uuid[])
returns record language sql as $$ select $$;
""",
}


def test_the_migration_resolver_folds_each_statement_into_the_final_schema(tmp_path):
    for name, sql in SYNTHETIC_MIGRATIONS.items():
        (tmp_path / name).write_text(sql, encoding="utf-8")

    assert _schema(tmp_path) == {
        "teams": {
            "team_id_master",
            "club_name",
            "state",
            "age_group",
            "gender",
            "from_begin",
            "from_else",
            "from_then",
        },
        "published": {"id"},
        "new_name": {"id", "note"},
    }
    assert _parameters("link_game_team", tmp_path) == ["p_game_id", "p_team_id_master", "p_is_home_team"]
    assert _parameters("keep_me", tmp_path) == ["p_a", "p_c", "p_d"]
    with pytest.raises(AssertionError, match="no migration defines unlink_game_team"):
        _parameters("unlink_game_team", tmp_path)
