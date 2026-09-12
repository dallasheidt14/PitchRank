"""
Affinity Sports OR game matcher - Oregon Youth Soccer (oysa.sportsaffinity.com).

Creates new teams when no match found (like TGS/Modular11) so games are not dropped.
All teams are OR state.

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
from difflib import SequenceMatcher
from typing import Dict, Optional

from config.settings import MATCHING_CONFIG
from src.models.game_matcher import GameHistoryMatcher
from src.utils.club_normalizer import are_same_club, normalize_club_name
from src.utils.team_name_utils import resolve_distinction

logger = logging.getLogger(__name__)

STATE_CODE = "OR"


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


def _token_sort_ratio(a: str, b: str) -> float:
    """Order-insensitive similarity on two names, 0.0-1.0, stdlib only.

    Deliberately not ``rapidfuzz``. It is in neither requirements file, so
    ``club_normalizer`` carries a difflib fallback and CI and the scheduled
    workflows all run on it — and that fallback defines no ``token_sort_ratio``
    at all. Importing rapidfuzz here made every threshold in this module
    measured against a library production does not have, and would have raised
    ``AttributeError`` into the broad ``except`` below, matching nothing and
    autocreating every Oregon team.
    """
    sorted_a = " ".join(sorted(a.split()))
    sorted_b = " ".join(sorted(b.split()))
    return SequenceMatcher(None, sorted_a, sorted_b).ratio()


def _is_same_club(provider_club: str, candidate_club: str, threshold: float) -> bool:
    """Same club by canonical id AND by order-insensitive name similarity.

    Two shared shortcuts each merge distinct Oregon clubs on their own, so
    this requires both to agree:

    - ``are_same_club`` returns on canonical id alone when both names resolve,
      and the canonical map folds every Oregon "Timbers" affiliate into
      ``portland_timbers``. Eastside, Eugene, Rogue Valley and Portland
      Timbers are four clubs, and Cascade Surf and Oregon Surf two more.
    - ``similarity_score`` is ``token_set_ratio``, which scores containment:
      "portland" sits inside "portland city united", so FC Portland and
      Portland City United SC score a perfect 1.0.

    :func:`_token_sort_ratio` is the one that reads both names whole.
    Measured 2026-09-12 over the 106 distinct OR club names, genuinely-
    different pairs top out at 0.67 while same-club pairs reach 0.74-1.00,
    so the configured threshold clears every different-club pair. It also declines two true
    same-club pairs that differ by a trailing "and Thorns"; that costs a
    duplicate row, which ``merging-duplicate-teams`` reverses, where the other
    direction fuses two squads into one and does not reverse.

    The ``are_same_club`` half is redundant on every Oregon pair measured, and
    a mutation run confirms no test here pins it: ``token_set_ratio`` never
    scores below a token-sort score, so a name pair clearing the sort check
    clears it too. It is kept because the one case that *can* separate two
    near-identical names is a hand-curated canonical id, which lives there and
    nowhere else.
    """
    if not are_same_club(provider_club, candidate_club, threshold=threshold):
        return False
    return (
        _token_sort_ratio(
            normalize_club_name(provider_club),
            normalize_club_name(candidate_club),
        )
        >= threshold
    )


_TIER_TOKENS = frozenset(
    {"ecnl", "rl", "npl", "dpl", "ga", "mls", "premier", "elite", "select", "classic", "academy"}
)

# One tier, three spellings in this data — game_matcher.extract_club_from_team_name
# strips all of ``ECNL-RL|ECNL RL|ECRL``. Splitting on the hyphen makes the first
# two agree; the contraction has to be expanded explicitly or it reads as no tier
# at all and an ECNL-RL squad merges onto its club's ECNL squad.
_TIER_ALIASES = {"ecrl": frozenset({"ecnl", "rl"})}


def _extract_tier_tokens(name: str) -> frozenset:
    """Competitive tiers named in a team name, e.g. 'United PDX ECNL 2013' -> {'ecnl'}.

    Returned as a set so every spelling of ECNL-RL ({'ecnl', 'rl'}) stays
    distinct from plain 'ECNL' ({'ecnl'}), the pair CLAUDE.md singles out as
    never mergeable.
    """
    if not name:
        return frozenset()
    words = {w.lower() for w in re.split(r"[\s/\-]+", name) if w}
    tiers = set(words & _TIER_TOKENS)
    for word in words:
        tiers |= _TIER_ALIASES.get(word, frozenset())
    return frozenset(tiers)


def _extract_lane_number(name: str) -> Optional[str]:
    """Trailing squad number, e.g. 'Columbia Premier SC 2013 Black 1' -> '1'.

    Oregon separates same-colour squads of one club by a trailing number, the
    role WA fills with an RCL number.  ``extract_team_variant`` cannot see it —
    'Black 1' and 'Black 2' both reduce to 'black' — so without this the two
    squads match each other at full confidence.  A four-digit birth year is not
    a lane: the word boundary keeps '... 2013' from reading as lane 13.

    A trailing parenthetical hides the lane, and DB rows carry one far more
    often than provider rows do — 'Columbia Premier SC ... Black 1 (OR)'
    against provider 'Columbia Premier SC 2013 Black 2' left the gate with
    only one lane number and so no opinion, which is the shape that let the
    two squads match. Any parenthetical is stripped, not just a state code.

    A lane is one digit. Measured over the 2,861 OR team names on 2026-09-12:
    every trailing single digit is a lane ('Comp 1', 'Prem 2', 'East 3', 152
    rows) and every trailing two-digit token is the tail of a birth-year band
    ('ECNL RL B2013/14', 'B06/07', 93 rows), so reading two digits would make
    the gate reject correct candidates over a year.
    """
    if not name:
        return None
    trimmed = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    m = re.search(r"(?<![\d/])(\d)\s*$", trimmed)
    return m.group(1) if m else None


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

    All teams from Oregon Youth Soccer are OR state.
    Uses hygiene-style normalization so provider names match DB-normalized teams.
    """

    def __init__(self, supabase, provider_id=None, alias_cache=None, dry_run=False):
        super().__init__(supabase, provider_id=provider_id, alias_cache=alias_cache, dry_run=dry_run)
        self.default_state_code = STATE_CODE
        self._affinity_variant_gate_required = MATCHING_CONFIG.get("affinity_variant_gate_required", True)
        self._affinity_club_similarity_threshold = MATCHING_CONFIG.get("affinity_club_similarity_threshold", 0.9)
        self._affinity_debug_match_reasons = MATCHING_CONFIG.get("affinity_debug_match_reasons", False)

    def _fuzzy_match_team(
        self, team_name: str, age_group: str, gender: str, club_name: Optional[str] = None
    ) -> Optional[Dict]:
        """Affinity-only fuzzy matching with gated candidate selection."""
        try:
            from src.models.game_matcher import extract_club_from_team_name, extract_team_variant

            # Canonicalize provider inputs before any candidate retrieval/scoring.
            provider_team_name = _normalize_for_affinity_or(team_name)
            age_group_normalized = age_group.lower() if age_group else age_group
            if not club_name:
                extracted = extract_club_from_team_name(provider_team_name)
                if extracted:
                    club_name = extracted
            provider_club_name = _normalize_club_for_affinity(club_name)

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

            # Affinity teams are OR-only; filter candidates to OR to avoid cross-state club noise.
            result = (
                self.db.table("teams")
                .select("team_id_master, team_name, club_name, age_group, gender, state_code")
                .eq("age_group", age_group_normalized)
                .eq("gender", gender)
                .eq("state_code", STATE_CODE)
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
                "state_code": STATE_CODE,
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
                candidate_tiers = _extract_tier_tokens(candidate_name_norm)
                if provider_tiers and candidate_tiers and provider_tiers != candidate_tiers:
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
                    club_name=club_name,
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

        # Affinity OR: pass clean_team_name (built above by stripping club prefix).
        distinction = resolve_distinction(clean_team_name, club_name, STATE_CODE)

        team_data = {
            "team_id_master": team_id_master,
            "team_name": clean_team_name,
            "club_name": club_name or clean_team_name,
            "age_group": age_group_normalized,
            "gender": gender_normalized,
            "state_code": STATE_CODE,
            "provider_id": provider_id,
            "provider_team_id": provider_team_id,
            "distinction": distinction,
        }
        if not self.dry_run:
            self.db.table("teams").insert(team_data).execute()
        return team_id_master
