-- Restore ml_overperformance bypass in prevent_game_updates trigger
-- The 20260305 migration (add_unlink_game_team_function) accidentally dropped
-- Exception 3 (ML field bypass) that was added in 20260206. This restores it.

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

        -- EXCEPTION 2: Allow safe team linking (NULL -> value) AND unlinking (value -> NULL)
        DECLARE
            is_safe_team_change BOOLEAN := FALSE;
        BEGIN
            IF (
                -- Home team linking: NULL -> value
                (OLD.home_team_master_id IS NULL AND NEW.home_team_master_id IS NOT NULL AND
                 OLD.away_team_master_id IS NOT DISTINCT FROM NEW.away_team_master_id)
                OR
                -- Away team linking: NULL -> value
                (OLD.away_team_master_id IS NULL AND NEW.away_team_master_id IS NOT NULL AND
                 OLD.home_team_master_id IS NOT DISTINCT FROM NEW.home_team_master_id)
                OR
                -- Both team linking at once: NULL -> value for both
                (OLD.home_team_master_id IS NULL AND NEW.home_team_master_id IS NOT NULL AND
                 OLD.away_team_master_id IS NULL AND NEW.away_team_master_id IS NOT NULL)
                OR
                -- Home team unlinking: value -> NULL
                (OLD.home_team_master_id IS NOT NULL AND NEW.home_team_master_id IS NULL AND
                 OLD.away_team_master_id IS NOT DISTINCT FROM NEW.away_team_master_id)
                OR
                -- Away team unlinking: value -> NULL
                (OLD.away_team_master_id IS NOT NULL AND NEW.away_team_master_id IS NULL AND
                 OLD.home_team_master_id IS NOT DISTINCT FROM NEW.home_team_master_id)
            ) THEN
                -- Verify NO other fields changed (strict safety check)
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
                    is_safe_team_change := TRUE;
                END IF;
            END IF;

            IF is_safe_team_change THEN
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

        -- Block all other updates on immutable games
        RAISE EXCEPTION 'Cannot update immutable game. Use game_corrections table. Game ID: %', OLD.id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
