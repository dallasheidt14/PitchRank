import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_pack import analyze_pack, make_pack
from src.tournaments.seeding_predictions import SeedingPredictionBatch
from tests.unit.test_seeding_tiers import prediction


def preview_fixture():
    rows = parse_roster("Boys U14\n" + "\n".join(f"Club\tTeam {i}\tVA" for i in range(8))).rows
    ids = [str(i) for i in range(8)]
    teams = {key: {"team_id_master": f"00000000-0000-4000-8000-{int(key)+1:012d}",
                   "team_name": f"Team {key}", "power_score_final": 0.8-int(key)/100,
                   "prediction_game_count": 12, "games_played": 12, "age": 14, "gender": "M"} for key in ids}
    resolved = tuple(ResolvedTeam(int(key), "gotsport_id", team_id_master=team["team_id_master"])
                     for key, team in teams.items())

    def pairs(elite):
        result = {}
        for a in ids:
            for b in ids:
                if a == b:
                    continue
                margin = 3*(int(a in elite)-int(b in elite))
                result[a, b] = replace(prediction(margin), confidence="low", confidence_score=0,
                                        win_probability_a=0.8 if margin > 0 else 0.1 if margin < 0 else 0.45,
                                        win_probability_b=0.8 if margin < 0 else 0.1 if margin > 0 else 0.45)
        return result
    baseline = pairs(set(ids[:4]))
    changed = pairs({"7", "1", "2", "3"})
    variant = {"omitted_game_id": "observed-game", "kind": "game_removal", "predictions": [
        {"entrant_a": a, "entrant_b": b, **asdict(value)} for (a, b), value in changed.items()
        if value != baseline[a, b]
    ]}
    frozen = json.dumps({"model": "results", "teams": teams, "games": []})
    key = "u14|Male"
    batch = SeedingPredictionBatch(predictions={key: baseline}, teams={key: teams}, unavailable={key: {}},
                                    unavailable_codes={key: {}}, generated_at="2026-10-16T12:00:00Z",
                                    ratings_as_of=None, predictor_sha256="a"*64, model="results",
                                    evidence={key: {"canonical_json": frozen}},
                                    input_digests={key: hashlib.sha256(frozen.encode()).hexdigest()},
                                    sensitivity={key: [variant]})
    return make_pack(rows, resolved, {}, [key], batch, {}), rows, resolved


def test_observed_result_changes_seeds_and_tier_membership_and_cache_is_independent(monkeypatch):
    import src.tournaments.seeding_sensitivity as sensitivity
    pack, rows, resolved = preview_fixture()
    first = analyze_pack(pack, rows, resolved, {})["u14", "Male"].ordering_evidence["game_sensitivity"]
    assert first["changed_tier_memberships"] == 1
    assert first["seed_ranges"]["0"][1] == 5
    assert first["seed_ranges"]["7"][0] == 4
    monkeypatch.setattr(sensitivity, "_calculate_sensitivity", lambda *a, **k: pytest.fail("cache miss"))
    first["checks"].clear()
    second = analyze_pack(pack, rows, resolved, {})["u14", "Male"].ordering_evidence["game_sensitivity"]
    assert len(second["checks"]) == 1


def test_manual_holds_and_preferences_reopen_without_changing_frozen_order():
    pack, rows, resolved = preview_fixture()
    original_order = deepcopy(pack["ordering"])
    pack["manual_seed_orders"] = {"u14|Male": {"seeded": [str(i) for i in range(7)], "held": ["7"]}}
    pack["cohort_format_preferences"] = {"u14|Male": {"minimum_games": 4}}
    analysis = analyze_pack(json.loads(json.dumps(pack)), rows, resolved, {})["u14", "Male"]
    assert analysis.manual_holds == ("7",)
    assert "7" not in analysis.ordered_ids
    assert pack["ordering"] == original_order
    assert analysis.ordering_evidence["game_sensitivity"]["checks"]


@pytest.mark.parametrize("fault", ["empty", "duplicate", "asymmetric"])
def test_malformed_sensitivity_never_claims_stability(fault):
    pack, rows, resolved = preview_fixture()
    variants = pack["sensitivity_predictions"]["u14|Male"]
    if fault == "empty":
        variants[0]["predictions"] = []
    elif fault == "duplicate":
        variants.append(deepcopy(variants[0]))
    else:
        variants[0]["predictions"].pop()
    with pytest.raises(ValueError, match="sensitivity|orientations"):
        analyze_pack(pack, rows, resolved, {})


def test_field_only_instability_reaches_director_content_without_a_large_central_move():
    from src.tournaments.seeding_content import build_director_cohort
    from src.tournaments.seeding_sheet import CohortSheet, SheetTeam

    pack, rows, resolved = preview_fixture()
    analysis = analyze_pack(pack, rows, resolved, {})["u14", "Male"]
    evidence = deepcopy(analysis.ordering_evidence)
    evidence.pop("game_sensitivity")
    evidence["prediction_model"] = "cohort"
    evidence["teams"]["0"].update(field_sensitivity_seeds=[1, 3], cautions=["Field sensitivity: seeds 1–3"])
    analysis = replace(analysis, ordering_evidence=evidence)
    sheet = CohortSheet("u14", "Male", tuple(SheetTeam(f"Team {i}", "Club", .8-i/100, entrant_id=str(i))
                                            for i in range(8)), (), tier_analysis=analysis)
    assert any("Field sensitivity: seeds 1–3" in note for note in build_director_cohort(sheet).notes)
