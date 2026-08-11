"""SOM Sports / athletes2events tournament matcher.

Extends ``GameHistoryMatcher`` with **only** the SOM Sports-specific name
normalization. Discovery (auto-create on no-match) is intentionally NOT
implemented here — that responsibility belongs to the weekly hygiene
pipeline (``scripts/find_queue_matches.py`` +
``scripts/find_fuzzy_duplicate_teams.py``), which runs distinction-aware
matching (colors, programs, regions all must match — see
``scripts/_team_distinction.should_skip_pair``) and is tuned for
PitchRank's full team registry. SOM Sports import-time leaves sub-0.91
candidates in ``team_match_review_queue`` and the Monday/Tuesday hygiene
pass auto-merges 0.95+ exact matches → real ``direct_id`` aliases.

Why not auto-create like SincSports does?
  - SincSports's ``_create_new_sincsports_team`` exists for its discovery
    flow (separate from game import). Mirroring it for SOM Sports caused
    contradictory dual writes: the base writes a review-queue row at
    0.75–0.91 fuzzy confidence AND the subclass auto-created the team
    anyway, ignoring the queue signal.
  - The hygiene pipeline already knows how to distinguish "Crossfire
    Premier" from "Crossfire Select", "MVLA ECNL" from "MVLA Corinthians",
    "Beach FC RL" from "Beach FC NPL TL". The import-time matcher does
    not have that distinction-aware logic. Letting it auto-create silently
    merges or splits teams in ways the hygiene pipeline would catch.

What this subclass DOES contribute:
  1. ``_normalize_team_name`` — strip SOM Sports-specific decorations
     (``B07/08``, ``ECNL``, ``MLS Next``, coach suffix) before the base's
     shared ``normalize_name_for_matching`` runs. This is what gets the
     fuzzy score from ~0.4 (raw decorated string) up to 0.85+ where the
     hygiene queue can actually resolve it.
  2. ``_fuzzy_match_team`` — forward ``state_code`` to the base so the
     location component of the score sees the provider team's state.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, Optional

from src.models.game_matcher import GameHistoryMatcher
from src.utils.club_canonical_overrides import canonicalize_club_name
from src.utils.team_pair_scoring import score_team_pair
from supabase import Client

# Optional: shared structured club extractor (kept optional so the matcher
# doesn't hard-fail if team_name_utils is missing in a stripped env — matches
# the import discipline of game_matcher.py and sincsports_matcher.py).
try:
    from src.utils.team_name_utils import extract_club_from_team_name

    HAVE_TEAM_NAME_UTILS = True
except ImportError:
    HAVE_TEAM_NAME_UTILS = False

logger = logging.getLogger(__name__)

# Multi-year birth tokens: ``B07/08``, ``G06/07``, ``2007/2008``.
_SOMSPORTS_BIRTH_RANGE_RE = re.compile(
    r"\b(?:[BG]\d{2}/\d{2}|20\d{2}/(?:20)?\d{2})\b",
    re.IGNORECASE,
)
# Tier / league markers SOM Sports decorates team names with.
_SOMSPORTS_TIER_MARKERS_RE = re.compile(
    r"\b(?:ECNL(?:\s*RL)?|ECRL|MLS\s*Next(?:\s*HD)?|MLS\s*AD|RL|AD|EA\d?|Academy)\b",
    re.IGNORECASE,
)
# Words that look like a coach-name pattern (title-case at the end after
# ``-`` or ``,``) but are actually structural distinctions the hygiene
# pipeline relies on to keep squads separate. If we stripped these as
# coaches, ``Beach FC - North`` would collapse with ``Beach FC - South``
# under the same canonical, silently merging distinct teams.
_NOT_A_COACH_TRAILING = frozenset(
    {
        # Directions
        "north",
        "south",
        "east",
        "west",
        "central",
        "northeast",
        "northwest",
        "southeast",
        "southwest",
        # Colors
        "red",
        "blue",
        "white",
        "black",
        "gold",
        "grey",
        "gray",
        "green",
        "orange",
        "purple",
        "yellow",
        "navy",
        "maroon",
        "silver",
        "pink",
        "sky",
        "royal",
        "crimson",
        "teal",
        # Tier/program markers (already stripped by tier regex, but defensive)
        "ecnl",
        "ecrl",
        "premier",
        "elite",
        "academy",
        "select",
        "national",
    }
)
# Trailing coach-name suffix: ``- Jorge Reyes`` or ``, Aleu`` at end of
# string. Applied via ``_strip_coach_suffix`` (not a one-shot ``.sub``)
# because we need to inspect the captured word(s) and refuse to strip
# direction / color / tier tokens that share the title-case shape.
_SOMSPORTS_COACH_SUFFIX_RE = re.compile(r"(\s*[-,]\s*)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*$")


def _strip_coach_suffix(name: str) -> str:
    """Strip trailing ``- Coach`` / ``, Coach`` but only when the trailing
    title-case token(s) don't match a known direction / color / tier word.

    Examples:
      ``"Beach FC 2011 RL Maudlin"`` → ``"Beach FC 2011 RL"``  (coach stripped)
      ``"Beach FC - North"``          → ``"Beach FC - North"`` (direction kept)
      ``"Crossfire - Blue"``          → ``"Crossfire - Blue"`` (color kept)
    """
    if not name:
        return name
    m = _SOMSPORTS_COACH_SUFFIX_RE.search(name)
    if not m:
        return name
    trailing = m.group(2).lower()
    # If ANY of the trailing tokens is a structural distinction, refuse
    # to strip. Multi-word case (``- Jorge Reyes``) only counts as a
    # distinction if EVERY token is one — e.g., ``- South West`` stays.
    if any(tok in _NOT_A_COACH_TRAILING for tok in trailing.split()):
        return name
    return name[: m.start()].rstrip()


class SomSportsGameMatcher(GameHistoryMatcher):
    """SOM Sports tournament matcher — normalization-only.

    Unmatched teams flow through the base's review-queue path. The weekly
    hygiene pipeline (``find_queue_matches.py``) resolves the queue.
    """

    def __init__(
        self,
        supabase: Client,
        provider_id: Optional[str] = None,
        alias_cache: Optional[Dict] = None,
        dry_run: bool = False,
    ):
        super().__init__(supabase, provider_id=provider_id, alias_cache=alias_cache, dry_run=dry_run)
        # Inherit MATCHING_CONFIG defaults verbatim — keep alignment with the
        # hygiene pipeline's auto-merge cutoffs (0.95 EXACT, 0.90 HIGH).
        logger.info(
            "Initialized SomSportsGameMatcher (fuzzy: %s, auto-approve: %s, review: %s, dry_run: %s)",
            self.fuzzy_threshold,
            self.auto_approve_threshold,
            self.review_threshold,
            self.dry_run,
        )

    # ------------------------------------------------------------------
    # Name normalization — SOM Sports-specific preprocessing
    # ------------------------------------------------------------------
    @staticmethod
    def _pre_strip(name: str, *, strip_tier_markers: bool) -> str:
        """Strip SOM Sports decorations from a team name.

        Two callers with one intentional asymmetry:

        - ``_normalize_team_name`` (terminal normalize before fuzzy compare
          via base similarity) passes ``strip_tier_markers=True`` so the
          resulting string is the cleanest possible canonical form.
        - ``_strip_somsports_decorations`` (pre-scoring pass before the
          hygiene ``score_team_pair`` runs) passes
          ``strip_tier_markers=False`` because the hygiene scorer's RL /
          ECNL alignment bonus reads those tokens off the input name —
          if we stripped them, we'd silently lose +0.05 / -0.08 on every
          comparison.

        Coach suffix removal uses ``_strip_coach_suffix`` rather than a
        one-shot regex sub so direction / color / tier tokens that share
        the title-case shape (``- North``, ``, Blue``) survive.
        """
        if not name:
            return ""
        out = _SOMSPORTS_BIRTH_RANGE_RE.sub("", name).strip()
        if strip_tier_markers:
            out = _SOMSPORTS_TIER_MARKERS_RE.sub("", out).strip()
        out = _strip_coach_suffix(out)
        return re.sub(r"\s{2,}", " ", out).strip()

    def _normalize_team_name(self, name: str, club_name: Optional[str] = None) -> str:
        """Strip SOM Sports decorations, then delegate to base.

        ``club_name`` is accepted for signature parity with the gated-funnel
        callers (``_calculate_match_score`` passes it), but — like the
        SincSports analog — we drop it before calling ``super()`` which
        only knows ``_normalize_team_name(self, name)``.
        """
        if not name:
            return ""
        return super()._normalize_team_name(self._pre_strip(name, strip_tier_markers=True))

    # ------------------------------------------------------------------
    # Fuzzy matching — canonicalize club name before the gated funnel
    # ------------------------------------------------------------------
    def _fuzzy_match_team(
        self,
        team_name: str,
        age_group: str,
        gender: str,
        club_name: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Optional[Dict]:
        """Canonicalize the club name via the Monday standardization registry
        before the base's gated ``ilike("club_name", X)`` query.

        Why this matters: the Monday ``update-missing-club-and-state.yml``
        workflow rewrites ``teams.club_name`` to canonical values
        (``"Mustang SC"`` → ``"Mustang Soccer"``, ``"Beach FC (CA)"`` →
        ``"Beach Futbol Club"``, ``"MVLA"`` →
        ``"Mountain View Los Altos Soccer Club"``). SOM Sports import-time
        extracts the raw, decorated club from the team name and would
        otherwise miss those canonicals because the strings don't share
        a substring after stripping. Running the same registry at
        import-time aligns the two so the gate hits.

        ``state_code`` is accepted for signature parity with the base's
        polymorphic dispatch and is used ONLY as the lookup key for the
        per-state override registry. It is NOT forwarded to ``super()``
        — the base ``_fuzzy_match_team`` signature has no ``state_code``
        parameter, and the location component of the base's scoring
        derives state from the provider_team dict (which has no
        state_code in the base flow either).
        """
        # Pre-strip SOM Sports decorations (coach suffix, birth-range tokens)
        # so the base's ``extract_distinctions`` doesn't pull the coach into
        # ``squad_words`` and hard-reject the candidate on the strict
        # set-equality check at game_matcher.py:1219.
        # Without this, ``"Mustang SC 2011B ECNL - Mittler"`` extracts
        # ``squad_words={"mittler", "mustang"}`` and never matches the
        # canonical ``"Mustang SC 2011 ECNL"`` (``squad_words={"mustang"}``).
        stripped_name = self._strip_somsports_decorations(team_name) or team_name

        effective_club = club_name
        if not effective_club and stripped_name and HAVE_TEAM_NAME_UTILS:
            effective_club = extract_club_from_team_name(stripped_name)

        if effective_club:
            canonical = canonicalize_club_name(state_code, effective_club)
            if canonical != effective_club:
                logger.debug(
                    "[SomSports] club canonicalized: %r -> %r (state=%s)",
                    effective_club,
                    canonical,
                    state_code,
                )
            effective_club = canonical

        return super()._fuzzy_match_team(stripped_name, age_group, gender, effective_club)

    # ------------------------------------------------------------------
    # Helpers for pre-scoring normalization
    # ------------------------------------------------------------------
    @classmethod
    def _strip_somsports_decorations(cls, name: Optional[str]) -> str:
        """Pre-scoring strip: drop coach suffix + birth-range tokens but
        keep tier markers (``ECNL``/``RL``/``MLS Next``) intact so the
        hygiene scorer's RL/ECNL alignment bonuses still see them.

        Critical for variant rejection: the hygiene scorer's
        ``extract_team_variant`` reads coach names off the raw provider
        name (``"Mustang SC 2011B ECNL - Mittler"`` → variant=``"Mittler"``),
        then refuses to compare against a canonical that has no matching
        variant. Stripping the coach upfront removes that false-negative.
        """
        return cls._pre_strip(name or "", strip_tier_markers=False)

    # ------------------------------------------------------------------
    # Scoring — delegate to the weekly hygiene pipeline's score_team_pair
    # ------------------------------------------------------------------
    def _calculate_match_score(self, provider_team: Dict, candidate: Dict) -> float:
        """Use the weekly hygiene pipeline's ``score_team_pair`` so SOM Sports
        import-time scoring aligns with the cutoffs the Monday
        ``find_queue_matches.py`` job uses when resolving the review queue:

        - **Club-word stripping pass** when clubs match — handles
          ``"FC PRE-ECNL 2014 Mee"`` vs ``"Fever United 2014 Mee"``.
        - **+0.15 club-identity boost** when normalized clubs match exactly.
        - **+0.05 RL alignment / +0.05 ECNL alignment** bonuses; **-0.08
          penalty on RL vs non-RL mismatch.**
        - **Variant rejection** via ``extract_team_variant`` — Mittler ≠
          Smith squads under the same club return ``None``.

        ``None`` from ``score_team_pair`` (variant mismatch / protected
        division) maps to ``0.0`` so the base loop's ``>= fuzzy_threshold``
        check naturally rejects it.

        **Known divergence from Monday hygiene queue resolution** — the
        base ``_fuzzy_match_team`` (game_matcher.py:1245-1274) applies a
        SECOND pass of the same league/club boosts on top of the score
        returned here, so SOM Sports import-time scoring is slightly more
        aggressive than the queue resolver. Net effect on U15: ~1-2
        additional auto-merges per cohort vs. strict hygiene parity.
        Accepted for now because the extra matches were the goal — the
        ones missed at import still flow through Monday's queue path.
        Tracked as a follow-up to align if the extra aggressiveness
        causes false positives.

        **Known limitation**: ``provider_team`` from base
        ``_fuzzy_match_team`` does not carry ``state_code``, so cross-state
        false positives are not penalized here. The base candidate
        retrieval (via ``ilike("club_name", X)``) already filters out most
        cross-state collisions because the Monday canonical-club registry
        assigns distinct names per state (e.g., ``"Beach Futbol Club"``
        for CA vs ``"Beach FC"`` for VA). If practice shows otherwise,
        the next iteration adds a state filter to the candidate query.
        """
        provider_name = self._strip_somsports_decorations(provider_team.get("team_name"))
        # Candidates come from canonical rows already standardized by the
        # Monday hygiene job; no SOM Sports decorations to strip.
        candidate_name = candidate.get("team_name", "") or ""

        score = score_team_pair(
            {
                "team_name": provider_name,
                "club_name": provider_team.get("club_name") or "",
            },
            {
                "team_name": candidate_name,
                "club_name": candidate.get("club_name") or "",
            },
        )
        if score is None:
            # Variant mismatch / protected division — distinct from a
            # genuine 0.0 score. Log at DEBUG so the difference is
            # surfaceable in a noisy import without polluting INFO.
            logger.debug(
                "[SomSports] score_team_pair rejected pair (variant/protected): %r vs %r",
                provider_name,
                candidate_name,
            )
            return 0.0
        return float(score)
