"""Where the game-reassignment tool writes its log: the folder --exports-dir names, or data/exports."""

import sys

from scripts import reassign_games_between_teams as reassign

FROM, TO = "aaaaaaaa-0000-4000-8000-000000000001", "bbbbbbbb-0000-4000-8000-000000000002"


def _team(team_id):
    return {"team_id_master": team_id, "team_name": f"Team {team_id[:4]}", "age_group": "u12", "gender": "Male",
            "state_code": "AZ"}


def _run(monkeypatch, tmp_path, *argv):
    games = [{"id": "g1", "game_date": "2026-09-05", "home_team_master_id": FROM, "away_team_master_id": "opp",
              "home_score": 2, "away_score": 1, "competition": "League"}]
    monkeypatch.setattr(reassign, "load_env", lambda: None)
    monkeypatch.setattr(reassign, "get_supabase", lambda require_service_role=False: object())
    monkeypatch.setattr(reassign, "fetch_team", lambda sb, team_id: _team(team_id))
    monkeypatch.setattr(reassign, "fetch_games", lambda sb, team_id, since, before: games)
    monkeypatch.setattr(reassign, "EXPORTS_DIR", tmp_path / "default")
    monkeypatch.setattr(sys, "argv", ["reassign_games_between_teams.py", "--from", FROM, "--to", TO,
                                      "--since", "2026-08-01", *argv])
    reassign.main()


def test_a_dry_run_log_lands_in_the_exports_dir_given(monkeypatch, tmp_path, capsys):
    store = tmp_path / "store with space"

    _run(monkeypatch, tmp_path, "--exports-dir", str(store))

    [log] = list(store.iterdir())
    assert log.name.startswith("reassign_games_between_teams_")
    assert not (tmp_path / "default").exists()
    assert f'--revert "{log}" --execute' in capsys.readouterr().out


def test_without_an_exports_dir_the_log_lands_in_the_default(monkeypatch, tmp_path):
    _run(monkeypatch, tmp_path)

    assert [p.name.startswith("reassign_games_between_teams_") for p in (tmp_path / "default").iterdir()] == [True]
