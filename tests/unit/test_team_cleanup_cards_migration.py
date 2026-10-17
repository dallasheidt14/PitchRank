"""Pin the parts of the team_cleanup_cards migration that fail silently.

ci.yml applies no migrations, so these text assertions stand in for executing the SQL. Without the
run reference a card can name a run that never existed; without the build-id check a card can claim
another build's page; without the auto-lane check the loop could apply a card nobody chose; without
both RLS with its policies and the REVOKE, pg_default_acl leaves anon free to decide, add or erase the
owner's cards, and RLS alone still leaves TRUNCATE. A CHECK passes on NULL, so each one is only as
good as the NOT NULLs beside it.

Definitions resolve by name across every migration, newest wins.
"""

import os
import re
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.team_cleanup.decisions import TEAM_DECISIONS, new_page_run  # noqa: E402
from scripts.team_cleanup.propose_week import PROPOSED_STAGES  # noqa: E402
from scripts.team_cleanup.review_page import card_id  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

TABLE = "team_cleanup_cards"
# The table as a migration may name it: schema-qualified or not, quoted or not.
NAMED = rf'(?:"?public"?\.)?"?{TABLE}"?\b'


def _executable(text: str) -> str:
    """`text` with -- line and /* */ block comments removed, so a commented-out statement never
    satisfies a substring check."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"--[^\n]*", "", text)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", _executable(text)).strip()


def _migrations() -> list[Path]:
    """Every migration, oldest first: filenames are timestamp-prefixed."""
    return sorted(MIGRATIONS.glob("*.sql"))


def _tree() -> str:
    return "\n".join(_executable(p.read_text(encoding="utf-8")) for p in _migrations())


def _newest_statement(pattern: str) -> str:
    """The last statement matching `pattern`, in migration order."""
    found = None
    for path in _migrations():
        sql = _executable(path.read_text(encoding="utf-8"))
        for match in re.finditer(pattern, sql):
            found = sql[match.start() : sql.index(";", match.end()) + 1]
    assert found is not None, f"no migration contains {pattern}"
    return re.sub(r"\s+", " ", found).strip()


def _create_table() -> str:
    return _flat(_newest_statement(rf"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?{NAMED}\s*\("))


def _in_list(column: str) -> tuple[str, ...]:
    """The values the table's CHECK on `column` accepts, in the order it lists them."""
    found = re.search(rf"{column} TEXT[^,]*CHECK \({column} IN \(([^)]*)\)\)", _create_table())
    assert found, f"no IN-list CHECK on {column}"
    return tuple(v.strip().strip("'") for v in found.group(1).split(","))


def test_a_card_s_columns_carry_the_not_nulls_its_checks_rely_on():
    """A NULL page_run passes the build-id check and a NULL position passes position >= 1, since a
    CHECK passes on NULL."""
    table = _create_table()

    for column in (
        "card_id TEXT PRIMARY KEY,",
        "run_id TEXT NOT NULL REFERENCES team_cleanup_runs (run_id),",
        "lane TEXT NOT NULL CHECK (lane IN ('auto', 'owner')),",
        "page_run TEXT NOT NULL,",
        "position INTEGER NOT NULL CHECK (position >= 1),",
        "card JSONB NOT NULL,",
    ):
        assert column in table, f"the cards table no longer declares {column}"


def test_a_card_s_stage_and_decision_are_the_ones_the_loop_uses():
    """The loop writes the stage and reads the decision back through these constants, and the table
    refuses anything else; a value added on one side only fails against the live table."""
    assert _in_list("stage") == PROPOSED_STAGES == ("clubs", "states", "ages")
    assert _in_list("decision") == TEAM_DECISIONS == ("apply", "dont_apply", "unsure")


def test_a_note_is_bounded():
    assert "note TEXT CHECK (char_length(note) <= 2000)," in _create_table()


def test_a_card_belongs_to_the_build_its_id_names():
    """The collector takes a card's change from its build's manifest; a card claiming another build's
    page would let a choice land on a change the owner never saw. The page build names its cards
    with card_id(page_run, ...), which the check reads back."""
    run = new_page_run()
    names = card_id(run, "team|state_code|NV")

    assert "CHECK (left(card_id, char_length(page_run) + 1) = page_run || '_')" in _create_table()
    assert names[: len(run) + 1] == run + "_"


def test_an_auto_card_is_always_apply_never_undecided():
    """Only an owner card waits on a person; the loop applies every auto card as written. A bare
    decision = 'apply' passes for a NULL decision."""
    table = _create_table()

    assert (
        "CONSTRAINT team_cleanup_cards_auto_is_apply CHECK (lane = 'owner' OR decision IS NOT DISTINCT FROM 'apply')"
    ) in table
    assert "decision = 'apply'" not in table


def test_the_admin_who_decided_is_a_user_reference():
    assert "decided_by_user_id UUID REFERENCES auth.users (id) ON DELETE SET NULL," in _create_table()


def test_a_page_s_cards_read_in_order_without_a_place_being_unique():
    """Each lane may number its own cards, so a place is an order, not a key."""
    index = _flat(_newest_statement(r"(?is)create\s+index\s+(?:if\s+not\s+exists\s+)?idx_team_cleanup_cards_page"))
    unique = re.findall(rf"(?is)create\s+unique\s+index\s+[^;]*\bon\s+{NAMED}", _tree())

    assert f"ON {TABLE} (page_run, position);" in index
    assert not unique, f"a unique index on the cards would refuse a second lane's numbering: {unique}"


def test_row_level_security_is_enabled():
    assert re.search(rf"(?is)alter\s+table\s+(?:only\s+)?{NAMED}\s+enable\s+row\s+level\s+security", _tree()), (
        f"{TABLE} ships without RLS, which leaves both policies inert"
    )


def test_the_deny_all_policy_covers_anon_and_authenticated_on_the_cards():
    deny = _flat(_newest_statement(rf'(?is)create\s+policy\s+"{TABLE}_deny_all"'))

    assert f"ON {TABLE} FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)" in deny, (
        f"the deny-all policy no longer refuses both browser roles on the cards: {deny}"
    )


def test_the_service_role_policy_is_on_the_cards():
    allow = _flat(_newest_statement(rf'(?is)create\s+policy\s+"{TABLE}_service_role_all"'))

    assert f"ON {TABLE} FOR ALL TO service_role USING (true) WITH CHECK (true)" in allow, (
        f"the service-role policy no longer grants the loop and the admin routes the cards: {allow}"
    )


def test_the_default_table_grant_is_revoked():
    """RLS governs SELECT/INSERT/UPDATE/DELETE and not TRUNCATE, so the deny-all policy
    leaves the TRUNCATE in pg_default_acl's grant to anon untouched."""
    assert f"REVOKE ALL ON public.{TABLE} FROM anon, authenticated;" in _flat(_tree())


def test_nothing_grants_the_table_to_a_browser_role():
    named = re.findall(rf"(?is)grant\s+[^;]*\bon\b[^;]*\b{TABLE}\b[^;]*;", _tree())
    schema_wide = re.findall(r"(?is)grant\s+[^;]*\bon\s+all\s+tables\s+in\s+schema\s+public[^;]*;", _tree())
    offending = [g for g in named + schema_wide if re.search(r"(?i)\bto\b[^;]*\b(anon|authenticated|public)\b", g)]

    assert not offending, f"{TABLE} is reachable by a browser role: {offending}"


def test_nothing_revokes_the_table_from_the_service_role():
    revokes = re.findall(rf"(?is)revoke\s+[^;]*\bon\b[^;]*\b{TABLE}\b[^;]*;", _tree())
    schema_wide = re.findall(r"(?is)revoke\s+[^;]*\bon\s+all\s+tables\s+in\s+schema\s+public[^;]*;", _tree())
    offending = [r for r in revokes + schema_wide if re.search(r"(?i)\bfrom\b[^;]*\bservice_role\b", r)]

    assert not offending, f"{TABLE} is revoked from service_role, which writes and reads the cards: {offending}"


def test_nothing_later_reshapes_the_table_behind_these_guards():
    """These guards read migration text and CI applies none, so a later ALTER, DROP or re-CREATE,
    however it names the table, could leave them green against a table that no longer matches; fail
    on the first one so its author widens them."""
    tree = _tree()

    for verb, pattern, allowed in (
        ("CREATE TABLE", rf"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?{NAMED}", 1),
        ("DROP TABLE", rf"(?is)drop\s+table\s+(?:if\s+exists\s+)?{NAMED}", 0),
        ("ALTER TABLE", rf"(?is)alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?{NAMED}", 1),
        ("DROP POLICY", rf'(?is)drop\s+policy\s+[^;]*"{TABLE}_', 2),
        ("DROP INDEX", r"(?is)drop\s+index\s+[^;]*idx_team_cleanup_cards", 0),
    ):
        hits = re.findall(pattern, tree)
        assert len(hits) <= allowed, (
            f"{verb} on {TABLE} appeared in a migration; these guards read only its "
            f"original definition and no longer describe the live table: {hits}"
        )
