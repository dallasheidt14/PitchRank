# Team pages viewed by logged-in users, last 24h

2026-09-03. Source: Vercel runtime logs, production, `/teams/[id]` with status 200.

Team pages are premium-gated in `middleware.ts`, so anonymous visitors and crawlers get a
307 to `/upgrade` and never reach the page. In the window: **61,784 redirects** (bots) vs
**3,277 renders** across **908 distinct teams**. Only the 200s are below.

Two caveats. The page sets `revalidate = 3600`, so a count is *renders*, not raw views —
a popular page caps out near 24/day and repeat views inside an hour are free. And the log
API returns at most 25 grouped rows per query, so this is the top ~70 of the 908, gathered
by partitioning on the UUID prefix. The long tail is teams with one or two renders.

## Clusters

The list is not 70 unrelated teams. It is four users each working through a league table.

| Cluster | Teams here | Read |
|---|---|---|
| Illinois 2012 girls (u15) — GA, DPL, ECNL, Premier | ~28 | Someone comparing an entire IL 2012G cohort |
| Ohio / Mid-Atlantic 2015 boys (u12) PRE-ECNL | ~8 | 2015B pre-academy shopping |
| Indiana 2013 girls (u14) | ~10 | One club's league table |
| Texas 2013 boys (u14) — HD / academy | ~7 | Matches the kmboxberger trial signup |

## Full list

| Renders | Team | Age | G | ST | Club |
|---|---|---|---|---|---|
| 17 | Cleveland Force 2015 PRE-ECNL Blue | u12 | M | OH | Cleveland Force SC |
| 15 | ECS 2012 G Elite | u15 | F | IL | Elmhurst City Surf |
| 15 | FC United Soccer Club - 2012 GA | u15 | F | IL | FC United Soccer Club |
| 14 | FC 1974 Libertyville Elite-12G | u15 | F | IL | Greater Libertyville SA |
| 14 | Windy City Pride 2012 | u15 | F | IL | Windy City Pride |
| 12 | 2012 GA | u15 | F | IL | Galaxy SC |
| 12 | FUTBOLTECH CHSC - 2015 LIVERPOOL | u12 | M | NJ | Futboltech |
| 12 | S.S.A15B7 | u12 | M | TX | Spann Soccer Academy |
| 12 | Sporting Athletic Club 2015 Black | u12 | M | DE | Sporting Athletic Club |
| 11 | 2012 Aspire | u15 | F | IL | Wheaton United SC |
| 11 | 2012 Chicago Rush South Premier | u15 | F | IL | Chicago Rush SC |
| 11 | Brownsville Rayados 2013 | u14 | M | TX | BOYSA |
| 11 | Central Illinois United - 2012 GA | u15 | F | IL | Central Illinois United |
| 11 | Chicago FC United 2012 White | u15 | F | IL | FC United Soccer Club |
| 11 | Chicago Rush North Shore 2012 Premier | u15 | F | IL | Wilmette Wings SC |
| 11 | Coppermine SC 2015 PRE-ACADEMY I | u12 | M | MD | Coppermine Soccer Club |
| 11 | FC Dallas U13 HD | u14 | M | TX | FC Dallas |
| 11 | North Carolina FC 2015 North Blue | u12 | M | NC | NCFC |
| 11 | Pegasus FC/1974 2012 Red | u15 | F | IL | Pegasus FC |
| 10 | Ajax FC Naperville 2012 Red | u15 | F | IL | Ajax FC Naperville |
| 10 | Austin FC U13 HD | u14 | M | TX | Austin FC |
| 10 | Chicago Inter 2012 ECNL | u15 | F | IL | Chicago Inter |
| 10 | Deportivo U59 FC 2012G Premier | u15 | F | IL | Deportivo 59 FC |
| 10 | FC Stars 2011G Academy | u15 | F | IL | FC Stars (il) |
| 10 | Midwest United - 2012 GA | u15 | F | MI | Midwest United FC |
| 10 | Palatine Celtic SC 2012 Black | u15 | F | IL | Palatine Celtic SC |
| 10 | Team Chicago 2012 Performance | u15 | F | IL | Team Chicago SC |
| 9 | Chicago City 2012 DPL | u15 | F | IL | Chicago City Soccer Club |
| 9 | Galaxy SC - 2012 Aspire | u15 | F | IL | Galaxy SC |
| 9 | Glen-Ed SC 2012 United | u15 | F | IL | Glen-Ed SC |
| 9 | Metro Alliance FC 2012 Elite | u15 | F | IL | Metro Alliance FC |
| 9 | MidState 2012/2013 | u15 | F | IL | Illinois Alliance |
| 9 | Morton United FC 2012 Red | u15 | F | IL | Morton United FC |
| 8 | Ohio Galaxies FC - BSA Celtic 2015 White | u12 | M | OH | Ohio Galaxies FC |
| 7 | Columbus Force 2015 PRE-ECNL | u12 | M | OH | Columbus Force SC |
| 6 | Baltimore Armour - 2012 Aspire | u15 | F | MD | Baltimore Armour |
| 6 | CFYSC 2012 Premier- DPL | u15 | F | IL | Chicago Fire Youth SC |
| 6 | Circle City FC 2013 | u14 | F | IN | Circle City FC |
| 6 | Cleveland Force 2015 PRE-ECNL White | u12 | M | OH | Cleveland Force SC |
| 6 | Eclipse Select 2012 | u15 | F | IL | Eclipse Select SC |
| 6 | Hoosier FC - 2013 Elite Wolves II | u14 | F | IN | Hoosier Futbol Club |
| 6 | Indy Premier 2013 COPA | u14 | F | IN | Indy Premier SC |
| 6 | Polaris SC 2015 Navy | u12 | M | OH | Polaris Soccer Club |
| 6 | WSU 2013 Elite | u14 | F | IN | Westside United FC |
| 4 | Eastside FC 2012 Black | u15 | F | MI | Eastside FC |
| 4 | Echo Premier 2013 Elite I | u14 | F | IN | Indy Premier SC |
| 4 | FC Allen 2013 Red | u14 | M | TX | FC Allen |
| 4 | Kernow Storm FC 2013 Red River NPL | u14 | M | TX | Kernow Storm FC |
| 4 | Liverpool FC 2013 Dallas | u14 | M | TX | Liverpool FC Texas |
| 4 | LouCity Academy 2012 KPL | u15 | M | KY | LouCity / Racing Youth Academy |
| 4 | LouCity South 2012 Black | u15 | M | KY | LouCity / Racing Youth Academy |
| 4 | Milwaukee Kickers 2012 DPL | u15 | F | WI | Milwaukee Kickers Academy |
| 4 | **Rush WI 2012 Rush** (watchlisted x1) | u15 | F | WI | Rush Wisconsin |
| 4 | SWM Kickers 2013 Blue | u14 | F | MI | Southwest Michigan SC |
| 3 | AC River U13 AD | u14 | M | TX | AC River |
| 3 | Aspire 11/12 | u15 | F | WI | Croatian Eagles SC |
| 3 | Blue River SA- BRSA BLAST U12 | u13 | F | IN | Blue River SA |
| 3 | Carmel FC 2013 White | u14 | F | IN | Carmel FC |
| 3 | Cutters SC 2013 Red | u14 | F | IN | Cutters Soccer Club |
| 3 | FUTBOLTECH CHSC - 2013 BAYERN | u14 | M | NJ | Futboltech |
| 3 | Indy Eleven 2013 White 2 | u14 | F | IN | Indy Eleven Academy |
| 3 | Internationals SC PRE-ECNL 2015 | u12 | F | OH | Internationals SC |
| 3 | Lakota FC 2015 Red | u12 | M | OH | Lakota Futbol Club |
| 3 | PFC 2014 Grey | u13 | F | IN | (no club) |
| 3 | Philadelphia Union - SWAG Academy Blue '17 | u10 | M | PA | Philadelphia Union |
| 3 | SCSA Eleven 2013 Red | u14 | F | IN | South Central Soccer Academy |
| 3 | SOCA ECNL RL B2013/14 Elite | u13 | M | NC | SOCA |
| 3 | Southeast 2013 Black | u14 | M | AZ | Next Level Soccer (AZ) |
| 3 | TH Premier 2014 COPA | u13 | F | IN | Indy Premier SC |
| 3 | U12 NEAL Green | u13 | M | NJ | Cedar Stars Academy North |
