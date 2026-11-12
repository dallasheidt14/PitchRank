from src.predictions.challenger_capture import candidate_definition
from src.predictions.form_policy import PINNED_REVISION


def qualification_report():
    return {"status": "qualifies_for_confirmation", "production_promotion": False, "aa_parity": True,
            "evaluation_status": "performed", "selected_candidate": "residual_sequence",
            "policy": {"predictor_revision": PINNED_REVISION, "evaluation_end": "2026-01-01"},
            "server_observed_at": "2026-01-02T00:00:00Z", "dataset_sha256": "d" * 64,
            "study_manifest_sha256": "e" * 64, "log_loss_delta_95": [-.1, -.01],
            "evaluation": {"baseline": {"brier_score": .5}, "candidate": {"brier_score": .4}},
            "audit": {"periods": {period: {"games": 1000, "groups": 20}
                                   for period in ("development", "evaluation")}}}


def manifest():
    sources = {"src/predictions/form_research.py": "b" * 64}
    return candidate_definition(qualification_report(), "a" * 40, sources, reviewed=True, qualified_sources=sources)
