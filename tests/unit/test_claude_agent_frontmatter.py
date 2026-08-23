"""Every agent definition under .claude/agents parses as a registrable agent.

Claude Code silently skips an agent file whose frontmatter is absent or
malformed — the parse error reaches only the debug log — so nothing else
reports the omission.
"""

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENTS = sorted((PROJECT_ROOT / ".claude" / "agents").rglob("*.md"))


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name} must start with YAML frontmatter"
    block = text.split("---", 2)[1]
    parsed = yaml.safe_load(block)
    assert isinstance(parsed, dict), f"{path.name} frontmatter must be a YAML mapping"
    return parsed


def test_agents_directory_is_not_empty() -> None:
    assert AGENTS


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: str(p.relative_to(PROJECT_ROOT / ".claude" / "agents")))
def test_agent_frontmatter_is_registrable(path: Path) -> None:
    parsed = _frontmatter(path)
    for key in ("name", "description"):
        assert parsed.get(key), f"{path.name} frontmatter must define {key}"
