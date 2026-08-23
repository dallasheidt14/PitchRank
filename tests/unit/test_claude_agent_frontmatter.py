"""Every agent definition under .claude/agents parses as a registrable agent
and preloads only skills that exist.

Claude Code silently skips an agent file whose frontmatter is absent or
malformed — the parse error reaches only the debug log — so nothing else
reports the omission. A `skills:` entry naming a missing directory is just as
quiet: the agent still registers and simply preloads nothing.
"""

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = PROJECT_ROOT / ".claude" / "agents"
SKILLS_DIR = PROJECT_ROOT / ".claude" / "skills"
AGENTS = sorted(AGENTS_DIR.rglob("*.md"))


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name} must start with YAML frontmatter"
    block = text.split("---", 2)[1]
    parsed = yaml.safe_load(block)
    assert isinstance(parsed, dict), f"{path.name} frontmatter must be a YAML mapping"
    return parsed


def test_agents_directory_is_not_empty() -> None:
    assert AGENTS


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: str(p.relative_to(AGENTS_DIR)))
def test_agent_frontmatter_is_registrable(path: Path) -> None:
    parsed = _frontmatter(path)
    for key in ("name", "description"):
        assert parsed.get(key), f"{path.name} frontmatter must define {key}"


def test_some_agent_preloads_skills() -> None:
    assert any(_frontmatter(path).get("skills") for path in AGENTS)


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: str(p.relative_to(AGENTS_DIR)))
def test_agent_skills_resolve(path: Path) -> None:
    skills = _frontmatter(path).get("skills") or []
    assert isinstance(skills, list), f"{path.name} skills frontmatter must be a YAML list"
    for name in skills:
        skill = SKILLS_DIR / name / "SKILL.md"
        assert skill.is_file(), f"{path.name} preloads skill {name!r} but {skill} does not exist"
