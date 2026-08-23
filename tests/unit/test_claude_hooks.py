"""The Claude Code hooks in .claude/hooks block what CLAUDE.md forbids and nothing else.

Each hook is a shell script fed a JSON payload on stdin. A false block stops
legitimate work (a branch name containing `-f`, like `stop-gotsport-firewall-block`,
must not read as a force push); a missed block lets a commit land on main. Both
fail silently, so the command table here is the only thing that pins the
regexes. Add a row whenever a spelling is found to slip through or to trip
wrongly.

The hooks run under Git Bash on Windows and bash on CI; the module skips rather
than failing a machine that does not use them.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOOKS = PROJECT_ROOT / ".claude" / "hooks"
BASH = shutil.which("bash")


def _gnu_realpath() -> bool:
    if BASH is None:
        return False
    probe = subprocess.run([BASH, "-c", "realpath -m --relative-to=/ /tmp"], capture_output=True, text=True)
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(
    BASH is None or shutil.which("jq") is None or not _gnu_realpath(),
    reason="hooks need bash, jq and GNU realpath on PATH",
)


def _exec(hook: str, stdin: str, project_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    return subprocess.run([BASH, str(HOOKS / hook)], input=stdin, capture_output=True, text=True, env=env, timeout=60)


def _run(hook: str, payload: dict, project_dir: Path, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return _exec(hook, json.dumps({**payload, "cwd": str(cwd or project_dir)}), project_dir)


def _bash(command: str, project_dir: Path, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return _run("git-guard.sh", {"tool_input": {"command": command}}, project_dir, cwd)


def _edit(file_path: str, project_dir: Path, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return _run("protect-paths.sh", {"tool_input": {"file_path": file_path}}, project_dir, cwd)


def _post_edit(file_path: Path, project_dir: Path) -> str | None:
    result = _run("post-edit.sh", {"tool_input": {"file_path": str(file_path)}}, project_dir)
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]


def _decision(result: subprocess.CompletedProcess) -> str | None:
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "supabase" / "migrations").mkdir(parents=True)
    (root / "supabase" / "migrations" / "20240101000000_applied.sql").write_text("select 1;\n")
    (root / "scripts").mkdir()
    (root / "scripts" / "legacy_writer.py").write_text('sb.table("teams").update({}).execute()\n')
    _git(root, "add", "supabase", "scripts")
    _git(root, "commit", "-qm", "init")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "checkout", "-qb", "feat/x")


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("hookrepo")
    _init_repo(root)
    return root


ALLOWED_COMMANDS = [
    'git status && echo "git add . is fine"',
    "grep -n 'a\\|ruff format\\|b' CLAUDE.md",
    "cat > doc.md <<'EOF'\ngit add -A\ngit push -f\nEOF\n",
    "echo git add -A",
    'echo "Bob\'s note" && git commit -m "that\'s it"',
    "git push origin codex/fix-rankings-fetch-outage",
    "git push origin stop-gotsport-firewall-block",
    "git push origin feat/x --follow-tags",
    "git push -u origin feat/x",
    "git push origin HEAD:maintenance",
    "git push origin feat/x && git checkout main",
    "git add a.py\ngit commit -m x",
    "git add src/x.py scripts/y.py",
    "grep -q foo <<<bar\ngit add src/x.py",
    "git reset --soft HEAD~1",
    "python -m ruff format --diff src/x.py",
    "ruff format --check .",
    "python -m ruff check --fix src/x.py",
    "python -m pytest tests/unit -q",
]

BLOCKED_COMMANDS = [
    "cd frontend && git add -A",
    'git add "."',
    "(git add .)",
    "if true; then\n  git add -A\nfi",
    "git add -u",
    "git add -- .",
    "git add \\\n  -A",
    "git -C /somewhere add -A",
    "git -c user.email=t@e.com add -A",
    "git --no-pager add -A",
    "env GIT_TRACE=1 git add -A",
    "GIT_TRACE=1 git add -A",
    "exec git add -A",
    "echo $(git add -A)",
    'echo "Here\'s the diff"; git add -A; echo "that\'s it"',
    "grep -q foo <<<bar\ngit add -A",
    'python -c "x = 1 << n"\ngit push --force origin x',
    "cat > f <<-EOF\n\ttext\n\tEOF\ngit add -A",
    'echo "use << EOF for heredocs"\ngit add -A',
    "git push --force origin x",
    "git push -f origin x",
    "git push --force-with-lease",
    "git push --force-with-lease=origin/feat/x",
    "git push origin +HEAD:feat/x",
    "git push origin HEAD:main",
    "git push origin main",
    "git push origin HEAD:refs/heads/main",
    "git push origin --delete main",
    "git switch main && git commit -am x",
    "git checkout main && git push",
    "git reset --hard HEAD~1",
    'git reset "--hard"',
    "python3 -m ruff format src/x.py",
    "uv run ruff format src/x.py",
    "git diff --check && python -m ruff format src/x.py",
    "python -m ruff format --diff a.py && python -m ruff format a.py",
]


@pytest.mark.parametrize("command", ALLOWED_COMMANDS)
def test_git_guard_allows(command: str, repo: Path) -> None:
    result = _bash(command, repo)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("command", BLOCKED_COMMANDS)
def test_git_guard_blocks(command: str, repo: Path) -> None:
    result = _bash(command, repo)
    assert result.returncode == 2, result.stderr
    assert result.stderr.startswith("BLOCKED:")


def test_git_guard_blocks_commit_on_main(repo: Path, tmp_path: Path) -> None:
    main_checkout = tmp_path / "main"
    _git(repo, "clone", "-q", str(repo), str(main_checkout))
    _git(main_checkout, "checkout", "-q", "main")
    assert _bash("git commit -m x", repo, cwd=main_checkout).returncode == 2
    assert _bash('echo "Bob\'s note" && git commit -m "that\'s it"', repo, cwd=main_checkout).returncode == 2
    assert _bash(f'git -C "{main_checkout.as_posix()}" commit -m x', repo, cwd=repo).returncode == 2
    assert _bash("git commit -m x", repo, cwd=repo).returncode == 0


def test_git_guard_fails_closed_on_bad_payload(repo: Path) -> None:
    assert _exec("git-guard.sh", "not json", repo).returncode == 2


@pytest.mark.parametrize(
    "name",
    [".env", ".ENV", ".env ", ".env.", ".env.local", ".Env.production", "frontend/package-lock.json", "yarn.lock"],
)
def test_protect_paths_blocks_secrets_and_lockfiles(name: str, repo: Path) -> None:
    result = _edit(str(repo / name), repo)
    assert result.returncode == 2, result.stderr


@pytest.mark.parametrize("name", [".env.example", "requirements.lock", "src/etl/v53e.py"])
def test_protect_paths_allows(name: str, repo: Path) -> None:
    result = _edit(str(repo / name), repo)
    assert result.returncode == 0 and result.stdout == "", result.stdout


def test_protect_paths_fails_closed_on_bad_payload(repo: Path) -> None:
    assert _exec("protect-paths.sh", "not json", repo).returncode == 2


def test_protect_paths_asks_before_editing_an_applied_migration(repo: Path) -> None:
    applied = repo / "supabase" / "migrations" / "20240101000000_applied.sql"
    assert _decision(_edit(str(applied), repo)) == "ask"
    assert _decision(_edit(applied.as_posix(), repo)) == "ask"
    new = repo / "supabase" / "migrations" / "20990101000000_new.sql"
    assert _decision(_edit(str(new), repo)) is None


def test_protect_paths_asks_when_origin_main_is_unknown(tmp_path: Path) -> None:
    bare = tmp_path / "noremote"
    _git(tmp_path, "init", "-q", "-b", "main", str(bare))
    (bare / "supabase" / "migrations").mkdir(parents=True)
    target = bare / "supabase" / "migrations" / "20240101000000_x.sql"
    target.write_text("select 1;\n")
    assert _decision(_edit(str(target), bare)) == "ask"


def test_protect_paths_ignores_paths_outside_the_project(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere" / "supabase" / "migrations" / "20240101000000_applied.sql"
    assert _decision(_edit(str(outside), repo)) is None


def test_protect_paths_resolves_against_the_active_worktree(repo: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", str(worktree), "main")
    try:
        applied = worktree / "supabase" / "migrations" / "20240101000000_applied.sql"
        assert _decision(_edit(str(applied), repo, cwd=worktree)) == "ask"
    finally:
        _git(repo, "worktree", "remove", "--force", str(worktree))


def test_dry_run_check_warns_only_for_new_unguarded_supabase_writers(repo: Path) -> None:
    new = repo / "scripts" / "new_writer.py"
    new.write_text('sb.table("teams").update({}).execute()\n')
    assert "no --dry-run" in (_post_edit(new, repo) or "")
    new.write_text('sb.table("teams")\n    .update({})\n    .execute()\n')
    assert "no --dry-run" in (_post_edit(new, repo) or "")
    new.write_text('p.add_argument("--dry-run")\nsb.table("teams").update({}).execute()\n')
    assert "no --dry-run" not in (_post_edit(new, repo) or "")
    new.write_text("progress.update(task)\nsession.headers.update({})\n")
    assert "no --dry-run" not in (_post_edit(new, repo) or "")
    legacy = repo / "scripts" / "legacy_writer.py"
    assert "no --dry-run" not in (_post_edit(legacy, repo) or "")


@pytest.mark.skipif(
    subprocess.run(["python", "-P", "-m", "ruff", "--version"], capture_output=True).returncode != 0,
    reason="ruff not importable",
)
def test_ruff_fix_reports_only_real_rewrites(repo: Path) -> None:
    target = repo / "scripts" / "lintme.py"
    target.write_text("import os\nx = 1\n")
    assert "rewrote" in (_post_edit(target, repo) or "")
    assert target.read_text() == "x = 1\n"
    target.write_text("x = undefined_name\n")
    note = _post_edit(target, repo) or ""
    assert "unresolved" in note and "rewrote" not in note
    target.write_text("x = 1\n")
    assert _post_edit(target, repo) is None


def test_cohort_line_comes_from_team_utils() -> None:
    from src.utils.team_utils import calculate_age_group_from_birth_year

    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(PROJECT_ROOT)}
    result = subprocess.run(["python", str(HOOKS / "cohort_line.py")], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith(f"so 14B = {calculate_age_group_from_birth_year(2014)} Male")
