# OpenClaw Agent Model Names Reference

> **Last Updated:** 2026-02-02 by Codey 💻

This document lists the correct model name formats for OpenClaw cron jobs and agent configurations.

## TL;DR - Quick Reference

| Use Case | Model Name | Notes |
|----------|------------|-------|
| **Fast/Cheap tasks** | `anthropic/claude-haiku-4-5` | Daily health checks, simple crons |
| **Standard tasks** | `anthropic/claude-sonnet-4-5` | Knowledge compounding, complex analysis |
| **Best quality** | `anthropic/claude-opus-4-5` | Critical decisions, main agent default |

## Model Name Format

**Format:** `provider/model-name`

Examples:
- ✅ `anthropic/claude-haiku-4-5`
- ✅ `anthropic/claude-sonnet-4-5`
- ✅ `anthropic/claude-opus-4-5`
- ❌ `haiku` (missing provider prefix)
- ❌ `anthropic/haiku` (invalid model name)
- ❌ `claude-3-5-haiku-latest` (missing provider prefix)
- ❌ `anthropic/claude-sonnet-4` (incomplete version)

## Anthropic Models (Valid Names)

### Claude 4.5 Family (Current Gen - Recommended)
- `anthropic/claude-haiku-4-5` - Fast, cheapest
- `anthropic/claude-haiku-4-5-20251001` - Dated version
- `anthropic/claude-sonnet-4-5` - Balanced
- `anthropic/claude-sonnet-4-5-20250929` - Dated version
- `anthropic/claude-opus-4-5` - Best quality (default)
- `anthropic/claude-opus-4-5-20251101` - Dated version

### Claude 4.x Family
- `anthropic/claude-sonnet-4-0`
- `anthropic/claude-sonnet-4-20250514`
- `anthropic/claude-opus-4-0`
- `anthropic/claude-opus-4-1`
- `anthropic/claude-opus-4-1-20250805`
- `anthropic/claude-opus-4-20250514`

### Claude 3.7 Family
- `anthropic/claude-3-7-sonnet-20250219`
- `anthropic/claude-3-7-sonnet-latest`

### Claude 3.5 Family (Legacy)
- `anthropic/claude-3-5-haiku-20241022`
- `anthropic/claude-3-5-haiku-latest`
- `anthropic/claude-3-5-sonnet-20240620`
- `anthropic/claude-3-5-sonnet-20241022`

### Claude 3 Family (Older Legacy)
- `anthropic/claude-3-haiku-20240307`
- `anthropic/claude-3-sonnet-20240229`
- `anthropic/claude-3-opus-20240229`

## PitchRank Cron Model Assignments

All crons now use `anthropic/claude-haiku-4-5` for cost efficiency:

| Cron Job | Model | Rationale |
|----------|-------|-----------|
| Watchy: Health Check | `anthropic/claude-haiku-4-5` | Simple checks, runs daily |
| Cleany: Data Hygiene | `anthropic/claude-haiku-4-5` | Script execution, weekly |
| Ranky: Rankings Calc | `anthropic/claude-haiku-4-5` | Script execution |
| Scrappy: Scrape Monitor | `anthropic/claude-haiku-4-5` | Status checks |
| Scrappy: Future Games | `anthropic/claude-haiku-4-5` | Script execution |
| Movy: Movers Report | `anthropic/claude-haiku-4-5` | Report generation |
| Movy: Weekend Preview | `anthropic/claude-haiku-4-5` | Content generation |
| Socialy: SEO Report | `anthropic/claude-haiku-4-5` | Analysis |
| COMPY: Knowledge Compound | `anthropic/claude-sonnet-4-5` | Complex analysis (upgraded) |

## How to Update a Cron Model

```bash
openclaw cron edit <job-id> --model "anthropic/claude-haiku-4-5"
```

## How to List Available Models

```bash
openclaw models list --all           # Full catalog
openclaw models list --all | grep anthropic  # Anthropic only
openclaw models status               # Current config
```

## Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `Unknown model: anthropic/haiku` | Model name too short | Use `anthropic/claude-haiku-4-5` |
| `Unknown model: anthropic/claude-sonnet-4` | Incomplete version | Use `anthropic/claude-sonnet-4-5` |
| `404` on `claude-3-5-haiku-latest` | Missing provider | Use `anthropic/claude-3-5-haiku-latest` |
| Model not in allowlist | Not configured | Add to `agents.defaults.models` in config |

## Alternative Providers

OpenCode Zen (if configured):
- `opencode/claude-haiku-4-5`
- `opencode/claude-sonnet-4-5`
- `opencode/claude-opus-4-5`

OpenRouter:
- `openrouter/anthropic/claude-haiku-4.5`
- `openrouter/anthropic/claude-sonnet-4.5`
- `openrouter/anthropic/claude-opus-4.5`

## Reference

- OpenClaw Docs: `/Users/pitchrankio-dev/Projects/moltbot/docs/providers/models.md`
- Model Providers: `/Users/pitchrankio-dev/Projects/moltbot/docs/concepts/model-providers.md`
- CLI: `openclaw models --help`
