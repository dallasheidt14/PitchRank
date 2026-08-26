"""The two hand-edited Claude Code config files parse, every .mcp.json server
that .claude/settings.json pre-approves is one .mcp.json defines, the supabase
server stays read-only and project-scoped, and the tracked permission allowlist
stays inside the line it was drawn on.

That last one matters because this repo is public. `.claude/settings.json` is
tracked, so anything it allows is pre-approved for every clone, on every machine,
with no prompt.

The line the allowlist holds is that **no entry lets the command string itself
name what gets executed**. `git fetch --upload-pack=<prog>` does, and against a
local path remote it runs that program here, so `git fetch` appears only in exact
form. So does any interpreter or runner given a bare wildcard.

The line it does not hold, and cannot: several entries run code that lives in the
repo, so anything that can write a file into the repo can steer them. `pytest`
collects whatever sits under `tests/`, and `git commit` runs
`frontend/.husky/pre-commit`. That reach comes from being able to write files at
all, not from this list, and dropping the test runner while keeping `git commit`
would only look like a fix. What stays out regardless is the last step: nothing
here merges.

A settings file that fails to parse is dropped — behind a Settings Error dialog
in an interactive session, silently in headless `-p` runs — which unwires every
hook in it; the hook tests exec the scripts by path and would stay green either
way. A pre-approval naming a server .mcp.json does not define is just as quiet:
no prompt appears and the tools are simply absent. Entries Claude Code rejects
individually (an unknown hook event, a malformed matcher) are not covered here;
`claude doctor` lists those.
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS = PROJECT_ROOT / ".claude" / "settings.json"
MCP = PROJECT_ROOT / ".mcp.json"


def _load(path: Path) -> dict:
    # utf-8-sig: Claude Code accepts a BOM, and PowerShell 5.1 writes one by default.
    parsed = json.loads(path.read_text(encoding="utf-8-sig"))
    assert isinstance(parsed, dict), f"{path.name} must be a JSON object"
    return parsed


def test_settings_json_parses_with_hooks() -> None:
    hooks = _load(SETTINGS)["hooks"]
    assert isinstance(hooks, dict) and hooks


def test_mcp_json_parses_with_servers() -> None:
    servers = _load(MCP)["mcpServers"]
    assert isinstance(servers, dict) and servers


def test_pre_approved_servers_exist_in_mcp_json() -> None:
    enabled = _load(SETTINGS)["enabledMcpjsonServers"]
    assert enabled, "settings.json pre-approves no .mcp.json server"
    assert set(enabled) <= set(_load(MCP)["mcpServers"])


def test_supabase_server_stays_read_only_and_project_scoped() -> None:
    args = _load(MCP)["mcpServers"]["supabase"]["args"]
    assert "--read-only" in args
    assert any(arg.startswith("--project-ref=") for arg in args)


# A trailing wildcard lets the caller choose the argument, so it is only safe on a
# command that cannot be made to execute what it is handed. ruff reads Python and
# never runs it; git and gh act on the repo and the API, and the guard hook covers
# their destructive verbs. `python -m pytest <any path>` runs that path, and eslint
# and prettier execute the config they are pointed at, so those keep exact forms.
WILDCARD_OK = {
    "git add",
    "git commit",
    "git checkout",
    "git switch",
    "git stash push",
    "git stash pop",
    "git stash show",
    # Not bare `git stash`: `clear` and `drop` delete saved WIP with no undo,
    # and the guard hook does not look at stash at all.
    "git worktree",
    "git push origin",
    # Not `git fetch`: `--upload-pack=` names a program git then runs, and against
    # a local path remote it runs it here. `git push origin` escapes the same trap
    # only because `--receive-pack=` has to precede the remote to take effect.
    "gh pr create",
    "gh pr edit",
    "gh pr comment",
    "python -m ruff check",
    "python -m ruff format --diff",
}


def _allowed() -> list[str]:
    allow = _load(SETTINGS)["permissions"]["allow"]
    assert allow, "settings.json allows nothing; the point is to stop per-machine approvals"
    return allow


def test_a_wildcard_never_reaches_a_command_that_runs_its_argument() -> None:
    for rule in _allowed():
        if not rule.startswith("Bash(") or not rule.endswith("*)"):
            continue
        command = rule[len("Bash(") : -len("*)")].strip()
        assert command in WILDCARD_OK, f"{rule} lets the caller pick what {command} runs"


def test_allowlist_stops_short_of_landing_a_change() -> None:
    # pr_wait.py merges, so pre-approving the wrapper pre-approves the merge just
    # as surely as naming `gh pr merge` would.
    for rule in _allowed():
        for lands in ("gh pr merge", "git push origin main", "pr_wait"):
            assert lands not in rule, f"{rule} lets an agent land a change without asking"
