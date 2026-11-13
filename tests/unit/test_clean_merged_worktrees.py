"""What clean_merged_worktrees.py will and will not remove.

Removing a worktree is not undoable: the folder goes, ignored files included,
and so does the branch. So every reason to keep one is pinned here on its own,
each fixture breaking exactly one, against a real git repository. git runs for
real; gh and schtasks are doubles that each answer only the one query the script
makes, so a changed query fails here instead of reaching the real, logged-in gh.
A few tests also replace one step, such as the copy or the open-folder probe, to
make it fail.
"""

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scripts.clean_merged_worktrees as cleaner  # noqa: E402

REAL_RUN = cleaner.run
TODAY = dt.date(2026, 11, 12)
OTHER_SHA = "1111111111111111111111111111111111111111"
SCHTASKS = ("schtasks", "/query", "/fo", "LIST", "/v")


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return done.stdout.strip()


class FakeCommands:
    """gh and schtasks as doubles; git runs for real."""

    def __init__(self) -> None:
        self.prs: dict[str, list[dict]] = {}
        self.unreachable: set[str] = set()
        self.gh_calls: list[tuple[str, ...]] = []
        self.schtasks = SimpleNamespace(returncode=0, stdout="Start In:                             N/A\n")

    def __call__(self, *command: str, cwd: Path | None = None, timeout: int | None = None):
        if command[0] == "git":
            return REAL_RUN(*command, cwd=cwd, timeout=timeout)
        if command[0] == "gh":
            return self.gh(command)
        if command == SCHTASKS:
            return subprocess.CompletedProcess(command, self.schtasks.returncode, self.schtasks.stdout, "denied")
        raise AssertionError(f"unexpected command {command}")

    def gh(self, command: tuple[str, ...]) -> subprocess.CompletedProcess:
        prefix = ("gh", "pr", "list", "--state", "all", "--head")
        suffix = ("--limit", "100", "--json", "number,state,headRefOid")
        if command[: len(prefix)] != prefix or command[len(prefix) + 1 :] != suffix:
            raise AssertionError(f"the gh double does not model {command}")
        self.gh_calls.append(command)
        branch = command[len(prefix)]
        if branch in self.unreachable:
            return subprocess.CompletedProcess(command, 1, "", 'Post "https://api.github.com/graphql": timeout')
        return subprocess.CompletedProcess(command, 0, json.dumps(self.prs.get(branch, [])), "")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    config = (
        ("user.email", "t@example.com"),
        ("user.name", "t"),
        ("core.autocrlf", "false"),
        ("commit.gpgsign", "false"),
    )
    for key, value in config:
        _git(main, "config", key, value)
    ignored = ["data/*", "node_modules/", "__pycache__/", ".pytest_cache/", ".next/", ".env", ".env.local", "*.pyc"]
    (main / ".gitignore").write_text("\n".join([*ignored, ".turbo/*", ""]))
    (main / "app.py").write_text("print('hi')\n")
    _git(main, "add", ".gitignore", "app.py")
    _git(main, "commit", "-qm", "init")
    _git(main, "update-ref", "refs/remotes/origin/main", "HEAD")
    monkeypatch.setattr(cleaner, "ROOT", main)
    monkeypatch.setattr(cleaner, "dt", SimpleNamespace(date=SimpleNamespace(today=lambda: TODAY)))
    monkeypatch.setattr(cleaner, "WINDOWS", False)
    return main


@pytest.fixture
def commands(monkeypatch) -> FakeCommands:
    fake = FakeCommands()
    monkeypatch.setattr(cleaner, "run", fake)
    return fake


def _worktree(main: Path, branch: str, *, commit: bool = False) -> tuple[Path, str]:
    path = main.parent / branch.replace("/", "-")
    _git(main, "worktree", "add", "-q", "-b", branch, str(path))
    if commit:
        (path / "feature.py").write_text("x = 1\n")
        _git(path, "add", "feature.py")
        _git(path, "commit", "-qm", "feature")
    return path, _git(path, "rev-parse", "HEAD")


def _merged(commands: FakeCommands, branch: str, head: str, number: int = 42) -> None:
    commands.prs[branch] = [{"number": number, "state": "MERGED", "headRefOid": head}]


def _branch_exists(main: Path, branch: str) -> bool:
    return bool(_git(main, "branch", "--list", branch))


def _assert_kept(main: Path, path: Path, branch: str, out: str, reason: str) -> None:
    assert path.is_dir() and _branch_exists(main, branch)
    assert f"kept {path}  (" in out and reason in out


def _folder_link(link: Path, target: Path) -> None:
    """A junction on Windows, which git deletes through; a symlink elsewhere."""
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


def _rescued(rescue: Path) -> set[str]:
    return {p.relative_to(rescue).as_posix() for p in rescue.rglob("*") if p.is_file()}


# --- removal --------------------------------------------------------------------------------------------


def _with_ignored_files(path: Path) -> None:
    for relative in (
        "data/backups/rollback.json",
        ".turbo/smoke/report.md",
        ".turbo/smoke/.vite/deps/chunk.js",
        "node_modules/pkg/index.js",
        "__pycache__/app.cpython-311.pyc",
        ".pytest_cache/v/cache/lastfailed",
        ".next/server/page.js",
        "stray.pyc",
        ".env",
        ".env.local",
    ):
        (path / relative).parent.mkdir(parents=True, exist_ok=True)
        (path / relative).write_text("keep me\n" if relative.endswith((".json", ".md")) else "disposable\n")


def test_a_merged_clean_worktree_is_removed_after_its_ignored_files_are_copied(repo, commands, capsys) -> None:
    path, head = _worktree(repo, "feat/done", commit=True)
    _merged(commands, "feat/done", head)
    _with_ignored_files(path)

    assert cleaner.sweep(execute=True) == [path]

    rescue = repo / "data" / "backups" / "worktree-rescue" / "2026-11-12_feat-done"
    assert _rescued(rescue) == {"data/backups/rollback.json", ".turbo/smoke/report.md"}
    assert (rescue / "data" / "backups" / "rollback.json").read_text() == "keep me\n"
    assert not path.exists()
    assert not _branch_exists(repo, "feat/done")
    assert (repo / "app.py").is_file()
    query = ("--limit", "100", "--json", "number,state,headRefOid")
    assert commands.gh_calls == [("gh", "pr", "list", "--state", "all", "--head", "feat/done", *query)]
    out = capsys.readouterr().out
    assert f"copied 2 ignored file(s), 0.0 MB from {path} to {rescue}" in out
    assert f"removed {path}  (#42 merged; branch feat/done)" in out


def test_a_folder_link_is_unlinked_first_so_its_target_survives(repo, commands, capsys) -> None:
    """A worktree's node_modules is often a junction into the main checkout's, which git would empty."""
    path, head = _worktree(repo, "feat/linked")
    _merged(commands, "feat/linked", head)
    shared = repo.parent / "shared-install"
    (shared / "pkg").mkdir(parents=True)
    (shared / "pkg" / "index.js").write_text("installed\n")
    (path / "data").mkdir()
    _folder_link(path / "data" / "shared", shared)

    assert cleaner.sweep(execute=True) == [path]

    assert (shared / "pkg" / "index.js").read_text() == "installed\n"
    assert not path.exists()
    assert not (repo / "data" / "backups" / "worktree-rescue").exists()
    assert f"removed {path}  (#42 merged; branch feat/linked); unlinked data/shared" in capsys.readouterr().out


def test_a_file_past_the_windows_path_limit_is_still_copied(repo, commands) -> None:
    path, head = _worktree(repo, "feat/deep")
    _merged(commands, "feat/deep", head)
    deep = Path("data", *["d" * 40] * 7, "rollback.json")
    assert len(str(path / deep)) > 300
    os.makedirs(cleaner.native(path / deep.parent))
    with open(cleaner.native(path / deep), "w") as handle:
        handle.write("keep me\n")

    assert cleaner.sweep(execute=True) == [path]

    rescue = repo / "data" / "backups" / "worktree-rescue" / "2026-11-12_feat-deep"
    with open(cleaner.native(rescue / deep)) as handle:
        assert handle.read() == "keep me\n"


def test_a_dry_run_names_what_would_go_and_changes_nothing(repo, commands, capsys) -> None:
    path, head = _worktree(repo, "feat/done")
    _merged(commands, "feat/done", head)
    _with_ignored_files(path)

    assert cleaner.sweep(execute=False) == [path]

    out = capsys.readouterr().out
    assert f"would remove {path}  (#42 merged; branch feat/done)" in out
    assert "would copy 2 ignored file(s)" in out
    assert "DRY RUN — nothing written. Re-run with --execute." in out
    assert path.is_dir() and _branch_exists(repo, "feat/done")
    assert not (repo / "data").exists()


def test_the_bare_command_is_a_dry_run(repo, commands, monkeypatch, capsys) -> None:
    """pr_wait --dry-run prints this command as its preview, so it must never remove anything."""
    path, head = _worktree(repo, "feat/done")
    _merged(commands, "feat/done", head)
    monkeypatch.setattr(sys, "argv", ["clean_merged_worktrees.py"])
    assert cleaner.main() == 0
    assert path.is_dir() and _branch_exists(repo, "feat/done")
    assert "DRY RUN — nothing written. Re-run with --execute." in capsys.readouterr().out


def test_a_dry_run_never_probes_whether_a_folder_is_open(repo, commands, monkeypatch) -> None:
    """The probe renames the folder and back, which is a write."""
    path, head = _worktree(repo, "feat/done")
    _merged(commands, "feat/done", head)
    monkeypatch.setattr(cleaner, "in_use", lambda _: pytest.fail("probed in a dry run"))
    assert cleaner.sweep(execute=False) == [path]


def test_a_second_rescue_the_same_day_takes_a_fresh_folder(repo, commands) -> None:
    path, head = _worktree(repo, "feat/twice")
    _merged(commands, "feat/twice", head)
    (path / "data" / "backups").mkdir(parents=True)
    (path / "data" / "backups" / "log.json").write_text("second\n")
    earlier = repo / "data" / "backups" / "worktree-rescue" / "2026-11-12_feat-twice"
    earlier.mkdir(parents=True)
    (earlier / "log.json").write_text("first\n")

    assert cleaner.sweep(execute=True) == [path]

    assert (earlier / "log.json").read_text() == "first\n" and _rescued(earlier) == {"log.json"}
    assert (earlier.with_name("2026-11-12_feat-twice-2") / "data" / "backups" / "log.json").read_text() == "second\n"


# --- every reason to keep one, each on its own ------------------------------------------------------------


def test_a_detached_worktree_is_kept_without_asking_github(repo, commands, capsys) -> None:
    path = repo.parent / "detached"
    _git(repo, "worktree", "add", "-q", "--detach", str(path))
    assert cleaner.sweep(execute=True) == []
    assert path.is_dir() and commands.gh_calls == []
    assert f"kept {path}  (detached)" in capsys.readouterr().out


def test_a_locked_worktree_is_kept(repo, commands, capsys) -> None:
    path, head = _worktree(repo, "feat/locked")
    _merged(commands, "feat/locked", head)
    _git(repo, "worktree", "lock", str(path))
    assert cleaner.sweep(execute=True) == []
    _assert_kept(repo, path, "feat/locked", capsys.readouterr().out, "(locked)")


def test_a_worktree_whose_folder_is_gone_is_left_to_git_prune(repo, commands, capsys) -> None:
    path, head = _worktree(repo, "feat/vanished")
    _merged(commands, "feat/vanished", head)
    for child in sorted(path.rglob("*"), reverse=True):
        child.rmdir() if child.is_dir() else child.unlink()
    path.rmdir()
    assert cleaner.sweep(execute=True) == []
    assert commands.gh_calls == [] and _branch_exists(repo, "feat/vanished")
    assert "folder missing (git worktree prune clears the entry)" in capsys.readouterr().out


def test_a_git_status_that_fails_keeps_the_worktree(repo, commands, monkeypatch, capsys) -> None:
    """An empty answer from a failed status must not read as a clean worktree."""
    path, head = _worktree(repo, "feat/unreadable")
    _merged(commands, "feat/unreadable", head)

    def failing_status(*command, cwd=None, timeout=None):
        if "status" in command:
            return subprocess.CompletedProcess(command, 128, "", "fatal: not a git repository")
        return commands(*command, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(cleaner, "run", failing_status)
    assert cleaner.sweep(execute=True) == []
    _assert_kept(repo, path, "feat/unreadable", capsys.readouterr().out, "git status failed: fatal: not a git")


def test_an_open_pr_keeps_the_worktree_even_after_an_earlier_merge(repo, commands, capsys) -> None:
    path, head = _worktree(repo, "feat/again")
    commands.prs["feat/again"] = [
        {"number": 41, "state": "MERGED", "headRefOid": head},
        {"number": 43, "state": "OPEN", "headRefOid": head},
    ]
    assert cleaner.sweep(execute=True) == []
    _assert_kept(repo, path, "feat/again", capsys.readouterr().out, "#43 PR still open")


def test_a_closed_unmerged_pr_keeps_the_worktree_and_counts_its_commits(repo, commands, capsys) -> None:
    path, head = _worktree(repo, "feat/abandoned", commit=True)
    commands.prs["feat/abandoned"] = [{"number": 44, "state": "CLOSED", "headRefOid": head}]
    assert cleaner.sweep(execute=True) == []
    out = capsys.readouterr().out
    _assert_kept(repo, path, "feat/abandoned", out, "#44 PR closed without merging; 1 commit(s) not on main")


def test_a_branch_that_never_had_a_pr_is_listed_and_kept(repo, commands, capsys) -> None:
    path, _ = _worktree(repo, "codex/experiment", commit=True)
    assert cleaner.sweep(execute=True) == []
    _assert_kept(repo, path, "codex/experiment", capsys.readouterr().out, "(no PR; 1 commit(s) not on main")


def test_a_head_other_than_the_merged_one_keeps_the_worktree(repo, commands, capsys) -> None:
    path, _ = _worktree(repo, "feat/more", commit=True)
    _merged(commands, "feat/more", OTHER_SHA)
    assert cleaner.sweep(execute=True) == []
    _assert_kept(repo, path, "feat/more", capsys.readouterr().out, "branch head differs from the merged PR's head")


def test_a_commit_landing_during_the_lookups_keeps_the_worktree(repo, commands, monkeypatch, capsys) -> None:
    """The head the PR is matched against is read before the lookups, so it is read again before removal."""
    path, head = _worktree(repo, "feat/busy")
    _merged(commands, "feat/busy", head)
    answer_lookup = commands.gh

    def lookup_then_commit(command):
        answer = answer_lookup(command)
        (path / "late.py").write_text("y = 2\n")
        _git(path, "add", "late.py")
        _git(path, "commit", "-qm", "late")
        return answer

    monkeypatch.setattr(commands, "gh", lookup_then_commit)
    assert cleaner.sweep(execute=True) == []
    _assert_kept(repo, path, "feat/busy", capsys.readouterr().out, "HEAD no longer matches the merged PR's head")


def test_a_tracked_change_keeps_the_worktree(repo, commands, capsys) -> None:
    path, head = _worktree(repo, "feat/edited")
    _merged(commands, "feat/edited", head)
    (path / "app.py").write_text("print('changed')\n")
    assert cleaner.sweep(execute=True) == []
    _assert_kept(repo, path, "feat/edited", capsys.readouterr().out, "uncommitted changes or untracked files")


def test_an_untracked_file_keeps_the_worktree(repo, commands, capsys) -> None:
    path, head = _worktree(repo, "feat/scratch")
    _merged(commands, "feat/scratch", head)
    (path / "notes.md").write_text("only ever existed here\n")
    assert cleaner.sweep(execute=True) == []
    _assert_kept(repo, path, "feat/scratch", capsys.readouterr().out, "uncommitted changes or untracked files")


def test_an_untracked_file_counts_even_when_git_is_set_to_hide_them(repo, commands, capsys) -> None:
    """git worktree remove's own check reads the same setting, so it would not catch this either."""
    path, head = _worktree(repo, "feat/hidden")
    _merged(commands, "feat/hidden", head)
    _git(repo, "config", "status.showUntrackedFiles", "no")
    (path / "notes.md").write_text("only ever existed here\n")
    assert cleaner.sweep(execute=True) == []
    _assert_kept(repo, path, "feat/hidden", capsys.readouterr().out, "uncommitted changes or untracked files")


def test_a_worktree_holding_another_worktree_is_kept(repo, commands, capsys) -> None:
    """An ignore rule hides the inner one from both status checks, and the removal would take it too."""
    outer, head = _worktree(repo, "feat/outer")
    _merged(commands, "feat/outer", head)
    inner = outer / ".turbo" / "worktrees" / "inner"
    _git(repo, "worktree", "add", "-q", "-b", "feat/inner", str(inner))
    commands.prs["feat/inner"] = [{"number": 7, "state": "OPEN", "headRefOid": head}]
    assert cleaner.sweep(execute=True) == []
    _assert_kept(repo, outer, "feat/outer", capsys.readouterr().out, "another worktree is inside it")
    assert inner.is_dir()


def test_a_scheduled_tasks_folder_is_kept(repo, commands, monkeypatch, capsys) -> None:
    path, head = _worktree(repo, "feat/weekly")
    _merged(commands, "feat/weekly", head)
    monkeypatch.setattr(cleaner, "WINDOWS", True)
    commands.schtasks.stdout = f"Start In:                             {path}\n"
    assert cleaner.sweep(execute=False) == []
    _assert_kept(repo, path, "feat/weekly", capsys.readouterr().out, "a scheduled task runs in this folder")


def test_a_task_running_above_the_worktree_does_not_protect_it(repo, commands, monkeypatch) -> None:
    """A task starting above a worktree, such as in C:\\ or the main checkout, does not hold it; one inside it does."""
    path, head = _worktree(repo, "feat/nested")
    _merged(commands, "feat/nested", head)
    monkeypatch.setattr(cleaner, "WINDOWS", True)
    commands.schtasks.stdout = f"Start In:                             {repo.parent}\nStart In:  Multiple actions\n"
    assert cleaner.sweep(execute=False) == [path]


def test_the_shells_own_working_folder_is_kept_with_the_command_to_finish(repo, commands, monkeypatch, capsys):
    path, head = _worktree(repo, "feat/here")
    _merged(commands, "feat/here", head)
    (path / "sub").mkdir()
    monkeypatch.chdir(path / "sub")
    assert cleaner.sweep(execute=True, show_others=False) == []
    out = capsys.readouterr().out
    _assert_kept(repo, path, "feat/here", out, "#42 this shell's working folder is inside it")
    assert f"once nothing has it open, run from {repo}: python scripts/clean_merged_worktrees.py --execute" in out


def test_a_folder_a_process_holds_is_kept(repo, commands, monkeypatch, capsys) -> None:
    path, head = _worktree(repo, "feat/open")
    _merged(commands, "feat/open", head)
    monkeypatch.setattr(cleaner, "in_use", lambda folder: folder == path)
    assert cleaner.sweep(execute=True) == []
    _assert_kept(repo, path, "feat/open", capsys.readouterr().out, cleaner.HELD_BY_A_PROCESS)


def test_pr_wait_mode_lists_only_merged_worktrees_it_kept(repo, commands, capsys) -> None:
    _worktree(repo, "codex/experiment", commit=True)
    assert cleaner.sweep(execute=True, show_others=False) == []
    out = capsys.readouterr().out
    assert "kept" in out.splitlines()[-1] and "no PR" not in out


# --- what happens when a step after the checks fails --------------------------------------------------------


def test_a_worktree_whose_files_cannot_be_listed_is_kept(repo, commands, monkeypatch, capsys) -> None:
    path, head = _worktree(repo, "feat/unlisted")
    _merged(commands, "feat/unlisted", head)

    def failing_listing(*command, cwd=None, timeout=None):
        if "ls-files" in command:
            return subprocess.CompletedProcess(command, 128, "", "fatal: index file corrupt")
        return commands(*command, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(cleaner, "run", failing_listing)
    assert cleaner.sweep(execute=True) == []
    out = capsys.readouterr().out
    _assert_kept(repo, path, "feat/unlisted", out, "reading its files failed: git ls-files failed: fatal: index file")


def test_a_failed_copy_keeps_the_worktree_and_its_files(repo, commands, monkeypatch, capsys) -> None:
    path, head = _worktree(repo, "feat/copy")
    _merged(commands, "feat/copy", head)
    _with_ignored_files(path)
    copy_file = cleaner.shutil.copy2
    copied = []

    def copy_once_then_fail(source, target):
        if copied:
            raise OSError(36, "File name too long")
        copied.append(source)
        return copy_file(source, target)

    monkeypatch.setattr(cleaner.shutil, "copy2", copy_once_then_fail)
    assert cleaner.sweep(execute=True) == []
    _assert_kept(repo, path, "feat/copy", capsys.readouterr().out, "copying its ignored files failed")
    assert (path / "data" / "backups" / "rollback.json").read_text() == "keep me\n"


def test_git_refusing_the_removal_keeps_folder_and_branch(repo, commands, monkeypatch, capsys) -> None:
    """A file written after the checks is git's to catch; without --force it refuses."""
    path, head = _worktree(repo, "feat/late")
    _merged(commands, "feat/late", head)
    _with_ignored_files(path)
    copy_out = cleaner.rescue

    def copy_out_then_write(worktree, files, destination):
        copy_out(worktree, files, destination)
        (path / "late.md").write_text("written after the checks\n")

    monkeypatch.setattr(cleaner, "rescue", copy_out_then_write)
    assert cleaner.sweep(execute=True) == []
    out = capsys.readouterr().out
    assert f"FAILED {path}  (#42 merged; branch feat/late): git worktree remove failed:" in out
    assert (path / "late.md").is_file() and _branch_exists(repo, "feat/late")


def test_a_branch_that_cannot_be_deleted_is_reported_not_counted(repo, commands, capsys) -> None:
    path, head = _worktree(repo, "feat/ref")
    _merged(commands, "feat/ref", head)
    (repo / ".git" / "refs" / "heads" / "feat" / "ref.lock").write_text("")
    assert cleaner.sweep(execute=True) == []
    out = capsys.readouterr().out
    assert f"FAILED {path}  (#42 merged; branch feat/ref): folder removed, but git branch -D feat/ref failed" in out
    assert not path.exists() and _branch_exists(repo, "feat/ref")


# --- the checks themselves ---------------------------------------------------------------------------------


def test_a_command_that_cannot_start_reads_as_a_failed_exit() -> None:
    done = REAL_RUN("pitchrank-no-such-command")
    assert done.returncode == -1 and done.stderr.startswith("FileNotFoundError")


def test_gh_answering_something_other_than_json_stops_the_sweep(monkeypatch) -> None:
    page = subprocess.CompletedProcess(("gh",), 0, "<html>rate limited</html>", "")
    monkeypatch.setattr(cleaner, "run", lambda *command, **_: page)
    with pytest.raises(cleaner.SweepRefused, match="answered something other than JSON"):
        cleaner.gh_json("pr", "list")


def test_a_folder_that_cannot_be_read_is_an_error_not_an_empty_folder(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        cleaner.walk(tmp_path / "missing")


def test_the_open_folder_probe_reads_a_refused_rename_as_in_use(tmp_path, monkeypatch) -> None:
    def refuse(*_):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(cleaner, "WINDOWS", True)
    monkeypatch.setattr(cleaner.os, "rename", refuse)
    assert cleaner.in_use(tmp_path) is True


def test_the_open_folder_probe_puts_a_free_folder_back(tmp_path, monkeypatch) -> None:
    folder = tmp_path / "wt"
    folder.mkdir()
    monkeypatch.setattr(cleaner, "WINDOWS", True)
    assert cleaner.in_use(folder) is False
    assert folder.is_dir() and not (tmp_path / "wt.in-use-probe").exists()


@pytest.mark.skipif(os.name != "nt", reason="the probe relies on Windows refusing to rename a folder in use")
def test_the_probe_sees_a_process_running_inside_the_folder(tmp_path) -> None:
    folder = tmp_path / "wt"
    (folder / "sub").mkdir(parents=True)
    script = "import time; print('running', flush=True); time.sleep(60)"
    child = subprocess.Popen([sys.executable, "-c", script], cwd=folder / "sub", stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline() == "running\n"
        assert cleaner.in_use(folder) is True
    finally:
        child.kill()
        child.wait()
    assert cleaner.in_use(folder) is False


def test_an_unreadable_task_list_removes_nothing(repo, commands, monkeypatch, capsys) -> None:
    path, head = _worktree(repo, "feat/done")
    _merged(commands, "feat/done", head)
    monkeypatch.setattr(cleaner, "WINDOWS", True)
    monkeypatch.setattr(sys, "argv", ["clean_merged_worktrees.py", "--execute"])
    commands.schtasks.returncode = 1
    assert cleaner.main() == 1
    assert path.is_dir() and _branch_exists(repo, "feat/done")
    assert "Stopped; nothing further was removed: schtasks failed" in capsys.readouterr().out


def test_a_task_list_with_no_start_in_lines_removes_nothing(repo, commands, monkeypatch) -> None:
    """Every task prints one, so none means the labels changed and protection would silently lapse."""
    path, head = _worktree(repo, "feat/done")
    _merged(commands, "feat/done", head)
    monkeypatch.setattr(cleaner, "WINDOWS", True)
    monkeypatch.setattr(sys, "argv", ["clean_merged_worktrees.py", "--execute"])
    commands.schtasks.stdout = "Startordner:                          C:\\x\n"
    assert cleaner.main() == 1
    assert path.is_dir()


def test_github_failing_for_any_branch_stops_the_sweep_before_it_removes_one(repo, commands, monkeypatch) -> None:
    """Every PR is looked up first, so an outage partway through cannot leave a half-done sweep."""
    first, first_head = _worktree(repo, "feat/aa")
    _merged(commands, "feat/aa", first_head)
    last, last_head = _worktree(repo, "feat/zz")
    _merged(commands, "feat/zz", last_head)
    commands.unreachable = {cleaner.list_worktrees()[1][-1].branch}
    monkeypatch.setattr(sys, "argv", ["clean_merged_worktrees.py", "--execute"])
    assert cleaner.main() == 1
    assert first.is_dir() and last.is_dir()
    assert _branch_exists(repo, "feat/aa") and _branch_exists(repo, "feat/zz")
