# Learnings Template

Reference for COMPY when extracting and documenting learnings.

## Learning Entry Format

```markdown
### {Date} - {Category}

**Context:** {What was being done}
**Discovery:** {What was learned}
**Impact:** {How this affects future work}
**Applied to:** {Which agent/skill was updated}
```

## Categories

### 🔧 Technical
- Model configuration
- API patterns
- Database queries
- Script improvements

### 📊 Data
- Quality patterns
- Edge cases
- Normalization rules
- Validation gotchas

### 🤖 Agent Behavior
- Task patterns
- Failure modes
- Coordination patterns
- Escalation rules

### 🚀 Performance
- Optimization tips
- Cost savings
- Token efficiency
- Speed improvements

## Where to Write Learnings

| Category | File |
|----------|------|
| Agent-specific | `.claude/skills/{agent}-learnings.skill.md` |
| Cross-agent | `docs/LEARNINGS.md` |
| Common pitfalls | `docs/GOTCHAS.md` |
| Proven solutions | `docs/PATTERNS.md` |

## Example Entry

```markdown
### 2026-02-02 - Technical

**Context:** Watchy health check failed with model 404
**Discovery:** Model names must be fully qualified: `anthropic/claude-haiku-4-5` not just `haiku`
**Impact:** All cron jobs need explicit model names
**Applied to:** Updated all crons, documented in AGENT_MODELS.md
```

## Review Checklist

When analyzing sessions, look for:
- [ ] Errors that were fixed (document the fix)
- [ ] Patterns that worked well (document for reuse)
- [ ] Time wasted on wrong approaches (document to avoid)
- [ ] New conventions established (document for consistency)
- [ ] Edge cases discovered (document for handling)

## Append-Only Rule
**NEVER delete existing learnings.** Only append new entries with dates. Old learnings remain valuable for context.
