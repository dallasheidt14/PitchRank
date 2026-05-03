"""Detect each division's playoff format from actual played games.

Backtest-mode invariant: simulated playoff structure must mirror what the
tournament actually used. Without ground-truth stage labels in the
schedule HTML (gotsport doesn't include them for many events), we infer
the format from three signals:

1. **Pool assignments** (``intake/pool_assignments.json``) — team -> pool
   membership within each division.
2. **Standings** (``intake/standings.jsonl``) — pool play finishing rank
   per team (rank=1 within Pool A is "1A", etc.).
3. **Game results** (``intake/game_results.jsonl``) — every played game.

Algorithm:

- Classify each intra-division game as POOL_PLAY (both teams same pool)
  or CROSSOVER (different pools).
- For each crossover game, identify the seed pairing (e.g. "1A vs 1B",
  "2A vs 2B", "1A vs 2B") via standings rank lookups.
- Map the set of crossover seed pairings to a known template:

  * ``POOL_ONLY``: zero crossover games (pool play decides everything).
  * ``F_ONLY``: single 1A-vs-1B game.
  * ``F_3P``: final + 3rd-place crossover (1A-vs-1B and 2A-vs-2B).
  * ``POOL_CROSSOVER``: 4 cross-pool games — 1A-vs-1B, 2A-vs-2B,
    3A-vs-3B, 4A-vs-4B (this is your U14 Boys Red format).
  * ``SF_F``: semis + final (1A-vs-2B, 1B-vs-2A, then winners' final).
  * ``SF_F_3P``: semis + final + 3rd-place.
  * ``QF_SF_F``: quarters + semis + final (top-4 from each pool advance).
  * ``CUSTOM``: pattern doesn't match any known template — operator
    review required, simulator falls back to single round-robin.

Output is the per-division template string, written to the
``DivisionStructure.advancement`` field so the structure spec carries
authoritative format info downstream to the simulator.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

__all__ = [
    "PLAYOFF_TEMPLATES",
    "detect_division_playoff_format",
    "detect_playoff_formats_for_event",
]


# Canonical template names. Some map directly to existing simulator
# templates; POOL_CROSSOVER is a new template the simulator needs taught.
PLAYOFF_TEMPLATES: tuple[str, ...] = (
    "POOL_ONLY",
    "F_ONLY",
    "F_3P",
    "POOL_CROSSOVER",
    "SF_F",
    "SF_F_3P",
    "QF_SF_F",
    "CUSTOM",
)


def _normalize_seed_pairing(home_seed: tuple[int, str], away_seed: tuple[int, str]) -> tuple:
    """Canonical hashable form: sorted by (rank, pool_label) so the same
    pairing produces the same key regardless of home/away order."""
    return tuple(sorted([home_seed, away_seed]))


def _classify_crossover_pattern(seed_pairings: set[tuple]) -> str:
    """Map the set of observed crossover seed-pairings to a template."""
    if not seed_pairings:
        return "POOL_ONLY"

    # Convert each pairing's seeds back to "rank+pool" notation for matching
    def pair_str(pairing: tuple) -> str:
        return ",".join(f"{rank}{pool}" for rank, pool in pairing)

    pair_set = {pair_str(p) for p in seed_pairings}

    # POOL_CROSSOVER: 1A-vs-1B + 2A-vs-2B + 3A-vs-3B + 4A-vs-4B (or
    # extended to N-A-vs-N-B for larger pools)
    same_rank_pairings = {p for p in seed_pairings if len({rank for rank, _ in p}) == 1}
    cross_rank_pairings = {p for p in seed_pairings if len({rank for rank, _ in p}) > 1}

    if not cross_rank_pairings and len(same_rank_pairings) == len(seed_pairings):
        if len(same_rank_pairings) == 1:
            # Only "1A vs 1B" -> single championship game
            return "F_ONLY"
        if len(same_rank_pairings) == 2:
            # "1A-1B" + "2A-2B" -> Final + 3rd Place via place games
            return "F_3P"
        if len(same_rank_pairings) >= 3:
            # 3+ same-rank pairings -> all places matter (POOL_CROSSOVER)
            return "POOL_CROSSOVER"

    # SF/Final patterns: cross-rank pairings indicate semis (1A-vs-2B etc.)
    sf_pattern = {"1A,2B", "1B,2A"}
    if sf_pattern.issubset(pair_set):
        # Has semis. Now look for final + optional 3rd place.
        # Final and 3rd place can't be detected by seed alone (they're
        # winners-vs-winners and losers-vs-losers from semis), but if we
        # see additional "1A,1B" or "2A,2B" pairings beyond semis it's
        # a hybrid format.
        n_extra = len(seed_pairings) - 2
        if n_extra == 0:
            # Just two semis observed (final not yet played, or final
            # uses winners not seeds — undetectable from seeds alone).
            return "SF_F"
        if n_extra == 1:
            return "SF_F"
        if n_extra >= 2:
            return "SF_F_3P"

    # QF pattern: 8-team bracket with 4 cross-pool quarterfinals
    if len(seed_pairings) >= 4 and len(cross_rank_pairings) >= 2:
        return "QF_SF_F"

    return "CUSTOM"


def detect_format_from_stage_labels(games: list[Any]) -> str | None:
    """Authoritative format detection from gotsport's per-match
    ``stage_label`` (e.g. "Final", "Third Place", "Consolation A",
    "Semifinal", "Quarterfinal"). Pool play games leave stage_label
    empty/None.

    Returns ``None`` when no game carries a stage_label (operator's
    raw_scrape pre-dates stage extraction OR the event genuinely had
    no labelled playoff games — fall back to inference).
    """
    labels = {
        str(getattr(g, "stage_label", "") or "").strip().lower()
        for g in games
        if getattr(g, "stage_label", None)
    }
    labels.discard("")
    if not labels:
        return None

    has_final = any("final" in lbl and "semi" not in lbl and "quarter" not in lbl for lbl in labels)
    has_third = any(("third" in lbl) or ("3rd" in lbl) for lbl in labels)
    has_consolation = any("consolation" in lbl for lbl in labels)
    has_semi = any("semi" in lbl for lbl in labels)
    has_quarter = any("quarter" in lbl or lbl.startswith("qf") for lbl in labels)
    # "5th Place Game", "7th Place", "9th Place Game" etc. — signals that EVERY
    # team plays a placement game (POOL_CROSSOVER), not just the top 4.
    # Pattern: a number >= 5 followed by "place" or "th place game".
    import re as _re
    place_pattern = _re.compile(r"\b([5-9]|1\d|2\d)(st|nd|rd|th)?\s+place\b")
    has_lower_placement = any(place_pattern.search(lbl) for lbl in labels)

    if has_quarter:
        return "QF_SF_F"
    if has_semi and has_third:
        return "SF_F_3P"
    if has_semi:
        return "SF_F"
    # POOL_CROSSOVER signature: every pool seed plays its mirror in the other
    # pool. Detected by ANY of:
    #   (a) explicit "Consolation" labels (4-team-pool form: Final, Third
    #       Place, Consolation A, Consolation B)
    #   (b) lower placement games beyond 3rd ("5th Place Game", "7th Place",
    #       etc.) — signals every pool finisher plays a placement match
    if has_final and has_third and (has_consolation or has_lower_placement):
        return "POOL_CROSSOVER"
    if has_final and has_third:
        return "F_3P"
    if has_final:
        return "F_ONLY"
    return "CUSTOM"


def detect_division_playoff_format(
    pool_assignments: list[dict[str, Any]],
    games: list[Any],
    standings: list[Any],
) -> str:
    """Return the playoff template name for one division.

    Prefers gotsport's per-match stage_label when present (authoritative
    ground truth). Falls back to pool-membership pattern inference when
    stage_label is missing (legacy game_results.jsonl pre-dating the
    stage_label extraction).

    ``pool_assignments`` is the list of pools for ONE group_id, each
    ``{label: "A", provider_team_ids: [...]}``. ``games`` is the list of
    ``GameResult`` rows for that group_id (or all games — non-division
    rows are filtered by pool membership). ``standings`` is the list of
    ``Standing`` rows for that group_id.
    """
    # Authoritative path: stage_label tells us directly.
    label_based = detect_format_from_stage_labels(games)
    if label_based is not None:
        return label_based
    # Build reg_id -> pool_label map
    pool_by_reg: dict[str, str] = {}
    for pool in pool_assignments:
        label = str(pool.get("label", "") or "")
        for reg in pool.get("provider_team_ids", []) or []:
            if reg:
                pool_by_reg[str(reg)] = label
    if not pool_by_reg:
        return "POOL_ONLY"

    # Build reg_id -> seed (rank within their pool) from standings
    seed_by_reg: dict[str, int] = {}
    for s in standings:
        reg = str(getattr(s, "provider_team_id", "") or "")
        rank = int(getattr(s, "rank", 0) or 0)
        if reg and rank > 0 and reg in pool_by_reg:
            # Standings rank within their pool — gotsport renders one
            # standings table per pool with rank=1..N inside each.
            seed_by_reg.setdefault(reg, rank)

    # Classify each intra-division game
    crossover_pairings: set[tuple] = set()
    for game in games:
        home_reg = str(getattr(game, "home_provider_team_id", "") or "")
        away_reg = str(getattr(game, "away_provider_team_id", "") or "")
        if home_reg not in pool_by_reg or away_reg not in pool_by_reg:
            continue
        home_pool = pool_by_reg[home_reg]
        away_pool = pool_by_reg[away_reg]
        if home_pool == away_pool:
            continue  # pool play, not crossover
        home_seed = seed_by_reg.get(home_reg)
        away_seed = seed_by_reg.get(away_reg)
        if not home_seed or not away_seed:
            continue  # can't classify without seeds
        crossover_pairings.add(
            _normalize_seed_pairing((home_seed, home_pool), (away_seed, away_pool))
        )

    return _classify_crossover_pattern(crossover_pairings)


def detect_playoff_formats_for_event(
    raw_scrape_records: list[dict[str, Any]],
    pools_by_group_id: dict[str, list[dict[str, Any]]],
    all_games: list[Any],
    all_standings: list[tuple[str, Any]],
) -> dict[tuple[str, str, str], str]:
    """Return ``{(cohort_age, cohort_gender, division_name): template_name}``
    for every division in the event.

    Convenience wrapper around ``detect_division_playoff_format`` that
    handles the join from raw_scrape's group_id <-> (cohort, division)
    mapping and the bridge between standings/games' reg-ids and the
    pool_assignments' reg-ids.
    """
    from src.tournaments.seeding_optimizer import normalize_age_group, normalize_gender_label
    from src.tournaments.triage import effective_cohort_for_team

    # Build group_id -> (cohort_key, division_name) via raw_scrape
    group_to_division: dict[str, tuple[tuple[str, str], str]] = {}
    raw_by_pid: dict[str, dict[str, Any]] = {}
    raw_by_reg: dict[str, dict[str, Any]] = {}
    for rec in raw_scrape_records:
        pid = str(rec.get("provider_team_id") or "")
        reg = str(rec.get("provider_registration_id") or "")
        if pid:
            raw_by_pid[pid] = rec
        if reg:
            raw_by_reg[reg] = rec
        try:
            natural_age = normalize_age_group(str(rec.get("cohort_age_group") or ""))
        except ValueError:
            continue
        natural_gender = normalize_gender_label(str(rec.get("cohort_gender") or ""))
        cohort = effective_cohort_for_team(natural_age, natural_gender, rec)
        division = str(rec.get("group_name") or "").strip()
        group_id = rec.get("group_id")
        if division and group_id is not None:
            group_to_division[str(group_id)] = (cohort, division)

    # Build reg_id -> group_id for game/standings classification
    # (both standings and game_results' team ids are reg-ids)
    reg_to_group: dict[str, str] = {}
    for group_id, pools in pools_by_group_id.items():
        for pool in pools:
            for reg in pool.get("provider_team_ids", []) or []:
                if reg:
                    reg_to_group[str(reg)] = str(group_id)

    # Bucket games by group_id (using one team's group as proxy — both
    # teams should be in the same group for intra-division games)
    games_by_group: dict[str, list[Any]] = defaultdict(list)
    for g in all_games:
        home_reg = str(getattr(g, "home_provider_team_id", "") or "")
        gid = reg_to_group.get(home_reg)
        if gid:
            games_by_group[gid].append(g)

    standings_by_group: dict[str, list[Any]] = defaultdict(list)
    for gid, s in all_standings:
        standings_by_group[str(gid)].append(s)

    out: dict[tuple[str, str, str], str] = {}
    for group_id, (cohort, division) in group_to_division.items():
        pools = pools_by_group_id.get(str(group_id), [])
        if not pools:
            out[(cohort[0], cohort[1], division)] = "POOL_ONLY"
            continue
        template = detect_division_playoff_format(
            pools,
            games_by_group.get(str(group_id), []),
            standings_by_group.get(str(group_id), []),
        )
        out[(cohort[0], cohort[1], division)] = template
    return out
