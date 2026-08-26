"""The two hand-edited Claude Code config files parse, every .mcp.json server
that .claude/settings.json pre-approves is one .mcp.json defines, the supabase
server stays read-only and project-scoped, and the tracked permission allowlist
stays inside the line it was drawn on.

That last one matters because this repo is public. `.claude/settings.json` is
tracked, so anything it allows is pre-approved for every clone, on every machine,
with no prompt. The allowlist deliberately covers verifying a change and never
landing one: an entry that grants a shell or interpreter a free hand, or that
pre-approves `gh pr merge`, hands an agent the whole loop.

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


# A wildcard on any of these is arbitrary code execution wearing one name.
UNBOUNDED = (
    "bash",
    "sh",
    "zsh",
    "eval",
    "exec",
    "ssh",
    "python",
    "python3",
    "node",
    "deno",
    "bun",
    "npx",
    "bunx",
    "uvx",
    "npm run",
    "yarn run",
    "pnpm run",
    "make",
    "gh api",
)


def _allowed() -> list[str]:
    allow = _load(SETTINGS)["permissions"]["allow"]
    assert allow, "settings.json allows nothing; the point is to stop per-machine approvals"
    return allow


def test_allowlist_never_grants_an_interpreter_a_free_hand() -> None:
    for rule in _allowed():
        if not rule.startswith("Bash(") or not rule.endswith("*)"):
            continue
        command = rule[len("Bash(") : -len("*)")].strip()
        for name in UNBOUNDED:
            assert command != name, f"{rule} allows anything {name} can run"


def test_allowlist_stops_short_of_landing_a_change() -> None:
    # pr_wait.py merges, so pre-approving the wrapper pre-approves the merge just
    # as surely as naming `gh pr merge` would.
    for rule in _allowed():
        for lands in ("gh pr merge", "git push origin main", "pr_wait"):
            assert lands not in rule, f"{rule} lets an agent land a change without asking"
