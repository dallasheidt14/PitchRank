-- Propagate game exclusion to duplicate rows
-- When is_excluded is set TRUE on a game, auto-propagate to all duplicate
-- game rows (same date, same master team pair, same scores) that represent
-- the same physical game scraped from different perspectives (event scraper
-- vs team scraper, or different teams' schedules).
-- Date: 2026-03-25

-- =====================================================
-- Step 1: Propagation trigger function
-- =====================================================

CREATE OR REPLACE FUNCTION propagate_game_exclusion()
RETURNS TRIGGER AS $$
DECLARE
  updated_count INTEGER;
  sorted_id_1 UUID;
  sorted_id_2 UUID;
  score_for_id_1 INTEGER;
  score_for_id_2 INTEGER;
BEGIN
  -- Only fire when is_excluded changes from FALSE to TRUE
  IF NEW.is_excluded = TRUE AND OLD.is_excluded = FALSE THEN
    -- Only propagate if both master IDs are resolved
    IF NEW.home_team_master_id IS NOT NULL AND NEW.away_team_master_id IS NOT NULL THEN
      -- Sort master IDs for consistent matching regardless of home/away orientation
      IF NEW.home_team_master_id < NEW.away_team_master_id THEN
        sorted_id_1 := NEW.home_team_master_id;
        sorted_id_2 := NEW.away_team_master_id;
        score_for_id_1 := NEW.home_score;
        score_for_id_2 := NEW.away_score;
      ELSE
        sorted_id_1 := NEW.away_team_master_id;
        sorted_id_2 := NEW.home_team_master_id;
        score_for_id_1 := NEW.away_score;
        score_for_id_2 := NEW.home_score;
      END IF;

      -- Update all duplicate rows: same date, same team pair, same scores
      -- Handles both orientations (home/away swapped)
      UPDATE games
      SET is_excluded = TRUE
      WHERE id != NEW.id
        AND is_excluded = FALSE
        AND game_date = NEW.game_date
        AND home_team_master_id IS NOT NULL
        AND away_team_master_id IS NOT NULL
        AND (
          -- Same orientation as sorted pair
          (LEAST(home_team_master_id, away_team_master_id) = sorted_id_1
           AND GREATEST(home_team_master_id, away_team_master_id) = sorted_id_2
           AND CASE WHEN home_team_master_id < away_team_master_id
                    THEN home_score ELSE away_score END IS NOT DISTINCT FROM score_for_id_1
           AND CASE WHEN home_team_master_id < away_team_master_id
                    THEN away_score ELSE home_score END IS NOT DISTINCT FROM score_for_id_2)
        );

      GET DIAGNOSTICS updated_count = ROW_COUNT;
      IF updated_count > 0 THEN
        RAISE LOG 'propagate_game_exclusion: excluded % duplicate(s) matching game % on %',
          updated_count, NEW.id, NEW.game_date;
      END IF;
    END IF;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- Step 2: Attach trigger to games table
-- =====================================================

DROP TRIGGER IF EXISTS trg_propagate_game_exclusion ON games;

CREATE TRIGGER trg_propagate_game_exclusion
  AFTER UPDATE OF is_excluded ON games
  FOR EACH ROW
  EXECUTE FUNCTION propagate_game_exclusion();

-- =====================================================
-- Step 3: RPC to bulk-exclude games for a team in a date range
-- =====================================================

CREATE OR REPLACE FUNCTION exclude_games_for_team_in_range(
  p_team_id UUID,
  p_start_date DATE,
  p_end_date DATE,
  p_dry_run BOOLEAN DEFAULT TRUE
)
RETURNS TABLE(
  game_id UUID,
  game_date DATE,
  home_master UUID,
  away_master UUID,
  home_score INTEGER,
  away_score INTEGER,
  game_uid TEXT,
  was_excluded BOOLEAN,
  action TEXT
) AS $$
BEGIN
  -- Return all matching games with their current and planned status
  RETURN QUERY
  SELECT
    g.id AS game_id,
    g.game_date,
    g.home_team_master_id AS home_master,
    g.away_team_master_id AS away_master,
    g.home_score,
    g.away_score,
    g.game_uid,
    g.is_excluded AS was_excluded,
    CASE
      WHEN g.is_excluded = TRUE THEN 'already_excluded'
      WHEN p_dry_run THEN 'would_exclude'
      ELSE 'excluded'
    END AS action
  FROM games g
  WHERE (g.home_team_master_id = p_team_id OR g.away_team_master_id = p_team_id)
    AND g.game_date >= p_start_date
    AND g.game_date <= p_end_date
    AND g.home_score IS NOT NULL
    AND g.away_score IS NOT NULL
  ORDER BY g.game_date, g.id;

  -- If not dry run, actually exclude the games
  -- The propagation trigger will handle duplicates automatically
  IF NOT p_dry_run THEN
    UPDATE games
    SET is_excluded = TRUE
    WHERE (home_team_master_id = p_team_id OR away_team_master_id = p_team_id)
      AND game_date >= p_start_date
      AND game_date <= p_end_date
      AND home_score IS NOT NULL
      AND away_score IS NOT NULL
      AND is_excluded = FALSE;
  END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION propagate_game_exclusion() IS
  'Trigger function: when a game is excluded, auto-propagate to duplicate rows '
  'with the same date, master team pair, and scores (handles perspective duplicates).';

COMMENT ON FUNCTION exclude_games_for_team_in_range(UUID, DATE, DATE, BOOLEAN) IS
  'RPC to find and exclude all games for a team in a date range. '
  'Use p_dry_run=TRUE to preview, FALSE to execute. '
  'The propagation trigger auto-excludes perspective duplicates.';
