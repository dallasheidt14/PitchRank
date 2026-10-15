"""An in-memory Supabase, the guards that keep a skill self-check off the database, the network and child
processes, and the command line the club and reconcile self-checks share.

The club and reconcile self-checks run each tool's own entry point against this stand-in, so a skill's
claim about what a tool writes is checked against what the tool sends, not against a reading of its
source. A stand-in more forgiving than PostgREST would pass a check for the wrong reason, so this one
refuses what PostgREST refuses: a table nobody seeded, a column its table does not declare whether or not
it holds rows, a function nobody seeded or a call that leaves out or adds an argument, a filter before
select or update, an update after a select and the reverse, ordering or paging a write, an in_ list past
the URI limit, a body JSON cannot encode, and any builder method it does not model. It evaluates every
filter at execute(), with NULL semantics and ILIKE's wildcards read after PostgREST turns each * into %,
returns copies holding only the selected columns, and reverses every second ranged read with no order().
Reads and writes are recorded when they execute, never when they are built.

The guards refuse where the I/O starts, not by the name of the code that reaches it: every process start,
name lookup and connection off this machine at the audit event the interpreter raises for it, whichever
library or binding gets there, and earlier, with plainer messages, at subprocess.Popen and the transports
httpx and requests send through.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import csv
import io
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Callable
from unittest import mock

import httpx
from requests.adapters import HTTPAdapter

# Every name the tools' own client builders read, fallbacks included.
CREDENTIALS = (
    "SUPABASE_URL",
    "NEXT_PUBLIC_SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_SERVICE_KEY",
)
# Past this many values an in_ filter overruns the request URI.
IN_LIMIT = 100
# Taken at import, before any guard or test replaces it.
_POPEN = subprocess.Popen


def like_regex(pattern: str) -> str:
    """PostgreSQL ILIKE with its default ``\\`` escape, after PostgREST has turned every ``*`` into ``%``,
    escaped or not."""
    out, escaped = [], False
    for char in pattern.replace("*", "%"):
        if escaped:
            out.append(re.escape(char))
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "%":
            out.append(".*")
        elif char == "_":
            out.append(".")
        else:
            out.append(re.escape(char))
    return "".join(out)


class Database:
    """Seeded tables and functions, and every request that executed.

    ``columns`` names each seeded table's columns and ``functions`` each seeded function's arguments, as
    production defines them; a request naming anything else is refused. ``defaults`` fills a column an
    insert leaves out, as the table's own defaults do. ``rpcs`` maps a function's name to
    ``f(database, params)``, whose return is the call's data. Each hook in ``before_write`` is called with
    a write's record before the write lands. ``children`` holds the command of each child process a tool
    tried to start, which the guards refuse.
    """

    def __init__(
        self,
        tables: dict,
        columns: dict,
        functions: dict | None = None,
        defaults: dict | None = None,
        rpcs: dict | None = None,
    ):
        self.columns = {name: tuple(names) for name, names in columns.items()}
        self.functions = {name: tuple(params) for name, params in (functions or {}).items()}
        undeclared = [name for name in tables if name not in self.columns]
        undeclared += [name for name in rpcs or {} if name not in self.functions]
        if undeclared:
            raise AssertionError(f"seeded without declaring their columns or arguments: {undeclared}")
        self.tables = {
            name: [{**dict.fromkeys(self.columns[name]), **self.known(name, row)} for row in rows]
            for name, rows in tables.items()
        }
        self.defaults = {name: self.known(name, values) for name, values in (defaults or {}).items()}
        self.rpcs = rpcs or {}
        self.reads: list[dict] = []
        self.writes: list[dict] = []
        self.children: list = []
        self.before_write: list[Callable[[dict], None]] = []
        self._unordered_pages = 0

    def known(self, table: str, names):
        """``names``, refused unless ``table`` declares each of them."""
        unknown = [name for name in names if name not in self.columns[table]]
        if unknown:
            raise AssertionError(f"{table} has no column {unknown[0]!r}")
        return names

    def table(self, name: str) -> _Request:
        if name not in self.tables:
            raise AssertionError(f"no table {name!r} was seeded")
        return _Request(self, name)

    def rpc(self, name: str, params: dict) -> _Call:
        if name not in self.rpcs:
            raise AssertionError(f"no function {name!r} was seeded")
        if sorted(params) != sorted(self.functions[name]):
            raise AssertionError(f"{name} takes {sorted(self.functions[name])}; it was called with {sorted(params)}")
        return _Call(self, name, params)

    def copy(self) -> Database:
        """The same tables and functions, with nothing recorded yet."""
        return Database(copy.deepcopy(self.tables), self.columns, self.functions, self.defaults, self.rpcs)

    def row(self, table: str, **match) -> dict:
        """The one row of ``table`` holding every value in ``match``, to read or change in place."""
        found = [row for row in self.tables[table] if all(row.get(k) == v for k, v in match.items())]
        if len(found) != 1:
            raise AssertionError(f"{len(found)} rows of {table} hold {match}")
        return found[0]

    def updates(self) -> list[tuple]:
        """Each update that executed, as (table, payload, filters), the filters sorted and an equality
        written (column, value)."""
        return [(w["table"], w["payload"], w["filters"]) for w in self.writes if w["kind"] == "update"]

    def _record_write(self, record: dict) -> None:
        # httpx encodes a body this way, so one it cannot encode never leaves the client.
        json.dumps(record["payload"], allow_nan=False)
        for hook in self.before_write:
            hook(record)
        self.writes.append(record)


def _shown(filters: list) -> list:
    return sorted(((column, value) if op == "eq" else (column, op, value) for op, column, value in filters), key=str)


def _order_key(column: str):
    return lambda row: (row[column] is None, row[column] if row[column] is not None else "")


class _Request:
    """One request against one table, refusing what postgrest's builders refuse."""

    def __init__(self, db: Database, table: str):
        self.db, self.table = db, table
        self.kind, self.columns, self.payload = None, None, None
        self.filters, self.orderings, self.window, self.cap = [], [], None, None

    def _become(self, kind: str) -> _Request:
        if self.kind is not None:
            raise AttributeError(f"a {self.kind} request has no {kind}")
        self.kind = kind
        return self

    def _require(self, kinds: tuple, what: str) -> None:
        if self.kind not in kinds:
            raise AttributeError(f"a {self.kind or 'table'} request has no {what}")

    def _known(self, column: str) -> str:
        return self.db.known(self.table, [column])[0]

    def select(self, columns: str = "*", **options) -> _Request:
        if options:
            raise AssertionError(f"select options the stand-in does not model: {sorted(options)}")
        self._become("select")
        if columns.strip() != "*":
            self.columns = [self._known(column.strip()) for column in columns.split(",")]
        return self

    def update(self, payload: dict) -> _Request:
        self._become("update")
        self.payload = {self._known(column): value for column, value in payload.items()}
        return self

    def insert(self, payload) -> _Request:
        self._become("insert")
        rows = payload if isinstance(payload, list) else [payload]
        self.payload = [{self._known(column): value for column, value in row.items()} for row in rows]
        return self

    def _filter(self, op: str, column: str, value) -> _Request:
        self._require(("select", "update"), "filters")
        self.filters.append((op, self._known(column), value))
        return self

    def eq(self, column, value):
        return self._filter("eq", column, value)

    def neq(self, column, value):
        return self._filter("neq", column, value)

    def gte(self, column, value):
        return self._filter("gte", column, value)

    def lt(self, column, value):
        return self._filter("lt", column, value)

    def ilike(self, column, pattern):
        return self._filter("ilike", column, pattern)

    def in_(self, column, values):
        values = tuple(values)
        if len(values) > IN_LIMIT:
            raise AssertionError(f"an in_ list of {len(values)} overruns the request URI")
        return self._filter("in", column, values)

    def is_(self, column, value):
        if value != "null":
            raise AssertionError(f"is_ value the stand-in does not model: {value!r}")
        return self._filter("is", column, None)

    def or_(self, expression: str):
        self._require(("select", "update"), "filters")
        terms = []
        for term in expression.split(","):
            column, op, value = term.split(".", 2)
            if op == "eq":
                terms.append(("eq", self._known(column), value))
            elif op == "is" and value == "null":
                terms.append(("is", self._known(column), None))
            else:
                raise AssertionError(f"or_ term the stand-in does not model: {term!r}")
        self.filters.append(("or", None, tuple(terms)))
        return self

    def order(self, column: str, *, desc: bool = False) -> _Request:
        self._require(("select",), "order")
        self.orderings.append((self._known(column), desc))
        return self

    def range(self, start: int, end: int) -> _Request:
        self._require(("select",), "range")
        self.window = (start, end)
        return self

    def limit(self, count: int) -> _Request:
        self._require(("select",), "limit")
        self.cap = count
        return self

    @staticmethod
    def _holds(row: dict, op: str, column, value) -> bool:
        if op == "or":
            return any(_Request._holds(row, *term) for term in value)
        cell = row[column]
        if op == "is":
            return cell is None
        if cell is None:
            return False
        if op == "eq":
            return cell == value
        if op == "neq":
            return cell != value
        if op == "in":
            return cell in value
        if op == "gte":
            return cell >= value
        if op == "lt":
            return cell < value
        if op == "ilike":
            return re.fullmatch(like_regex(value), cell, re.IGNORECASE | re.DOTALL) is not None
        raise AssertionError(f"unknown filter {op!r}")

    def _matched(self) -> list[dict]:
        return [row for row in self.db.tables[self.table] if all(self._holds(row, *f) for f in self.filters)]

    def execute(self) -> SimpleNamespace:
        if self.kind == "select":
            rows = self._matched()
            if self.orderings:
                # Sorted by the last ordering first, so each later one only orders rows the earlier ones tie.
                for column, desc in reversed(self.orderings):
                    rows.sort(key=_order_key(column), reverse=desc)
            elif self.window:
                # PostgREST promises no order without order(), so pages read that way may skip or repeat.
                self.db._unordered_pages += 1
                if self.db._unordered_pages % 2 == 0:
                    rows.reverse()
            if self.window:
                rows = rows[self.window[0] : self.window[1] + 1]
            if self.cap is not None:
                rows = rows[: self.cap]
            self.db.reads.append({"table": self.table, "filters": _shown(self.filters)})
            return SimpleNamespace(data=[{c: row[c] for c in self.columns or row} for row in rows])
        if self.kind == "update":
            record = {"kind": "update", "table": self.table, "payload": dict(self.payload)}
            record["filters"] = _shown(self.filters)
            self.db._record_write(record)
            rows = self._matched()
            for row in rows:
                row.update(self.payload)
            record["matched"] = len(rows)
            return SimpleNamespace(data=[dict(row) for row in rows])
        if self.kind == "insert":
            record = {"kind": "insert", "table": self.table, "payload": [dict(row) for row in self.payload]}
            self.db._record_write(record)
            empty = dict.fromkeys(self.db.columns[self.table])
            rows = [{**empty, **self.db.defaults.get(self.table, {}), **row} for row in self.payload]
            self.db.tables[self.table].extend(rows)
            return SimpleNamespace(data=[dict(row) for row in rows])
        raise AttributeError("a table has no execute before select, update or insert")


class _Call:
    def __init__(self, db: Database, name: str, params: dict):
        self.db, self.name, self.params = db, name, params

    def execute(self) -> SimpleNamespace:
        self.db._record_write({"kind": "rpc", "function": self.name, "payload": dict(self.params)})
        return SimpleNamespace(data=self.db.rpcs[self.name](self.db, self.params))


class Refused(RuntimeError):
    """A self-check reached what only a real run may reach."""


def _refuse(what: str):
    def refuse(*args, **kwargs):
        raise Refused(f"a self-check reached {what}")

    return refuse


# The children list of each guard now open, innermost last. While it is empty the audit hook returns at once.
_OPEN_GUARDS: list[list] = []
# Each audit event the interpreter raises before it starts a process, and which of its arguments holds the
# command, None where none does.
_PROCESS_STARTS = {
    "subprocess.Popen": 1,
    "os.system": 0,
    "os.spawn": 2,
    "os.exec": 1,
    "os.posix_spawn": 1,
    "os.fork": None,
    "os.forkpty": None,
    "os.startfile": 0,
    # The program: Python 3.13 hands the hook this event's command line garbled.
    "_winapi.CreateProcess": 0,
}
# Each audit event the interpreter raises for a name lookup.
_NAME_LOOKUPS = {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo"}


def _loopback(address) -> bool:
    try:
        return ipaddress.ip_address(address[0]).is_loopback
    except (TypeError, ValueError, IndexError):
        return False


def _as_text(command):
    """A recorded command as text: on POSIX the interpreter hands os.system and os.exec* their command as
    bytes, where Windows passes str."""
    if isinstance(command, bytes):
        return os.fsdecode(command)
    if isinstance(command, (list, tuple)):
        return type(command)(os.fsdecode(part) if isinstance(part, bytes) else part for part in command)
    return command


def _audit(event: str, args: tuple) -> None:
    """Inside a guard, refuse each process start, its command recorded first, each name lookup, and each
    connection to anything but a loopback address."""
    if not _OPEN_GUARDS:
        return
    if event in _PROCESS_STARTS:
        at = _PROCESS_STARTS[event]
        _OPEN_GUARDS[-1].append(event if at is None else _as_text(args[at]))
        raise Refused(f"a self-check reached a child process at {event}")
    if event in _NAME_LOOKUPS or (event == "socket.connect" and not _loopback(args[1])):
        raise Refused(f"a self-check reached the network at {event}")


sys.addaudithook(_audit)


@contextlib.contextmanager
def guarded(*modules, children: list | None = None):
    """Credentials blanked, and a ``Refused`` for what only a real run may reach. Every process start in
    ``_PROCESS_STARTS``, every name lookup in ``_NAME_LOOKUPS`` and every ``socket.connect`` to anything but a
    loopback address is refused at its audit event, whichever library or binding gets there. The
    ``subprocess.Popen`` name and the transports httpx and requests send through refuse the same earlier,
    with plainer messages, and ``create_client`` is refused on each of ``modules`` that has one. Each
    process start refused is recorded in ``children``, which is yielded: its command, its program for
    ``_winapi.CreateProcess``, or the event's name where the event carries neither."""
    children = [] if children is None else children

    # A subclass rather than a function, so a module imported under the guard can still subclass Popen.
    class NoChild(_POPEN):
        def __init__(self, *args, **kwargs):
            children.append(args[0] if args else kwargs.get("args"))
            raise Refused("a self-check reached a child process")

    network = _refuse("the network through httpx")
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ, dict.fromkeys(CREDENTIALS, "")))
        stack.enter_context(mock.patch.object(subprocess, "Popen", NoChild))
        stack.enter_context(mock.patch.object(httpx.HTTPTransport, "handle_request", network))
        stack.enter_context(mock.patch.object(httpx.AsyncHTTPTransport, "handle_async_request", network))
        stack.enter_context(mock.patch.object(HTTPAdapter, "send", _refuse("the network through requests")))
        for module in modules:
            if hasattr(module, "create_client"):
                stack.enter_context(mock.patch.object(module, "create_client", _refuse("a real database client")))
        _OPEN_GUARDS.append(children)
        stack.callback(_OPEN_GUARDS.pop)
        yield children


def _point_exports(stack: contextlib.ExitStack, modules, folder: Path | None) -> None:
    """Point each default exports folder of ``modules`` at ``folder``, a temporary one unless given, so a
    tool that ignores --exports-dir still writes nothing into the repo."""
    folder = folder or Path(stack.enter_context(tempfile.TemporaryDirectory()))
    for module in modules:
        names = [
            name
            for name, value in vars(module).items()
            if isinstance(value, Path) and value.parts[-2:] == ("data", "exports")
        ]
        for name in names:
            stack.enter_context(mock.patch.object(module, name, folder))


@contextlib.contextmanager
def offline(db: Database, *modules, argv: list[str] | None = None, exports: Path | None = None):
    """Hand each of ``modules`` ``db`` as its client, guarded, with its environment files left unread and
    its default exports folder pointed at ``exports``, or a temporary folder when none is given."""
    with contextlib.ExitStack() as stack:
        stack.enter_context(guarded(*modules, children=db.children))
        _point_exports(stack, modules, exports)
        for module in modules:
            if hasattr(module, "load_env"):
                stack.enter_context(mock.patch.object(module, "load_env", lambda: None))
            if hasattr(module, "get_supabase"):
                stack.enter_context(mock.patch.object(module, "get_supabase", lambda *a, **k: db))
        if argv is not None:
            stack.enter_context(mock.patch.object(sys, "argv", argv))
        yield


def _exit_status(code) -> int:
    """The status Python exits with on ``SystemExit(code)``: 0 for None, an int as given, else 1, the
    code printed to stderr."""
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    print(code, file=sys.stderr)
    return 1


def run_main(db: Database, module, *args: str, exports: Path | None = None) -> tuple[int, str]:
    """Run ``module``'s command line against ``db``, offline: its exit code and everything it printed."""
    out = io.StringIO()
    argv = [Path(module.__file__).name, *args]
    with (
        offline(db, module, argv=argv, exports=exports),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(out),
    ):
        try:
            code = module.main() or 0
        except SystemExit as exc:
            code = _exit_status(exc.code)
    return code, out.getvalue()


def run_with_anon_key(module, *args: str) -> tuple[int, str]:
    """Run ``module``'s command line, guarded, with only an anon key set, every other credential name unset,
    and its own client builder reading it: how many clients it built, each recorded rather than built, and
    everything it printed."""
    built, out = [], io.StringIO()
    anon = {"SUPABASE_URL": "https://offline.invalid", "SUPABASE_KEY": "anon"}
    with contextlib.ExitStack() as stack:
        stack.enter_context(guarded(module))
        _point_exports(stack, [module], None)
        stack.enter_context(mock.patch.dict(os.environ, anon))
        for name in CREDENTIALS:
            if name not in anon:
                del os.environ[name]
        stack.enter_context(mock.patch.object(module, "create_client", lambda *a: built.append(a)))
        stack.enter_context(mock.patch.object(module, "load_env", lambda: None))
        stack.enter_context(mock.patch.object(sys, "argv", [Path(module.__file__).name, *args]))
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(out))
        # A refusal reaches the operator through argparse or as the error itself; a run that got past the
        # key goes on to use the client it built, and fails on that.
        try:
            module.main()
        except (Exception, SystemExit) as exc:
            print(exc)
    return len(built), out.getvalue()


def _top_level(expr: str, operator: str) -> list[str]:
    """``expr`` split on ``operator`` wherever it sits outside every bracket and string."""
    parts, depth, quote, start, i = [], 0, None, 0, 0
    while i < len(expr):
        char = expr[i]
        if quote:
            quote = None if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif depth == 0 and expr.startswith(operator, i):
            parts.append(expr[start:i])
            start = i = i + len(operator)
            continue
        i += 1
    return [part.strip() for part in [*parts, expr[start:]]]


def _unwrap(part: str) -> str:
    while part.startswith("(") and part.endswith(")"):
        part = part[1:-1].strip()
    return part


def _never(condition) -> bool:
    expr = str(condition if condition is not None else "").strip()
    if expr.startswith("${{") and expr.endswith("}}"):
        expr = expr[3:-2].strip()
    return all(
        any(_unwrap(term).lower() == "false" for term in _top_level(branch, "&&")) for branch in _top_level(expr, "||")
    )


def workflow_steps(doc: dict) -> list[tuple[dict, dict]]:
    """Every (job, step) of a loaded workflow."""
    return [(job, step) for job in (doc.get("jobs") or {}).values() for step in job.get("steps") or []]


def step_is_off(job: dict, step: dict) -> bool:
    """True when the job's ``if:`` or the step's can never hold: a literal false, bare, YAML-quoted or inside
    ``${{ }}``, as a top-level ``&&`` term of every top-level ``||`` branch."""
    return _never(job.get("if")) or _never(step.get("if"))


@dataclass
class Result:
    assertions: list[dict] = field(default_factory=list)

    def check(self, name, ok, detail):
        self.assertions.append({"name": name, "ok": bool(ok), "detail": detail})

    @property
    def failures(self):
        return [a for a in self.assertions if not a["ok"]]


def csv_rows(path: Path | None) -> list[dict]:
    if path is None:
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def render(result: Result, unverified: list[tuple[str, str]]) -> None:
    print("\nASSERTIONS -- each FAIL is a claim or an agreement that no longer holds\n")
    for item in result.assertions:
        print(f"  {'PASS' if item['ok'] else 'FAIL'}  {item['name']}")
        if not item["ok"]:
            print(f"        {item['detail']}")
    print("\nNOT VERIFIED -- no code settles these; confirm them by hand before relying on them\n")
    for name, detail in unverified:
        print(f"  [??] {name}")
        print(f"         {detail}")
    print()
    if result.failures:
        print(f"{len(result.failures)} assertion(s) failed. Fix the code or update the skill, whichever moved.")
    else:
        print("Every assertion holds.")


def run_checks(checks: list, description: str, unverified: list[tuple[str, str]]) -> int:
    """A self-check's command line: every check run, one that stops reported as a failed assertion and
    the rest still run, and exit 1 when any assertion fails."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--code-only", action="store_true", help="Accepted for symmetry; nothing reads the database")
    parser.add_argument("--json", action="store_true", help="Emit the raw result")
    args = parser.parse_args()

    result = Result()
    for check in checks:
        try:
            check(result)
        except (Exception, SystemExit) as exc:
            result.check(f"{check.__name__} runs to the end", False, f"{type(exc).__name__}: {exc}")

    if args.json:
        notes = [{"name": name, "detail": detail} for name, detail in unverified]
        print(json.dumps({"assertions": result.assertions, "unverified": notes}, indent=1))
    else:
        render(result, unverified)
    return 1 if result.failures else 0
