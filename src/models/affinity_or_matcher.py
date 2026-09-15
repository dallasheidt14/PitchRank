"""
Affinity Sports OR game matcher - Oregon Youth Soccer (oysa.sportsaffinity.com).

Creates new teams when no match found (like TGS/Modular11) so games are not dropped.
Oregon is the default state, not a universal one -- OYSA's league reaches into
SW Washington, so the state is resolved per club. See the class docstring.

Uses hygiene-style normalization (14B→2014) to match DB teams that were
normalized by the weekly data hygiene pipeline.

Affinity-specific overrides (do not affect other providers):
- Broader club filter: "Portland Timbers" matches "Portland Timbers (OR)"
- Club+variant boost: when club same and variant same, strong match

The WA sibling separates squads by the RCL number in a team's name.  Oregon
names its RCL divisions but not its teams (38 names sampled across four RCL
flights on 2026-09-11 carried no RCL token), so that spelling of the gate is
inert here — but the need is not.  Oregon separates squads by a trailing
number, and ``extract_team_variant`` reduces both "Black 1" and "Black 2" to
"black", so :func:`_extract_lane_number` does the same job on Oregon's
convention.  Both were caught matching each other at confidence 1.0 in a dry
run before this gate existed.
"""

import logging
import re
from collections import Counter
from typing import Dict, Optional, Tuple

from config.settings import MATCHING_CONFIG
from src.models.game_matcher import GameHistoryMatcher
from src.models.squad_name_gates import extract_lane_number as _extract_lane_number
from src.models.squad_name_gates import extract_tier_tokens as _extract_tier_tokens
from src.models.squad_name_gates import is_same_club as _is_same_club
from src.models.squad_name_gates import tiers_conflict as _tiers_conflict
from src.utils.placeholder_clubs import is_placeholder_club
from src.utils.team_name_utils import resolve_distinction

logger = logging.getLogger(__name__)

STATE_CODE = "OR"
STATE_NAME = "Oregon"


def _normalize_for_affinity_or(name: str) -> str:
    """
    Hygiene-style normalization for affinity_or provider names only.
    Matches logic from team_name_normalizer / weekly data hygiene pipeline.
    - B14, G15 → 2014, 2015 (2-digit birth year)
    """
    if not name:
        return ""
    n = name.strip()

    # 2-digit birth year: B14→2014, G15→2015, 14B→2014, 15G→2015
    def _to_year(m):
        num = int(m.group(1))
        return str(2000 + num) if num < 30 else str(1900 + num)

    n = re.sub(r"\b[BG](\d{2})\b", _to_year, n, flags=re.IGNORECASE)
    n = re.sub(r"\b(\d{2})[BG]\b", _to_year, n, flags=re.IGNORECASE)
    n = re.sub(r"\bB(20\d{2})\b", r"\1", n, flags=re.IGNORECASE)
    n = re.sub(r"\bG(20\d{2})\b", r"\1", n, flags=re.IGNORECASE)

    # Normalize compact color/roster tokens seen in Affinity.
    n = re.sub(r"\bWHT\b", "White", n, flags=re.IGNORECASE)
    n = re.sub(r"\bBLK\b", "Black", n, flags=re.IGNORECASE)

    # Remove age-band labels that are often formatting noise in names.
    n = re.sub(r"\b[BG]?U\d{1,2}\b", " ", n, flags=re.IGNORECASE)
    n = " ".join(n.split())

    return n


def _normalize_club_for_affinity(club_name: Optional[str]) -> str:
    """Provider-only club normalization for robust Affinity matching."""
    if not club_name:
        return ""

    club = club_name.strip()
    club = re.sub(r"\(OR\)", "", club, flags=re.IGNORECASE)
    club = re.sub(r"\bF\.?C\.?\b", "FC", club, flags=re.IGNORECASE)
    club = re.sub(r"\s+", " ", club).strip(" -.,")
    return club


class AffinityORGameMatcher(GameHistoryMatcher):
    """
    Affinity OR matcher: creates new teams when no match found.

    Oregon is the default state, not a universal one. OYSA's league reaches
    across the Columbia into SW Washington — its own fixtures are played at
    Ridgefield, Fort Vancouver HS and Columbia River HS — and four of the 55
    clubs in a 261-team sample are stored in another state, three of them
    unanimously WA: FC Salmon Creek (48 rows), CYSA Timber Barons (39) and
    Pacific FC (33). Pacific FC is the club whose 12 teams the 2026-08-31 state
    sweep corrected OR -> WA, recorded in
    ``.turbo/reports/2026-08-31-targeting-the-gotsport-probe.md``. Stamping
    "OR" on every team would have refused those candidates, autocreated
    duplicates on the Oregon board, and undone that sweep.

    So the state is resolved per team from the club's existing rows and only
    falls back to OR when the club has no unanimous signal — the same contract
    the PlayMetrics tournament path uses, via the inherited
    ``_resolve_state_from_club``.

    Uses hygiene-style normalization so provider names match DB-normalized teams.
    """

    def __init__(self, supabase, provider_id=None, alias_cache=None, dry_run=False):
        super().__init__(supabase, provider_id=provider_id, alias_cache=alias_cache, dry_run=dry_run)
        self.default_state_code = STATE_CODE
        self._affinity_variant_gate_required = MATCHING_CONFIG.get("affinity_variant_gate_required", True)
        self._affinity_club_similarity_threshold = MATCHING_CONFIG.get("affinity_club_similarity_threshold", 0.9)
        self._affinity_debug_match_reasons = MATCHING_CONFIG.get("affinity_debug_match_reasons", False)
        self._or_search_state_cache: Dict[str, Optional[str]] = {}
        self._or_stored_club_name: Dict[str, Optional[str]] = {}

    def _club_for(self, team_name: Optional[str], club_name: Optional[str]) -> Optional[str]:
        """The club to reason about for this team, inferred when the feed omits it.

        The scraper writes an empty ``club_name`` for every row, because an
        Affinity schedule page names teams and never clubs. Both the state
        resolver and the ``teams.club_name`` column therefore depend on this
        inference, and it has to happen in one place: it used to be a local in
        ``_fuzzy_match_team``, so matching saw "FC Salmon Creek" while creation
        saw None -- which stored the entire squad name as the club and put a
        Washington team on the Oregon board.
        """
        if club_name:
            return club_name
        if not team_name:
            return None
        from src.models.game_matcher import extract_club_from_team_name

        return extract_club_from_team_name(_normalize_for_affinity_or(team_name)) or None

    def _state_for_new_team(self, club_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """``(state_code, state)`` to STORE on a newly created team.

        Three cases, and only one of them may default:

        - the club's stated teams are unanimous -> that state;
        - the club has stated teams that disagree -> ``(None, None)``. A guess
          here becomes the value every later heuristic agrees with, and a club
          that agrees with itself is invisible to every correction
          ``assigning-team-states`` can make; a NULL it can still fill;
        - the club is unknown to us -> the league's own state, Oregon.

        Deliberately stricter than :meth:`_state_for_club`, which picks where
        to *look* and may take a plurality, because nothing it decides is
        written down.
        """
        # Ask the unanimity question under the club's OWN stored spelling. The
        # inherited resolver compares with a case-sensitive eq, so handing it
        # the inferred "CYSA Timber Barons" against 27 stored "Cysa Timber
        # Barons" rows made it report no unanimous state while the plurality
        # below saw them -- and this branch then read unanimous agreement as
        # disagreement and stored NULL.
        plurality = self._club_state_plurality(club_name)
        stored_name = self._or_stored_club_name.get(club_name) or club_name

        resolved_code, resolved_state = self._resolve_state_from_club(stored_name)
        if resolved_code:
            return resolved_code, resolved_state
        if plurality is not None:
            return None, None
        return STATE_CODE, STATE_NAME

    def _state_for_club(self, club_name: Optional[str]) -> str:
        """State to SEARCH for this club's candidates, defaulting to Oregon.

        Deliberately looser than ``_resolve_state_from_club``, which answers
        only on unanimity and so abstains for exactly the clubs this exists to
        serve: Pacific FC is 82 WA rows and one BC, FC Salmon Creek 31 WA and
        two OR. One outlier silences the strict resolver, and searching OR then
        guarantees a miss and an autocreated duplicate on the wrong board.

        Being wrong here costs a missed candidate and nothing else — the value
        is never written, and the strict resolver still decides what a created
        team stores. That asymmetry is why a plurality is good enough here and
        not good enough there. Bounded at 1000 rows: a sample cannot settle a
        question about the whole, which is why this only chooses where to look.
        """
        return self._club_state_plurality(club_name) or STATE_CODE

    def _club_state_plurality(self, club_name: Optional[str]) -> Optional[str]:
        """Most common stated state among the club's rows, or None if it has none.

        None means "this club is unknown to us", which is a different answer
        from "this club is known and its rows disagree" — the first is safe to
        default, the second is not.
        """
        # A placeholder is not a club, so it cannot be asked — the same reason
        # the base resolver refuses one. "No Club Selection" alone covers 1,596
        # teams across 23 states, and its plurality would be noise stamped on
        # every team that carries it.
        if not club_name or is_placeholder_club(club_name):
            return None
        if club_name in self._or_search_state_cache:
            return self._or_search_state_cache[club_name]
        state = None
        stored = None
        try:
            rows = (
                self.db.table("teams")
                .select("club_name, state_code")
                # ilike with no wildcards is case-insensitive equality: the DB
                # stores "Cysa Timber Barons" where the name infers
                # "CYSA Timber Barons", and an exact eq misses it entirely.
                .ilike("club_name", club_name)
                .not_.is_("state_code", "null")
                .neq("state_code", "")
                .limit(1000)
                .execute()
            )
            data = rows.data or []
            counts = Counter(r["state_code"] for r in data if r.get("state_code"))
            if counts:
                state = counts.most_common(1)[0][0]
            spellings = Counter(r["club_name"] for r in data if r.get("club_name"))
            if spellings:
                stored = spellings.most_common(1)[0][0]
        except Exception as e:  # a read failure must not block matching
            logger.debug(f"[AffinityOR] Club state lookup failed for {club_name!r}: {e}")
        self._or_stored_club_name[club_name] = stored
        self._or_search_state_cache[club_name] = state
        return state

    def _fuzzy_match_team(
        self, team_name: str, age_group: str, gender: str, club_name: Optional[str] = None
    ) -> Optional[Dict]:
        """Affinity-only fuzzy matching with gated candidate selection."""
        try:
            from src.models.game_matcher import extract_club_from_team_name, extract_team_variant

            # Canonicalize provider inputs before any candidate retrieval/scoring.
            provider_team_name = _normalize_for_affinity_or(team_name)
            age_group_normalized = age_group.lower() if age_group else age_group
            provider_club_name = _normalize_club_for_affinity(self._club_for(team_name, club_name))

            provider_variant = extract_team_variant(provider_team_name)
            provider_tiers = _extract_tier_tokens(provider_team_name)
            provider_lane = _extract_lane_number(provider_team_name)
            provider_year = re.search(r"\b(20\d{2})\b", provider_team_name)
            provider_year_token = provider_year.group(1) if provider_year else None

            name_lower = provider_team_name.lower() if provider_team_name else ""
            provider_has_rl = (
                " rl" in name_lower or "-rl" in name_lower or "ecnl rl" in name_lower or "ecnl-rl" in name_lower
            )
            provider_has_ecnl = "ecnl" in name_lower and not provider_has_rl

            # Scope candidates to one state to avoid cross-state club noise, but
            # ask the club which state rather than assuming Oregon: a Pacific FC
            # or FC Salmon Creek team plays in OYSA and lives in WA, and an OR
            # filter cannot see its own canonical row.
            search_state = self._state_for_club(provider_club_name)
            result = (
                self.db.table("teams")
                .select("team_id_master, team_name, club_name, age_group, gender, state_code")
                .eq("age_group", age_group_normalized)
                .eq("gender", gender)
                .eq("state_code", search_state)
                .execute()
            )

            if not result or not result.data:
                return None

            reject_counts = {
                "club_mismatch": 0,
                "club_unknown": 0,
                "variant_mismatch": 0,
                "tier_mismatch": 0,
                "lane_mismatch": 0,
            }
            best_match = None
            best_score = 0.0
            best_tiebreak = (0, 0, 0)
            provider_team = {
                "team_name": provider_team_name,
                "club_name": provider_club_name,
                "age_group": age_group,
                "state_code": search_state,
            }

            candidate_count_before_gate = len(result.data)
            candidate_count_after_gate = 0

            for team in result.data:
                candidate_name_raw = team.get("team_name", "")
                candidate_name_norm = _normalize_for_affinity_or(candidate_name_raw)
                candidate_club_raw = team.get("club_name")
                candidate_club_norm = _normalize_club_for_affinity(candidate_club_raw)
                # A row with no club_name still names its club inside team_name.
                # Derive it once: the gate below and the scoring further down must
                # agree, or a candidate admitted on the derived club is then scored
                # as having none, which caps it at 0.55 against a 0.75 threshold and
                # makes every club-less row an unmatchable duplicate.
                candidate_club_effective = candidate_club_norm or _normalize_club_for_affinity(
                    extract_club_from_team_name(candidate_name_norm)
                )

                # Stage 1 gate: canonical same-club (or very high similarity).
                # 9% of OR rows carry no club_name, so comparing the column alone
                # skips the gate on exactly those and lets any same-variant team
                # through — that is how 'FC Portland 2013 Red' reached
                # 'RVT N1 2013/14 Red'. Fall back to the club in the row's own
                # name, and when the provider names a club that the candidate
                # cannot produce at all, decline: a duplicate is recoverable by
                # merge, a wrong match fuses two squads.
                if provider_club_name:
                    if not candidate_club_effective:
                        reject_counts["club_unknown"] += 1
                        continue
                    if not _is_same_club(
                        provider_club_name,
                        candidate_club_effective,
                        self._affinity_club_similarity_threshold,
                    ):
                        reject_counts["club_mismatch"] += 1
                        continue

                # Stage 2 gate: variant compatibility.
                candidate_variant = extract_team_variant(candidate_name_norm)
                if self._affinity_variant_gate_required and provider_variant != candidate_variant:
                    reject_counts["variant_mismatch"] += 1
                    continue

                # Stage 2b gate: tier separation. extract_team_variant only knows
                # colours, so it returns None for both 'Academy' and 'Premier' and
                # the variant gate above reads None != None as agreement — which
                # matched a Premier squad onto its club's ECNL squad, the merge
                # CLAUDE.md's division-tier rule forbids.
                # A one-sided competitive tier is a difference, not an absence:
                # requiring both sides to name one let plain 'FC Portland 13B Red'
                # match 'FC Portland ECNL 2013 Red' with the club and variant
                # boosts carrying it past auto-approve. Only the two club-shaped
                # words still need naming on both sides before they count.
                candidate_tiers = _extract_tier_tokens(candidate_name_norm)
                if _tiers_conflict(provider_tiers, candidate_tiers):
                    reject_counts["tier_mismatch"] += 1
                    continue

                # Stage 2c gate: strict squad-lane separation ('Black 1' vs 'Black 2').
                candidate_lane = _extract_lane_number(candidate_name_norm)
                if provider_lane and candidate_lane and provider_lane != candidate_lane:
                    reject_counts["lane_mismatch"] += 1
                    continue

                candidate_count_after_gate += 1
                candidate = {
                    "team_name": candidate_name_norm,
                    "club_name": candidate_club_effective or candidate_club_raw,
                    "age_group": team.get("age_group"),
                    "state_code": team.get("state_code"),
                }
                score = self._calculate_match_score(provider_team, candidate)
                cand_lower = candidate_name_norm.lower()
                cand_has_rl = (
                    " rl" in cand_lower or "-rl" in cand_lower or "ecnl rl" in cand_lower or "ecnl-rl" in cand_lower
                )
                cand_has_ecnl = "ecnl" in cand_lower and not cand_has_rl
                if provider_has_rl and cand_has_rl:
                    score = min(1.0, score + 0.05)
                elif provider_has_ecnl and cand_has_ecnl and not cand_has_rl:
                    score = min(1.0, score + 0.05)
                elif provider_has_rl != cand_has_rl:
                    score = max(0.0, score - 0.08)

                # Deterministic tie-breakers for near-equal scores.
                candidate_year = re.search(r"\b(20\d{2})\b", candidate_name_norm)
                candidate_year_token = candidate_year.group(1) if candidate_year else None
                tiebreak = (
                    1 if provider_variant == candidate_variant else 0,
                    1
                    if provider_year_token and candidate_year_token and provider_year_token == candidate_year_token
                    else 0,
                    1
                    if provider_club_name
                    and candidate_club_norm
                    and _is_same_club(provider_club_name, candidate_club_effective, 0.95)
                    else 0,
                )

                if score >= self.fuzzy_threshold and (
                    score > best_score or (score == best_score and tiebreak > best_tiebreak)
                ):
                    best_score = score
                    best_tiebreak = tiebreak
                    best_match = {
                        "team_id": team["team_id_master"],
                        "team_name": candidate_name_raw,
                        "confidence": round(score, 3),
                    }

            if self._affinity_debug_match_reasons:
                logger.info(
                    "[AffinityOR] Candidate gate stats: before=%s after=%s "
                    "rejected(club=%s, club_unknown=%s, variant=%s, tier=%s, lane=%s) for '%s'",
                    candidate_count_before_gate,
                    candidate_count_after_gate,
                    reject_counts["club_mismatch"],
                    reject_counts["club_unknown"],
                    reject_counts["variant_mismatch"],
                    reject_counts["tier_mismatch"],
                    reject_counts["lane_mismatch"],
                    team_name,
                )
            return best_match
        except Exception as e:
            logger.error(f"AffinityOR fuzzy match error: {e}")
            return None

    def _calculate_match_score(self, provider_team: Dict, candidate: Dict) -> float:
        """Override: add club+variant boost for Affinity (e.g. '14B Red' vs 'FC Portland 2014 Red')."""
        score = super()._calculate_match_score(provider_team, candidate)
        provider_club = provider_team.get("club_name")
        candidate_club = candidate.get("club_name")
        if provider_club and candidate_club:
            if _is_same_club(provider_club, candidate_club, 0.9):
                boost = MATCHING_CONFIG.get("club_variant_match_boost", 0.35)
                score = min(1.0, score + boost)  # Club+variant match boost (caller filters by variant)
        return score

    def _normalize_team_name(self, name: str) -> str:
        """Override: apply hygiene-style normalization (14B→2014) before base."""
        pre = _normalize_for_affinity_or(name)
        return super()._normalize_team_name(pre)

    def _match_team(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_name: Optional[str],
        age_group: Optional[str],
        gender: Optional[str],
        club_name: Optional[str] = None,
    ) -> Dict:
        """Override: create new team when no match found."""
        base_result = super()._match_team(provider_id, provider_team_id, team_name, age_group, gender, club_name)
        if base_result.get("matched"):
            return base_result

        if team_name and age_group and gender:
            logger.info(f"[AffinityOR] No match for '{team_name}' ({age_group}, {gender}), creating new team")
            try:
                new_team_id = self._create_new_affinity_or_team(
                    team_name=team_name,
                    club_name=self._club_for(team_name, club_name),
                    age_group=age_group,
                    gender=gender,
                    provider_id=provider_id,
                    provider_team_id=provider_team_id,
                )
                match_method = "direct_id" if provider_team_id else "import"
                self._create_alias(
                    provider_id=provider_id,
                    provider_team_id=provider_team_id,
                    team_name=team_name,
                    team_id_master=new_team_id,
                    match_method=match_method,
                    confidence=1.0,
                    age_group=age_group,
                    gender=gender,
                    review_status="approved",
                )
                logger.info(f"[AffinityOR] Created: {team_name} ({age_group}, {gender}) -> {new_team_id}")
                return {
                    "matched": True,
                    "team_id": new_team_id,
                    "method": match_method,
                    "confidence": 1.0,
                    "created": True,  # Signal to pipeline for teams_created metrics
                }
            except Exception as e:
                logger.error(f"[AffinityOR] Error creating team for {team_name}: {e}")

        return base_result

    def _create_new_affinity_or_team(
        self,
        team_name: str,
        club_name: Optional[str],
        age_group: str,
        gender: str,
        provider_id: Optional[str],
        provider_team_id: Optional[str] = None,
    ) -> str:
        """Create new team in teams table. All affinity_or teams are OR."""
        if not provider_team_id:
            import hashlib

            # MD5 for deterministic ID generation (not security)
            provider_team_id = hashlib.md5(f"{team_name}_{age_group}_{gender}".encode()).hexdigest()[:16]

        if provider_id:
            try:
                existing = (
                    self.db.table("teams")
                    .select("team_id_master")
                    .eq("provider_id", provider_id)
                    .eq("provider_team_id", provider_team_id)
                    .single()
                    .execute()
                )
                if existing.data:
                    return existing.data["team_id_master"]
            except Exception:
                pass

        team_id_master = self._new_team_id_master(provider_id, provider_team_id, team_name, age_group, gender)
        age_group_normalized = age_group.lower() if age_group else age_group
        gender_normalized = "Male" if gender.upper() in ("M", "MALE", "BOYS", "B") else "Female"
        clean_team_name = team_name
        if club_name and team_name.startswith(club_name):
            remaining = team_name[len(club_name) :].strip()
            if remaining and not remaining.startswith(("-", "–", "—")):
                clean_team_name = remaining
            elif remaining:
                clean_team_name = remaining.lstrip("-–—").strip() or team_name

        # OYSA reaches into SW Washington, so ask the club before stamping OR.
        # Pacific FC, FC Salmon Creek and CYSA Timber Barons all play here and
        # all live in WA; writing OR would duplicate them onto the wrong board
        # and undo the 2026-08-31 state sweep that corrected them.
        new_state_code, new_state = self._state_for_new_team(club_name)

        # Affinity OR: pass clean_team_name (built above by stripping club prefix).
        distinction = resolve_distinction(clean_team_name, club_name, new_state_code)

        team_data = {
            "team_id_master": team_id_master,
            "team_name": clean_team_name,
            "club_name": club_name or clean_team_name,
            "age_group": age_group_normalized,
            "gender": gender_normalized,
            "state_code": new_state_code,
            "state": new_state,
            "provider_id": provider_id,
            "provider_team_id": provider_team_id,
            "distinction": distinction,
        }
        if not self.dry_run:
            self.db.table("teams").insert(team_data).execute()
        return team_id_master
