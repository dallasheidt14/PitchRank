"""Verify the production adapter selects exactly the measured complete profile."""
import sys
from dataclasses import asdict, replace
from types import SimpleNamespace

import pandas as pd
import pytest

import scripts.calculate_rankings as command
from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import RatingConvergenceError
from src.rankings import calculator
from src.rankings.layer13_predictive_adjustment import Layer13Config
from src.rankings.offline_publication import PublicationExperiment

AS_OF = pd.Timestamp('2026-10-12T00:00:00Z')


def fixture():
    rows = []
    for a, b, age, other in [('a', 'b', '11', '11'), ('c', 'd', '12', '12'), ('a', 'c', '11', '12')]:
        for i in range(12 if age == other else 4):
            gid = str(len(rows) // 2)
            for own, opp, own_age, opp_age, gf, ga in [
                (a, b, age, other, 3, 1), (b, a, other, age, 1, 3),
            ]:
                rows.append(dict(id=gid, game_id=gid, team_id=own, opp_id=opp,
                    date=AS_OF - pd.Timedelta(days=i+1), age=own_age, opp_age=opp_age,
                    gender='male', opp_gender='male', gf=gf, ga=ga))
    return pd.DataFrame(rows)


class Client:
    def table(self, name):
        assert name == 'teams'
        return self

    def select(self, columns):
        self.columns = columns
        return self

    def in_(self, *_):
        return self

    def eq(self, *_):
        return self

    def execute(self):
        if self.columns == 'team_id_master':
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=[dict(team_id_master=team, state_code='WA', league=None)
                                     for team in 'abcd'])


def test_profile_is_the_exact_measured_pair():
    cfg, policy = calculator._ranking_profile_configuration('reproducible-v2')
    assert asdict(cfg) == asdict(GlickoConfig(RATING_UPDATE_MODE='fixed-prior-mode-v2'))
    assert asdict(policy) == {'profile': 'support-continuous-v2', 'independent_prior_mass': 4., 'connectivity_floor': .5}
    assert command._resolve_ranking_profile('glicko') == 'reproducible-v2'
    assert command._resolve_ranking_profile('glicko', 'legacy') is None
    assert command._resolve_ranking_profile('v53e') is None
    with pytest.raises(ValueError):
        command._resolve_ranking_profile('v53e', 'reproducible-v2')


@pytest.mark.parametrize('fault', ['solver', 'damping', 'window', 'prior', 'unknown', 'engine'])
def test_profile_cannot_release_a_different_experiment(fault):
    cfg = GlickoConfig(RATING_UPDATE_MODE='fixed-prior-mode-v2')
    profile, use_glicko = 'reproducible-v2', True
    if fault == 'solver':
        cfg = replace(cfg, RATING_UPDATE_MODE='fixed-prior-v1')
    elif fault == 'damping':
        cfg = replace(cfg, FIXED_PRIOR_DAMPING=.4)
    elif fault == 'window':
        cfg = replace(cfg, MAX_GAMES=20)
    elif fault == 'prior':
        cfg = replace(cfg, INITIAL_SIGMA=300)
    elif fault == 'unknown':
        profile = 'support-bands-v1'
    else:
        use_glicko = False
    with pytest.raises(ValueError):
        calculator._require_offline_candidate(cfg, use_glicko=use_glicko,
            fetch_from_supabase=True, ranking_profile=profile, save_snapshot=True)


@pytest.mark.asyncio
async def test_named_profile_reaches_fetch_with_one_pinned_timestamp(monkeypatch):
    seen = []

    class ReachedFetch(Exception):
        pass

    async def fetch(**kwargs):
        seen.append(kwargs)
        raise ReachedFetch

    monkeypatch.setattr(calculator, 'fetch_games_for_rankings', fetch)
    with pytest.raises(ReachedFetch):
        await calculator.compute_all_cohorts(object(), today=AS_OF, ranking_profile='reproducible-v2')
    assert len(seen) == 1
    assert seen[0]['today'] == AS_OF.tz_localize(None)


@pytest.mark.asyncio
async def test_production_pair_matches_the_measured_offline_path_exactly(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    args = dict(supabase_client=Client(), games_df=fixture(), today=AS_OF,
        fetch_from_supabase=False, force_rebuild=True, ceiling_connectivity_enabled=True,
        layer13_cfg=Layer13Config(enabled=False), persist_game_residuals=False,
        persist_game_explainability=False, calculate_rank_changes_enabled=False, save_snapshot=False)
    expected = await calculator.compute_all_cohorts(**args,
        glicko_cfg=GlickoConfig(RATING_UPDATE_MODE='fixed-prior-mode-v2'),
        publication_policy=PublicationExperiment('support-continuous-v2'))
    original = calculator.compute_rankings_with_ml
    seen = []

    async def record(*positional, **kwargs):
        seen.append(kwargs['ctx'])
        return await original(*positional, **kwargs)

    monkeypatch.setattr(calculator, 'compute_rankings_with_ml', record)
    actual = await calculator.compute_all_cohorts(**args, ranking_profile='reproducible-v2')
    assert len(seen) == 4
    assert {context.pass_label for context in seen} == {'Pass1', 'Pass2'}
    assert all(context.ranking_profile == 'reproducible-v2' for context in seen)
    for key, frame in expected.items():
        if isinstance(frame, pd.DataFrame):
            pd.testing.assert_frame_equal(frame, actual[key], check_exact=True)
    assert not actual['publication_diagnostics'].policy_older_preserved.any()


@pytest.mark.asyncio
async def test_production_solver_failure_aborts_the_calculation(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fail(**_):
        raise RatingConvergenceError('deliberate non-convergence', {'converged': False})

    monkeypatch.setattr(calculator, 'compute_rankings_v2', fail)
    with pytest.raises(RatingConvergenceError):
        await calculator.compute_all_cohorts(Client(), games_df=fixture(), today=AS_OF,
            fetch_from_supabase=False, ranking_profile='reproducible-v2',
            persist_game_residuals=False, persist_game_explainability=False,
            calculate_rank_changes_enabled=False, save_snapshot=False)


@pytest.mark.asyncio
@pytest.mark.parametrize('flag,value', [('--age-group', 'u11'), ('--gender', 'Male'), ('--provider', 'gotsport')])
async def test_profile_cannot_publish_filtered_boards(monkeypatch, flag, value):
    monkeypatch.setattr(sys, 'argv', ['calculate_rankings.py', flag, value])
    monkeypatch.setattr(command, 'create_client', lambda *_: pytest.fail('Must refuse before creating a database client'))
    with pytest.raises(SystemExit) as error:
        await command.main()
    assert error.value.code == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('ml', [False, True])
@pytest.mark.parametrize('legacy', [False, True])
async def test_actual_cli_selects_profile_and_preserves_dry_run_flags(monkeypatch, ml, legacy):
    arguments = ['calculate_rankings.py', '--dry-run']
    if ml:
        arguments.append('--ml')
    if legacy:
        arguments += ['--ranking-profile', 'legacy']
    monkeypatch.setattr(sys, 'argv', arguments)
    monkeypatch.setenv('SUPABASE_URL', 'https://example.invalid')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'fixture-only')
    monkeypatch.setattr(command, 'create_client', lambda *_: object())
    monkeypatch.setattr(command, 'MergeResolver', lambda *_: SimpleNamespace(
        load_merge_map=lambda: None, has_merges=False, version='fixture'))
    seen = []

    async def compute(**kwargs):
        seen.append(kwargs)
        assert kwargs['ranking_profile'] == (None if legacy else 'reproducible-v2')
        assert kwargs['persist_game_residuals'] is False
        assert kwargs['persist_game_explainability'] is False
        assert kwargs['save_snapshot'] is False
        return {'teams': pd.DataFrame()}

    monkeypatch.setattr(command, 'compute_all_cohorts', compute)
    await command.main()
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('primary_games', [16, 30])
async def test_publication_evidence_uses_only_the_retained_source_solve(monkeypatch, tmp_path, primary_games):
    from src.rankings import offline_publication

    monkeypatch.chdir(tmp_path)
    frame = fixture()
    base = frame[frame.team_id.eq('a')].copy()
    additions = []
    for i in range(primary_games - len(base)):
        row = base.iloc[[i % len(base)]].copy()
        row['id'] = row['game_id'] = f'primary-extra-{i}'
        additions.append(row)
    discarded = base.head(4).copy()
    discarded['age'] = discarded['opp_age'] = '12'
    discarded['id'] = discarded['game_id'] = [f'discarded-{i}' for i in range(4)]
    discarded['gf'], discarded['ga'] = 0, 6
    frame = pd.concat([frame, *additions, discarded], ignore_index=True)
    original = offline_publication.evidence
    observed = []

    def record(selected, teams, *args):
        observed.append(selected.copy())
        return original(selected, teams, *args)

    monkeypatch.setattr(offline_publication, 'evidence', record)
    result = await calculator.compute_all_cohorts(Client(), games_df=frame, today=AS_OF,
        fetch_from_supabase=False, force_rebuild=True, ranking_profile='reproducible-v2',
        layer13_cfg=Layer13Config(enabled=False), persist_game_residuals=False,
        persist_game_explainability=False, calculate_rank_changes_enabled=False, save_snapshot=False)
    assert len(observed) == 1
    selected = observed[0].query("team_id == 'a'")
    assert len(selected) == primary_games
    assert set(selected.age) == {'11'}
    assert not selected.game_id.str.startswith('discarded-').any()
    assert result['teams'].query("team_id == 'a'").games_played.item() == primary_games
    assert result['games_used'].game_id.str.startswith('discarded-').any()
    assert '_publication_source_cohort' not in result['teams']
    assert '_publication_source_cohort' not in result['games_used']
