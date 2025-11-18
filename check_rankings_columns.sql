-- First, check what columns exist in rankings_full table
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'rankings_full'
ORDER BY ordinal_position;

-- Also check what's in the teams table
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_name = 'teams'
-- ORDER BY ordinal_position;
