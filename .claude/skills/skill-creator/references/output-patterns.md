# Output Design Patterns

## Table of Contents

- [Template Pattern](#template-pattern)
- [Example-Driven Pattern](#example-driven-pattern)
- [Schema Pattern](#schema-pattern)
- [Combining Patterns](#combining-patterns)

## Template Pattern

Provide a literal template when output format must be exact:

```markdown
## Output Format

Return a CSV with these columns:
original,normalized,confidence,notes

- `original`: Input string unchanged
- `normalized`: Cleaned and standardized value
- `confidence`: Float 0.0-1.0
- `notes`: Empty unless action needed
```

**When to use**: CSV/JSON output, API responses, structured reports, file generation where format is rigid.

## Example-Driven Pattern

Show input/output pairs when the transformation logic is complex:

```markdown
## Examples

Input: "FC Dallas 2012B ECNL"
Output: club_id=fc-dallas, birth_year=2012, gender=boys, tier=ecnl

Input: "Solar SC G14 Premier"
Output: club_id=solar-sc, birth_year=2010, gender=girls, tier=premier
```

Provide 2-4 examples covering distinct cases. Avoid redundant examples that test the same logic.

**When to use**: Name normalization, data transformation, classification tasks, any mapping where rules are easier shown than described.

## Schema Pattern

Define the data structure when output is programmatic:

```markdown
## Output Schema

```json
{
  "status": "success" | "error",
  "results": [
    {
      "input": "string",
      "output": "string",
      "confidence": "number (0-1)"
    }
  ],
  "summary": {
    "total": "number",
    "processed": "number",
    "skipped": "number"
  }
}
```

**When to use**: API responses, configuration files, structured data exchange.

## Combining Patterns

For complex outputs, combine patterns:

1. **Schema** for structure definition
2. **Template** for exact formatting requirements
3. **Examples** for edge cases and nuance

Place the primary pattern in SKILL.md. Move extended examples to a reference file if they exceed 20 lines.
