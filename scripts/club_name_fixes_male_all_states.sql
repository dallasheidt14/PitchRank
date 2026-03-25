-- Club Name Standardization Fixes (all teams, both genders)
-- Generated automatically by full_club_analysis.py
-- Includes BOTH caps fixes AND naming variations
--
-- Each UPDATE filtered by state_code (applies to both Male and Female)

BEGIN;

-- ========== CA ==========
-- [CAPS] "Legends FC (CA)" → "Legends FC (ca)" (90 teams)
UPDATE teams SET club_name = 'Legends FC (ca)' WHERE club_name = 'Legends FC (CA)' AND state_code = 'CA';

-- [CAPS] "FRESNO HEAT FC" → "Fresno Heat FC" (41 teams)
UPDATE teams SET club_name = 'Fresno Heat FC' WHERE club_name = 'FRESNO HEAT FC' AND state_code = 'CA';

-- [CAPS] "apple valley sc" → "Apple Valley SC" (22 teams)
UPDATE teams SET club_name = 'Apple Valley SC' WHERE club_name = 'apple valley sc' AND state_code = 'CA';

-- [CAPS] "La Mirada FC" → "LA Mirada FC" (11 teams)
UPDATE teams SET club_name = 'LA Mirada FC' WHERE club_name = 'La Mirada FC' AND state_code = 'CA';

-- [CAPS] "bakersfield alliance" → "Bakersfield Alliance" (6 teams)
UPDATE teams SET club_name = 'Bakersfield Alliance' WHERE club_name = 'bakersfield alliance' AND state_code = 'CA';

-- [CAPS] "atletico so cal" → "Atletico So Cal" (4 teams)
UPDATE teams SET club_name = 'Atletico So Cal' WHERE club_name = 'atletico so cal' AND state_code = 'CA';

-- [CAPS] "capitol city fc" → "Capitol City FC" (1 teams)
UPDATE teams SET club_name = 'Capitol City FC' WHERE club_name = 'capitol city fc' AND state_code = 'CA';


-- ========== GA ==========
-- [CAPS] "NASA Tophat" → "Nasa Tophat" (20 teams)
UPDATE teams SET club_name = 'Nasa Tophat' WHERE club_name = 'NASA Tophat' AND state_code = 'GA';


-- ========== TX ==========
-- [CANONICAL] "MAFC" → "Matias Almeyda Futbol Club" (50 teams)
UPDATE teams SET club_name = 'Matias Almeyda Futbol Club' WHERE club_name = 'MAFC' AND state_code = 'TX';

-- [CANONICAL] "BVB International Academy" → "BVB International Academy Texas" (45 teams)
UPDATE teams SET club_name = 'BVB International Academy Texas' WHERE club_name = 'BVB International Academy' AND state_code = 'TX';

-- [CANONICAL] "Lonestar SC" → "Lonestar" (41 teams)
UPDATE teams SET club_name = 'Lonestar' WHERE club_name = 'Lonestar SC' AND state_code = 'TX';

-- [CANONICAL] "Coppell Youth SA" → "Coppell FC" (37 teams)
UPDATE teams SET club_name = 'Coppell FC' WHERE club_name = 'Coppell Youth SA' AND state_code = 'TX';

-- [CANONICAL] "HTX Soccer" → "HTX" (29 teams)
UPDATE teams SET club_name = 'HTX' WHERE club_name = 'HTX Soccer' AND state_code = 'TX';

-- [CANONICAL] "SG1 Soccer" → "SG1" (26 teams)
UPDATE teams SET club_name = 'SG1' WHERE club_name = 'SG1 Soccer' AND state_code = 'TX';

-- [CANONICAL] "Kaptiva Sports Academy TX" → "Kaptiva Sports Academy" (14 teams)
UPDATE teams SET club_name = 'Kaptiva Sports Academy' WHERE club_name = 'Kaptiva Sports Academy TX' AND state_code = 'TX';

-- [CANONICAL] "Coastal Premier FC" → "Coastal Premier Alliance FC" (13 teams)
UPDATE teams SET club_name = 'Coastal Premier Alliance FC' WHERE club_name = 'Coastal Premier FC' AND state_code = 'TX';

-- [CANONICAL] "Juventus Premier Futbol Club" → "Juventus Premier FC" (12 teams)
UPDATE teams SET club_name = 'Juventus Premier FC' WHERE club_name = 'Juventus Premier Futbol Club' AND state_code = 'TX';

-- [CANONICAL] "Capital City North" → "Capital City SC" (5 teams)
UPDATE teams SET club_name = 'Capital City SC' WHERE club_name = 'Capital City North' AND state_code = 'TX';

-- [CANONICAL] "Capital City South" → "Capital City SC" (5 teams)
UPDATE teams SET club_name = 'Capital City SC' WHERE club_name = 'Capital City South' AND state_code = 'TX';

-- [CANONICAL] "GFI Academy North" → "GFI Academy" (5 teams)
UPDATE teams SET club_name = 'GFI Academy' WHERE club_name = 'GFI Academy North' AND state_code = 'TX';

-- [CANONICAL] "GFI Academy South" → "GFI Academy" (5 teams)
UPDATE teams SET club_name = 'GFI Academy' WHERE club_name = 'GFI Academy South' AND state_code = 'TX';

-- [CANONICAL] "Houston Futsal Club (HFA)" → "Houston Futsal Soccer Club" (5 teams)
UPDATE teams SET club_name = 'Houston Futsal Soccer Club' WHERE club_name = 'Houston Futsal Club (HFA)' AND state_code = 'TX';

-- [CANONICAL] "Cosmos FC" → "Cosmos FC Academy" (3 teams)
UPDATE teams SET club_name = 'Cosmos FC Academy' WHERE club_name = 'Cosmos FC' AND state_code = 'TX';

-- [CANONICAL] "Global Football Innovation" → "GFI Academy" (3 teams)
UPDATE teams SET club_name = 'GFI Academy' WHERE club_name = 'Global Football Innovation' AND state_code = 'TX';

-- [CANONICAL] "Texas Spurs FC" → "Texas Spurs" (3 teams)
UPDATE teams SET club_name = 'Texas Spurs' WHERE club_name = 'Texas Spurs FC' AND state_code = 'TX';

-- [CANONICAL] "Texoma Soccer Academy" → "Texoma SC" (2 teams)
UPDATE teams SET club_name = 'Texoma SC' WHERE club_name = 'Texoma Soccer Academy' AND state_code = 'TX';


COMMIT;