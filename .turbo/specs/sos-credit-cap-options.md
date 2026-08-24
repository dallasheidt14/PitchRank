---
status: design-options
---

# Engine-Native SOS-Credit Cap — Design Options (scope only, no code)

## Problem (from the manual audit, 2026-06-23)

The published board over-rewards strength-of-schedule. Two symptoms, one root:

- **Over-ranked:** mediocre-record teams on brutal schedules sit in the top 10 — Strikers FC (53% wins, 0.98 SOS) #4, TSF (52%) #5, Cedar Stars (57%) #6; San Diego Surf #5, Utah Royals #6 (u17F).
- **Under-ranked:** strong-record teams on *lower* SOS are buried — SOLAR (90% wins, 0.97 SOS) #20, 2009 GA (86% wins, 0.50 SOS) #25, De Anza (67%) #70, Michigan Wolves (53%) #84.

The SCF divisor sweep failed because it works the wrong axis (schedule *diversity*, not SOS *magnitude*): it only demoted the one regionally-isolated team (SC Del Sol) and pushed the strong-but-low-SOS teams further down.

## Where SOS enters the published score today

1. **Core Glicko `mu`** — opponent quality is baked into the rating: a competitive loss to an elite team barely dents `mu`, an upset win lifts it a lot. This is the dominant SOS channel and the root of the over-ranking.
2. **`SOS_ADJ`** (`src/etl/glicko_engine.py:1734-1744`) — an isolated post-`mu` rescale `mu_sos = 1500 + (mu-1500)·sos_scale`, `sos_scale = 1 + 3%·strong − 16%·weak`, clipped to [0.84, 1.03]. Today it *rewards* high SOS (+3%) and *penalizes* low SOS (−16%).
3. Downstream of `mu_sos`: evidence-shrink → `powerscore_core` (normalized) → `powerscore_adj` (×provisional) → publication caps → ML → `power_score_true` → `rank_in_cohort_final`.

Record signals available at every hook: `win_percentage`, `wins/games_played`, `off_norm`/`def_norm` (goal-based offense/defense).

## The unifying design principle (solves BOTH cases)

**Cap *SOS-credit*, defined as the portion of a team's published score that exceeds what its own record justifies — and gate the cap on record, never on SOS alone.** This is what makes it safe:

- It only reduces teams whose score is *SOS-inflated* (mediocre record + high SOS) → Strikers drops.
- It never reduces a team whose score is *record-justified* (strong record) → SOLAR / 2009 GA / De Anza are untouched, and they rise *relatively* as the inflated teams fall.
- Gating on record (not "high SOS") protects the genuine elite that legitimately have both (Total Futbol 80%/0.99, ALBION LA 63%/0.98) — their score is record-backed, so there's little SOS-credit to cap.

Every option below is a variant of "limit SOS-credit, conditioned on record." They differ in *where* they hook and *how blunt* they are.

---

## Option 1 — Record-conditional `SOS_ADJ` (smallest; reuses the existing knob)

- **Hook:** the existing `SOS_ADJ` block, `glicko_engine.py:1734-1744`. No new pipeline stage.
- **What it caps:** the +3% high-SOS *reward*. Replace the unconditional `strong` reward with a record-gated term: high SOS only rewards `mu` when the record is also strong; for a mediocre record + high SOS, flip it to a mild *penalty*. Optionally relax the −16% weak penalty for strong-record teams so low-SOS winners aren't shrunk.
- **Why it should help:** directly turns "brutal schedule" from a tailwind into a neutral/headwind for mediocre teams, and stops punishing strong low-SOS teams.
- **Risks / side effects:** `SOS_ADJ` is a *small* lever (±3–16% of `mu−1500`). The bulk of Strikers' rank comes from the **core `mu`**, not this +3% — so this alone is likely **too weak** to move #4→35–50 without widening the band, and widening it risks broad collateral movement. Smallest change, but may not be sufficient on its own.
- **Validation:** rebuild offline (8.0-style harness), run the ground-truth scorer (`audit_ground_truth.py`); require over-ranked teams move toward targets and elite not pushed down. Cheap, but expect a partial result.

## Option 2 — Record-gated SOS-credit cap as a new post-`mu` shaping step (recommended sweet spot)

- **Hook:** immediately after `powerscore_core` is formed (`glicko_engine.py:~1756`), before `provisional_mult`/ranking. A new, isolated function `apply_sos_credit_cap(team_df, cfg)`.
- **What it caps:** the gap between a team's score and a **record-expected score**. Compute `record_score` from the team's own results (win% + goal-diff / `off_norm`,`def_norm`), then `capped = min(powerscore_core, record_score + SOS_CREDIT_MAX·f(record))`, where `f(record)` shrinks the allowed SOS bonus as the record weakens. Strong records keep full credit; mediocre records get little.
- **Why it should help:** this is the *most targeted* expression of the principle — it explicitly limits "how far above your record SOS can carry you." Strikers (score ≫ record-justified) is pulled to ~record level (→ 35–50); 2009 GA / SOLAR (score ≈ record-justified, low SOS bonus) are untouched and rise as inflated teams fall; Total Futbol (record-justified) is untouched.
- **Risks / side effects:** requires defining `record_score` (choice of win% vs goal-diff vs the existing `off_norm`/`def_norm`) and calibrating `SOS_CREDIT_MAX` + the record-gate curve; a poorly-set curve could over-flatten the top (compressing genuine separation) or under-correct. It's a new stage (more surface than Option 1) but fully isolated and reversible behind a flag.
- **Validation:** same harness + ground-truth scorer as the primary gate; plus the bubble guardrail + losing-in-top-decile + the prediction backtest to confirm it doesn't wreck calibration; tune `SOS_CREDIT_MAX` to the lowest value that clears the ground truth.

## Option 3 — Record-gated publication cap (reuses the existing cap layer; symptom-level)

- **Hook:** the existing publication-cap / same-age evidence-gate machinery (`src/rankings/calculator.py`, the `publication_cap_rank` path) that already floors some teams' published rank.
- **What it caps:** the published *rank* directly — add a rule that assigns a rank floor to a team that is ranked high **and** has a mediocre record **and** whose high standing is SOS-driven (high `sos_norm`, score ≫ record-expected).
- **Why it should help:** acts straight on the visible symptom (a team can't be published in the top-N on a mediocre record + SOS alone), and reuses infrastructure rather than adding a scoring stage.
- **Risks / side effects:** rank-flooring is blunter than score-shaping — it can create visible "stuck at rank N" artifacts and interacts with the existing evidence-gate logic (must not double-penalize or fight the SCF/evidence caps); harder to make smooth. Caps the symptom, not the score, so two capped teams can tie awkwardly.
- **Validation:** same harness + ground-truth scorer; additionally diff against the current publication-cap behavior to ensure no regression in the cases it already handles.

## Option 4 — Reduce core-`mu` SOS credit (root cause; largest, last resort)

- **Hook:** the core Glicko update / game-outcome scoring (opponent-quality credit), `glicko_engine.py` `compute_sos`/the rating update.
- **What it caps:** how much a competitive-but-losing result vs a strong opponent inflates `mu` in the first place.
- **Why it should help:** addresses the root (the dominant SOS channel) rather than shaping it afterward.
- **Risks / side effects:** **highest.** `mu` feeds everything — SOS itself, cross-age anchors, ML, prediction. A global change is hard to target to the pathology, likely over-corrects, and would need the full prediction backtest to clear. Reserve for if post-`mu` shaping (Options 1–3) can't get there.
- **Validation:** full unit suite + the prediction backtest (mu change moves accuracy/log-loss) in addition to the ground-truth scorer.

---

## Recommendation

Lead with **Option 2** (record-gated SOS-credit cap, post-`mu`): it is the most direct expression of the principle, isolated/reversible behind a flag, and the only one that cleanly fixes both symptoms without touching strong-record teams. Try **Option 1** first as a cheap probe (it may partially help and is one-block), but expect it to be too weak alone because the over-ranking lives in the core `mu`. Keep **Option 3** as a complementary symptom-level guard and **Option 4** as the last resort. Validate every option against the **same manual-audit ground truth** (`data/staging/audit_ground_truth.json` + `audit_ground_truth.py`: the 23-team u16M/u17F pass/fail, must beat prod's 7/23 by dropping the over-ranked and lifting the under-ranked elite), plus the bubble guardrail and the prediction backtest as guardrails.
