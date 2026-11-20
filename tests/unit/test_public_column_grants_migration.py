"""Pin that the browser roles cannot read a provider's team id, and that the site never asks them to.

The anon key ships in every page and any free account holds an authenticated session, so either one
reading `teams.provider_team_id`, or a game's two sides, source link or game_uid (older uids are built
from the two provider ids), hands the provider id map to anyone who pages the table. Migration
20261121000100 grants those roles the remaining columns by name.

Three things undo that silently, and each is pinned here:
  - a later migration re-granting a hidden column, or SELECT on the whole table, in any of the forms
    this tree writes: a comma-listed GRANT, a grant TO PUBLIC, `ON ALL TABLES IN SCHEMA public`, or a
    DROP and CREATE that hands the rebuilt relation back to the browser roles whole;
  - the site naming a column the grant leaves out, or `*`, which PostgREST then refuses with 42501;
  - one of the server-only tables or owner-run objects reopening to the browser roles.

CI applies none of these migrations, so these read migration text, resolving each object's final
state by replaying every migration in order, never by trusting the newest file. Confirm the live
state after applying them:
  SELECT has_column_privilege('anon', 'public.teams', 'provider_team_id', 'SELECT');
"""

import re
from functools import lru_cache
from pathlib import Path

from tests.unit.test_scrape_requests_rls_migration import _roles, _signature, _sources

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"

BROWSER = ("anon", "authenticated")

HIDDEN = {
    "teams": {"provider_team_id"},
    "games": {"home_provider_id", "away_provider_id", "source_url", "game_uid"},
}

# Every site read that names a column outside the browser grant, with how many it makes. Each runs on
# the service key, behind requireAdmin or requirePremium or in a script that holds it; a new entry needs
# the same.
SERVICE_READS = {
    ("frontend/app/api/create-team/route.ts", "games"): 1,
    ("frontend/app/api/game-provider-ids/route.ts", "games"): 1,
    ("frontend/app/api/link-opponent/route.ts", "games"): 1,
    ("frontend/app/api/scrape-missing-game/route.ts", "teams"): 1,
    ("frontend/app/api/unlink-opponent/route.ts", "games"): 1,
    ("frontend/app/api/watchlist/add/route.ts", "teams"): 1,
    ("frontend/lib/matchPredictionService.ts", "games"): 1,
    ("frontend/lib/prospectiveCapture.ts", "games"): 1,
}


SERVER_ONLY_TABLES = ("team_link_audit", "team_merge_audit", "scheduled_games")
OWNER_RUN_VIEWS = ("games_with_resolved_teams", "recent_merge_activity")

# Receivers whose `.from(...)` is not a Supabase table read.
NON_SUPABASE_FROM = {"Array", "Buffer", "Uint8Array"}

STATEMENT = re.compile(
    r"(?is)\b(grant|revoke|drop\s+(?:materialized\s+)?(?:view|table)"
    r"|create\s+(?:or\s+replace\s+)?(?:materialized\s+)?(?:view|table))\b[^;]*;"
)
RELATION_VERB = re.compile(
    r"(?is)^(drop|create(\s+or\s+replace)?)\s+(materialized\s+)?(view|table)\s+(if\s+(not\s+)?exists\s+)?"
)
PRIVILEGE_STATEMENT = re.compile(r"(?is)^(grant|revoke)\s+(.*?)\s+on\s+(.*?)\s+(to|from)\s+(.*);$")
OBJECT_KIND = re.compile(r"(?is)^(table|sequence|function|procedure|routine|schema|all|foreign|large|database)\b")


def _ref(name: str) -> str:
    return rf'(?:"?public"?\s*\.\s*)?"?{name}"?'


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _targets(objects: str, name: str, kind: str) -> bool:
    """Whether a GRANT/REVOKE object list reaches `name`, named directly, in a comma list, or schema-wide."""
    if re.match(rf"(?is)^all\s+{kind}s\s+in\s+schema\s+\"?public\"?\b", objects):
        return True
    leading = OBJECT_KIND.match(objects)
    if leading and leading.group(1).lower() != kind:
        return False
    listed = re.sub(rf"(?is)^{kind}\s+", "", objects)
    return any(re.fullmatch(_ref(name), part.strip(), re.I) for part in listed.split(","))


def _grantees(clause: str) -> set[str]:
    """The browser roles a GRANT reaches: PUBLIC reaches both."""
    roles = _roles(clause)
    return set(BROWSER) if "public" in roles else roles & set(BROWSER)


@lru_cache(maxsize=None)
def browser_readable_columns(name: str, kind: str = "table") -> dict[str, set[str] | None]:
    """Role -> the columns it may SELECT on `name` after every migration, or None for all of it.

    pg_default_acl gives anon and authenticated the whole of a new relation, so a plain CREATE or a
    DROP starts the role over at None; CREATE OR REPLACE keeps the ACL. A table-wide REVOKE also clears
    column grants, as Postgres does, while a REVOKE FROM PUBLIC leaves a role's own grants standing.
    For a sequence any privilege counts as access, and only a REVOKE ALL takes it away.
    """
    access: dict[str, set[str] | None] = {role: None for role in BROWSER}
    for _, sql in _sources():
        for match in STATEMENT.finditer(sql):
            statement = _flat(match.group(0))
            verb = match.group(1).lower()
            if not verb.startswith(("grant", "revoke")):
                rebuilt = re.sub(RELATION_VERB, "", statement)
                if "or replace" not in verb and re.match(rf"(?is){_ref(name)}(\s|,|\(|;|$)", rebuilt):
                    access = {role: None for role in BROWSER}
                continue
            parts = PRIVILEGE_STATEMENT.match(statement)
            if not parts or not _targets(parts.group(3).strip(), name, kind):
                continue
            privileges = parts.group(2)
            relevant = r"\b(select|all)\b" if kind == "table" else r"\b(select|all|usage|update)\b"
            if not re.search(rf"(?is){relevant}", privileges):
                continue
            columns = re.search(r"(?is)\bselect\s*\(([^)]*)\)", privileges)
            listed = {c.strip().strip('"').lower() for c in columns.group(1).split(",")} if columns else None
            if verb == "grant":
                for role in _grantees(parts.group(5)):
                    held = access[role]
                    access[role] = None if listed is None or held is None else held | listed
            elif kind == "table" or re.search(r"(?is)\ball\b", privileges):
                for role in _roles(parts.group(5)) & set(BROWSER):
                    if listed is None:
                        access[role] = set()
                    elif access[role] is not None:
                        access[role] = access[role] - listed
    return access


def _function_grantees(name: str, signature: str) -> set[str] | None:
    """Which of PUBLIC, anon and authenticated may EXECUTE `name(signature)`, or None when it does not exist.

    A new function here is executable by PUBLIC and, through pg_default_acl, by anon and authenticated
    directly, so a REVOKE FROM PUBLIC alone leaves both browser roles able to call it.
    """
    pattern = re.compile(
        rf"(?is)\b(create\s+or\s+replace\s+function|create\s+function|drop\s+function)\s+(?:if\s+exists\s+)?"
        rf"{_ref(name)}\s*\(([^)]*)\)|\b(grant|revoke)\b[^;]*;"
    )
    granted: set[str] | None = None
    for _, sql in _sources():
        for match in pattern.finditer(sql):
            if match.group(1):
                if _signature(match.group(2)) != signature:
                    continue
                verb = match.group(1).lower()
                if verb.startswith("drop"):
                    granted = None
                elif granted is None:
                    granted = {"public", *BROWSER}
                continue
            parts = PRIVILEGE_STATEMENT.match(_flat(match.group(0)))
            if not parts or not re.search(r"(?is)\b(execute|all)\b", parts.group(2)):
                continue
            objects = parts.group(3).strip()
            schema_wide = re.match(r"(?is)^all\s+(functions|routines)\s+in\s+schema\s+\"?public\"?\b", objects)
            named = re.search(rf"(?is)\b{_ref(name)}\s*\(([^)]*)\)", objects)
            if not schema_wide and not (named and _signature(named.group(1)) == signature):
                continue
            roles = _roles(parts.group(5))
            if parts.group(1).lower() == "grant":
                granted = (granted or set()) | roles
            else:
                granted = (granted or set()) - roles
    return granted


def _live_policies(table: str) -> dict[str, str]:
    """Policy name -> its latest CREATE or ALTER clauses after `ON <table>`; a DROP removes it."""
    pattern = re.compile(
        rf'(?is)\b(create|alter|drop)\s+policy\s+(?:if\s+exists\s+)?(?:"([^"]+)"|(\w+))\s+on\s+{_ref(table)}\b([^;]*);'
    )
    live: dict[str, str] = {}
    for _, sql in _sources():
        for match in pattern.finditer(sql):
            verb, name = match.group(1).lower(), match.group(2) or match.group(3)
            if verb == "drop":
                live.pop(name, None)
            else:
                live[name] = _flat(match.group(4))
    return live


def _opens_to_browser(body: str) -> bool:
    """Whether a permissive policy body lets a browser role read or write rows.

    No TO clause means PUBLIC. A qualifier of false grants nothing; WITH CHECK falls back to USING.
    """
    if re.search(r"(?is)\bas\s+restrictive\b", body):
        return False
    to_clause = re.search(r"(?is)\bto\s+(.*?)(?=\busing\b|\bwith\s+check\b|$)", body)
    if to_clause is not None and not _roles(to_clause.group(1)):
        return False
    using = re.search(r"(?is)\busing\s*\(\s*(true|false)\s*\)", body)
    check = re.search(r"(?is)\bwith\s+check\s*\(\s*(true|false)\s*\)", body)
    reads = using is None or using.group(1).lower() != "false"
    writes = (check or using) is None or (check or using).group(1).lower() != "false"
    return reads or writes


def _frontend_sources() -> list[tuple[str, str]]:
    sources = []
    for path in sorted(FRONTEND.rglob("*")):
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix not in (".ts", ".tsx") or "node_modules" in path.parts or ".next" in path.parts:
            continue
        if ".test." in rel or "__tests__" in rel or rel.startswith("frontend/test/"):
            continue
        sources.append((rel, path.read_text(encoding="utf-8")))
    return sources


FROM = re.compile(r"""(\w+)?\.from\(\s*(?:(['"`])([^'"`]+)\2\s*\))?""")
CALL = re.compile(r"""\s*\.(\w+)\(([^)]*)\)""")
QUOTED = re.compile(r"""['"`]([^'"`]*)['"`]""")


def _api_constant(name: str) -> set[str]:
    text = (FRONTEND / "lib" / "api.ts").read_text(encoding="utf-8")
    match = re.search(rf"const {name}\s*=\s*'([^']+)'", text)
    assert match, f"{name} is no longer a single quoted list in frontend/lib/api.ts"
    return {c.strip() for c in match.group(1).split(",")}


def _site_reads() -> list[tuple[str, str, set[str]]]:
    """Every `.from('teams'|'games').select(...)` in the site: (file, table, the columns it names).

    A select argument is quoted column lists (any options object after them is ignored) or an api.ts
    column constant. A `.from(...)` whose table is not a literal, on anything but an array or buffer,
    fails here instead of going unchecked.
    """
    reads = []
    for rel, text in _frontend_sources():
        for match in FROM.finditer(text):
            receiver, quote, table = match.groups()
            if not quote:
                assert receiver in NON_SUPABASE_FROM, f"{rel} reads a table this guard cannot name: {match.group(0)}"
                continue
            if table not in HIDDEN:
                continue
            call = CALL.match(text, match.end())
            assert call, f"a {table} read in {rel} is not written as .from(...).<method>(...)"
            if call.group(1) in ("insert", "update", "upsert", "delete"):
                continue
            assert call.group(1) == "select", f"a {table} read in {rel} starts with .{call.group(1)}("
            head = call.group(2).split("{")[0]
            columns = {c.strip() for quoted in QUOTED.findall(head) for c in quoted.split(",") if c.strip()}
            for constant in QUOTED.sub("", head).replace(",", " ").split():
                columns |= _api_constant(constant)
            reads.append((rel, table, {re.sub(r"^\w+:|::\w+$", "", c) for c in columns} or {"*"}))
    return reads


def test_no_browser_role_can_read_a_provider_team_id():
    for table, hidden in HIDDEN.items():
        for role, columns in browser_readable_columns(table).items():
            assert columns is not None, f"{role} holds SELECT on the whole of {table}, hidden columns included"
            assert not columns & hidden, f"{role} can read {sorted(columns & hidden)} on {table}"


def test_the_site_column_lists_stay_inside_the_grant():
    """A column the grant leaves out makes PostgREST refuse the whole read."""
    for constant, table in (("TEAM_COLUMNS", "teams"), ("GAME_COLUMNS", "games")):
        for role, granted in browser_readable_columns(table).items():
            missing = _api_constant(constant) - (granted or set())
            assert not missing, f"{constant} names {sorted(missing)}, which {role} cannot read on {table}"


def test_every_site_read_stays_inside_the_grant_or_runs_on_the_service_key():
    reads = _site_reads()
    assert len(reads) >= 40, f"only {len(reads)} teams/games reads found; the scan no longer sees the site"

    outside: dict[tuple[str, str], int] = {}
    for rel, table, columns in reads:
        access = browser_readable_columns(table)
        granted = set.intersection(*(access[role] or set() for role in BROWSER))
        if columns - granted:
            outside[(rel, table)] = outside.get((rel, table), 0) + 1

    assert outside == SERVICE_READS, (
        "a site read names a column the browser grant leaves out, or `*`, outside the service-key reads "
        f"listed above, or a listed one no longer does (remove it then): {outside}"
    )


def test_the_server_only_tables_are_closed_to_the_browser_roles():
    tree = "\n".join(sql for _, sql in _sources())
    for table in SERVER_ONLY_TABLES:
        ref = _ref(table)
        assert re.search(rf"(?is)alter\s+table\s+(?:only\s+)?{ref}\s+enable\s+row\s+level\s+security", tree), (
            f"{table} never has RLS enabled"
        )
        assert not re.search(rf"(?is)alter\s+table[^;]*{ref}\b[^;]*disable\s+row\s+level\s+security", tree)
        assert browser_readable_columns(table) == {"anon": set(), "authenticated": set()}, (
            f"a browser role can read {table}: {browser_readable_columns(table)}"
        )
        opened = {name: body for name, body in _live_policies(table).items() if _opens_to_browser(body)}
        assert not opened, f"a policy on {table} opens it to a browser role: {opened}"
    sequence = browser_readable_columns("scheduled_games_id_seq", "sequence")
    assert sequence == {"anon": set(), "authenticated": set()}, f"a browser role holds the sequence: {sequence}"


def test_the_owner_run_objects_are_closed_to_the_browser_roles():
    """These run as their owner, so their own grant is the only thing between them and the browser."""
    for view in OWNER_RUN_VIEWS:
        access = browser_readable_columns(view)
        assert access == {"anon": set(), "authenticated": set()}, f"a browser role can read {view}: {access}"

    granted = _function_grantees("exclude_games_for_team_in_range", "uuid, date, date, boolean")
    assert granted is not None, "exclude_games_for_team_in_range(uuid, date, date, boolean) is never created"
    assert not granted & {"public", *BROWSER}, f"the function is callable by {sorted(granted)}"
