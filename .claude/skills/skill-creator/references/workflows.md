# Workflow Design Patterns

## Table of Contents

- [Sequential Workflows](#sequential-workflows)
- [Conditional Branching](#conditional-branching)
- [Iterative Workflows](#iterative-workflows)
- [Error Handling](#error-handling)

## Sequential Workflows

For multi-step processes where order matters, use numbered steps with clear inputs/outputs:

```markdown
## Workflow

1. Collect input (CSV path + column name)
2. Validate input format and existence
3. Process each row: normalize, extract fields, assign IDs
4. Output results as CSV with summary
```

Keep steps action-oriented. Each step should produce a verifiable result before proceeding.

**When to use**: Data pipelines, file transformations, build processes, deployment sequences.

## Conditional Branching

When behavior varies based on context, provide decision criteria:

```markdown
## Approach Selection

Determine the approach based on input:
- **Single file** (<1MB): Process in memory, return inline results
- **Multiple files** or **large file** (>1MB): Use streaming, write output to disk
- **API source**: Fetch with pagination, cache intermediate results
```

Put the decision criteria in SKILL.md. Put variant-specific details in reference files.

## Iterative Workflows

For tasks requiring refinement cycles:

```markdown
## Process

1. Generate initial output
2. Validate against criteria: [list criteria]
3. If validation fails, identify specific issues and regenerate
4. Repeat until criteria met (max 3 iterations)
```

Always set a maximum iteration count to prevent infinite loops.

## Error Handling

Specify error behavior explicitly when it's non-obvious:

```markdown
## Error Handling

- **Missing input file**: Ask user for correct path, do not guess
- **Malformed data**: Skip row, log warning, continue processing
- **API failure**: Retry 3 times with backoff, then report failure with details
```

Only include error handling guidance for non-obvious cases. Claude handles standard errors well without instruction.
