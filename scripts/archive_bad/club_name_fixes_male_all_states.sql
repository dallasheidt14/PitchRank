-- Club Name Standardization - ALL STATES (Male)
-- Excludes CA, AZ, WA (already done)
-- Generated with MAJORITY RULE
--
-- Run in Supabase SQL Editor: https://supabase.com/dashboard

BEGIN;

-- ========== AL (1 fixes) ==========
-- [NAMING] "Phoenix FC" → "Phoenix Football Club" (1 teams)
UPDATE teams SET club_name = 'Phoenix Football Club' WHERE club_name = 'Phoenix FC' AND state_code = 'AL' AND gender = 'Male';


-- ========== AR (1 fixes) ==========
-- [NAMING] "Arkansas Rising" → "Arkansas Rising Soccer Club" (9 teams)
UPDATE teams SET club_name = 'Arkansas Rising Soccer Club' WHERE club_name = 'Arkansas Rising' AND state_code = 'AR' AND gender = 'Male';


-- ========== FL (10 fixes) ==========
-- [NAMING] "Wellington Soccer Club" → "Wellington SC" (13 teams)
UPDATE teams SET club_name = 'Wellington SC' WHERE club_name = 'Wellington Soccer Club' AND state_code = 'FL' AND gender = 'Male';

-- [NAMING] "Florida Hawks FC" → "Florida Hawks Futbol Club" (11 teams)
UPDATE teams SET club_name = 'Florida Hawks Futbol Club' WHERE club_name = 'Florida Hawks FC' AND state_code = 'FL' AND gender = 'Male';

-- [NAMING] "Doral Soccer Club" → "Doral SC" (10 teams)
UPDATE teams SET club_name = 'Doral SC' WHERE club_name = 'Doral Soccer Club' AND state_code = 'FL' AND gender = 'Male';

-- [NAMING] "Springs SC" → "Springs Soccer Club" (8 teams)
UPDATE teams SET club_name = 'Springs Soccer Club' WHERE club_name = 'Springs SC' AND state_code = 'FL' AND gender = 'Male';

-- [NAMING] "Orlando City SC" → "Orlando City Soccer Club" (7 teams)
UPDATE teams SET club_name = 'Orlando City Soccer Club' WHERE club_name = 'Orlando City SC' AND state_code = 'FL' AND gender = 'Male';

-- [NAMING] "Florida Celtic Soccer Club" → "Florida Celtic" (6 teams)
UPDATE teams SET club_name = 'Florida Celtic' WHERE club_name = 'Florida Celtic Soccer Club' AND state_code = 'FL' AND gender = 'Male';

-- [NAMING] "South Orlando Soccer Club" → "South Orlando SC" (6 teams)
UPDATE teams SET club_name = 'South Orlando SC' WHERE club_name = 'South Orlando Soccer Club' AND state_code = 'FL' AND gender = 'Male';

-- [CAPS] "NONA Soccer Academy" → "Nona Soccer Academy" (4 teams)
UPDATE teams SET club_name = 'Nona Soccer Academy' WHERE club_name = 'NONA Soccer Academy' AND state_code = 'FL' AND gender = 'Male';

-- [NAMING] "Palm Beach United FC" → "Palm Beach United" (3 teams)
UPDATE teams SET club_name = 'Palm Beach United' WHERE club_name = 'Palm Beach United FC' AND state_code = 'FL' AND gender = 'Male';

-- [NAMING] "Orlando City" → "Orlando City Soccer Club" (1 teams)
UPDATE teams SET club_name = 'Orlando City Soccer Club' WHERE club_name = 'Orlando City' AND state_code = 'FL' AND gender = 'Male';


-- ========== IL (7 fixes) ==========
-- [NAMING] "Chicago Magic" → "Chicago Magic Soccer Club" (8 teams)
UPDATE teams SET club_name = 'Chicago Magic Soccer Club' WHERE club_name = 'Chicago Magic' AND state_code = 'IL' AND gender = 'Male';

-- [NAMING] "Eclipse Select SC" → "Eclipse Select Soccer Club" (5 teams)
UPDATE teams SET club_name = 'Eclipse Select Soccer Club' WHERE club_name = 'Eclipse Select SC' AND state_code = 'IL' AND gender = 'Male';

-- [NAMING] "Chicago City SC" → "Chicago City Soccer Club" (3 teams)
UPDATE teams SET club_name = 'Chicago City Soccer Club' WHERE club_name = 'Chicago City SC' AND state_code = 'IL' AND gender = 'Male';

-- [NAMING] "Chicago Fire" → "Chicago Fire FC" (2 teams)
UPDATE teams SET club_name = 'Chicago Fire FC' WHERE club_name = 'Chicago Fire' AND state_code = 'IL' AND gender = 'Male';

-- [NAMING] "Galaxy Soccer Club" → "Galaxy SC" (1 teams)
UPDATE teams SET club_name = 'Galaxy SC' WHERE club_name = 'Galaxy Soccer Club' AND state_code = 'IL' AND gender = 'Male';

-- [NAMING] "Green White Soccer Club" → "Green White SC" (1 teams)
UPDATE teams SET club_name = 'Green White SC' WHERE club_name = 'Green White Soccer Club' AND state_code = 'IL' AND gender = 'Male';

-- [CAPS] "Naz United FC" → "NAZ United FC" (1 teams)
UPDATE teams SET club_name = 'NAZ United FC' WHERE club_name = 'Naz United FC' AND state_code = 'IL' AND gender = 'Male';


-- ========== IN (1 fixes) ==========
-- [NAMING] "Westside United SC" → "Westside United FC" (6 teams)
UPDATE teams SET club_name = 'Westside United FC' WHERE club_name = 'Westside United SC' AND state_code = 'IN' AND gender = 'Male';


-- ========== LA (2 fixes) ==========
-- [NAMING] "Louisiana Fire Soccer Club" → "Louisiana Fire SC" (12 teams)
UPDATE teams SET club_name = 'Louisiana Fire SC' WHERE club_name = 'Louisiana Fire Soccer Club' AND state_code = 'LA' AND gender = 'Male';

-- [NAMING] "Bayou FC" → "Bayou Soccer Club" (1 teams)
UPDATE teams SET club_name = 'Bayou Soccer Club' WHERE club_name = 'Bayou FC' AND state_code = 'LA' AND gender = 'Male';


-- ========== MA (3 fixes) ==========
-- [NAMING] "Valeo Futbol Club" → "Valeo FC" (7 teams)
UPDATE teams SET club_name = 'Valeo FC' WHERE club_name = 'Valeo Futbol Club' AND state_code = 'MA' AND gender = 'Male';

-- [NAMING] "New England Surf SC" → "New England Surf" (5 teams)
UPDATE teams SET club_name = 'New England Surf' WHERE club_name = 'New England Surf SC' AND state_code = 'MA' AND gender = 'Male';

-- [NAMING] "Western United Pioneers" → "Western United Pioneers FC" (4 teams)
UPDATE teams SET club_name = 'Western United Pioneers FC' WHERE club_name = 'Western United Pioneers' AND state_code = 'MA' AND gender = 'Male';


-- ========== MD (4 fixes) ==========
-- [NAMING] "Achilles Football Club" → "Achilles FC" (12 teams)
UPDATE teams SET club_name = 'Achilles FC' WHERE club_name = 'Achilles Football Club' AND state_code = 'MD' AND gender = 'Male';

-- [NAMING] "Maryland United FC" → "Maryland United Football Club" (12 teams)
UPDATE teams SET club_name = 'Maryland United Football Club' WHERE club_name = 'Maryland United FC' AND state_code = 'MD' AND gender = 'Male';

-- [NAMING] "Coppermine SC" → "Coppermine Soccer Club" (4 teams)
UPDATE teams SET club_name = 'Coppermine Soccer Club' WHERE club_name = 'Coppermine SC' AND state_code = 'MD' AND gender = 'Male';

-- [NAMING] "Future Soccer Club" → "Future FC" (4 teams)
UPDATE teams SET club_name = 'Future FC' WHERE club_name = 'Future Soccer Club' AND state_code = 'MD' AND gender = 'Male';


-- ========== MN (4 fixes) ==========
-- [NAMING] "Minneapolis United SC" → "Minneapolis United" (12 teams)
UPDATE teams SET club_name = 'Minneapolis United' WHERE club_name = 'Minneapolis United SC' AND state_code = 'MN' AND gender = 'Male';

-- [NAMING] "Lakeville SC" → "Lakeville Soccer Club" (4 teams)
UPDATE teams SET club_name = 'Lakeville Soccer Club' WHERE club_name = 'Lakeville SC' AND state_code = 'MN' AND gender = 'Male';

-- [CAPS] "BOREAL FC" → "Boreal FC" (2 teams)
UPDATE teams SET club_name = 'Boreal FC' WHERE club_name = 'BOREAL FC' AND state_code = 'MN' AND gender = 'Male';

-- [NAMING] "CC United" → "CC United Soccer Club" (1 teams)
UPDATE teams SET club_name = 'CC United Soccer Club' WHERE club_name = 'CC United' AND state_code = 'MN' AND gender = 'Male';


-- ========== MO (3 fixes) ==========
-- [NAMING] "St. Louis Stars" → "St. Louis Stars SC" (17 teams)
UPDATE teams SET club_name = 'St. Louis Stars SC' WHERE club_name = 'St. Louis Stars' AND state_code = 'MO' AND gender = 'Male';

-- [NAMING] "Sporting City" → "Sporting City Soccer Club" (10 teams)
UPDATE teams SET club_name = 'Sporting City Soccer Club' WHERE club_name = 'Sporting City' AND state_code = 'MO' AND gender = 'Male';

-- [CAPS] "St. Louis City SC" → "St. Louis CITY SC" (3 teams)
UPDATE teams SET club_name = 'St. Louis CITY SC' WHERE club_name = 'St. Louis City SC' AND state_code = 'MO' AND gender = 'Male';


-- ========== MS (2 fixes) ==========
-- [NAMING] "Hattiesburg FC" → "Hattiesburg Futbol Club" (6 teams)
UPDATE teams SET club_name = 'Hattiesburg Futbol Club' WHERE club_name = 'Hattiesburg FC' AND state_code = 'MS' AND gender = 'Male';

-- [NAMING] "Tupelo FC" → "Tupelo Futbol Club" (6 teams)
UPDATE teams SET club_name = 'Tupelo Futbol Club' WHERE club_name = 'Tupelo FC' AND state_code = 'MS' AND gender = 'Male';


-- ========== NC (4 fixes) ==========
-- [NAMING] "Charlotte Independence" → "Charlotte Independence SC" (17 teams)
UPDATE teams SET club_name = 'Charlotte Independence SC' WHERE club_name = 'Charlotte Independence' AND state_code = 'NC' AND gender = 'Male';

-- [NAMING] "Queen City Mutiny" → "Queen City Mutiny FC" (15 teams)
UPDATE teams SET club_name = 'Queen City Mutiny FC' WHERE club_name = 'Queen City Mutiny' AND state_code = 'NC' AND gender = 'Male';

-- [NAMING] "Charlotte Independence Soccer Club" → "Charlotte Independence SC" (14 teams)
UPDATE teams SET club_name = 'Charlotte Independence SC' WHERE club_name = 'Charlotte Independence Soccer Club' AND state_code = 'NC' AND gender = 'Male';

-- [NAMING] "Carolina Football Club" → "Carolina FC" (1 teams)
UPDATE teams SET club_name = 'Carolina FC' WHERE club_name = 'Carolina Football Club' AND state_code = 'NC' AND gender = 'Male';


-- ========== NE (4 fixes) ==========
-- [NAMING] "Sporting Nebraska Football Club" → "Sporting Nebraska FC" (17 teams)
UPDATE teams SET club_name = 'Sporting Nebraska FC' WHERE club_name = 'Sporting Nebraska Football Club' AND state_code = 'NE' AND gender = 'Male';

-- [NAMING] "Omaha Surf" → "Omaha Surf Soccer Club" (2 teams)
UPDATE teams SET club_name = 'Omaha Surf Soccer Club' WHERE club_name = 'Omaha Surf' AND state_code = 'NE' AND gender = 'Male';

-- [NAMING] "Omaha Surf sc" → "Omaha Surf Soccer Club" (1 teams)
UPDATE teams SET club_name = 'Omaha Surf Soccer Club' WHERE club_name = 'Omaha Surf sc' AND state_code = 'NE' AND gender = 'Male';

-- [NAMING] "Omaha United" → "Omaha United SC" (1 teams)
UPDATE teams SET club_name = 'Omaha United SC' WHERE club_name = 'Omaha United' AND state_code = 'NE' AND gender = 'Male';


-- ========== TN (4 fixes) ==========
-- [NAMING] "Tennessee Soccer Club" → "Tennessee SC" (16 teams)
UPDATE teams SET club_name = 'Tennessee SC' WHERE club_name = 'Tennessee Soccer Club' AND state_code = 'TN' AND gender = 'Male';

-- [NAMING] "Tennessee United" → "Tennessee United SC" (5 teams)
UPDATE teams SET club_name = 'Tennessee United SC' WHERE club_name = 'Tennessee United' AND state_code = 'TN' AND gender = 'Male';

-- [NAMING] "Chattanooga FC" → "Chattanooga Football Club" (3 teams)
UPDATE teams SET club_name = 'Chattanooga Football Club' WHERE club_name = 'Chattanooga FC' AND state_code = 'TN' AND gender = 'Male';

-- [NAMING] "Nashville FC" → "Nashville SC" (3 teams)
UPDATE teams SET club_name = 'Nashville SC' WHERE club_name = 'Nashville FC' AND state_code = 'TN' AND gender = 'Male';


-- ========== VA (5 fixes) ==========
-- [NAMING] "Fredericksburg Soccer Club" → "Fredericksburg FC" (9 teams)
UPDATE teams SET club_name = 'Fredericksburg FC' WHERE club_name = 'Fredericksburg Soccer Club' AND state_code = 'VA' AND gender = 'Male';

-- [NAMING] "The St. James" → "The St. James Football Club" (5 teams)
UPDATE teams SET club_name = 'The St. James Football Club' WHERE club_name = 'The St. James' AND state_code = 'VA' AND gender = 'Male';

-- [NAMING] "Chesapeake Soccer Club" → "Chesapeake SC" (3 teams)
UPDATE teams SET club_name = 'Chesapeake SC' WHERE club_name = 'Chesapeake Soccer Club' AND state_code = 'VA' AND gender = 'Male';

-- [NAMING] "Chesapeake United" → "Chesapeake United SC" (1 teams)
UPDATE teams SET club_name = 'Chesapeake United SC' WHERE club_name = 'Chesapeake United' AND state_code = 'VA' AND gender = 'Male';

-- [NAMING] "Virginia Rush SC" → "Virginia Rush" (1 teams)
UPDATE teams SET club_name = 'Virginia Rush' WHERE club_name = 'Virginia Rush SC' AND state_code = 'VA' AND gender = 'Male';


COMMIT;