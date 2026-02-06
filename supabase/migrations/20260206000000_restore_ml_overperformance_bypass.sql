-- Restore ml_overperformance bypass in prevent_game_updates trigger
-- The 20251209 migration accidentally dropped the ML field bypass that was
-- added in 20251125. This restores it alongside the existing exceptions
-- for is_immutable toggle and safe team linking.

CREATE OR REPLACE FUNCTION prevent_game_updates() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.is_immutable = TRUE THEN
        -- EXCEPTION 1: Allow changing is_immutable itself (for admin/function use)
        IF (NEW.is_immutable IS DISTINCT FROM OLD.is_immutable) AND
           (OLD.home_team_master_id IS NOT DISTINCT FROM NEW.home_team_master_id) AND
           (OLD.away_team_master_id IS NOT DISTINCT FROM NEW.away_team_master_id) AND
           (OLD.home_score IS NOT DISTINCT FROM NEW.home_score) AND
           (OLD.away_score IS NOT DISTINCT FROM NEW.away_score) AND
           (OLD.game_date IS NOT DISTINCT FROM NEW.game_date)
        THEN
            RETURN NEW;
        END IF;

        -- EXCEPTION 2: Allow safe team linking (filling NULL team IDs)
        DECLARE
            is_safe_team_link BOOLEAN := FALSE;
        BEGIN
            IF (
                (OLD.home_team_master_id IS NULL AND NEW.home_team_master_id IS NOT NULL AND
                 OLD.away_team_master_id IS NOT DISTINCT FROM NEW.away_team_master_id)
                OR
                (OLD.away_team_master_id IS NULL AND NEW.away_team_master_id IS NOT NULL AND
                 OLD.home_team_master_id IS NOT DISTINCT FROM NEW.home_team_master_id)
                OR
                (OLD.home_team_master_id IS NULL AND NEW.home_team_master_id IS NOT NULL AND
                 OLD.away_team_master_id IS NULL AND NEW.away_team_master_id IS NOT NULL)
            ) THEN
                IF OLD.home_score IS NOT DISTINCT FROM NEW.home_score AND
                   OLD.away_score IS NOT DISTINCT FROM NEW.away_score AND
                   OLD.game_date IS NOT DISTINCT FROM NEW.game_date AND
                   OLD.home_provider_id IS NOT DISTINCT FROM NEW.home_provider_id AND
                   OLD.away_provider_id IS NOT DISTINCT FROM NEW.away_provider_id AND
                   OLD.competition IS NOT DISTINCT FROM NEW.competition AND
                   OLD.division_name IS NOT DISTINCT FROM NEW.division_name AND
                   OLD.event_name IS NOT DISTINCT FROM NEW.event_name AND
                   OLD.venue IS NOT DISTINCT FROM NEW.venue AND
                   OLD.result IS NOT DISTINCT FROM NEW.result AND
                   OLD.provider_id IS NOT DISTINCT FROM NEW.provider_id AND
                   OLD.source_url IS NOT DISTINCT FROM NEW.source_url AND
                   OLD.is_immutable IS NOT DISTINCT FROM NEW.is_immutable THEN
                    is_safe_team_link := TRUE;
                END IF;
            END IF;

            IF is_safe_team_link THEN
                RETURN NEW;
            END IF;
        END;

        -- EXCEPTION 3: Allow updating only ml_overperformance (computed ML field)
        -- This enables batch_update_ml_overperformance() RPC to work on immutable games
        IF (
            OLD.game_date IS NOT DISTINCT FROM NEW.game_date AND
            OLD.home_team_master_id IS NOT DISTINCT FROM NEW.home_team_master_id AND
            OLD.away_team_master_id IS NOT DISTINCT FROM NEW.away_team_master_id AND
            OLD.home_score IS NOT DISTINCT FROM NEW.home_score AND
            OLD.away_score IS NOT DISTINCT FROM NEW.away_score AND
            OLD.game_uid IS NOT DISTINCT FROM NEW.game_uid AND
            OLD.provider_id IS NOT DISTINCT FROM NEW.provider_id AND
            OLD.is_immutable IS NOT DISTINCT FROM NEW.is_immutable
        ) THEN
            -- Only ml_overperformance or other computed fields changed - allow it
            RETURN NEW;
        END IF;

        RAISE EXCEPTION 'Cannot update immutable game. Use game_corrections table. Game ID: %', OLD.id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
