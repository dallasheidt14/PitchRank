"""Pin that the browser roles cannot write the tables only the service role writes, nor call the owner-run writers,
and read of those tables only what the site reads.

The anon key ships in every page and any free account holds an authenticated session, so whatever either
role may do, anyone may do. Migrations 20261121000200 and 20261121000300 revoke the writes, and
20261124120000 turns row level security on with read-only policies, so a write needs both a grant and a
policy handed back; TRUNCATE ignores row level security, so for it the grant alone decides.
20261124120100 narrows team_social_profiles to approved handles. This replays every migration in order, as
the column-grant guard does, so a later GRANT, a GRANT TO PUBLIC, a schema-wide GRANT, a DISABLE or a DROP
and CREATE that hands a table back to the browser roles fails here. Live checks, for each table:
  SELECT has_table_privilege('anon', 'public.<table>', 'INSERT, UPDATE, DELETE, TRUNCATE');
  SELECT relname, relrowsecurity FROM pg_class WHERE relname = '<table>';
  SELECT policyname, permissive, roles, cmd, qual FROM pg_policies WHERE tablename = '<table>';
"""

import re

from tests.unit.test_public_column_grants_migration import (
    BROWSER,
    PRIVILEGE_STATEMENT,
    STATEMENT,
    _flat,
    _function_grantees,
    _live_policies,
    _opens_to_browser,
    _ref,
    _roles,
    _targets,
    browser_readable_columns,
    policy_qualifier,
    policy_roles,
    privilege_events,
)
from tests.unit.test_scrape_requests_rls_migration import _signature, _sources

WRITES = frozenset({"insert", "update", "delete", "truncate"})

SERVICE_WRITTEN_TABLES = (
    "rankings_full",
    "ranking_history",
    "team_merge_map",
    "team_social_profiles",
    "team_momentum",
    "team_trajectory",
    "game_history",
    "announcements",
)

INSTAGRAM_PROFILES = "team_social_profiles"
SITE_HANDLES_VIEW = "team_instagram_handles"
APPROVED_STATUSES = r"(?i:review_status)\s+(?i:in)\s*\(\s*'auto_approved'\s*,\s*'confirmed'\s*\)"
APPROVED_POLICY = re.compile(rf"(?s)\b(?i:using)\s*\(\s*{APPROVED_STATUSES}\s*\)")
APPROVED_VIEW = re.compile(rf"(?s)\b(?i:where)\b.*\b(?:\w+\.)?{APPROVED_STATUSES}")

OWNER_RUN_WRITERS = (
    "backfill_total_game_stats",
    "backfill_total_game_stats_page",
    "batch_backfill_null_scores",
    "batch_upsert_game_explainability",
    "batch_update_ml_overperformance",
)

DO_BLOCK = re.compile(r"(?is)\bdo\s+\$(\w*)\$(.*?)\$\1\$")
GUARDED_BRANCH = re.compile(
    r"(?is)\bif\s+to_regclass\(\s*'public\.(\w+)'\s*\)\s+is\s+not\s+null\s+then(.*?)(?:\belse\b|\bend\s+if\s*;)"
)
CONDITION = re.compile(r"(?is)\b(?:if|elsif|elseif)\b[^;]*?\bthen\b")
RLS_SWITCH = re.compile(r"(?is)\b(enable|disable)\s+row\s+level\s+security\b")
VIEW_STATEMENT = re.compile(
    r"(?is)\b(?P<verb>create\s+(?:or\s+replace\s+)?|drop\s+)(?:materialized\s+)?view\s+(?:if\s+(?:not\s+)?exists\s+)?"
    r'(?:"?public"?\s*\.\s*)?"?(?P<name>\w+)"?(?P<body>[^;]*);'
)


def _table_statements(table: str) -> re.Pattern[str]:
    """A pattern for each statement that creates or drops `table`, alters it, or changes one of its policies."""
    ref = _ref(table)
    return re.compile(
        rf"(?is)\b(?:(?P<create>create\s+table\s+(?P<if_not_exists>if\s+not\s+exists\s+)?{ref}(?=[\s(;]))"
        rf"|(?P<drop>drop\s+table\s+(?:if\s+exists\s+)?(?:[^;(]*?,\s*)?{ref}(?=[\s,;]))"
        rf"|(?P<alter>alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?{ref}\b)"
        rf'|(?P<policy>(?P<verb>create|alter|drop)\s+policy\s+(?:if\s+exists\s+)?(?:"(?P<quoted>[^"]+)"|(?P<bare>\w+))'
        rf"\s+on\s+{ref}\b))(?P<rest>[^;]*);"
    )


def _replay(table: str) -> tuple[bool, dict[str, str]]:
    """Whether row level security is on for `table` after every migration, and its live policies by name.

    A DROP, or a CREATE that makes the table, starts both over, as Postgres creates a table with row level
    security off and drops its policies with it; CREATE TABLE IF NOT EXISTS over one an earlier migration created
    does nothing, while for a table no migration creates it reads as a rebuild, which fails safe.
    Of several switches in one ALTER TABLE the last one holds. An unquoted policy name folds to lower case.
    """
    on, policies, exists = False, {}, False
    pattern = _table_statements(table)
    for _, sql in _sources():
        for match in pattern.finditer(sql):
            if match.group("drop"):
                on, policies, exists = False, {}, False
            elif match.group("create"):
                if not (exists and match.group("if_not_exists")):
                    on, policies, exists = False, {}, True
            elif match.group("alter"):
                switches = RLS_SWITCH.findall(match.group(0))
                if switches:
                    on = switches[-1].lower() == "enable"
            else:
                name = match.group("quoted") or match.group("bare").lower()
                if match.group("verb").lower() == "drop":
                    policies.pop(name, None)
                else:
                    policies[name] = _flat(match.group("rest"))
    return on, policies


def _replayed_statements(table: str, text: str) -> int:
    """How many revokes on, row level security switches for, or policy statements on `table` are in `text`."""
    revokes = 0
    for match in STATEMENT.finditer(text):
        parts = PRIVILEGE_STATEMENT.match(_flat(match.group(0)))
        if parts and parts.group(1).lower() == "revoke" and _targets(parts.group(3).strip(), table, "table"):
            revokes += 1
    switches = sum(
        1
        for match in _table_statements(table).finditer(text)
        if match.group("policy") or (match.group("alter") and RLS_SWITCH.search(match.group(0)))
    )
    return revokes + switches


def _views_reading(table: str) -> dict[str, str]:
    """Each view or materialized view whose newest definition reads `table`, with that definition."""
    views: dict[str, str] = {}
    for _, sql in _sources():
        for match in VIEW_STATEMENT.finditer(sql):
            name = match.group("name").lower()
            if match.group("verb").lower().startswith("drop"):
                views.pop(name, None)
            else:
                views[name] = _flat(match.group("body"))
    return {name: body for name, body in views.items() if re.search(rf"(?is)\b{table}\b", body)}


def _named_writes(privileges: str) -> set[str]:
    """The write privileges a GRANT or REVOKE list names; ALL names every one."""
    if re.search(r"(?is)\ball\b", privileges):
        return set(WRITES)
    return {word.lower() for word in re.findall(r"(?is)\b(insert|update|delete|truncate)\b", privileges)}


def browser_writes(table: str) -> dict[str, set[str]]:
    """Role -> the write privileges it holds on `table` after every migration, directly or through PUBLIC.

    pg_default_acl gives anon and authenticated every privilege on a new relation, so a rebuild starts
    both over at every write, and a table no migration creates starts there too. PUBLIC is tracked on its
    own, as Postgres does: revoking a role's own grant leaves what it inherits from PUBLIC. A column-level
    grant (`UPDATE (col)`) counts as holding the privilege; a column-level revoke does not take a
    table-wide one away, so only a revoke without a column list removes it.
    """
    fresh = {"public": set(), **{role: set(WRITES) for role in BROWSER}}
    held = {grantee: set(privileges) for grantee, privileges in fresh.items()}
    for parts in privilege_events(table):
        if parts is None:
            held = {grantee: set(privileges) for grantee, privileges in fresh.items()}
            continue
        named = _named_writes(parts.group(2))
        grantees = _roles(parts.group(5))
        if parts.group(1).lower() == "grant":
            for grantee in grantees:
                held[grantee] |= named
        else:
            whole = {w for w in named if not re.search(rf"(?is)\b{w}\s*\(", parts.group(2))}
            for grantee in grantees:
                held[grantee] -= whole
    return {role: held[role] | held["public"] for role in BROWSER}


def _created_signatures(name: str) -> set[str]:
    """Every argument signature any migration creates `name` with, so a later overload is checked too."""
    pattern = re.compile(rf"(?is)\bcreate\s+(?:or\s+replace\s+)?function\s+{_ref(name)}\s*\(([^)]*)\)")
    return {_signature(match.group(1)) for _, sql in _sources() for match in pattern.finditer(sql)}


def _command(body: str) -> str:
    """No FOR clause means ALL, as in Postgres."""
    found = re.search(r"(?is)\bfor\s+(all|select|insert|update|delete)\b", body)
    return found.group(1).lower() if found else "all"


def _covers_reads(body: str) -> bool:
    return _command(body) in {"all", "select"}


def _opens_reads_to_browser(body: str) -> bool:
    """Whether a permissive policy body lets a browser role read rows."""
    return _covers_reads(body) and policy_roles(body) != set() and policy_qualifier(body, "using") != "false"


def _reads_every_row(body: str) -> bool:
    """Whether a permissive policy body lets both browser roles read every row."""
    roles = policy_roles(body)
    admits_browser = roles is None or "public" in roles or set(BROWSER) <= roles
    return _covers_reads(body) and admits_browser and policy_qualifier(body, "using") == "true"


def test_no_browser_role_can_write_a_service_written_table():
    held = {table: browser_writes(table) for table in SERVICE_WRITTEN_TABLES}
    open_tables = {table: roles for table, roles in held.items() if any(roles.values())}
    assert not open_tables, f"a browser role can write: {open_tables}"


def test_row_level_security_stays_on_for_each_service_written_table():
    """A DISABLE, or a rebuild of the table, after the last ENABLE switches it off again."""
    for table in SERVICE_WRITTEN_TABLES:
        on, _ = _replay(table)
        assert on, f"row level security is off on {table} after the last migration"


def test_each_service_written_table_keeps_a_read_policy_for_the_browser_roles():
    """Without a policy admitting every row, beside a restrictive one, or without a table-wide SELECT grant, the
    browser roles lose rows or columns the site reads."""
    for table in SERVICE_WRITTEN_TABLES:
        if table == INSTAGRAM_PROFILES:
            continue
        _, live = _replay(table)
        readers = [name for name, body in live.items() if _reads_every_row(body)]
        assert readers, f"no policy lets the browser roles read every row of {table}"
        narrowing = [name for name, body in live.items() if re.search(r"(?is)\bas\s+restrictive\b", body)]
        assert not narrowing, f"a restrictive policy on {table} narrows what the read policy admits: {narrowing}"
        for role, columns in browser_readable_columns(table).items():
            assert columns is None, f"{role} cannot read the whole of {table}: {columns}"


def test_the_browser_roles_read_only_approved_instagram_handles():
    """The site shows approved handles alone; the rest are read with the service key, those awaiting review by
    the admin review page."""
    _, live = _replay(INSTAGRAM_PROFILES)
    readers = {name: body for name, body in live.items() if _opens_reads_to_browser(body)}
    assert readers, f"no policy lets the browser roles read the approved rows of {INSTAGRAM_PROFILES}"
    wider = {name: body for name, body in readers.items() if not APPROVED_POLICY.search(body)}
    assert not wider, f"a policy lets the browser roles read more than approved handles: {wider}"


def test_every_view_over_instagram_profiles_shows_the_browser_roles_approved_handles_only():
    """A view without security_invoker reads as its owner, past row level security: the site's view must filter
    to approved handles and stay readable, and any other must be closed to the browser roles."""
    views = _views_reading(INSTAGRAM_PROFILES)
    site = views.pop(SITE_HANDLES_VIEW, None)
    assert site is not None, f"{SITE_HANDLES_VIEW}, which the site reads, no longer reads {INSTAGRAM_PROFILES}"
    assert APPROVED_VIEW.search(site), f"{SITE_HANDLES_VIEW} no longer filters to approved handles"
    access = browser_readable_columns(SITE_HANDLES_VIEW)
    assert all(columns is None for columns in access.values()), f"the site cannot read {SITE_HANDLES_VIEW}: {access}"
    for name, body in views.items():
        if re.search(r"(?is)\bsecurity_invoker\s*=\s*(?:true|on)\b", body):
            continue
        access = browser_readable_columns(name)
        assert access == {"anon": set(), "authenticated": set()}, f"a browser role can read {name}: {access}"


def test_no_browser_policy_admits_a_write_on_a_service_written_table():
    """Row level security backs up the write revoke only while no policy lets a browser role write."""
    for table in SERVICE_WRITTEN_TABLES:
        _, live = _replay(table)
        writers = {name: body for name, body in live.items() if _command(body) != "select" and _opens_to_browser(body)}
        assert not writers, f"a policy lets a browser role write {table}: {writers}"


def test_no_migration_alters_a_policy_on_a_service_written_table():
    """ALTER POLICY keeps every clause it leaves out, which the replay cannot see; drop and create instead."""
    for path, sql in _sources():
        for table in SERVICE_WRITTEN_TABLES:
            statements = _table_statements(table).finditer(sql)
            altered = [match.group(0) for match in statements if (match.group("verb") or "").lower() == "alter"]
            assert not altered, f"{path.name} alters a policy on {table}: {altered}"


def test_no_migration_renames_a_table_onto_a_service_written_table():
    """A renamed table keeps its own policies, grants and row level security, which no replay here follows."""
    for path, sql in _sources():
        for table in SERVICE_WRITTEN_TABLES:
            renames = re.findall(rf'(?is)\balter\s+table\s+[^;]*?\brename\s+to\s+"?{table}"?(?=[\s;])', sql)
            assert not renames, f"{path.name} renames a table onto {table}: {renames}"


def test_a_guarded_statement_runs_whenever_its_table_exists():
    """The replays count a statement inside a DO block whatever its IF says, so pin each IF to its table or view."""
    guarded_objects = (*SERVICE_WRITTEN_TABLES, *_views_reading(INSTAGRAM_PROFILES))
    for path, sql in _sources():
        for block in DO_BLOCK.finditer(sql):
            body = block.group(2)
            for table in guarded_objects:
                inside = _replayed_statements(table, body)
                if not inside:
                    continue
                assert not re.search(r"(?is)\bexception\b", body), f"{path.name}: the DO block swallows errors"
                assert len(CONDITION.findall(body)) == len(GUARDED_BRANCH.findall(body)), (
                    f"{path.name}: a condition other than IF to_regclass(...) IS NOT NULL decides whether a "
                    f"statement on {table} runs"
                )
                guarded = sum(
                    _replayed_statements(table, branch.group(2))
                    for branch in GUARDED_BRANCH.finditer(body)
                    if branch.group(1).lower() == table
                )
                assert guarded == inside, (
                    f"{path.name}: a statement on {table} does not run under "
                    f"IF to_regclass('public.{table}') IS NOT NULL"
                )


def test_the_owner_run_writers_are_closed_to_the_browser_roles():
    """They write as their owner, so their own grant is the only thing between them and the browser."""
    for name in OWNER_RUN_WRITERS:
        signatures = _created_signatures(name)
        assert signatures, f"{name} is never created"
        for signature in signatures:
            granted = _function_grantees(name, signature)
            if granted is None:
                continue
            assert not granted & {"public", *BROWSER}, f"{name}({signature}) is callable by {sorted(granted)}"


def test_no_browser_role_can_read_newsletter_subscribers():
    """The signup form inserts a row; nothing on the site reads subscribers back."""
    tree = "\n".join(sql for _, sql in _sources())
    ref = _ref("newsletter_subscribers")
    assert re.search(rf"(?is)alter\s+table\s+(?:only\s+)?{ref}\s+enable\s+row\s+level\s+security", tree)
    assert not re.search(rf"(?is)alter\s+table[^;]*{ref}\b[^;]*disable\s+row\s+level\s+security", tree), (
        "row level security is switched off, which opens every subscriber row to the browser roles' SELECT"
    )
    live = _live_policies("newsletter_subscribers")
    opened = {name: body for name, body in live.items() if _opens_reads_to_browser(body)}
    assert not opened, f"a policy lets a browser role read subscriber emails: {opened}"


def test_a_signed_out_visitor_can_still_subscribe():
    """The signup route inserts with the anon key, so its grant and an insert policy that admits it must stay."""
    assert "insert" in browser_writes("newsletter_subscribers")["anon"], "the anon key lost INSERT on subscribers"
    admits_anon = [
        name
        for name, body in _live_policies("newsletter_subscribers").items()
        if re.search(r"(?is)\bfor\s+insert\b", body)
        and (policy_roles(body) is None or policy_roles(body) & {"public", "anon"})
        and (policy_qualifier(body, r"with\s+check") or policy_qualifier(body, "using")) != "false"
    ]
    assert admits_anon, "no insert policy admits the anon key, so subscribing would fail"
