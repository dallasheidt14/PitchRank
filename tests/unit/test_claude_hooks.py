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
    BASH is None or shutil.which("jq") is None or shutil.which("python") is None or not _gnu_realpath(),
    reason="hooks need bash, jq and GNU realpath on PATH",
)


def _exec(hook: str, stdin: str, project_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    return subprocess.run(
        [BASH, str(HOOKS / hook)], input=stdin, capture_output=True, text=True, encoding="utf-8", env=env, timeout=60
    )


def _run(hook: str, payload: dict, project_dir: Path, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return _exec(hook, json.dumps({**payload, "cwd": str(cwd or project_dir)}), project_dir)


def _bash(command: str, project_dir: Path, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return _run("git-guard.sh", {"tool_input": {"command": command}}, project_dir, cwd)


def _edit(file_path: str, project_dir: Path, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return _run("protect-paths.sh", {"tool_input": {"file_path": file_path}}, project_dir, cwd)


def _post_edit(file_path: Path, project_dir: Path, **tool_input: object) -> str | None:
    result = _run("post-edit.sh", {"tool_input": {"file_path": str(file_path), **tool_input}}, project_dir)
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


def _fresh_repo(parent: Path, name: str) -> Path:
    """A repo of its own, for the checks that depend on commit and remote state."""
    root = parent / name
    root.mkdir()
    _init_repo(root)
    return root


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
    'python -c "print(1)"',
    "bash scripts/run-enhanced-validation.sh",
    'powershell -NoProfile -Command "Get-ChildItem"',
    'powershell -Command "git status"',
    # A bare -c is a count flag far more often than a command string.
    'rg -c "git add -A" CLAUDE.md',
    'grep -c "git push --force" CLAUDE.md',
    'sort -c "git add -A"',
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
    "git push -fu origin feat/x",
    "git push -uf origin feat/x",
    "git push --all origin",
    "git push --mirror origin",
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
    # A shell wrapper's quoted argument is a command, not prose. Every one of
    # these passed straight through before the flag became a separator.
    'powershell -Command "git push --force origin main"',
    'powershell -NoProfile -Command "git push --force origin x"',
    'pwsh -Command "git push -f origin x"',
    'bash -c "git push --force origin x"',
    "bash -c 'git add -A'",
    'bash -lc "git reset --hard HEAD~1"',
    'sh -c "git add -A"',
    'cmd /c "git reset --hard HEAD~1"',
    # An escaped quote does not end the argument, so the force push is still in it.
    'bash -c "git commit -m \\"x\\"; git push --force origin x"',
    'powershell -Command "git commit -m \\"msg\\"; git add -A"',
    # A wrapper's own long options come before its command flag.
    'bash --noprofile -c "git push --force origin x"',
    'bash --norc --noprofile -c "git add -A"',
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
    assert _bash(f'cd "{main_checkout.as_posix()}" && git commit -m x', repo, cwd=repo).returncode == 2
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
    shutil.which("python") is None
    or subprocess.run(["python", "-P", "-m", "ruff", "--version"], capture_output=True).returncode != 0,
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


def test_replace_all_multi_site_edits_get_flagged(repo: Path) -> None:
    target = repo / "notes.md"
    target.write_text("alpha\nalpha\nalpha\n")
    flagged = _post_edit(target, repo, replace_all=True, old_string="beta", new_string="alpha")
    assert flagged is not None and "3 occurrences" in flagged
    target.write_text("alpha\n")
    assert _post_edit(target, repo, replace_all=True, old_string="beta", new_string="alpha") is None
    target.write_text("alpha\nalpha\n")
    assert _post_edit(target, repo, old_string="beta", new_string="alpha") is None


def test_replace_all_counts_the_exact_multiline_needle(repo: Path) -> None:
    target = repo / "block.md"
    # Lopsided on purpose: the needle's first line appears three times but the
    # full needle only twice, so a truncated needle inflates the count.
    target.write_text("def f():\n    x = 1\ndef f():\n    x = 1\ndef f():\n    y = 2\n")
    flagged = _post_edit(target, repo, replace_all=True, old_string="q", new_string="def f():\n    x = 1\n")
    assert flagged is not None and "2 occurrences" in flagged
    # A site missing the trailing newline is not a match for the full needle.
    target.write_text("def f():\n    x = 1\ndef f():\n    x = 1")
    assert _post_edit(target, repo, replace_all=True, old_string="q", new_string="def f():\n    x = 1\n") is None


def test_replace_all_normalizes_crlf_needles(repo: Path) -> None:
    target = repo / "crlf.md"
    target.write_text("aa\nbb\naa\nbb\n")
    flagged = _post_edit(target, repo, replace_all=True, old_string="q", new_string="aa\r\nbb\r\n")
    assert flagged is not None and "2 occurrences" in flagged


def test_replace_all_deletion_stays_silent(repo: Path) -> None:
    target = repo / "notes.md"
    target.write_text("alpha\nalpha\n")
    assert _post_edit(target, repo, replace_all=True, old_string="alpha", new_string="") is None


def test_replace_all_handles_raw_utf8_payloads(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the locale-codepage stdin path the explicit UTF-8 decode exists to defeat.
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    target = repo / "utf8.md"
    target.write_text("alpha — beta\nalpha — beta\n", encoding="utf-8")
    payload = {
        "cwd": str(repo),
        "tool_input": {
            "file_path": str(target),
            "replace_all": True,
            "old_string": "q",
            "new_string": "alpha — beta\n",
        },
    }
    result = _exec("post-edit.sh", json.dumps(payload, ensure_ascii=False), repo)
    assert result.returncode == 0, result.stderr
    note = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "2 occurrences" in note


@pytest.mark.skipif(
    shutil.which("python") is None
    or subprocess.run(["python", "-P", "-m", "ruff", "--version"], capture_output=True).returncode != 0,
    reason="ruff not importable",
)
def test_replace_all_counts_before_ruff_rewrites(repo: Path) -> None:
    target = repo / "scripts" / "ordered.py"
    target.write_text('import os\nimport os\nsb.table("teams").update({}).execute()\n')
    note = _post_edit(target, repo, replace_all=True, old_string="q", new_string="import os\n") or ""
    assert "2 occurrences" in note
    assert "rewrote" in note
    assert "no --dry-run" in note


def test_git_guard_allows_amend_until_the_commit_is_pushed(tmp_path: Path) -> None:
    """Amending a pushed commit strands the branch: only a force push lands it."""
    root = _fresh_repo(tmp_path, "amend")
    # HEAD is still origin/main's commit here, so an amend would rewrite main's tip.
    assert _bash("git commit --amend --no-edit", root, cwd=root).returncode == 2
    (root / "scripts" / "later.py").write_text("x = 1\n")
    _git(root, "add", "scripts/later.py")
    _git(root, "commit", "-qm", "local only")
    assert _bash("git commit --amend --no-edit", root, cwd=root).returncode == 0
    assert _bash('git commit --amend -m "reword"', root, cwd=root).returncode == 0
    _git(root, "update-ref", "refs/remotes/origin/feat/x", "HEAD")
    assert _bash("git commit --amend --no-edit", root, cwd=root).returncode == 2


def test_git_guard_amend_reads_the_repo_git_will_run_in(tmp_path: Path) -> None:
    """`git -C <dir>` and a leading `cd <dir>` both move where the amend lands."""
    pushed = _fresh_repo(tmp_path, "pushed")
    _git(pushed, "update-ref", "refs/remotes/origin/feat/x", "HEAD")
    elsewhere = _fresh_repo(tmp_path, "elsewhere")
    (elsewhere / "scripts" / "later.py").write_text("x = 1\n")
    _git(elsewhere, "add", "scripts/later.py")
    _git(elsewhere, "commit", "-qm", "local only")

    assert _bash(f'git -C "{pushed.as_posix()}" commit --amend --no-edit', pushed, cwd=elsewhere).returncode == 2
    assert _bash(f'cd "{pushed.as_posix()}" && git commit --amend --no-edit', pushed, cwd=elsewhere).returncode == 2
    # An earlier -C names a repo the amend never touches, so it must not be read.
    cmd = f'git -C "{elsewhere.as_posix()}" status && git commit --amend --no-edit'
    assert _bash(cmd, pushed, cwd=pushed).returncode == 2


def test_dry_run_check_warns_when_a_tracked_file_gains_a_write(tmp_path: Path) -> None:
    """The old check exited on any file already on main, so an added write never warned."""
    root = _fresh_repo(tmp_path, "gains")
    legacy = root / "scripts" / "legacy_writer.py"
    assert "no --dry-run" not in (_post_edit(legacy, root) or "")
    legacy.write_text('sb.table("teams").update({}).execute()\nsb.table("games").insert({}).execute()\n')
    assert "no --dry-run" in (_post_edit(legacy, root) or "")


def _session_start(project_dir: Path, stub_gh: Path | None = None) -> subprocess.CompletedProcess:
    """Run the session-start hook, optionally with a `gh` that always fails.

    The stub keeps the test hermetic and fast: a temp repo has no GitHub remote,
    so every real `gh` call would go out to the network only to error.
    """
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir)}
    if stub_gh is not None:
        env["PATH"] = f"{stub_gh}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        [BASH, str(HOOKS / "session-start.sh")],
        input=json.dumps({"cwd": str(project_dir)}),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


@pytest.fixture
def no_gh(tmp_path: Path) -> Path:
    return _gh_stub(tmp_path, "stub")


def _gh_stub(tmp_path: Path, name: str, rankings: str | None = None) -> Path:
    """A `gh` that fails, except for a canned answer to the rankings query.

    The hook lets gh run the jq, so the stub prints the finished line rather than
    JSON. That keeps these tests off the network and lets them pin states a real
    run only occupies for a few hours a week.
    """
    stub = tmp_path / name
    stub.mkdir()
    body = ["#!/bin/sh"]
    if rankings is not None:
        body += ['case "$*" in', f"  *calculate-rankings*) echo '{rankings}'; exit 0 ;;", "esac"]
    body.append("exit 1")
    script = stub / "gh"
    script.write_text("\n".join(body) + "\n")
    script.chmod(0o755)
    return script.parent


def test_session_start_still_reports_when_github_is_unreachable(tmp_path: Path, no_gh: Path) -> None:
    """It runs before every conversation, so it must never be what fails."""
    root = _fresh_repo(tmp_path, "offline")
    result = _session_start(root, no_gh)
    assert result.returncode == 0, result.stderr
    assert "## Repo state" in result.stdout
    assert "on feat/x" in result.stdout
    assert "ATTENTION" not in result.stdout


def test_session_start_flags_a_worktree_holding_uncommitted_work(tmp_path: Path, no_gh: Path) -> None:
    """A worktree with uncommitted work cannot be removed without losing it."""
    root = _fresh_repo(tmp_path, "worktrees")
    linked = tmp_path / "linked"
    _git(root, "worktree", "add", "-q", "-b", "side", str(linked))
    assert "uncommitted work" not in _session_start(root, no_gh).stdout

    (linked / "scripts" / "legacy_writer.py").write_text("changed\n")
    out = _session_start(root, no_gh).stdout
    assert "ATTENTION: worktrees with uncommitted work: linked" in out


def test_session_start_does_not_call_a_running_ranking_job_a_failure(tmp_path: Path) -> None:
    """A run takes 2.5-3.7 hours, so in_progress is the healthy state most of Monday."""
    root = _fresh_repo(tmp_path, "running")
    running = _session_start(root, _gh_stub(tmp_path, "gh_running", "2026-08-24 in_progress"))
    assert "rankings 2026-08-24 in_progress" in running.stdout
    assert "ATTENTION" not in running.stdout

    failed = _session_start(root, _gh_stub(tmp_path, "gh_failed", "2026-08-24 failure"))
    assert "ATTENTION: last rankings run 2026-08-24 failure" in failed.stdout


def test_session_start_flags_a_worktree_holding_only_untracked_files(tmp_path: Path, no_gh: Path) -> None:
    """Scratch files nobody committed are the ones that exist in no other copy."""
    root = _fresh_repo(tmp_path, "scratch_wt")
    linked = tmp_path / "scratch"
    _git(root, "worktree", "add", "-q", "-b", "scratchwork", str(linked))
    assert "uncommitted work" not in _session_start(root, no_gh).stdout

    (linked / "notes.md").write_text("only ever existed here\n")
    assert "ATTENTION: worktrees with uncommitted work: scratch" in _session_start(root, no_gh).stdout
