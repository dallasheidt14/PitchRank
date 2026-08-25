"""The two hand-edited Claude Code config files parse, every .mcp.json server
that .claude/settings.json pre-approves is one .mcp.json defines, and the
supabase server stays read-only and project-scoped.

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
