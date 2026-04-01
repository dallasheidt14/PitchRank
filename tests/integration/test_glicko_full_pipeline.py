from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import compute_rankings_v2


class TestGlickoFullPipeline:
    """Integration test: 20-team synthetic league through the full Glicko-2 pipeline."""

    @pytest.fixture
    def synthetic_league(self):
        """Create a 20-team league with known strength ordering."""
        np.random.seed(42)
        cfg = GlickoConfig()
        today = pd.Timestamp('2026-03-31')

        # 4 tiers of 5 teams each
        tiers = {
            'elite': {'teams': [f'elite_{i}' for i in range(5)], 'strength': 3.0},
            'good': {'teams': [f'good_{i}' for i in range(5)], 'strength': 2.0},
            'average': {'teams': [f'avg_{i}' for i in range(5)], 'strength': 1.0},
            'weak': {'teams': [f'weak_{i}' for i in range(5)], 'strength': 0.0},
        }

        all_teams = []
        team_tier = {}
        team_strength = {}
        for tier_name, tier_info in tiers.items():
            for team in tier_info['teams']:
                all_teams.append(team)
                team_tier[team] = tier_name
                team_strength[team] = tier_info['strength']

        # Generate ~100 games
        rows = []
        game_count = 0
        # Each team plays ~10 games against various opponents
        for team in all_teams:
            opponents = [t for t in all_teams if t != team]
            chosen = np.random.choice(opponents, size=min(10, len(opponents)), replace=False)
            for opp in chosen:
                # Already generated this matchup?
                if any(r['team_id'] == opp and r['opp_id'] == team for r in rows):
                    continue

                # Generate score based on strength difference
                diff = team_strength[team] - team_strength[opp]
                # Expected goals for team: base 1.5 + 0.5 * diff
                exp_gf = max(0.5, 1.5 + 0.5 * diff)
                exp_ga = max(0.5, 1.5 - 0.5 * diff)
                gf = max(0, int(np.random.poisson(exp_gf)))
                ga = max(0, int(np.random.poisson(exp_ga)))

                date = pd.Timestamp('2026-01-01') + pd.Timedelta(days=game_count)
                rows.append({
                    'team_id': team, 'opp_id': opp,
                    'gf': gf, 'ga': ga,
                    'date': date, 'age': 'U15', 'gender': 'M',
                    'opp_age': 'U15', 'opp_gender': 'M',
                })
                rows.append({
                    'team_id': opp, 'opp_id': team,
                    'gf': ga, 'ga': gf,
                    'date': date, 'age': 'U15', 'gender': 'M',
                    'opp_age': 'U15', 'opp_gender': 'M',
                })
                game_count += 1

        games_df = pd.DataFrame(rows)
        return games_df, cfg, today, team_tier, team_strength

    def test_ranking_matches_known_ordering(self, synthetic_league):
        """Output ranking should roughly match the tier ordering."""
        games_df, cfg, today, team_tier, team_strength = synthetic_league
        result = compute_rankings_v2(games_df, today=today, cfg=cfg)
        teams = result['teams']

        # Map each team to its true strength and computed mu
        true_strengths = []
        computed_mus = []
        for _, row in teams.iterrows():
            true_strengths.append(team_strength[row['team_id']])
            computed_mus.append(row['mu'])

        corr, pval = spearmanr(true_strengths, computed_mus)
        assert corr > 0.8, f"Spearman correlation {corr:.3f} too low (expected > 0.8)"

    def test_all_columns_present(self, synthetic_league):
        """All rankings_full columns should be present."""
        games_df, cfg, today, _, _ = synthetic_league
        result = compute_rankings_v2(games_df, today=today, cfg=cfg)
        teams = result['teams']

        critical_cols = [
            'team_id', 'powerscore_adj', 'off_norm', 'def_norm',
            'sos_norm', 'national_rank', 'status', 'games_played',
            'power_score_final', 'provisional_mult',
        ]
        for col in critical_cols:
            assert col in teams.columns, f"Missing: {col}"

    def test_no_nan_in_critical_columns(self, synthetic_league):
        """Critical columns should not have NaN for active teams."""
        games_df, cfg, today, _, _ = synthetic_league
        result = compute_rankings_v2(games_df, today=today, cfg=cfg)
        teams = result['teams']
        active = teams[teams['status'] == 'Active']

        for col in ['powerscore_adj', 'off_norm', 'def_norm', 'sos_norm', 'mu']:
            nan_count = active[col].isna().sum()
            assert nan_count == 0, f"Found {nan_count} NaN in {col}"

    def test_elite_teams_rank_higher(self, synthetic_league):
        """Elite teams should generally rank higher than weak teams."""
        games_df, cfg, today, team_tier, _ = synthetic_league
        result = compute_rankings_v2(games_df, today=today, cfg=cfg)
        teams = result['teams']

        elite_mu = teams[teams['team_id'].isin([f'elite_{i}' for i in range(5)])]['mu'].mean()
        weak_mu = teams[teams['team_id'].isin([f'weak_{i}' for i in range(5)])]['mu'].mean()
        assert elite_mu > weak_mu, "Elite teams should have higher average mu"

    def test_sos_correlates_with_opponent_quality(self, synthetic_league):
        """SOS should correlate with the average mu of opponents faced."""
        games_df, cfg, today, _, _ = synthetic_league
        result = compute_rankings_v2(games_df, today=today, cfg=cfg)
        teams = result['teams']

        mu_map = dict(zip(teams['team_id'], teams['mu']))

        # Compute average opponent mu for each team
        avg_opp_mu = (
            games_df.assign(opp_mu=games_df['opp_id'].map(mu_map))
            .groupby('team_id')['opp_mu']
            .mean()
            .rename('avg_opp_mu')
        )
        merged = teams.merge(avg_opp_mu, on='team_id', how='inner')

        corr, _ = spearmanr(merged['avg_opp_mu'], merged['sos_raw'])
        assert corr > 0.7, f"SOS-vs-opponent-mu Spearman {corr:.3f} too low (expected > 0.7)"
