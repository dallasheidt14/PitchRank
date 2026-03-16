"""
Affinity Sports WA game matcher - Washington Youth Soccer (sctour.sportsaffinity.com).

Creates new teams when no match found (like TGS/Modular11) so games are not dropped.
All teams are WA state.

Uses hygiene-style normalization (B14→2014, XF→Crossfire) to match DB teams
that were normalized by the weekly data hygiene pipeline.

Affinity-specific overrides (do not affect other providers):
- Broader club filter: "Eastside FC" matches "Eastside FC (WA)"
- Club+variant boost: when club same and variant same, strong match (e.g. "B14 Red" vs "Eastside FC 2014 Red")
"""
import logging
import re
import uuid
from typing import Dict, Optional

from supabase import Client
from config.settings import MATCHING_CONFIG

from src.models.game_matcher import GameHistoryMatcher
from src.utils.club_normalizer import are_same_club

logger = logging.getLogger(__name__)

STATE_CODE = "WA"

# Club abbreviations for team name comparison (align with hygiene pipeline / scraper)
_CLUB_ABBREVS = {"xf": "crossfire"}


def _normalize_for_affinity_wa(name: str) -> str:
    """
    Hygiene-style normalization for affinity_wa provider names only.
    Matches logic from team_name_normalizer / weekly data hygiene pipeline.
    - B14, G15 → 2014, 2015 (2-digit birth year)
    - XF → Crossfire (club abbreviation)
    """
    if not name:
        return ""
    n = name.strip()

    # Expand club abbreviations (XF → Crossfire)
    for abbr, full in _CLUB_ABBREVS.items():
        n = re.sub(rf"\b{re.escape(abbr)}\b", full, n, flags=re.IGNORECASE)

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


def _extract_rcl_number(name: str) -> Optional[str]:
    """Extract RCL division from team name, e.g. 'XF B14 RCL 3' -> '3', 'Crossfire 2014 RCL 2' -> '2'."""
    if not name:
        return None
    m = re.search(r'\bRCL\s*(\d+)\b', name, re.IGNORECASE)
    return m.group(1) if m else None


def _normalize_club_for_affinity(club_name: Optional[str]) -> str:
    """Provider-only club normalization for robust Affinity matching."""
    if not club_name:
        return ""

    club = club_name.strip()
    club = re.sub(r"\(WA\)", "", club, flags=re.IGNORECASE)
    club = re.sub(r"\bF\.?C\.?\b", "FC", club, flags=re.IGNORECASE)
    club = re.sub(r"\s+", " ", club).strip(" -.,")
    return club


class AffinityWAGameMatcher(GameHistoryMatcher):
    """
    Affinity WA matcher: creates new teams when no match found.

    All teams from Washington Youth Soccer are WA state.
    Uses hygiene-style normalization so provider names match DB-normalized teams.
    Rejects fuzzy matches when RCL number differs (e.g. RCL 3 must not match RCL 2).
    """

    def __init__(self, supabase, provider_id=None, alias_cache=None):
        super().__init__(supabase, provider_id=provider_id, alias_cache=alias_cache, default_state_code='WA')
        self._affinity_variant_gate_required = MATCHING_CONFIG.get('affinity_variant_gate_required', True)
        self._affinity_rcl_strict = MATCHING_CONFIG.get('affinity_rcl_strict', True)
        self._affinity_club_similarity_threshold = MATCHING_CONFIG.get('affinity_club_similarity_threshold', 0.9)
        self._affinity_debug_match_reasons = MATCHING_CONFIG.get('affinity_debug_match_reasons', False)

    def _fuzzy_match_team(
        self,
        team_name: str,
        age_group: str,
        gender: str,
        club_name: Optional[str] = None
    ) -> Optional[Dict]:
        """Affinity-only fuzzy matching with gated candidate selection."""
        try:
            from src.models.game_matcher import extract_team_variant, extract_club_from_team_name

            # Canonicalize provider inputs before any candidate retrieval/scoring.
            provider_team_name = _normalize_for_affinity_wa(team_name)
            age_group_normalized = age_group.lower() if age_group else age_group
            if not club_name:
                extracted = extract_club_from_team_name(provider_team_name)
                if extracted:
                    club_name = extracted
            provider_club_name = _normalize_club_for_affinity(club_name)

            provider_variant = extract_team_variant(provider_team_name)
            provider_rcl = _extract_rcl_number(provider_team_name)
            provider_year = re.search(r"\b(20\d{2})\b", provider_team_name)
            provider_year_token = provider_year.group(1) if provider_year else None

            name_lower = provider_team_name.lower() if provider_team_name else ''
            provider_has_rl = (' rl' in name_lower or '-rl' in name_lower or 'ecnl rl' in name_lower or 'ecnl-rl' in name_lower)
            provider_has_ecnl = 'ecnl' in name_lower and not provider_has_rl

            # Affinity teams are WA-only; filter candidates to WA to avoid cross-state club noise.
            result = self.db.table('teams').select(
                'team_id_master, team_name, club_name, age_group, gender, state_code'
            ).eq('age_group', age_group_normalized).eq('gender', gender).eq('state_code', STATE_CODE).execute()

            if not result or not result.data:
                return None

            reject_counts = {'club_mismatch': 0, 'variant_mismatch': 0, 'rcl_mismatch': 0}
            best_match = None
            best_score = 0.0
            best_tiebreak = (0, 0, 0)
            provider_team = {
                'team_name': provider_team_name,
                'club_name': provider_club_name,
                'age_group': age_group,
                'state_code': 'WA',
            }

            candidate_count_before_gate = len(result.data)
            candidate_count_after_gate = 0

            for team in result.data:
                candidate_name_raw = team.get('team_name', '')
                candidate_name_norm = _normalize_for_affinity_wa(candidate_name_raw)
                candidate_club_raw = team.get('club_name')
                candidate_club_norm = _normalize_club_for_affinity(candidate_club_raw)

                # Stage 1 gate: canonical same-club (or very high similarity).
                if provider_club_name and candidate_club_norm:
                    if not are_same_club(
                        provider_club_name,
                        candidate_club_norm,
                        threshold=self._affinity_club_similarity_threshold,
                    ):
                        reject_counts['club_mismatch'] += 1
                        continue

                # Stage 2 gate: variant compatibility.
                candidate_variant = extract_team_variant(candidate_name_norm)
                if self._affinity_variant_gate_required and provider_variant != candidate_variant:
                    reject_counts['variant_mismatch'] += 1
                    continue

                # Stage 2b gate: strict RCL lane separation.
                candidate_rcl = _extract_rcl_number(candidate_name_norm)
                if self._affinity_rcl_strict and provider_rcl and candidate_rcl and provider_rcl != candidate_rcl:
                    reject_counts['rcl_mismatch'] += 1
                    continue

                candidate_count_after_gate += 1
                candidate = {
                    'team_name': candidate_name_norm,
                    'club_name': candidate_club_norm or candidate_club_raw,
                    'age_group': team.get('age_group'),
                    'state_code': team.get('state_code')
                }
                score = self._calculate_match_score(provider_team, candidate)
                cand_lower = candidate_name_norm.lower()
                cand_has_rl = (' rl' in cand_lower or '-rl' in cand_lower or 'ecnl rl' in cand_lower or 'ecnl-rl' in cand_lower)
                cand_has_ecnl = 'ecnl' in cand_lower and not cand_has_rl
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
                    1 if provider_year_token and candidate_year_token and provider_year_token == candidate_year_token else 0,
                    1 if provider_club_name and candidate_club_norm and are_same_club(provider_club_name, candidate_club_norm, threshold=0.95) else 0,
                )

                if score >= self.fuzzy_threshold and (score > best_score or (score == best_score and tiebreak > best_tiebreak)):
                    best_score = score
                    best_tiebreak = tiebreak
                    best_match = {'team_id': team['team_id_master'], 'team_name': candidate_name_raw, 'confidence': round(score, 3)}

            if self._affinity_debug_match_reasons:
                logger.info(
                    "[AffinityWA] Candidate gate stats: before=%s after=%s rejected(club=%s, variant=%s, rcl=%s) for '%s'",
                    candidate_count_before_gate,
                    candidate_count_after_gate,
                    reject_counts['club_mismatch'],
                    reject_counts['variant_mismatch'],
                    reject_counts['rcl_mismatch'],
                    team_name,
                )
            return best_match
        except Exception as e:
            logger.error(f"AffinityWA fuzzy match error: {e}")
            return None

    def _calculate_match_score(self, provider_team: Dict, candidate: Dict) -> float:
        """Override: add club+variant boost for Affinity (e.g. 'B14 Red' vs 'Eastside FC 2014 Red')."""
        score = super()._calculate_match_score(provider_team, candidate)
        provider_club = provider_team.get('club_name')
        candidate_club = candidate.get('club_name')
        if provider_club and candidate_club:
            if are_same_club(provider_club, candidate_club, threshold=0.9):
                boost = MATCHING_CONFIG.get('club_variant_match_boost', 0.35)
                score = min(1.0, score + boost)  # Club+variant match boost (caller filters by variant)
        return score

    def _normalize_team_name(self, name: str) -> str:
        """Override: apply hygiene-style normalization (B14→2014, XF→Crossfire) before base."""
        pre = _normalize_for_affinity_wa(name)
        return super()._normalize_team_name(pre)

    def _match_team(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_name: Optional[str],
        age_group: Optional[str],
        gender: Optional[str],
        club_name: Optional[str] = None
    ) -> Dict:
        """Override: create new team when no match found. Reject fuzzy matches when RCL differs."""
        base_result = super()._match_team(
            provider_id, provider_team_id, team_name, age_group, gender, club_name
        )
        if base_result.get('matched'):
            # Reject fuzzy matches when RCL number differs (RCL 2 vs RCL 3 are different teams)
            method = base_result.get('method', '')
            if 'fuzzy' in str(method).lower() and team_name and 'RCL' in team_name.upper():
                provider_rcl = _extract_rcl_number(team_name)
                if provider_rcl:
                    try:
                        row = self.db.table('teams').select('team_name').eq(
                            'team_id_master', base_result['team_id']
                        ).single().execute()
                        if row.data:
                            matched_rcl = _extract_rcl_number(row.data.get('team_name', ''))
                            if matched_rcl and provider_rcl != matched_rcl:
                                logger.info(
                                    f"[AffinityWA] Rejecting fuzzy match: '{team_name}' RCL {provider_rcl} "
                                    f"!= matched RCL {matched_rcl}, creating new team"
                                )
                                base_result = {'matched': False}
                    except Exception as e:
                        logger.debug(f"[AffinityWA] RCL check failed: {e}")
            if base_result.get('matched'):
                return base_result

        if team_name and age_group and gender:
            logger.info(
                f"[AffinityWA] No match for '{team_name}' ({age_group}, {gender}), creating new team"
            )
            try:
                new_team_id = self._create_new_affinity_wa_team(
                    team_name=team_name,
                    club_name=club_name,
                    age_group=age_group,
                    gender=gender,
                    provider_id=provider_id,
                    provider_team_id=provider_team_id
                )
                match_method = 'direct_id' if provider_team_id else 'import'
                self._create_alias(
                    provider_id=provider_id,
                    provider_team_id=provider_team_id,
                    team_name=team_name,
                    team_id_master=new_team_id,
                    match_method=match_method,
                    confidence=1.0,
                    age_group=age_group,
                    gender=gender,
                    review_status='approved'
                )
                logger.info(
                    f"[AffinityWA] Created: {team_name} ({age_group}, {gender}) -> {new_team_id}"
                )
                return {
                    'matched': True,
                    'team_id': new_team_id,
                    'method': match_method,
                    'confidence': 1.0,
                    'created': True,  # Signal to pipeline for teams_created metrics
                }
            except Exception as e:
                logger.error(f"[AffinityWA] Error creating team for {team_name}: {e}")

        return base_result

    def _create_new_affinity_wa_team(
        self,
        team_name: str,
        club_name: Optional[str],
        age_group: str,
        gender: str,
        provider_id: Optional[str],
        provider_team_id: Optional[str] = None
    ) -> str:
        """Create new team in teams table. All affinity_wa teams are WA."""
        if not provider_team_id:
            import hashlib
            provider_team_id = hashlib.md5(
                f"{team_name}_{age_group}_{gender}".encode()
            ).hexdigest()[:16]

        if provider_id:
            try:
                existing = self.db.table('teams').select('team_id_master').eq(
                    'provider_id', provider_id
                ).eq('provider_team_id', provider_team_id).single().execute()
                if existing.data:
                    return existing.data['team_id_master']
            except Exception:
                pass

        team_id_master = str(uuid.uuid4())
        age_group_normalized = age_group.lower() if age_group else age_group
        gender_normalized = 'Male' if gender.upper() in ('M', 'MALE', 'BOYS', 'B') else 'Female'
        clean_team_name = team_name
        if club_name and team_name.startswith(club_name):
            remaining = team_name[len(club_name):].strip()
            if remaining and not remaining.startswith(('-', '–', '—')):
                clean_team_name = remaining
            elif remaining:
                clean_team_name = remaining.lstrip('-–—').strip() or team_name

        team_data = {
            'team_id_master': team_id_master,
            'team_name': clean_team_name,
            'club_name': club_name or clean_team_name,
            'age_group': age_group_normalized,
            'gender': gender_normalized,
            'state_code': STATE_CODE,
            'provider_id': provider_id,
            'provider_team_id': provider_team_id,
        }
        self.db.table('teams').insert(team_data).execute()
        return team_id_master
