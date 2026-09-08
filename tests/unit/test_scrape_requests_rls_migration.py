"""Pin the scrape_requests lockdown against the ways it silently comes undone.

ci.yml applies no migrations, so nothing in CI executes this SQL and nothing else reads it.
These text assertions stand in for execution.

Two design decisions, both learned the hard way when an earlier draft of this file was
mutation-tested and a two-line later migration reopened anonymous INSERT with every
assertion green.

**Resolve effective final state, never the statements this migration wrote.** Objects here
are superseded by new migration files rather than edited in place, so a guard pinned to what
one file says defends that file and not the table. Policies replay CREATE/ALTER/DROP;
grants replay against the newest REVOKE; the function's ACL replays REVOKE/GRANT/DROP.

**Assume the widening will not name a role, a table, or a policy the way this file does.**
The three policies removed here carry no TO clause at all, so a role-name filter is blind to
a re-added copy. A grant can arrive as GRANT ... ON ALL TABLES IN SCHEMA public. pg_dump
emits ALTER TABLE ONLY. Identifiers may be quoted or bare. Each of those was a live hole.

These read migration text, not the live table. pg_default_acl re-grants arwdDxtm on any
rebuilt relation, so re-check the live ACL after any table rebuild:
  SELECT relacl FROM pg_class WHERE relname = 'scrape_requests';
"""

import re
from functools import lru_cache
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

TABLE = "scrape_requests"
CONSTRAINT = "scrape_requests_priority_check"
CLAIM_FN = "claim_queue_items"

BROWSER_ROLES = {"public", "anon", "authenticated"}

# public.x, public."x", "public"."x" or bare x — pg_dump and hand-written SQL differ.
TABLE_REF = rf'(?:"?public"?\s*\.\s*)?"?{TABLE}"?'
IDENT = r'(?:"([^"]+)"|([A-Za-z_]\w*))'

POLICY_RE = re.compile(
    rf"(?is)(create|alter|drop)\s+policy\s+(?:if\s+exists\s+)?{IDENT}\s+on\s+{TABLE_REF}\b"
)


def _executable(text: str) -> str:
    """`text` with -- line and /* */ block comments removed.

    Every assertion goes through this. A substring check against comment-preserving text is
    satisfied by a commented-out clause, and this migration's header discusses the very
    grants and policies the tests below assert are absent. The migration is hand-applied, so
    the file text is what an operator pastes — a block-commented REVOKE is a real shape.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"--[^\n]*", "", text)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=1)
def _sources() -> tuple[tuple[Path, str], ...]:
    """Every migration as (path, comment-stripped SQL), oldest first by timestamp prefix."""
    return tuple(
        (path, _executable(path.read_text(encoding="utf-8")))
        for path in sorted(MIGRATIONS.glob("*.sql"))
    )


def _tree() -> str:
    return "\n".join(sql for _, sql in _sources())


def _statement(sql: str, start: int, end: int) -> str:
    return _flat(sql[start : sql.index(";", end) + 1])


def _name(match: re.Match) -> str:
    """The policy identifier, quoted or bare. Groups 2 and 3 — group 1 is the verb."""
    return match.group(2) or match.group(3)


MULTI_WORD_TYPES = (
    "timestamp without time zone",
    "timestamp with time zone",
    "time with time zone",
    "character varying",
    "double precision",
)
ARG_MODES = ("in", "out", "inout", "variadic")


def _signature(raw: str) -> str:
    """`p_provider_id uuid DEFAULT NULL, p_limit integer DEFAULT 500` -> `uuid, integer`.

    A REVOKE names types only while a CREATE names parameters, so comparing raw text treats
    the same function as two and the CREATE's synthetic EXECUTE-to-PUBLIC is never revoked.

    Splits on top-level commas only, so a precision argument (`numeric(10,2)`) survives, and
    keeps multi-word type names whole.
    """
    args, depth, current = [], 0, ""
    for char in raw:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            args.append(current)
            current = ""
        else:
            current += char
    args.append(current)

    types = []
    for arg in args:
        arg = re.sub(r"(?is)\bdefault\b.*$", "", arg).strip().lower()
        if not arg:
            continue
        tokens = arg.split()
        if tokens and tokens[0] in ARG_MODES:
            tokens = tokens[1:]
        rest = " ".join(tokens)
        for multi in MULTI_WORD_TYPES:
            if rest.endswith(multi):
                rest = multi
                break
        else:
            rest = tokens[-1] if len(tokens) > 1 else rest
        types.append(rest)
    return ", ".join(types)


def _roles(clause: str) -> set[str]:
    """Browser-reachable role names in a GRANT's TO list or a REVOKE's FROM list.

    Scoped to the clause, never the whole statement: scanning a whole
    `GRANT EXECUTE ON FUNCTION public.claim_queue_items(...) TO service_role` matches the
    `public.` in the qualified name and reddens a correct grant.
    """
    return {role.lower() for role in re.findall(r"(?i)\b(public|anon|authenticated)\b", clause)}


def _functions_touching_the_table() -> set[str]:
    """Every function whose body names the table, derived rather than hand-listed.

    A hand-written constant covers the function whose name the author happened to know;
    `enqueue_scrape_request` is the second writer here and was missed exactly that way.
    """
    names: set[str] = set()
    for _, sql in _sources():
        for match in re.finditer(
            r"(?is)\bcreate\s+(?:or\s+replace\s+)?function\s+(?:public\.)?(\w+)\s*\(", sql
        ):
            end = sql.find("$$", sql.find("$$", match.end()) + 2)
            body = sql[match.start() : end if end > 0 else match.end()]
            if re.search(rf"(?i)\b{TABLE}\b", body):
                names.add(match.group(1).lower())
    return names


def _body(policy: str) -> str:
    """The part of a CREATE/ALTER POLICY statement after the table reference.

    Parsing the whole statement lets a TO- or FOR-regex start matching inside the policy
    *name*: `CREATE POLICY "Allow anyone to enqueue" ON scrape_requests FOR INSERT WITH
    CHECK (true)` reported itself server-only, so the guard passed on the exact regression
    it exists to catch.
    """
    return re.split(rf"(?is)\bon\s+{TABLE_REF}\b", policy, maxsplit=1)[-1]


def _live_policies() -> dict[str, str]:
    """Policy name -> its effective statement, replaying CREATE, ALTER and DROP in order.

    ALTER POLICY matters as much as CREATE: widening one to `TO anon, authenticated` leaves
    a newest-CREATE lookup still reading `TO service_role`.
    """
    live: dict[str, str] = {}
    for _, sql in _sources():
        for match in POLICY_RE.finditer(sql):
            verb, name = match.group(1).lower(), _name(match)
            if verb == "drop":
                live.pop(name, None)
            elif verb == "alter":
                live[name] = _statement(sql, match.start(), match.end())
            else:
                live[name] = _statement(sql, match.start(), match.end())
    return live


def _is_browser_reachable(policy: str) -> bool:
    """True when a browser role can exercise `policy`.

    No TO clause means PUBLIC, which includes anon. All three policies this migration
    removes are written that way.
    """
    body = _body(policy)
    to_clause = re.search(r"(?is)\bto\s+([\w\s,\"]+?)(?=\busing\b|\bwith\s+check\b|;|$)", body)
    if to_clause is None:
        return True
    roles = {role.strip().strip('"').lower() for role in to_clause.group(1).split(",")}
    return bool(roles & BROWSER_ROLES)


def _permits_write(policy: str) -> bool:
    """Whether `policy` lets a write through.

    Two parts. The command: no FOR clause means FOR ALL, which includes INSERT. And the
    qualifier: Postgres uses WITH CHECK for new rows, falling back to USING when WITH CHECK
    is omitted, so a policy qualified `false` grants nothing however broad its FOR and TO.
    Without this second half a correct deny-all reads as an open door.
    """
    body = _body(policy)
    for_clause = re.search(r"(?is)\bfor\s+(all|select|insert|update|delete)\b", body)
    if for_clause is not None and for_clause.group(1).lower() == "select":
        return False

    # WITH CHECK governs new rows and falls back to USING only when absent. A WITH CHECK that
    # is present but not a bare true/false is an expression this parser cannot evaluate, so
    # treat it as permissive rather than falling through to a USING (false) beside it —
    # `FOR ALL USING (false) WITH CHECK (status = 'pending')` permits the INSERT.
    if re.search(r"(?is)\bwith\s+check\b", body):
        trivial = re.search(r"(?is)\bwith\s+check\s*\(\s*(true|false)\s*\)", body)
        return trivial is None or trivial.group(1).lower() != "false"

    using = re.search(r"(?is)\busing\s*\(\s*(true|false)\s*\)", body)
    return using is None or using.group(1).lower() != "false"


def _grants_after_the_newest_revoke() -> list[str]:
    """Every GRANT reaching this table that is issued after the newest table-level REVOKE.

    GRANTs accumulate rather than supersede, so inspecting only the newest one misses a
    later `REVOKE ALL; GRANT INSERT; GRANT SELECT;` trio. A schema-wide grant never names
    the table, and is the form pg_default_acl and Supabase's own bootstrap use.
    """
    reach = rf"\b(?:{TABLE_REF}|all\s+tables\s+in\s+schema\s+\"?public\"?)\b"
    pattern = rf"(?is)\b(grant|revoke)\s+[^;]*?\bon\s+[^;]*?{reach}"
    grants: list[str] = []
    for _, sql in _sources():
        # One alternation yields events already in document order — no sort, and no tuple
        # ending in an unorderable re.Match.
        for match in re.finditer(pattern, sql):
            statement = _statement(sql, match.start(), match.end())
            if match.group(1).lower() == "grant":
                grants.append(statement)
                continue
            if not re.search(r"(?is)\brevoke\s+all\b", statement):
                continue
            # A REVOKE clears only what it names. `REVOKE ALL ... FROM service_role` after a
            # `GRANT ... TO anon` must not launder the accumulator.
            revoked = _roles(re.split(r"(?i)\bfrom\b", statement)[-1])
            grants = [g for g in grants if _roles(re.split(r"(?i)\bto\b", g)[-1]) - revoked]
    return grants


def test_no_live_policy_lets_a_browser_role_write():
    """The exposure this migration closes: grant plus policy both permitted the write."""
    offending = {
        name: policy
        for name, policy in _live_policies().items()
        if _is_browser_reachable(policy) and _permits_write(policy)
    }

    assert not offending, (
        f"a browser-reachable write policy is live on {TABLE}, so anyone holding the public "
        f"anon key can enqueue scrape work: {offending}"
    )


def test_the_browser_is_denied_outright():
    """Reads are closed too: error_message is written from raw exception text and the
    ZenRows key travels in a query string, so the column can absorb a live credential."""
    live = _live_policies()

    assert "scrape_requests_deny_all" in live, "the deny-all policy is gone"
    policy = live["scrape_requests_deny_all"]
    assert _is_browser_reachable(policy), "the deny-all policy no longer names the browser roles"
    assert re.search(r"(?is)using\s*\(\s*false\s*\)", _body(policy)), "deny-all no longer denies"


def test_nothing_grants_the_table_to_a_browser_role():
    """A schema-wide grant is the form that reopened this in mutation testing."""
    offending = [
        grant
        for grant in _grants_after_the_newest_revoke()
        if re.search(r"(?is)\bto\b[^;]*\b(public|anon|authenticated)\b", grant)
    ]

    assert not offending, (
        f"{TABLE} is granted to a browser-reachable role after the newest REVOKE, which "
        f"restores the grant half of the exposure: {offending}"
    )


def test_the_default_table_grant_is_revoked():
    """RLS governs SELECT/INSERT/UPDATE/DELETE and not TRUNCATE, so the deny-all policy
    leaves the TRUNCATE in pg_default_acl's grant untouched."""
    revokes = [
        _statement(sql, m.start(), m.end())
        for _, sql in _sources()
        for m in re.finditer(rf"(?is)\brevoke\s+all\s+on\s+(?:table\s+)?{TABLE_REF}\b", sql)
    ]

    assert revokes, f"nothing revokes the default grant on {TABLE}"
    newest = revokes[-1]
    for role in ("anon", "authenticated"):
        assert re.search(rf"(?is)\bfrom\b[^;]*\b{role}\b", newest), (
            f"the REVOKE does not name {role}: {newest}"
        )


def test_the_priority_range_is_constrained():
    """Not the control that closes the priority-1 lane — 1 is what user clicks use, and the
    REVOKE is what stops an outsider sending it. This rejects 0 and 6+."""
    final = None
    for _, sql in _sources():
        for match in re.finditer(
            rf"(?is)(add|drop)\s+constraint\s+(?:if\s+exists\s+)?{CONSTRAINT}\b", sql
        ):
            final = (match.group(1).lower(), _statement(sql, match.start(), match.end()))

    assert final is not None, f"{CONSTRAINT} is never defined"
    verb, statement = final
    assert verb == "add", f"the last statement touching {CONSTRAINT} drops it: {statement}"
    assert re.search(r"(?is)between\s+1\s+and\s+5", statement), (
        f"{CONSTRAINT} no longer pins priority to 1-5: {statement}"
    )


def test_row_level_security_is_enabled():
    """Without it every policy above is inert. This migration does not restate the ENABLE
    from 20251113150557, so the guard has to reach back to it — and the reshape test cannot,
    since deleting that line lowers the ALTER TABLE count rather than raising it."""
    assert re.search(
        rf"(?is)alter\s+table\s+(?:only\s+)?{TABLE_REF}\s+enable\s+row\s+level\s+security", _tree()
    ), f"{TABLE} never has RLS enabled, so its policies decide nothing"


def test_no_live_policy_lets_a_browser_role_read():
    """Reads are half the point of this lockdown, and the deny-all policy existing does not
    stop a permissive SELECT policy being added beside it — permissive policies OR together."""
    offending = {
        name: policy
        for name, policy in _live_policies().items()
        if _is_browser_reachable(policy)
        and re.search(r"(?is)\bfor\s+(all|select)\b", _body(policy))
        and not re.search(r"(?is)\bas\s+restrictive\b", policy)
        and re.search(r"(?is)\busing\s*\(\s*(?!false\s*\))", _body(policy))
    }

    assert not offending, (
        f"a browser-reachable read policy is live on {TABLE}; error_message carries raw "
        f"exception text, so this is the credential sink reopening: {offending}"
    )


def test_the_queue_claim_function_is_not_browser_callable():
    """claim_queue_items is SECURITY INVOKER and updates this table.

    Resolved by replay, not by finding one REVOKE somewhere in the tree: a later GRANT, a
    DROP FUNCTION plus re-CREATE (which resets EXECUTE to PUBLIC, and is how functions are
    superseded here), or an overload with a different signature each leave a substring
    search green while the call is reachable again.
    """
    functions = _functions_touching_the_table()
    assert functions, f"no function body names {TABLE}; the derivation broke"

    granted: dict[tuple[str, str], set[str]] = {}
    for _, sql in _sources():
        for name in functions:
            pattern = (
                r"(?is)\b(revoke\s+execute|grant\s+execute|drop\s+function"
                r"|create\s+or\s+replace\s+function|create\s+function)\b"
                rf"[^;]*?\b(?:public\.)?{name}\s*\((.*?)\)"
            )
            for match in re.finditer(pattern, sql):
                verb = re.sub(r"\s+", " ", match.group(1).lower())
                key = (name, _signature(match.group(2)))
                statement = _statement(sql, match.start(), match.end())
                if verb.startswith("revoke"):
                    granted[key] = granted.get(key, set()) - _roles(
                        re.split(r"(?i)\bfrom\b", statement)[-1]
                    )
                elif verb.startswith("grant"):
                    granted[key] = granted.get(key, set()) | _roles(
                        re.split(r"(?i)\bto\b", statement)[-1]
                    )
                elif verb.startswith("drop"):
                    granted.pop(key, None)
                else:
                    # A function that does not yet exist defaults to EXECUTE for PUBLIC.
                    # CREATE OR REPLACE preserves the ACL of one that does, and creates one
                    # that does not — so preserve only what has already been seen. Treating
                    # OR REPLACE as an unconditional reset reddens a legitimate
                    # redefinition; treating it as an unconditional no-op lets a brand-new
                    # queue-touching function ship publicly executable.
                    granted.setdefault(key, {"public"})

        for match in re.finditer(
            r"(?is)\b(grant|revoke)\s+execute\s+on\s+all\s+functions\s+in\s+schema\s+\"?public\"?", sql
        ):
            statement = _statement(sql, match.start(), match.end())
            if match.group(1).lower() == "grant":
                roles = _roles(re.split(r"(?i)\bto\b", statement)[-1])
                granted = {k: v | roles for k, v in granted.items()}
            else:
                roles = _roles(re.split(r"(?i)\bfrom\b", statement)[-1])
                granted = {k: v - roles for k, v in granted.items()}

    reachable = {key: roles for key, roles in granted.items() if roles & BROWSER_ROLES}
    assert not reachable, (
        f"a function that reaches {TABLE} is callable by a browser role, and both are "
        f"SECURITY INVOKER so the caller's privileges apply: {reachable}"
    )


def test_nothing_later_reshapes_the_table_behind_these_guards():
    """These guards read migration text, not the live table, and CI applies no SQL. A later
    statement would satisfy every assertion above while the database no longer matches.

    The allowance is not 1: ENABLE RLS in the original migration, the priority column, and
    this migration's DROP/ADD CONSTRAINT pair make four.
    """
    tree = _tree()

    for verb, pattern, allowed in (
        ("ALTER TABLE", rf"(?is)alter\s+table\s+(?:only\s+|if\s+exists\s+)*{TABLE_REF}\b", 4),
        ("DROP INDEX", rf"(?is)drop\s+index\s+[^;]*{TABLE}", 0),
        ("DISABLE RLS", rf"(?is)alter\s+table[^;]*{TABLE_REF}[^;]*disable\s+row\s+level\s+security", 0),
        ("DROP TABLE", rf"(?is)drop\s+table\s+(?:if\s+exists\s+)?{TABLE_REF}\b", 0),
    ):
        hits = re.findall(pattern, tree)
        assert len(hits) <= allowed, (
            f"{verb} on {TABLE} appeared in a migration; these guards read only the "
            f"definitions they were written against and no longer describe the live table: "
            f"{len(hits)} occurrences"
        )
