-- Create rankings_full table to store all v53E + Layer 13 ranking outputs
-- This comprehensive table preserves all ranking engine outputs for analytics and future features

CREATE TABLE IF NOT EXISTS rankings_full (
    team_id UUID REFERENCES teams(team_id_master) ON DELETE CASCADE PRIMARY KEY,
    
    -- Team identity (denormalized from teams table for performance)
    age_group TEXT NOT NULL,
    gender TEXT NOT NULL,
    state_code TEXT,
    
    -- Status & tracking
    status TEXT CHECK (status IN ('Active', 'Inactive', 'Not Enough Ranked Games')),
    last_game TIMESTAMPTZ,
    last_calculated TIMESTAMPTZ DEFAULT NOW(),
    
    -- Game statistics
    games_played INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    draws INTEGER DEFAULT 0,
    goals_for INTEGER DEFAULT 0,
    goals_against INTEGER DEFAULT 0,
    win_percentage FLOAT,
    
    -- Offense/Defense metrics (v53E Layer 2-5)
    off_raw FLOAT, -- Raw offensive strength (goals for per game, weighted)
    sad_raw FLOAT, -- Raw defensive weakness (goals against per game, weighted)
    off_shrunk FLOAT, -- Bayesian-shrunk offensive strength (Layer 7)
    sad_shrunk FLOAT, -- Bayesian-shrunk defensive weakness (Layer 7)
    def_shrunk FLOAT, -- Defensive strength (inverse of SAD with ridge regularization)
    off_norm FLOAT, -- Normalized offensive strength (Layer 9, percentile or z-score)
    def_norm FLOAT, -- Normalized defensive strength (Layer 9, percentile or z-score)
    
    -- Strength of Schedule (v53E Layer 8)
    sos FLOAT, -- Raw SOS value (direct opponent strength, iteratively refined)
    sos_norm FLOAT, -- Normalized SOS (percentile or z-score within cohort)
    strength_of_schedule FLOAT, -- Alias for sos (backward compatibility with current_rankings)
    
    -- Power Score layers (v53E Layer 10)
    power_presos FLOAT, -- Power score before SOS (OFF + DEF only)
    anchor FLOAT, -- Cross-age anchor value for normalization (Layer 11)
    abs_strength FLOAT, -- Absolute strength (power_presos / anchor, clipped to [0, 1.5])
    powerscore_core FLOAT, -- Core power score (OFF + DEF + SOS, before provisional)
    provisional_mult FLOAT, -- Provisional multiplier (0.85 if < 5 games, 0.95 if < 15 games, 1.0 otherwise)
    powerscore_adj FLOAT, -- Adjusted power score (core * provisional_mult * anchor scaling)
    
    -- Performance metrics (v53E Layer 6)
    perf_raw FLOAT, -- Raw performance delta (actual vs expected goal margin, recency-weighted)
    perf_centered FLOAT, -- Centered performance metric (~[-0.5, +0.5] within cohort)
    
    -- ML Layer fields (Layer 13)
    ml_overperf FLOAT, -- Raw ML residual per team (goal units, recency-weighted)
    ml_norm FLOAT, -- Cohort-normalized ML residual (~[-0.5, +0.5])
    powerscore_ml FLOAT, -- Final ML-adjusted power score (powerscore_adj + alpha * ml_norm)
    rank_in_cohort_ml INTEGER, -- Rank within cohort using ML-adjusted score
    
    -- Ranking fields
    rank_in_cohort INTEGER, -- Rank within age_group + gender cohort (using powerscore_adj)
    national_rank INTEGER, -- Rank using power_score_final (computed in view, stored for reference)
    state_rank INTEGER, -- State-specific rank (computed in view, stored for reference)
    global_rank INTEGER, -- Global rank across all ages (computed in view, stored for reference)
    
    -- Rank change tracking (from calculator.py)
    rank_change_7d INTEGER, -- Rank change over 7 days
    rank_change_30d INTEGER, -- Rank change over 30 days
    
    -- Final power scores (for views and backward compatibility)
    national_power_score FLOAT NOT NULL, -- Maps to powerscore_ml or powerscore_adj (primary power score)
    global_power_score FLOAT, -- Cross-age normalized (if computed)
    power_score_final FLOAT -- COALESCE(powerscore_ml, global_power_score, powerscore_adj)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_rankings_full_age_gender ON rankings_full(age_group, gender);
CREATE INDEX IF NOT EXISTS idx_rankings_full_state ON rankings_full(state_code) WHERE state_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_rankings_full_power_score ON rankings_full(power_score_final DESC) WHERE power_score_final IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_rankings_full_ml_score ON rankings_full(powerscore_ml DESC) WHERE powerscore_ml IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_rankings_full_national_rank ON rankings_full(age_group, gender, national_rank) WHERE national_rank IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_rankings_full_state_rank ON rankings_full(age_group, gender, state_code, state_rank) WHERE state_rank IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_rankings_full_last_calculated ON rankings_full(last_calculated DESC);

-- Comments for documentation
COMMENT ON TABLE rankings_full IS 'Comprehensive rankings table storing all v53E + Layer 13 engine outputs. Enables analytics, debugging, and future features.';
COMMENT ON COLUMN rankings_full.power_score_final IS 'Final power score with fallback: COALESCE(powerscore_ml, global_power_score, powerscore_adj)';
COMMENT ON COLUMN rankings_full.national_power_score IS 'Primary power score: powerscore_ml if ML enabled, otherwise powerscore_adj';
COMMENT ON COLUMN rankings_full.strength_of_schedule IS 'Alias for sos field, maintained for backward compatibility with current_rankings';

-- Enable Row Level Security (RLS) if needed
-- Note: RLS policies should be added if this table needs access control
-- For now, we'll rely on view-level RLS through rankings_view

