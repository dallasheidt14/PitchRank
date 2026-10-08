"""Rebuild the generic, arithmetic-checked format catalog from reusable families."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from src.tournaments.seeding_format_mechanics import (
    calculate_format_games,
    knockout_stages,
    partial_matches,
    pool_slots,
    rank_stage,
    round_robin_matches,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/references/youth-soccer-tournament-formats-2026-10.source.md"
SOURCE_ID = "format-field-guide-2026-10"


def build_catalog() -> dict:
    legacy = json.loads((ROOT / "config/matchbalance_format_library_v1.json").read_text())
    catalog = deepcopy(legacy)
    catalog.update(schema_version=2, library_version="2.0.0")
    catalog["source_documents"].append(
        {
            "source_id": SOURCE_ID,
            "title": "Youth Soccer Tournament Formats by Number of Teams",
            "sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            "location": SOURCE.relative_to(ROOT).as_posix(),
            "verification_status": "generic_mechanics_calculated_source_claims_separate",
            "note": "Generic options derived from the supplied guide; no named event endorsement. "
            "Protocol 515 and Soccer Showcase advancement descriptions checked on 2026-10-08; "
            "source arithmetic corrections are recorded in docs/matchbalance-format-reference.md.",
        }
    )
    templates, coverage = [], []

    def add(
        slug,
        sizes,
        play="round_robin",
        *,
        games=3,
        cross=(),
        advance=0,
        top=1,
        wildcard=0,
        wildcard_rank=None,
        overall=False,
        placement=False,
        silver=False,
        special=None,
        label=None,
    ):
        slots = pool_slots(sizes)
        flat = sum(slots, [])
        matches, stages = [], []
        crossed = {index for pair in cross for index in pair}
        for index, pool in enumerate(slots):
            if index not in crossed:
                if play in {"partial_round_robin", "league_phase"}:
                    matches.extend(partial_matches(pool, games))
                elif play != "knockout":
                    matches.extend(round_robin_matches(pool, 2 if play == "double_round_robin" else 1))
        for first, second in cross:
            if play == "partial_crossover":
                matches.extend(
                    [
                        [a, slots[second][(i + shift) % len(slots[second])]]
                        for i, a in enumerate(slots[first])
                        for shift in range(games)
                    ]
                )
            else:
                matches.extend([[a, b] for a in slots[first] for b in slots[second]])
        if special == "own_plus_cross":
            matches.extend([[a, b] for a, b in zip(slots[0], slots[1], strict=True)])
        if special == "ghost":
            # Exact generic variant: each three-team-pool entrant plays a different
            # four-team-pool entrant; those opponents receive one extra game.
            small = next(pool for pool in slots if len(pool) == 3)
            large = next(pool for pool in slots if len(pool) == 4)
            matches.extend([[a, b] for a, b in zip(small, large)])

        rankings = []
        if advance or silver or special in {"points_match", "third_crossover", "gothia", "ecnl66"}:
            rankings = (
                [rank_stage(stages, "table", flat)]
                if overall
                else [rank_stage(stages, f"pool{i + 1}", pool) for i, pool in enumerate(slots)]
            )
        if special == "points_match":
            table = rankings[0]
            stages.append(
                {
                    "kind": "match",
                    "round": "points",
                    "playoff": False,
                    "inputs": table[1:],
                    "outputs": ["points:W", "points:L"],
                }
            )
            points = rank_stage(stages, "cumulative", ["points:W", "points:L"])
            stages[-1]["ranking_rule"] = "Cumulative points from round robin and the extra points match; "
            stages[-1]["ranking_rule"] += "then goal difference, goals scored, and original anonymous slot number."
            knockout_stages(stages, [table[0], points[0]], "title")
        elif special == "third_crossover":
            contenders = []
            for i, pool in enumerate(rankings):
                outputs = [f"cross{i}:W", f"cross{i}:L"]
                stages.append(
                    {
                        "kind": "match",
                        "round": "crossover",
                        "playoff": False,
                        "inputs": [pool[1], rankings[(i - 1) % 3][2]],
                        "outputs": outputs,
                    }
                )
                contenders.extend(outputs)
            wild = rank_stage(stages, "cumulative", contenders)
            stages[-1]["ranking_rule"] = "Cumulative points per game including crossover results; "
            stages[-1]["ranking_rule"] += "then goal difference per game, goals per game, and original slot number."
            knockout_stages(stages, [pool[0] for pool in rankings] + wild[:1], "title")
        elif special == "gothia":
            table = rankings[0]
            knockout_stages(stages, table[:4], "championship")
            knockout_stages(stages, table[4:8], "consolation")
            for i in range(8, len(table), 2):
                knockout_stages(stages, table[i : i + 2], f"placement{i}")
        elif special == "ecnl66":
            qualifiers = [pool[0] for pool in rankings[:15]]
            knockout_stages(stages, [pool[0] for pool in rankings[15:]], "playin")
            qualifiers.append("playin:r1:m1:W")
            knockout_stages(stages, qualifiers, "title")
        elif advance:
            if overall:
                qualifiers = rankings[0][:advance]
            else:
                qualifiers = [item for pool in rankings for item in pool[:top]]
                if wildcard:
                    remaining = [
                        item
                        for pool in rankings
                        for item in (pool[wildcard_rank - 1 : wildcard_rank] if wildcard_rank else pool[top:])
                    ]
                    wild = rank_stage(stages, "wildcard", remaining)
                    qualifiers += wild[:wildcard]
                if special == "four_winner_plus_best":
                    qualifiers = [rankings[0][0]]
                    remaining = rankings[0][1:] + sum(rankings[1:], [])
                    qualifiers += rank_stage(stages, "best", remaining)[:3]
                if special == "four_winners_plus_cross":
                    qualifiers = [pool[0] for pool in rankings[:2]]
                    qualifiers += rank_stage(stages, "cross_table", sum(rankings[2:], []))[:2]
                if special == "eighteen_combined":
                    combined = rank_stage(stages, "cross_table", sum(rankings[3:], []))
                    # Builder pairs first vs last, then second vs next-to-last.
                    qualifiers = [
                        rankings[0][1],
                        rankings[1][1],
                        rankings[2][1],
                        combined[1],
                        rankings[1][0],
                        rankings[0][0],
                        rankings[2][0],
                        combined[0],
                    ]
            if len(qualifiers) != advance:
                raise ValueError(f"{slug}: qualifier count does not match advancement.")
            knockout_stages(stages, qualifiers, "title", placement=placement)
            if silver:
                remaining = [item for pool in rankings for item in pool[top:]]
                knockout_stages(stages, remaining, "silver", placement=placement)
            if special == "third_place":
                knockout_stages(stages, [pool[2] for pool in rankings], "third")
            if special == "round32_consolation":
                knockout_stages(stages, [f"title:r1:m{i + 1}:L" for i in range(16)], "consolation")
        elif play == "knockout":
            knockout_stages(stages, flat, "title", placement=placement)
        structure = {"preliminary_matches": matches, "stages": stages}
        counts = calculate_format_games(len(flat), structure)
        unequal = len(set(counts.preliminary_games_by_slot)) > 1
        special_titles = {
            "points_match": "Round robin, extra points match and final",
            "third_crossover": "Round robin, third crossover and semifinals",
            "gothia": "Four-game league with championship and placement paths",
            "ecnl66": "Mixed pools, play-in and 16-team knockout",
            "round32_consolation": "Knockout with first-round consolation",
        }
        title = label or special_titles.get(special) or play.replace("_", " ").capitalize()
        if cross and label is None:
            title = "Mixed pools and crossover" if len(sizes) > 2 else "Crossover"
        if advance and play != "knockout" and special not in special_titles:
            title += " with " + {2: "final", 4: "semifinals", 8: "quarterfinals"}.get(
                advance, f"{advance}-team knockout"
            )
        if silver:
            title += " and consolation"
        if placement:
            title += " and placement games"
        if not counts.has_playoffs:
            description = "Standings determine finish; no knockout playoffs."
        elif special == "points_match":
            description = "First place advances to the final; second and third play once more for cumulative "
            description += "points, which determine the other finalist."
        elif special == "third_crossover":
            description = "Three pool winners and the best remaining team after crossovers enter semifinals."
        elif special == "gothia":
            description = "Top four enter championship semifinals; next four enter consolation semifinals; "
            description += "remaining adjacent standings positions play one placement game."
        elif special == "ecnl66":
            description = "Fifteen four-team pool winners qualify; two three-team pool winners play for the "
            description += "last place in the 16-team knockout."
        elif play == "knockout":
            description = f"All {len(flat)} teams enter a knockout; top-ranked slots receive any first-round byes."
            if special == "round32_consolation":
                description += " First-round losers enter a separate 16-team consolation knockout."
        elif special == "eighteen_combined":
            description = "Top two in each four-team pool and the top two in the combined crossover table "
            description += "enter quarterfinals."
        elif overall:
            description = f"Top {advance} in the combined standings enter the championship knockout."
        else:
            description = f"{advance} teams qualify: top {top} per pool"
            if wildcard_rank:
                description += f" plus the best {wildcard} teams finishing at pool rank {wildcard_rank}."
            else:
                description += f" plus {wildcard} best remaining wildcard slots." if wildcard else "."
            if special == "four_winner_plus_best":
                description = "Four-team pool winner plus the best three remaining teams enter semifinals."
            elif special == "four_winners_plus_cross":
                description = "Two four-team pool winners plus the top two combined crossover teams enter semifinals."
        if silver:
            description += " Remaining teams enter a separate consolation knockout."
        if placement:
            description += " Losing branches continue through placement matches."
        if special == "third_place":
            description += " The two third-place teams play a consolation match."
        if advance and advance & (advance - 1):
            description += " Highest-ranked qualifiers receive first-round byes."
        template_id = f"mb-expanded-{slug}-v2"
        templates.append(
            {
                "template_id": template_id,
                "version": 2,
                "team_count": len(flat),
                "pool_sizes": sizes,
                "preliminary_play_type": play,
                "advancement_description": description,
                "championship_type": "knockout" if counts.has_playoffs else "standings_only",
                "minimum_guaranteed_games_per_team": counts.minimum_games,
                "maximum_possible_games_per_team": counts.maximum_games,
                "total_matches": counts.total_matches,
                "maximum_pair_meetings": counts.maximum_pair_meetings,
                "display_name": title,
                "playing_structure": structure,
                "unequal_pool_requirements": [
                    "Use points per game for unequal preliminary game counts; "
                    "all played games still count toward the game guarantee."
                ]
                if unequal
                else [],
                "operational_requirements": [
                    "Anonymous slots describe format mechanics, not team assignments or a timetable."
                ],
                "unresolved_assumptions": [],
                "source_id": SOURCE_ID,
                "source_section": slug,
                "rule_year": None,
                "provenance_status": "generic_mathematically_valid_not_official_event_rules",
                "availability_status": "enabled",
                "blocked_reason": None,
            }
        )
        return template_id

    def record(entry, *ids, reason=None):
        coverage.append(
            {
                "source_entry": entry,
                "template_ids": list(ids),
                "status": "enabled_generic_equivalent" if ids else "reference_only",
                "reason": reason or "Exact generic mechanics; event-specific seeding/tiebreak rules remain separate.",
            }
        )

    for n in range(3, 17):
        add(f"{n}-rr", [n])

    def rr(n):
        return f"mb-expanded-{n}-rr-v2"

    record("3A", add("3-final", [3], advance=2, overall=True))
    record("3B", add("3-double", [3], "double_round_robin"))
    record("3C", add("3-points", [3], special="points_match"))
    record("3D", reason="Merging cohorts or adding guest entrants changes the roster and requires a director decision.")
    record("4A", rr(4))
    record("4B", add("4-final", [4], advance=2, overall=True))
    record("4C", add("4-placement", [4], advance=2, silver=True, top=2))
    record("4D", add("4-knockout-placement", [4], "knockout", placement=True))
    record("5A", rr(5))
    record("5B", add("5-final", [5], advance=2, overall=True))
    record(
        "5C",
        add("5-partial", [5], "partial_round_robin"),
        add("5-partial-final", [5], "partial_round_robin", advance=2, overall=True),
        reason="Generic schedule gives one slot four matches and four slots three; points per game used.",
    )
    record("5D", add("5-playin", [5], "partial_round_robin", games=2, advance=5, overall=True))
    record("6A", add("6-cross-semis", [3, 3], "crossover", cross=((0, 1),), advance=4, overall=True))
    record("6B", add("6-own-cross-semis", [3, 3], special="own_plus_cross", advance=4, overall=True))
    record("6C", add("6-cross-final", [3, 3], "crossover", cross=((0, 1),), advance=2, overall=True))
    record("6D", add("6-consolation", [3, 3], advance=4, top=2, special="third_place"))
    record("6E", rr(6))
    record("6F", add("6-partial-final", [6], "partial_round_robin", advance=2, overall=True))
    record("7A", add("7-mixed", [4, 3], advance=4, wildcard=2))
    record("7B", add("7-ghost", [4, 3], special="ghost", advance=4, wildcard=2))
    record("7C", add("7-playin", [7], "partial_round_robin", games=2, advance=7, overall=True))
    record("8A", add("8-final", [4, 4], advance=2))
    record("8B", add("8-semis", [4, 4], advance=4, top=2))
    record(
        "8C",
        add("8-gold-silver", [4, 4], advance=4, top=2, silver=True),
        add("8-all-placement", [4, 4], advance=4, top=2, silver=True, placement=True),
        reason="18 matches gives four or five games each; 20 with placement gives every team five.",
    )
    record(
        "8D",
        add("8-full-cross", [4, 4], "crossover", cross=((0, 1),)),
        add("8-partial-cross", [4, 4], "partial_crossover", cross=((0, 1),)),
        reason="Full crossover is 16 matches/four each; partial crossover is 12 matches/three each.",
    )
    record("8E", add("8-knockout", [8], "knockout"), add("8-knockout-placement", [8], "knockout", placement=True))
    record("9A", add("9-mixed", [3, 3, 3], advance=4, wildcard=1))
    record("9B", add("9-third-cross", [3, 3, 3], special="third_crossover"))
    record(
        "9C",
        add("9-four-five", [4, 5], advance=2),
        reason="4+5 full round robins implemented. Unspecified three-pool crossover needs an exact opponent pattern.",
    )
    record(
        "10A",
        add(
            "10-overall",
            [4, 3, 3],
            "mixed_round_robin_and_crossover",
            cross=((1, 2),),
            advance=4,
            top=0,
            special="four_winner_plus_best",
        ),
    )
    record(
        "10B", add("10-winners", [4, 3, 3], "mixed_round_robin_and_crossover", cross=((1, 2),), advance=4, wildcard=1)
    )
    ten_fives = add("10-fives", [5, 5], advance=4, top=2)
    record("10C", ten_fives)
    record("5E", ten_fives, reason="Two pools of five is a ten-team division, not a five-team format.")
    record("10D", add("10-partial-fives", [5, 5], "partial_round_robin", advance=4, top=2))
    record("11A", add("11-mixed", [4, 4, 3], advance=4, wildcard=1))
    record("11B", add("11-ghost", [4, 4, 3], advance=4, wildcard=1, special="ghost"))
    record("12A", add("12-semis", [4, 4, 4], advance=4, wildcard=1))
    record("12B", add("12-quarterfinals", [4, 4, 4], advance=8, wildcard=5))
    record(
        "12C",
        add("12-threes", [3] * 4, advance=4),
        add("12-threes-cross", [3] * 4, "crossover", cross=((0, 1), (2, 3)), advance=4),
    )
    record(
        "12D",
        add("12-partial-sixes-final", [6, 6], "partial_round_robin", advance=2),
        add("12-partial-sixes-semis", [6, 6], "partial_round_robin", advance=4, top=2),
    )
    record("12E", add("12-league-three", [12], "league_phase"), add("12-league-four", [12], "league_phase", games=4))
    record("13A", add("13-mixed", [4, 3, 3, 3], advance=4))
    record(
        "14A",
        add(
            "14-overall",
            [4, 4, 3, 3],
            "mixed_round_robin_and_crossover",
            cross=((2, 3),),
            advance=4,
            top=0,
            special="four_winners_plus_cross",
        ),
    )
    record("14B", add("14-winners", [4, 4, 3, 3], "mixed_round_robin_and_crossover", cross=((2, 3),), advance=4))
    record("15A", add("15-mixed", [4, 4, 4, 3], advance=4))
    record("16A", add("16-semis", [4] * 4, advance=4))
    record("16B", add("16-quarterfinals", [4] * 4, advance=8, top=2))
    record("16C", add("16-league-placement", [16], "league_phase", games=4, overall=True, special="gothia"))
    record(
        "18A",
        add(
            "18-mixed",
            [4, 4, 4, 3, 3],
            "mixed_round_robin_and_crossover",
            cross=((3, 4),),
            advance=8,
            top=0,
            special="eighteen_combined",
        ),
        reason="Three four-team tables plus the combined six-team crossover table each supply two qualifiers; "
        "quarterfinal pairings follow the 2024 East Region diagram; generic standings tiebreaks remain separate.",
    )
    record("20A", add("20-quarterfinals", [4] * 5, advance=8, wildcard=3))
    record(
        "20B",
        add("20-final16", [4] * 5, advance=16, top=3, wildcard=1),
        reason="Championship path defined; "
        "the source does not specify the four excluded teams' showcase opponent schedule.",
    )
    record("24A", add("24-quarterfinals", [4] * 6, advance=8, wildcard=2))
    record(
        "24B",
        add("24-final16", [4] * 6, advance=16, top=2, wildcard=4, wildcard_rank=3),
        reason="Generic 16-team knockout; unspecified later showcase games are excluded from guarantees.",
    )
    record("24C", add("24-league-placement", [24], "league_phase", games=4, overall=True, special="gothia"))
    record("32A", add("32-consolation", [32], "knockout", advance=32, overall=True, special="round32_consolation"))
    record("32B", add("32-knockout", [32], "knockout"))
    record("32C", add("32-final16", [4] * 8, advance=16, top=2), add("32-quarterfinals", [4] * 8, advance=8))
    record("48A", add("48-final16", [4] * 12, advance=16, wildcard=4, wildcard_rank=2))
    record(
        "48B",
        add("48-final32", [4] * 12, advance=32, top=2, wildcard=8, wildcard_rank=3),
        reason="Generic arithmetic-valid arrangement; not claimed as a youth-event standard.",
    )
    record(
        "48C", reason="The supplied 2027 announcement does not define an exact bracket; no future event rules inferred."
    )
    record(
        "64+A",
        add("66-playin", [4] * 15 + [3, 3], special="ecnl66"),
        reason="Complete generic title path, including the small-pool winners' play-in; event-phase dates not modeled.",
    )
    record(
        "64+B",
        add("52-qualifier", [4] * 13),
        add("64-qualifier", [4] * 16),
        reason="Group standings only; qualification to another event does not promise extra games here.",
    )
    record(
        "64+C",
        add("64-a-b", [4] * 16, advance=32, top=2, silver=True),
        reason="Exact 64-team generic A/B variant; "
        "unspecified hundreds-of-teams layouts require an exact count and pool structure.",
    )
    catalog["templates"].extend(templates)
    for profile in catalog["profiles"]:
        profile["is_default"] = False
    expanded = deepcopy(legacy["profiles"][0])
    expanded.update(
        profile_id="matchbalance-expanded-v2",
        version=2,
        is_default=True,
        display_name="Automatic cohort formats",
        template_ids=[item["template_id"] for item in templates],
        preferred_template_ids_by_team_count={},
        required_minimum_games_per_team=None,
        source_note="Generic MatchBalance formats; game requirements are optional.",
        provenance_status="generic_validated_mechanics_not_official_event_profile",
        unresolved_assumptions=["Field, rest, referee and timetable feasibility remain the director's responsibility."],
        format_selection="practical_default",
        exact_search_enabled=True,
        maximum_search_states=1000000,
    )
    catalog["profiles"].append(expanded)
    catalog["source_coverage"] = coverage
    return catalog


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", "--dry-run", action="store_true", help="Check reproducibility without writing files."
    )
    args = parser.parse_args()
    target = ROOT / "config/matchbalance_format_library.json"
    content = json.dumps(build_catalog(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        raise SystemExit(0 if target.read_text(encoding="utf-8") == content else "Format catalog needs regeneration.")
    target.write_text(content, encoding="utf-8")
