-- Club Name Standardization Fixes (all teams, both genders)
-- Generated automatically by full_club_analysis.py
-- Includes BOTH caps fixes AND naming variations
--
-- Each UPDATE filtered by state_code (applies to both Male and Female)

BEGIN;

-- ========== CA ==========
-- [CANONICAL] "Beach FC (Ca)" → "Beach Futbol Club" (25 teams)
UPDATE teams SET club_name = 'Beach Futbol Club' WHERE club_name = 'Beach FC (Ca)' AND state_code = 'CA';

-- [CANONICAL] "Beach FC  (CA)" → "Beach Futbol Club" (24 teams)
UPDATE teams SET club_name = 'Beach Futbol Club' WHERE club_name = 'Beach FC  (CA)' AND state_code = 'CA';

-- [CANONICAL] "FC Golden State Force" → "FC Golden State" (20 teams)
UPDATE teams SET club_name = 'FC Golden State' WHERE club_name = 'FC Golden State Force' AND state_code = 'CA';

-- [CANONICAL] "Mustang SC" → "Mustang Soccer" (8 teams)
UPDATE teams SET club_name = 'Mustang Soccer' WHERE club_name = 'Mustang SC' AND state_code = 'CA';


-- ========== CT ==========
-- [CANONICAL] "Beachside Soccer Club CT" → "Beachside of Connecticut" (14 teams)
UPDATE teams SET club_name = 'Beachside of Connecticut' WHERE club_name = 'Beachside Soccer Club CT' AND state_code = 'CT';

-- [CANONICAL] "AC Connecticut" → "A.C. Connecticut" (12 teams)
UPDATE teams SET club_name = 'A.C. Connecticut' WHERE club_name = 'AC Connecticut' AND state_code = 'CT';


-- ========== GA ==========
-- [CANONICAL] "NTH NASA" → "NASA Tophat" (10 teams)
UPDATE teams SET club_name = 'NASA Tophat' WHERE club_name = 'NTH NASA' AND state_code = 'GA';

-- [CANONICAL] "Concord Fire" → "Concorde Fire" (1 teams)
UPDATE teams SET club_name = 'Concorde Fire' WHERE club_name = 'Concord Fire' AND state_code = 'GA';


-- ========== ID ==========
-- [CANONICAL] "Boise Timbers | Thorns" → "Boise Timbers | Thorns FC" (60 teams)
UPDATE teams SET club_name = 'Boise Timbers | Thorns FC' WHERE club_name = 'Boise Timbers | Thorns' AND state_code = 'ID';


-- ========== MI ==========
-- [CANONICAL] "Nationals SC" → "Nationals" (21 teams)
UPDATE teams SET club_name = 'Nationals' WHERE club_name = 'Nationals SC' AND state_code = 'MI';


-- ========== MN ==========
-- [CANONICAL] "St Croix Soccer Club" → "St. Croix" (17 teams)
UPDATE teams SET club_name = 'St. Croix' WHERE club_name = 'St Croix Soccer Club' AND state_code = 'MN';


-- ========== MS ==========
-- [CANONICAL] "MS Futbol Club" → "Mississippi Rush" (42 teams)
UPDATE teams SET club_name = 'Mississippi Rush' WHERE club_name = 'MS Futbol Club' AND state_code = 'MS';


-- ========== NJ ==========
-- [CANONICAL] "Match Fit Surf" → "Match Fit Academy" (88 teams)
UPDATE teams SET club_name = 'Match Fit Academy' WHERE club_name = 'Match Fit Surf' AND state_code = 'NJ';

-- [CANONICAL] "Franklin Township Youth Soccer Association" → "Franklin Township SC" (9 teams)
UPDATE teams SET club_name = 'Franklin Township SC' WHERE club_name = 'Franklin Township Youth Soccer Association' AND state_code = 'NJ';


-- ========== NV ==========
-- [CANONICAL] "LV Heat Surf SC" → "Las Vegas Heat Surf SC" (46 teams)
UPDATE teams SET club_name = 'Las Vegas Heat Surf SC' WHERE club_name = 'LV Heat Surf SC' AND state_code = 'NV';


-- ========== NY ==========
-- [CANONICAL] "WNY Flash" → "Western New York Flash" (44 teams)
UPDATE teams SET club_name = 'Western New York Flash' WHERE club_name = 'WNY Flash' AND state_code = 'NY';

-- [CANONICAL] "East Coast Surf SC" → "East Coast Surf" (9 teams)
UPDATE teams SET club_name = 'East Coast Surf' WHERE club_name = 'East Coast Surf SC' AND state_code = 'NY';


-- ========== OH ==========
-- [CANONICAL] "Cincinnati United" → "Cincinnati United Premier Soccer Club" (169 teams)
UPDATE teams SET club_name = 'Cincinnati United Premier Soccer Club' WHERE club_name = 'Cincinnati United' AND state_code = 'OH';

-- [CANONICAL] "Ohio Elite SA" → "Ohio Elite Soccer Academy" (44 teams)
UPDATE teams SET club_name = 'Ohio Elite Soccer Academy' WHERE club_name = 'Ohio Elite SA' AND state_code = 'OH';

-- [CANONICAL] "Canton Force" → "Canton Akron United Force" (11 teams)
UPDATE teams SET club_name = 'Canton Akron United Force' WHERE club_name = 'Canton Force' AND state_code = 'OH';


-- ========== OK ==========
-- [CANONICAL] "Oklahoma Celtic Football Club" → "Oklahoma Celtic" (71 teams)
UPDATE teams SET club_name = 'Oklahoma Celtic' WHERE club_name = 'Oklahoma Celtic Football Club' AND state_code = 'OK';

-- [CANONICAL] "West Side Alliance" → "West Side Alliance SC" (30 teams)
UPDATE teams SET club_name = 'West Side Alliance SC' WHERE club_name = 'West Side Alliance' AND state_code = 'OK';


-- ========== OR ==========
-- [CANONICAL] "Saints Soccer Academy" → "Saints Academy" (28 teams)
UPDATE teams SET club_name = 'Saints Academy' WHERE club_name = 'Saints Soccer Academy' AND state_code = 'OR';

-- [CANONICAL] "FC Portland" → "FC Portland Academy" (8 teams)
UPDATE teams SET club_name = 'FC Portland Academy' WHERE club_name = 'FC Portland' AND state_code = 'OR';

-- [CANONICAL] "Oregon Surf" → "Oregon Surf SC" (5 teams)
UPDATE teams SET club_name = 'Oregon Surf SC' WHERE club_name = 'Oregon Surf' AND state_code = 'OR';


-- ========== SC ==========
-- [CANONICAL] "South Carolina United" → "South Carolina United FC" (9 teams)
UPDATE teams SET club_name = 'South Carolina United FC' WHERE club_name = 'South Carolina United' AND state_code = 'SC';

-- [CANONICAL] "South Carolina Surf" → "South Carolina Surf SC" (8 teams)
UPDATE teams SET club_name = 'South Carolina Surf SC' WHERE club_name = 'South Carolina Surf' AND state_code = 'SC';

-- [CANONICAL] "James Island Youth SC    (JIYSC)" → "James Island Youth SC" (2 teams)
UPDATE teams SET club_name = 'James Island Youth SC' WHERE club_name = 'James Island Youth SC    (JIYSC)' AND state_code = 'SC';


-- ========== TN ==========
-- [CANONICAL] "FC Alliance" → "FC Alliance TN" (14 teams)
UPDATE teams SET club_name = 'FC Alliance TN' WHERE club_name = 'FC Alliance' AND state_code = 'TN';


-- ========== TX ==========
-- [CANONICAL] "Atlético Dallas Youth" → "Atletico Dallas Youth" (56 teams)
UPDATE teams SET club_name = 'Atletico Dallas Youth' WHERE club_name = 'Atlético Dallas Youth' AND state_code = 'TX';

-- [CANONICAL] "Lonestar Soccer Club" → "Lonestar" (31 teams)
UPDATE teams SET club_name = 'Lonestar' WHERE club_name = 'Lonestar Soccer Club' AND state_code = 'TX';

-- [CANONICAL] "Cavalry FC" → "Cavalry Youth Soccer" (15 teams)
UPDATE teams SET club_name = 'Cavalry Youth Soccer' WHERE club_name = 'Cavalry FC' AND state_code = 'TX';


-- ========== UT ==========
-- [CANONICAL] "Sparta United" → "Sparta United Soccer Club" (21 teams)
UPDATE teams SET club_name = 'Sparta United Soccer Club' WHERE club_name = 'Sparta United' AND state_code = 'UT';

-- [CANONICAL] "La Roca" → "La Roca FC" (12 teams)
UPDATE teams SET club_name = 'La Roca FC' WHERE club_name = 'La Roca' AND state_code = 'UT';


-- ========== VA ==========
-- [CANONICAL] "Arlington Soccer Association" → "Arlington Soccer" (84 teams)
UPDATE teams SET club_name = 'Arlington Soccer' WHERE club_name = 'Arlington Soccer Association' AND state_code = 'VA';

-- [CANONICAL] "Springfield SYC Soccer" → "Springfield SYC" (62 teams)
UPDATE teams SET club_name = 'Springfield SYC' WHERE club_name = 'Springfield SYC Soccer' AND state_code = 'VA';

-- [CANONICAL] "PWSI Courage" → "Prince William Soccer Inc" (16 teams)
UPDATE teams SET club_name = 'Prince William Soccer Inc' WHERE club_name = 'PWSI Courage' AND state_code = 'VA';

-- [CANONICAL] "Beach FC  (VA)" → "Beach FC" (12 teams)
UPDATE teams SET club_name = 'Beach FC' WHERE club_name = 'Beach FC  (VA)' AND state_code = 'VA';

-- [CANONICAL] "Beach FC (Va)" → "Beach FC" (12 teams)
UPDATE teams SET club_name = 'Beach FC' WHERE club_name = 'Beach FC (Va)' AND state_code = 'VA';

-- [CANONICAL] "VA Reign FC" → "Virginia Reign" (11 teams)
UPDATE teams SET club_name = 'Virginia Reign' WHERE club_name = 'VA Reign FC' AND state_code = 'VA';

-- [CANONICAL] "Richmond Utd" → "Richmond United" (4 teams)
UPDATE teams SET club_name = 'Richmond United' WHERE club_name = 'Richmond Utd' AND state_code = 'VA';


-- ========== WA ==========
-- [CANONICAL] "Eastside F.C" → "Eastside FC" (12 teams)
UPDATE teams SET club_name = 'Eastside FC' WHERE club_name = 'Eastside F.C' AND state_code = 'WA';

-- [CANONICAL] "Mount Rainier FC" → "Mt. Rainier Futbol Club" (8 teams)
UPDATE teams SET club_name = 'Mt. Rainier Futbol Club' WHERE club_name = 'Mount Rainier FC' AND state_code = 'WA';


COMMIT;