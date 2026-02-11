---
name: skill-creator
description: Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Claude's capabilities with specialized knowledge, workflows, or tool integrations.
---

# Skill Creator

Skills are modular packages that extend Claude's capabilities with specialized knowledge, workflows, and tools. They transform Claude from a general-purpose agent into a specialized one with procedural knowledge no model fully possesses.

## Core Principles

- **Concise is key**: The context window is shared. Only add what Claude doesn't already know. Prefer concise examples over verbose explanations.
- **Match freedom to fragility**: Narrow bridge = specific guardrails (low freedom). Open field = many valid routes (high freedom).
- **Progressive disclosure**: Metadata always loaded (~100 words), SKILL.md body on trigger (<5k words), bundled resources on demand (unlimited).

## Skill Structure

```
skill-name/
├── SKILL.md              (required)
│   ├── YAML frontmatter  (name + description, required)
│   └── Markdown body     (instructions, required)
├── scripts/              (optional - executable code)
├── references/           (optional - docs loaded into context as needed)
└── assets/               (optional - files used in output, not loaded into context)
```

## Creation Process

### Step 1: Understand with Concrete Examples

Ask the user for concrete usage examples. Key questions:
- "What functionality should this skill support?"
- "Can you give examples of how it would be used?"
- "What would a user say that should trigger this skill?"

Skip only if usage patterns are already clearly understood.

### Step 2: Plan Reusable Contents

For each example, identify:
1. What code gets rewritten each time → **scripts/**
2. What boilerplate is needed each time → **assets/**
3. What knowledge must be rediscovered each time → **references/**

### Step 3: Initialize

Run the bundled init script:

```bash
scripts/init_skill.py <skill-name> --path <output-directory>
```

This creates the template directory with SKILL.md and example resource dirs. Skip if updating an existing skill.

### Step 4: Edit the Skill

Start with reusable resources (scripts, references, assets), then update SKILL.md.

**SKILL.md Frontmatter** - Only `name` and `description`:
- `description` is the primary trigger mechanism. Include both what the skill does AND specific triggers/contexts for when to use it.
- All "when to use" info goes in the description, not the body.

**SKILL.md Body** - Use imperative/infinitive form. Keep under 500 lines. For variant-specific details, use reference files with progressive disclosure patterns.

For design patterns on workflows, output formatting, and progressive disclosure, see:
- [references/workflows.md](references/workflows.md) - Sequential workflows and conditional logic
- [references/output-patterns.md](references/output-patterns.md) - Template and example patterns

**Test added scripts** by running them to verify correctness.

### Step 5: Package

```bash
scripts/package_skill.py <path/to/skill-folder> [output-directory]
```

Validates frontmatter, structure, and completeness, then creates a `.skill` zip file. Fix any errors and re-run.

### Step 6: Iterate

Use the skill on real tasks, notice struggles, update SKILL.md or resources, test again.

## What NOT to Include

Never create: README.md, CHANGELOG.md, INSTALLATION_GUIDE.md, QUICK_REFERENCE.md, or other auxiliary docs. Skills are for AI agents, not human onboarding.

## Progressive Disclosure Patterns

**Pattern 1 - References by topic**: Keep core workflow in SKILL.md, link to `references/finance.md`, `references/sales.md`, etc. Claude loads only what's needed.

**Pattern 2 - References by variant**: Keep selection guidance in SKILL.md, link to `references/aws.md`, `references/gcp.md`, etc. Claude loads based on user's choice.

**Pattern 3 - Conditional details**: Show basic usage inline, link to advanced reference files for complex features.

Keep references one level deep from SKILL.md. For files >100 lines, include a table of contents.
