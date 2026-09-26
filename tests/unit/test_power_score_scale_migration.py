from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260925120000_add_versioned_power_score_scale.sql"
)


def _alter_block(sql: str, table: str) -> str:
    marker = f"ALTER TABLE public.{table}"
    start = sql.index(marker)
    end = sql.index(";", start)
    return sql[start:end]


def test_migration_adds_versioned_prediction_fields_to_all_persisted_surfaces():
    sql = MIGRATION.read_text(encoding="utf-8")

    rankings = _alter_block(sql, "rankings_full")
    history = _alter_block(sql, "ranking_history")
    prediction_history = _alter_block(sql, "prediction_feature_history")

    assert "prediction_power_score DOUBLE PRECISION" in rankings
    assert "power_score_scale_version TEXT" in rankings
    assert "power_score_true DOUBLE PRECISION" in history
    assert "prediction_power_score DOUBLE PRECISION" in history
    assert "power_score_scale_version TEXT" in history
    assert "prediction_power_score DOUBLE PRECISION" in prediction_history
    assert "power_score_scale_version TEXT" in prediction_history


def test_migration_constrains_versioned_rows_to_have_bounded_prediction_scores():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert sql.count("prediction_power_score BETWEEN 0.0 AND 1.0") == 3
    assert sql.count("power_score_scale_version IS NULL OR prediction_power_score IS NOT NULL") == 3
