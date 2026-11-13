#!/usr/bin/env python3
"""Remove the worktrees whose pull request has merged, with their local branches.

"Its PR merged" is not enough to make a worktree safe to remove:

* The branch head must be the PR's head when it merged. main takes squash merges, so a
  merged branch is never an ancestor of main and `git branch -d` cannot tell
  whether its work landed. The PR's recorded head commit can.
* It must hold no tracked change and no untracked file: those exist nowhere else.
  Nor may another worktree sit inside it, where an ignore rule hides it from both
  checks and the removal would take it too.
* `git worktree remove` deletes ignored files with the folder, and an ignored file
  is sometimes the only copy of a rollback log. They are copied to the main
  checkout's data/backups/worktree-rescue/ first; caches, dependencies and .env
  copies are not.
* On Windows git deletes through a junction into the folder it points at, and a
  worktree's frontend/node_modules is often a junction into the main checkout's.
  Every folder link inside is unlinked first, which leaves its target alone.
* Windows refuses to delete a folder a process is running in or has a file open
  in, and git deregisters the worktree before it finds that out, leaving a
  half-deleted folder. So such a folder stays, as do this shell's working folder
  and a scheduled task's Start In; the next run removes it once nothing holds it.

A worktree whose branch never had a PR is listed, never removed: that is
unfinished work, not a leftover.

Usage:
    python scripts/clean_merged_worktrees.py            # dry run: list what would go
    python scripts/clean_merged_worktrees.py --execute

Exit status: 0 the sweep ran, whatever it kept; 1 it could not safely go on (a
check every removal depends on could not run, or a probe left a folder renamed),
so it stopped and removed nothing further.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WINDOWS = os.name == "nt"
# Windows refuses paths past 260 characters without it unless long paths are enabled machine-wide.
LONG_PATH_PREFIX = "\\\\?\\" if os.name == "nt" else ""
COMMAND_TIMEOUT_SECONDS = 120
REMOVE_TIMEOUT_SECONDS = 900
GH_LOOKUPS_AT_ONCE = 8
RESCUE_DIR = Path("data") / "backups" / "worktree-rescue"

# Rebuilt by an install, a build or a test run, or a copy of a secret the main checkout holds.
DISPOSABLE_DIRS = frozenset(
    {"node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".next", ".vite"}
)
DISPOSABLE_NAMES = frozenset({".env", ".env.local"})
DISPOSABLE_SUFFIXES = (".pyc", ".tsbuildinfo")

KEPT_FOR_STATE = {
    "detached": "detached",
    "locked": "locked",
    "prunable": "folder missing (git worktree prune clears the entry)",
    "open": "PR still open",
    "closed": "PR closed without merging",
    "none": "no PR",
    "other-head": "branch head differs from the merged PR's head",
}
HELD_BY_THIS_SHELL = "this shell's working folder is inside it"
HELD_BY_A_PROCESS = "a process is running in it or has a file in it open"


class SweepRefused(RuntimeError):
    """The sweep cannot safely go on: a check every removal needs could not run, or a probe left a folder renamed."""


@dataclass(frozen=True)
class Worktree:
    path: Path
    head: str
    branch: str | None
    locked: bool = False
    prunable: bool = False


def run(*command: str, cwd: Path | None = None, timeout: int = COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    """A command that cannot start or finish comes back as a failed exit, so every caller's exit check covers it."""
    try:
        return subprocess.run(
            list(command), cwd=cwd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(list(command), -1, "", f"{type(exc).__name__}: {exc}")


def git(*args: str, cwd: Path, timeout: int = COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    """--no-optional-locks keeps `git status` from rewriting the index, which a dry run must not do."""
    return run("git", "--no-optional-locks", "-c", "core.longpaths=true", *args, cwd=cwd, timeout=timeout)


def gh_json(*args: str):
    done = run("gh", *args)
    if done.returncode != 0:
        raise SweepRefused(f"gh {' '.join(args)} failed: {done.stderr.strip()}")
    try:
        return json.loads(done.stdout or "null")
    except ValueError as exc:
        raise SweepRefused(f"gh {' '.join(args)} answered something other than JSON: {exc}") from None


def list_worktrees() -> tuple[Path, list[Worktree]]:
    """The main checkout, which the porcelain always lists first, and every linked worktree."""
    done = git("worktree", "list", "--porcelain", cwd=ROOT)
    if done.returncode != 0:
        raise SweepRefused(f"git worktree list failed: {done.stderr.strip()}")
    worktrees, fields = [], {}
    for line in [*done.stdout.splitlines(), ""]:
        if line:
            key, _, value = line.partition(" ")
            fields[key] = value
            continue
        if "worktree" in fields:
            branch = fields.get("branch")
            worktrees.append(
                Worktree(
                    path=Path(fields["worktree"]),
                    head=fields.get("HEAD", ""),
                    branch=branch.removeprefix("refs/heads/") if branch else None,
                    locked="locked" in fields,
                    prunable="prunable" in fields,
                )
            )
        fields = {}
    if not worktrees:
        raise SweepRefused("git worktree list named no main checkout")
    return worktrees[0].path, worktrees[1:]


def pr_state(worktree: Worktree) -> tuple[str, dict | None]:
    """The worktree's state, "merged" or a KEPT_FOR_STATE key, with the PR that decided it.

    An open PR wins: the branch is still in review, whatever an earlier PR from it did.
    """
    if worktree.branch is None:
        return "detached", None
    if worktree.locked:
        return "locked", None
    if worktree.prunable:
        return "prunable", None
    prs = gh_json(
        "pr", "list", "--state", "all", "--head", worktree.branch, "--limit", "100", "--json", "number,state,headRefOid"
    )
    by_state = {state: [pr for pr in prs if pr["state"] == state] for state in ("OPEN", "MERGED", "CLOSED")}
    if by_state["OPEN"]:
        return "open", by_state["OPEN"][0]
    for pr in by_state["MERGED"]:
        if pr["headRefOid"] == worktree.head:
            return "merged", pr
    if by_state["MERGED"]:
        return "other-head", by_state["MERGED"][0]
    if by_state["CLOSED"]:
        return "closed", by_state["CLOSED"][0]
    return "none", None


def scheduled_task_folders() -> list[Path]:
    """Every scheduled task's Start In folder. Windows only; empty elsewhere.

    Every task prints a Start In line, N/A included, so finding none means the
    query or its English labels changed, and a folder a task runs in would go
    unprotected.
    """
    if not WINDOWS:
        return []
    done = run("schtasks", "/query", "/fo", "LIST", "/v")
    if done.returncode != 0:
        raise SweepRefused(f"schtasks failed: {done.stderr.strip()}")
    values = [line.split(":", 1)[1].strip() for line in done.stdout.splitlines() if line.startswith("Start In:")]
    if not values:
        raise SweepRefused("schtasks listed no Start In folders, so scheduled tasks' folders cannot be protected")
    return [Path(value) for value in values if value not in ("N/A", "Multiple actions")]


def is_within(path: Path, folder: Path) -> bool:
    return Path(os.path.realpath(path)).is_relative_to(os.path.realpath(folder))


def in_use(path: Path) -> bool:
    """Whether a process is running inside the folder or has a file in it open. Windows only; False elsewhere.

    Windows refuses to rename a folder in either case, and renaming it back leaves
    no trace. An editor merely watching the folder does not count.
    """
    if not WINDOWS:
        return False
    probe = path.with_name(path.name + ".in-use-probe")
    try:
        os.rename(path, probe)
    except OSError:
        return True
    try:
        os.rename(probe, path)
    except OSError as exc:
        raise SweepRefused(f"{path} was left at {probe} ({exc}); rename it back before running again") from None
    return False


def keep_reason(
    worktree: Worktree, state: str, pr: dict | None, others: list[Path], scheduled: list[Path], execute: bool
) -> str | None:
    if state != "merged":
        return KEPT_FOR_STATE[state]
    if git("rev-parse", "HEAD", cwd=worktree.path).stdout.strip() != pr["headRefOid"]:
        return "HEAD no longer matches the merged PR's head"
    status = git("status", "--porcelain", "--untracked-files=normal", cwd=worktree.path)
    if status.returncode != 0:
        return f"git status failed: {status.stderr.strip()}"
    if status.stdout.strip():
        return "uncommitted changes or untracked files"
    if any(is_within(other, worktree.path) for other in others):
        return "another worktree is inside it"
    if any(is_within(folder, worktree.path) for folder in scheduled):
        return "a scheduled task runs in this folder"
    if is_within(Path.cwd(), worktree.path):
        return HELD_BY_THIS_SHELL
    if execute and in_use(worktree.path):
        return HELD_BY_A_PROCESS
    return None


def native(path: Path) -> str:
    return LONG_PATH_PREFIX + os.path.abspath(path)


def is_link(path: str) -> bool:
    """A symlink, or any Windows reparse point such as a junction, which os.path.islink does not report."""
    info = os.lstat(path)
    reparse_point = getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    return stat.S_ISLNK(info.st_mode) or bool(reparse_point)


def walk(top: Path, skip: frozenset[str] = frozenset()) -> tuple[list[Path], list[Path]]:
    """Every file under top and every folder link, relative to top, never entering a link or a skipped folder.

    os.walk enters junctions and passes over a folder it cannot read in silence, so
    links are pruned here and a read error is raised: a file missed here would be
    deleted without a copy.
    """
    root = native(top)
    files, links = [], []

    def refuse(exc: OSError) -> None:
        raise exc

    for folder, subfolders, names in os.walk(root, onerror=refuse):
        here = Path(os.path.relpath(folder, root))
        entering = []
        for name in subfolders:
            if is_link(os.path.join(folder, name)):
                links.append(here / name)
            elif name not in skip:
                entering.append(name)
        subfolders[:] = entering
        files.extend(here / name for name in names)
    return files, links


def is_disposable(relative: Path) -> bool:
    return (
        any(part in DISPOSABLE_DIRS for part in relative.parts)
        or relative.name in DISPOSABLE_NAMES
        or relative.name.endswith(DISPOSABLE_SUFFIXES)
    )


def ignored_to_rescue(worktree: Worktree) -> list[Path]:
    """The ignored files `git worktree remove` would delete, minus caches, dependencies and secret copies.

    `--directory` keeps a wholly ignored folder as one entry, so node_modules is
    dropped by name rather than walked file by file. It can also list a folder and
    a folder inside it (`data/` and `data/backups/`), so the walks overlap. A link
    is not followed: what it points at lives elsewhere and survives the removal.
    """
    done = git("ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory", cwd=worktree.path)
    if done.returncode != 0:
        raise OSError(f"git ls-files failed: {done.stderr.strip()}")
    files = set()
    for entry in filter(None, done.stdout.split("\0")):
        relative = Path(entry)
        absolute = native(worktree.path / relative)
        if is_disposable(relative) or is_link(absolute):
            continue
        if not os.path.isdir(absolute):
            files.add(relative)
            continue
        found, _ = walk(worktree.path / relative, skip=DISPOSABLE_DIRS)
        files.update(relative / name for name in found if not is_disposable(relative / name))
    return sorted(files)


def rescue_folder(main_root: Path, branch: str) -> Path:
    """Keyed by branch, since folder names repeat; a second rescue the same day takes the next free name."""
    base = main_root / RESCUE_DIR / f"{dt.date.today():%Y-%m-%d}_{branch.replace('/', '-')}"
    folder, attempt = base, 1
    while folder.exists():
        attempt += 1
        folder = base.with_name(f"{base.name}-{attempt}")
    return folder


def rescue(worktree: Worktree, files: list[Path], destination: Path) -> None:
    for relative in files:
        target = native(destination / relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(native(worktree.path / relative), target)


def unlink(link: str) -> None:
    """Remove the link alone. Windows removes a junction or folder symlink with rmdir, which keeps the target."""
    if os.name == "nt":
        os.rmdir(link)
    else:
        os.unlink(link)


def remove(worktree: Worktree, links: list[Path], main_root: Path) -> str | None:
    """Why it stopped, or None.

    No --force, so git's own check for local changes stands behind keep_reason's.
    A squash-merged branch is not an ancestor of main, so -d would refuse it.
    """
    for link in links:
        try:
            unlink(native(worktree.path / link))
        except OSError as exc:
            return f"unlinking {link} failed: {exc}"
    done = git("worktree", "remove", str(worktree.path), cwd=main_root, timeout=REMOVE_TIMEOUT_SECONDS)
    if done.returncode != 0:
        return f"git worktree remove failed: {done.stderr.strip()}"
    done = git("branch", "-D", worktree.branch, cwd=main_root)
    if done.returncode != 0:
        return f"folder removed, but git branch -D {worktree.branch} failed: {done.stderr.strip()}"
    return None


def unmerged_summary(worktree: Worktree, main_root: Path) -> str:
    ahead = git("rev-list", "--count", f"origin/main..{worktree.head}", cwd=main_root).stdout.strip() or "?"
    age = git("log", "-1", "--format=%cr", worktree.head, cwd=main_root).stdout.strip() or "?"
    return f"{ahead} commit(s) not on main, last commit {age}"


def size_text(worktree: Worktree, files: list[Path]) -> str:
    total = sum(os.stat(native(worktree.path / relative)).st_size for relative in files)
    return f"{len(files)} ignored file(s), {total / 1_000_000:.1f} MB"


def sweep(execute: bool, show_others: bool = True) -> list[Path]:
    """Remove every merged worktree it is safe to remove; returns those removed, or in a dry run those it would.

    Every PR is looked up before anything is removed, so a GitHub failure stops
    the sweep with nothing removed rather than part way through.
    """
    main_root, worktrees = list_worktrees()
    scheduled = scheduled_task_folders()
    retry = "python scripts/clean_merged_worktrees.py" + (" --execute" if execute else "")
    with ThreadPoolExecutor(max_workers=GH_LOOKUPS_AT_ONCE) as pool:
        states = list(pool.map(pr_state, worktrees))
    every_path = [main_root, *(worktree.path for worktree in worktrees)]
    removed, kept, failed = [], [], 0
    for worktree, (state, pr) in zip(worktrees, states):
        others = [path for path in every_path if path != worktree.path]
        reason = keep_reason(worktree, state, pr, others, scheduled, execute)
        if reason is None:
            try:
                files = ignored_to_rescue(worktree)
                _, links = walk(worktree.path)
                copied = size_text(worktree, files)
            except OSError as exc:
                reason = f"reading its files failed: {exc}"
        if reason is not None:
            kept.append((worktree, state, pr, reason))
            continue

        destination = rescue_folder(main_root, worktree.branch)
        merged = f"#{pr['number']} merged; branch {worktree.branch}"
        linked = ", ".join(link.as_posix() for link in links)
        if not execute:
            removed.append(worktree.path)
            print(f"  would remove {worktree.path}  ({merged})")
            if files:
                print(f"    would copy {copied} to {destination}")
            if links:
                print(f"    would unlink {len(links)} folder link(s) first, keeping their targets: {linked}")
            continue
        if files:
            try:
                rescue(worktree, files, destination)
            except OSError as exc:
                kept.append((worktree, state, pr, f"copying its ignored files failed: {exc}"))
                continue
            print(f"  copied {copied} from {worktree.path} to {destination}")
        failure = remove(worktree, links, main_root)
        if failure:
            failed += 1
            print(f"  FAILED {worktree.path}  ({merged}): {failure}")
            continue
        removed.append(worktree.path)
        print(f"  removed {worktree.path}  ({merged})" + (f"; unlinked {linked}" if links else ""))

    for worktree, state, pr, reason in kept:
        if not (show_others or state == "merged"):
            continue
        detail = f"; {unmerged_summary(worktree, main_root)}" if state in ("none", "closed") else ""
        number = f"#{pr['number']} " if pr else ""
        print(f"  kept {worktree.path}  ({number}{reason}{detail})")
        if reason in (HELD_BY_THIS_SHELL, HELD_BY_A_PROCESS):
            print(f"    once nothing has it open, run from {main_root}: {retry}")

    verb = "Removed" if execute else "Would remove"
    print(f"{verb} {len(removed)} merged worktree(s); kept {len(kept)}" + (f"; {failed} failed" if failed else ""))
    if not execute:
        print(
            "\nDRY RUN — nothing written. Re-run with --execute."
            "\nA folder a process holds open is only found, and kept, at --execute time."
        )
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--execute", action="store_true", help="remove them (default is a dry run)")
    args = parser.parse_args()
    try:
        sweep(args.execute)
    except SweepRefused as exc:
        print(f"Stopped; nothing further was removed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
