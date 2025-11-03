-- PitchRank Game Immutability and Corrections Migration
-- Adds immutability flags and corrections table for game data integrity

-- =====================================================
-- ADD IMMUTABILITY COLUMNS TO GAMES TABLE
-- =====================================================

-- Add is_immutable flag (default true for all existing and new games)
ALTER TABLE games ADD COLUMN IF NOT EXISTS is_immutable BOOLEAN DEFAULT TRUE;

-- Add original_import_id to track which import created the game
ALTER TABLE games ADD COLUMN IF NOT EXISTS original_import_id UUID;

-- Create index on original_import_id for tracking imports
CREATE INDEX IF NOT EXISTS idx_games_import_id ON games(original_import_id) WHERE original_import_id IS NOT NULL;

-- =====================================================
-- GAME CORRECTIONS TABLE
-- =====================================================

CREATE TABLE IF NOT EXISTS game_corrections (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    original_game_uid UUID NOT NULL REFERENCES games(game_uid),
    correction_type TEXT NOT NULL CHECK (correction_type IN ('score', 'date', 'teams', 'cancelled', 'other')),
    original_values JSONB NOT NULL,
    corrected_values JSONB NOT NULL,
    reason TEXT,
    submitted_by TEXT,
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected'))
);

-- Indexes for corrections table
CREATE INDEX IF NOT EXISTS idx_game_corrections_game_uid ON game_corrections(original_game_uid);
CREATE INDEX IF NOT EXISTS idx_game_corrections_status ON game_corrections(status);
CREATE INDEX IF NOT EXISTS idx_game_corrections_type ON game_corrections(correction_type);
CREATE INDEX IF NOT EXISTS idx_game_corrections_created ON game_corrections(created_at DESC);

-- =====================================================
-- IMMUTABILITY TRIGGER
-- =====================================================

-- Function to prevent updates on immutable games
CREATE OR REPLACE FUNCTION prevent_game_updates() RETURNS TRIGGER AS $$
BEGIN
    -- Allow updates only if is_immutable is false
    IF OLD.is_immutable = TRUE AND OLD != NEW THEN
        RAISE EXCEPTION 'Cannot update immutable game. Use game_corrections table instead. Game UID: %', OLD.game_uid;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to enforce immutability
DROP TRIGGER IF EXISTS enforce_game_immutability ON games;
CREATE TRIGGER enforce_game_immutability
    BEFORE UPDATE ON games
    FOR EACH ROW
    EXECUTE FUNCTION prevent_game_updates();

-- =====================================================
-- HELPER FUNCTION TO APPLY CORRECTIONS
-- =====================================================

-- Function to apply approved corrections (call this after approving a correction)
CREATE OR REPLACE FUNCTION apply_game_correction(correction_id UUID, approver_name TEXT)
RETURNS void AS $$
DECLARE
    correction_record game_corrections%ROWTYPE;
    game_record games%ROWTYPE;
BEGIN
    -- Get the correction record
    SELECT * INTO correction_record
    FROM game_corrections
    WHERE id = correction_id AND status = 'pending';
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Correction not found or not pending: %', correction_id;
    END IF;
    
    -- Get the game record
    SELECT * INTO game_record
    FROM games
    WHERE game_uid = correction_record.original_game_uid;
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Game not found: %', correction_record.original_game_uid;
    END IF;
    
    -- Temporarily set is_immutable to false to allow update
    UPDATE games
    SET is_immutable = FALSE
    WHERE game_uid = correction_record.original_game_uid;
    
    -- Apply the correction based on type
    CASE correction_record.correction_type
        WHEN 'score' THEN
            UPDATE games
            SET home_score = (correction_record.corrected_values->>'home_score')::INTEGER,
                away_score = (correction_record.corrected_values->>'away_score')::INTEGER,
                result = (correction_record.corrected_values->>'result')::CHAR(1)
            WHERE game_uid = correction_record.original_game_uid;
        WHEN 'date' THEN
            UPDATE games
            SET game_date = (correction_record.corrected_values->>'game_date')::DATE
            WHERE game_uid = correction_record.original_game_uid;
        WHEN 'teams' THEN
            UPDATE games
            SET home_team_master_id = (correction_record.corrected_values->>'home_team_master_id')::UUID,
                away_team_master_id = (correction_record.corrected_values->>'away_team_master_id')::UUID
            WHERE game_uid = correction_record.original_game_uid;
        WHEN 'cancelled' THEN
            -- Mark game as cancelled (could add a cancelled flag or delete)
            -- For now, we'll just mark it in the correction
            NULL;
        ELSE
            RAISE EXCEPTION 'Unknown correction type: %', correction_record.correction_type;
    END CASE;
    
    -- Restore immutability
    UPDATE games
    SET is_immutable = TRUE
    WHERE game_uid = correction_record.original_game_uid;
    
    -- Mark correction as approved
    UPDATE game_corrections
    SET status = 'approved',
        approved_by = approver_name,
        approved_at = NOW()
    WHERE id = correction_id;
END;
$$ LANGUAGE plpgsql;

