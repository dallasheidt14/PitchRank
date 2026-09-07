"""Agent-facing docs name files, commands, symbols and schedules that really exist.

CLAUDE.md, the skills and the agent definitions are loaded straight into an
agent's context and acted on without verification. Nothing else in the repo reads
them: ruff, tsc and eslint never see markdown, so a doc that names a deleted file,
an unregistered flag, or a column that does not exist sends every agent down a
dead end and no gate notices. Two rounds of hand-auditing (#1019, #1023) found
exactly this class -- a deleted `supabaseBrowserClient.ts`, a phantom
`validatePagination`, a `--file` flag argparse never registered, and a `games`
join on a column the table does not have.

Each check below carries a companion test asserting its parser found known-good
input, because a doc regex that silently matches nothing passes forever while
proving nothing.
"""

import ast
import re
import shlex
import subprocess
from pathlib import Path

import pytest

from src.utils.team_utils import calculate_age_group_from_birth_year

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"


def _corpus() -> list[Path]:
    """Every markdown file an agent loads automatically or on a skill trigger."""
    paths = [
        CLAUDE_MD,
        PROJECT_ROOT / "frontend" / "CLAUDE.md",
        PROJECT_ROOT / "AGENTS.md",
        PROJECT_ROOT / "frontend" / "AGENTS.md",
        PROJECT_ROOT / "README.md",
    ]
    paths += sorted((PROJECT_ROOT / ".claude" / "rules").glob("*.md"))
    paths += sorted((PROJECT_ROOT / ".claude" / "skills").glob("*/SKILL.md"))
    paths += sorted((PROJECT_ROOT / ".claude" / "agents").glob("*.md"))
    return [p for p in paths if p.is_file()]


CORPUS = _corpus()
CORPUS_IDS = [str(p.relative_to(PROJECT_ROOT)).replace("\\", "/") for p in CORPUS]


def _tracked_files() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


TRACKED = _tracked_files()
TRACKED_BY_BASENAME: dict[str, list[str]] = {}
for _path in TRACKED:
    TRACKED_BY_BASENAME.setdefault(_path.rsplit("/", 1)[-1], []).append(_path)


# --------------------------------------------------------------------------- #
# Check 1: backticked repo paths resolve
# --------------------------------------------------------------------------- #

CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".sql", ".yml", ".yaml", ".json", ".sh", ".md")

# Prose that looks like a path but is not one. Each entry states why.
PATH_SKIP_PATTERNS = (
    re.compile(r"[<>{}*\[\]]"),  # <placeholder>, globs, /teams/[id] route segments
    re.compile(r"^/"),  # URL routes (/rankings) and slash commands (/finalize)
    re.compile(r"^@"),  # TS path alias (@/lib/api) and md import (@CLAUDE.md)
    re.compile(r"^_"),  # leading-underscore suffix conventions (_approved.json)
    re.compile(r"^[A-Z][A-Z0-9_]*(/[A-Z][A-Z0-9_]*)+$"),  # SOS_ML_THRESHOLD_LOW/HIGH
    re.compile(r"^https?://"),  # URLs
    re.compile(r"^[a-z0-9.-]+\.(com|io|org|net)(/|$)"),  # home.gotsport.com/login/
    re.compile(r"^(origin|upstream)/"),  # git refs
    re.compile(r"^[A-Za-z]*\d+/\d+$"),  # GU18/19, 7d/30d, 0.75/0.90
)
# Slash-separated prose enumerations, not paths.
PATH_SKIP_EXACT = {
    "B/Boys/Boy/Male/M",
    "G/Girls/Girl/Female/F",
    "async/await",
    "home/away_team_master_id",
    "7d/30d",
    "HD/AD",
    "MIN/MAX",
    "GOTSPORT_DELAY_MIN/MAX",
    "N/A",
    "and/or",
    "id/team_id_master",
    "dallasheidt14/PitchRank",  # GitHub repo slug, not a path
    "ZenRows/zenrows-python-sdk",  # GitHub repo slug, not a path
    "sos_norm_national/state",  # two column names written as one enumeration
}
# Paths that are gitignored by design, so a tracked-file lookup can never find them.
# Env files are documented by name deliberately and must never be committed.
PATH_SKIP_PREFIXES = ("data/", "reports/", "logs/", "venv/", "node_modules/", ".turbo/", "models/")
ENV_FILE = re.compile(r"(^|/)\.env(\.|$)")

BACKTICKED = re.compile(r"`([^`\n]+)`")


def _path_candidates(path: Path) -> list[tuple[int, str]]:
    found = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for token in BACKTICKED.findall(line):
            token = token.strip()
            if " " in token or not token:
                continue
            if token in PATH_SKIP_EXACT or any(p.search(token) for p in PATH_SKIP_PATTERNS):
                continue
            if token.startswith(PATH_SKIP_PREFIXES) or ENV_FILE.search(token):
                continue
            if "/" not in token and not token.endswith(CODE_SUFFIXES):
                continue
            found.append((lineno, token))
    return found


def _resolves(token: str, doc: Path) -> bool:
    """Rungs: exact, doc-relative, frontend-relative, path-suffix, directory.

    Two doc conventions are normalized away first: a trailing `:anchor` (a line
    number, a line range, or a symbol name) and the `module.symbol` form, which
    names a function inside a module rather than a file of its own.

    Resolution runs against the tracked-file index only, never the working
    directory. An untracked file present on one machine and absent on another
    would otherwise make this test pass locally and fail in CI, which is how
    `frontend/.env.local` first broke it.
    """
    cleaned = token.removeprefix("./").rstrip("/")
    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[0]
    if not cleaned:
        return False
    if not cleaned.endswith(CODE_SUFFIXES) and "." in cleaned.rsplit("/", 1)[-1]:
        stem, _, _symbol = cleaned.rpartition(".")
        if stem and f"{stem}.py" in TRACKED:
            return True
    doc_dir = doc.parent.relative_to(PROJECT_ROOT).as_posix()
    for prefix in ("", doc_dir, "frontend"):
        joined = f"{prefix}/{cleaned}" if prefix else cleaned
        if joined in TRACKED:
            return True
        # A directory reference such as `scripts/` or `.claude/hooks/`
        if any(tracked.startswith(joined + "/") for tracked in TRACKED):
            return True
    return any(tracked.endswith("/" + cleaned) for tracked in TRACKED)


@pytest.mark.parametrize("doc", CORPUS, ids=CORPUS_IDS)
def test_documented_paths_exist(doc: Path) -> None:
    broken = []
    for lineno, token in _path_candidates(doc):
        if not _resolves(token, doc):
            near = TRACKED_BY_BASENAME.get(token.rsplit("/", 1)[-1], [])[:3]
            broken.append(
                f"{doc.relative_to(PROJECT_ROOT)}:{lineno}: documented path {token!r} does not "
                f"exist. Nearest tracked: {near or 'none'}. Fix the doc or drop the reference."
            )
    assert not broken, "\n".join(broken)


def test_path_scan_finds_known_paths() -> None:
    """The path extractor must actually match; a silent zero would pass forever."""
    tokens = [t for _, t in _path_candidates(CLAUDE_MD)]
    assert len(tokens) > 40, f"path scan found only {len(tokens)} candidates in CLAUDE.md"
    assert "src/etl/glicko_engine.py" in tokens
    assert not _resolves("src/utils/there_is_no_such_module.py", CLAUDE_MD)


# --------------------------------------------------------------------------- #
# Check 2: documented python commands name real scripts and real flags
# --------------------------------------------------------------------------- #

SHELL_FENCE = re.compile(r"^```(bash|sh|shell)\s*$")
FENCE_END = re.compile(r"^```\s*$")

# Scripts that define no argparse parser; flag-checking them is meaningless.
NO_ARGPARSE_SCRIPTS = {
    "scripts/pre_import_checklist.py",
    "scripts/review_aliases.py",
    "scripts/validate_post_ranking_run.py",
}


def _shell_commands(path: Path) -> list[tuple[int, str]]:
    commands, in_fence = [], False
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not in_fence and SHELL_FENCE.match(line):
            in_fence = True
            continue
        if in_fence and FENCE_END.match(line):
            in_fence = False
            continue
        if in_fence and line.strip().startswith("python "):
            commands.append((lineno, line.strip().rstrip("\\").strip()))
    return commands


def _argparse_flags(script: Path) -> set[str]:
    tree = ast.parse(script.read_text(encoding="utf-8"))
    flags = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and str(arg.value).startswith("--"):
                    flags.add(arg.value)
    return flags


@pytest.mark.parametrize("doc", CORPUS, ids=CORPUS_IDS)
def test_documented_commands_are_runnable(doc: Path) -> None:
    problems = []
    for lineno, command in _shell_commands(doc):
        try:
            parts = shlex.split(command, comments=True)
        except ValueError:
            continue
        if len(parts) < 2 or parts[1] == "-m" or parts[1].startswith("-"):
            continue
        script_ref = parts[1]
        if "<" in script_ref or ">" in script_ref:
            continue
        script = PROJECT_ROOT / script_ref
        if not script.is_file():
            problems.append(
                f"{doc.relative_to(PROJECT_ROOT)}:{lineno}: documented command runs "
                f"{script_ref!r}, which does not exist."
            )
            continue
        if script_ref in NO_ARGPARSE_SCRIPTS:
            continue
        registered = _argparse_flags(script)
        if not registered:
            continue
        for token in parts[2:]:
            flag = token.split("=", 1)[0]
            if flag.startswith("--") and flag not in registered:
                problems.append(
                    f"{doc.relative_to(PROJECT_ROOT)}:{lineno}: {script_ref} has no flag "
                    f"{flag!r}. Registered: {sorted(registered)}"
                )
    assert not problems, "\n".join(problems)


def test_command_scan_finds_known_commands() -> None:
    commands = [c for _, c in _shell_commands(CLAUDE_MD)]
    assert len(commands) > 5, f"command scan found only {len(commands)} in CLAUDE.md"
    flags = _argparse_flags(PROJECT_ROOT / "scripts" / "calculate_rankings.py")
    assert "--dry-run" in flags and "--lookback-days" in flags
    assert "--totally-bogus" not in flags and "--lookback_days" not in flags


def test_documented_ci_commands_match_the_workflow() -> None:
    """The doc's gate commands and ci.yml cannot drift apart again."""
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    docs = CLAUDE_MD.read_text(encoding="utf-8")
    for fragment in (
        "pytest tests/ --ignore=tests/test_enhanced_pipeline.py",
        "ruff check src/ scripts/ config/ tournament_intake.py dashboard.py",
    ):
        assert fragment in ci, f"ci.yml no longer runs {fragment!r}"
        assert fragment in docs, f"CLAUDE.md no longer documents {fragment!r}"


# --------------------------------------------------------------------------- #
# Check 3: the age-group table equals what the code returns
# --------------------------------------------------------------------------- #

AGE_ROW = re.compile(r"^\|\s*(\d{4})\s*/\s*(\d{4})\s*\|\s*U\d+\s*\|\s*\*{0,2}(u\d+)\*{0,2}")


def _age_table_rows() -> list[tuple[int, str, str]]:
    rows, in_section = [], False
    for lineno, line in enumerate(CLAUDE_MD.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("### Age Groups"):
            in_section = True
            continue
        if in_section and line.startswith("###"):
            break
        match = AGE_ROW.match(line.strip())
        if in_section and match:
            # A band is named by its YOUNGER (Jul 31) year, which the table lists FIRST:
            # `2018 / 2017 | U9 | u9` is U9 because 2026 - 2018 + 1 = 9.
            rows.append((lineno, match.group(1), match.group(3)))
    return rows


def test_age_table_matches_the_code() -> None:
    rows = _age_table_rows()
    assert len(rows) >= 10, f"age-table parser found only {len(rows)} rows"
    problems = []
    for lineno, younger_year, documented in rows:
        actual = calculate_age_group_from_birth_year(int(younger_year)).lower()
        if actual != documented.lower():
            problems.append(
                f"CLAUDE.md:{lineno}: birth year {younger_year} maps to {actual!r}, "
                f"table says {documented!r}. If the season just rolled over (Aug 1) this "
                f"is the expected alarm: update the table and follow the "
                f"AGE_ROLLOVER_FREEZE procedure in CLAUDE.md before lifting the flag."
            )
    assert not problems, "\n".join(problems)


def test_age_table_shorthand_examples_hold() -> None:
    """`14B` = 2014 = U13 and `G2016` = 2016 = U11, the examples under the table."""
    assert calculate_age_group_from_birth_year(2014).lower() == "u13"
    assert calculate_age_group_from_birth_year(2016).lower() == "u11"


# --------------------------------------------------------------------------- #
# Check 4: the workflow table equals the crons on disk, in both directions
# --------------------------------------------------------------------------- #

WORKFLOW_ROW = re.compile(r"^\|\s*`([a-z0-9-]+\.yml)`\s*\|\s*([^|]+?)\s*\|")
CRON_LINE = re.compile(r"^-?\s*cron:\s*['\"]([^'\"]+)['\"]")

# Scheduled workflows deliberately absent from the table, each with its reason.
UNSCHEDULED_OK = {
    "claude-code-review.yml": "review bot, not a data-pipeline job",
    "claude.yml": "review bot, not a data-pipeline job",
}


def _documented_workflows() -> dict[str, str]:
    rows, in_section = {}, False
    for line in CLAUDE_MD.read_text(encoding="utf-8").splitlines():
        if line.startswith("## GitHub Actions Workflows"):
            in_section = True
            continue
        if in_section and line.startswith("### "):
            break
        match = WORKFLOW_ROW.match(line.strip())
        if in_section and match:
            rows[match.group(1)] = match.group(2)
    return rows


def _live_crons(workflow: Path) -> list[str]:
    crons = []
    for line in workflow.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        match = CRON_LINE.match(stripped)
        if match:
            crons.append(match.group(1))
    return crons


def test_documented_workflows_exist() -> None:
    documented = _documented_workflows()
    assert len(documented) >= 20, f"workflow-table parser found only {len(documented)} rows"
    missing = [name for name in documented if not (WORKFLOWS / name).is_file()]
    assert not missing, f"CLAUDE.md documents workflows that do not exist: {missing}"


def test_every_scheduled_workflow_is_documented() -> None:
    documented = _documented_workflows()
    undocumented = []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        if not _live_crons(workflow):
            continue
        if workflow.name in documented or workflow.name in UNSCHEDULED_OK:
            continue
        undocumented.append(workflow.name)
    assert not undocumented, (
        f"these workflows run on a schedule but have no row in CLAUDE.md's workflow "
        f"table: {undocumented}. Add a row, or add it to UNSCHEDULED_OK with a reason."
    )


def test_unscheduled_ok_entries_are_not_stale() -> None:
    for name in UNSCHEDULED_OK:
        assert (WORKFLOWS / name).is_file(), f"UNSCHEDULED_OK names {name}, which no longer exists"


# --------------------------------------------------------------------------- #
# Check 5: TypeScript symbols named beside their module really export
# --------------------------------------------------------------------------- #

TS_IMPORT = re.compile(r"import\s+\{([^}]+)\}\s+from\s+'(@/[^']+)'")
EXPORT_FORMS = (
    "export function {name}",
    "export const {name}",
    "export let {name}",
    "export var {name}",
    "export class {name}",
    "export type {name}",
    "export interface {name}",
    "export enum {name}",
    "export default function {name}",
    "export async function {name}",
)


def _resolve_ts_module(spec: str) -> Path | None:
    base = PROJECT_ROOT / "frontend" / spec.removeprefix("@/")
    for candidate in (
        base.with_suffix(".ts"),
        base.with_suffix(".tsx"),
        base / "index.ts",
        base / "index.tsx",
        base,
    ):
        if candidate.is_file():
            return candidate
    return None


def _ts_imports(doc: Path) -> list[tuple[int, str, str]]:
    found = []
    for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
        match = TS_IMPORT.search(line)
        if match:
            for name in match.group(1).split(","):
                name = name.strip().split(" as ")[0].strip()
                if name:
                    found.append((lineno, name, match.group(2)))
    return found


def _exports_symbol(module: Path, symbol: str) -> bool:
    text = module.read_text(encoding="utf-8")
    if "export * from" in text:
        return True  # barrel re-export; resolving it is out of scope
    if any(form.format(name=symbol) in text for form in EXPORT_FORMS):
        return True
    return bool(re.search(r"export\s*\{[^}]*\b" + re.escape(symbol) + r"\b[^}]*\}", text))


@pytest.mark.parametrize("doc", CORPUS, ids=CORPUS_IDS)
def test_documented_ts_imports_resolve(doc: Path) -> None:
    problems = []
    for lineno, symbol, spec in _ts_imports(doc):
        module = _resolve_ts_module(spec)
        if module is None:
            problems.append(
                f"{doc.relative_to(PROJECT_ROOT)}:{lineno}: documented import from {spec!r}, "
                f"which resolves to no file under frontend/."
            )
            continue
        if not _exports_symbol(module, symbol):
            problems.append(
                f"{doc.relative_to(PROJECT_ROOT)}:{lineno}: {symbol!r} is not exported from "
                f"{module.relative_to(PROJECT_ROOT)}."
            )
    assert not problems, "\n".join(problems)


def test_ts_import_scan_finds_known_symbols() -> None:
    frontend_doc = PROJECT_ROOT / "frontend" / "CLAUDE.md"
    symbols = {s for _, s, _ in _ts_imports(frontend_doc)}
    assert "createClientSupabase" in symbols, f"ts-import scan found: {sorted(symbols)}"
    client = _resolve_ts_module("@/lib/supabase/client")
    assert client is not None
    assert _exports_symbol(client, "createClientSupabase")
    assert not _exports_symbol(client, "createBrowserClient")  # the #1023 defect


def test_shared_api_utility_files_match_the_directory() -> None:
    """Every helper frontend/CLAUDE.md names must exist, and vice versa."""
    api_dir = PROJECT_ROOT / "frontend" / "lib" / "api"
    on_disk = {p.stem for p in api_dir.glob("*.ts")}
    documented = set(
        re.findall(
            r"`lib/api/([a-zA-Z]+)\.ts`",
            (PROJECT_ROOT / "frontend" / "CLAUDE.md").read_text(encoding="utf-8")
            + CLAUDE_MD.read_text(encoding="utf-8"),
        )
    )
    assert documented, "no lib/api/*.ts references found in either CLAUDE.md"
    assert documented <= on_disk, f"documented but absent from lib/api/: {sorted(documented - on_disk)}"


# --------------------------------------------------------------------------- #
# Check 6: dead schema identifiers, and reviewer-agent verdict parity
# --------------------------------------------------------------------------- #

# Identifiers that read as schema but are not. Each maps to what is real.
DEAD_IDENTIFIERS = {
    "provider_code": "the column is provider_id (FK to providers.id)",
    "team_quarantine": "the tables are quarantine_games and quarantine_teams",
    "opp_id_master": "engine in-memory format (src/rankings/data_adapter.py), not a games column",
    "= t.id": "games join teams on teams.team_id_master, never teams.id",
}


@pytest.mark.parametrize("doc", CORPUS, ids=CORPUS_IDS)
def test_no_dead_schema_identifiers_in_sql_or_table_rows(doc: Path) -> None:
    problems, in_sql = [], False
    for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip().startswith("```sql"):
            in_sql = True
            continue
        if in_sql and FENCE_END.match(line.strip()):
            in_sql = False
            continue
        # Only SQL fences: prose may legitimately name a dead identifier to warn about it.
        if not in_sql:
            continue
        # A `--` comment inside the fence is prose too, and the schema blocks use it
        # to say which identifiers are NOT real. Check only the statement itself.
        statement = line.split("--", 1)[0]
        for dead, real in DEAD_IDENTIFIERS.items():
            if dead in statement:
                problems.append(
                    f"{doc.relative_to(PROJECT_ROOT)}:{lineno}: {dead!r} is not a real schema "
                    f"identifier — {real}."
                )
    assert not problems, "\n".join(problems)


def test_dead_identifier_scan_sees_sql_fences() -> None:
    """At least one SQL fence exists in the corpus, or this check scans nothing."""
    total = sum(doc.read_text(encoding="utf-8").count("```sql") for doc in CORPUS)
    assert total > 0, "no ```sql fences found in the corpus; the dead-identifier scan is inert"


def test_reviewer_agents_share_one_verdict_protocol() -> None:
    """The two reviewer agents' verdict sections are deliberately identical."""
    agents_dir = PROJECT_ROOT / ".claude" / "agents"
    sections = {}
    for name in ("migration-reviewer.md", "ranking-change-reviewer.md"):
        path = agents_dir / name
        if not path.is_file():
            pytest.skip(f"{name} not present")
        text = path.read_text(encoding="utf-8")
        marker = "## Verdict"
        assert text.count(marker) == 1, f"{name} must contain exactly one {marker!r} heading"
        sections[name] = "\n".join(
            line.rstrip() for line in text.split(marker, 1)[1].splitlines() if line.strip()
        )
    first, second = sections.values()
    assert first == second, (
        "the two reviewer agents' Verdict sections have diverged; they are deliberately "
        "identical shared protocol. Re-sync them or give each its own heading."
    )
