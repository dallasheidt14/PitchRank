# PitchRank Learnings

> Shared knowledge across all agents. Auto-updated by COMPY nightly. Append-only.

## Cross-Agent Insights

### 2026-02-01: Agent Activity and Resilience
Today's session analysis revealed:
- **High engagement**: 656 assistant messages vs 330 user messages shows strong interactivity
- **Error resilience**: Despite 174 API errors, the session continued functioning
- **Tool diversity**: Used 12 different tools showing good capability coverage

**Key insight**: Agents can maintain functionality even under heavy error conditions, but need better error prevention to avoid resource waste.

### 2026-02-02: API Errors Persist, Sub-Agent Coordination Works
- **Error pattern continues**: Main session still hitting 187 errors (auth + credit balance). The API key/billing issue from 2026-01-31 persists.
- **Good pattern**: Scrappy→Codey sub-agent delegation worked well for investigating TGS scrape failure
- **Model config issue**: Watchy's `claude-3-5-haiku-latest` failed (404) - need explicit model versions

## System-Wide Patterns

### 2026-02-02: Agent Role Flexibility
Agents can assume different roles via prompts:
- Movy ran Codey tasks (VCF header fixes)
- Codey ran Ranky tasks (rankings calculation)

This flexibility is good for workload distribution but can confuse session attribution. Consider standardizing cron job naming.

<!-- COMPY will append system patterns here -->

## Integration Learnings

<!-- COMPY will append integration insights here -->

---
*Last updated: 2026-02-01*
