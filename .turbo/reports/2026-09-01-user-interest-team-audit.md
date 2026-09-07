# Teams our users watch: data audit

2026-09-01. 137 teams from two signals: 59 watchlisted (30 users), 82 with a user-clicked
"find missing game". All 137 were re-scraped at priority 1 on 2026-09-01;
129 completed, 8 failed (TGS teams the drainer cannot scrape). 202 new game rows landed.

## Read staleness against the season, not the calendar

The season rolled over 2026-08-01 and most league play restarts in September, so on
Sept 1 a team whose record ends in June or July is *normal*. Last-game dates cluster
hard on weekends (11 teams end on 2026-06-07, 7 on 2026-05-25) because those are
season-end weekends. An earlier cut of this report treated 49 such teams as a risk
group; that was wrong.

| State | Teams | Action |
|---|---|---|
| Active this season (game since Aug 1) | 41 | none |
| Record ends on a season-end weekend | 87 | none - waiting on fall schedules |
| Dormant or never played | 9 | verify the team still exists |

## Dormant / never played (9)

Nothing for over a year. Rescraping found no new recent games, so these are almost
certainly disbanded or renamed squads rather than missing data.

| Team | Age | G | ST | Games | Last game | Days | Watch | Reqs |
|---|---|---|---|---|---|---|---|---|
| CITY SC SW 2008 MLS 2 | u19 | M | CA | 0 | never | - | 1 | 1 |
| PA Rush Blue B2014/2015 | u12 | M | PA | 10 | never | - | 1 | 1 |
| Colorado United - 2014 COPA Mercury | u13 | M | CO | 3 | 2024-05-26 | 828 | 0 | 2 |
| San Diego Force FC - 2011 Academy | u16 | M | CA | 7 | 2024-12-15 | 625 | 1 | 1 |
| 2017 Olympico | u10 | F | CO | 2 | 2025-05-10 | 479 | 0 | 2 |
| 2016G Gold | u10 | F | CO | 14 | 2025-05-18 | 471 | 0 | 2 |
| Tulsa SC ECNL RL 2013 | u14 | M | OK | 9 | 2025-05-25 | 464 | 0 | 2 |
| Bay Area Surf - 2014 Pre-MLS | u13 | M | CA | 26 | 2025-06-15 | 443 | 1 | 1 |
| Colorado United 2017G Copa Jrs. Elite | u10 | F | CO | 14 | 2025-08-17 | 380 | 0 | 2 |

## Games on record with no score (42 teams, 99 games)

A full rescrape on 2026-09-01 recovered one of these. The provider has not posted
the results, so this is not a PitchRank scraping gap and re-running scrapes will not
fix it. Anything from the last two weeks may still post normally.

| Team | Age | G | ST | Missing | Last game |
|---|---|---|---|---|---|
| Hawaiian Gardens Eagles 2011 | u16 | F | CA | 13 | 2026-08-23 |
| FW United 2012 Elite | u15 | F | IN | 6 | 2026-08-23 |
| Hibernian McKennie 2013 | u14 | M | NJ | 5 | 2026-07-12 |
| Yardley Makefield Soccer 2014 Milan | u13 | M | PA | 5 | 2026-08-30 |
| PRE MLS NEXT Black '15 | u12 | M | PA | 5 | 2026-06-28 |
| CUP 2014 Gold | u13 | M | OH | 4 | 2026-06-07 |
| ECNL RL 2013 | u14 | F | CA | 4 | 2026-08-30 |
| Hamden Ginga FC Coastal PRE MLS Next AD | u11 | M | CT | 4 | 2026-06-14 |
| Atletico Dallas Youth PRE-ECNL 2016 Meighen | u11 | F | TX | 4 | 2026-08-23 |
| YMS ECNL RL 2013 | u14 | M | PA | 3 | 2026-05-30 |
| 2014 LFC Select | u13 | M | MN | 3 | 2026-08-29 |
| Hoosier FC - 2015 Elite Wolves I | u12 | F | IN | 3 | 2026-08-29 |
| Southeast 2015 Black | u12 | M | AZ | 3 | 2026-08-24 |
| CUP 2015 Black | u12 | M | OH | 3 | 2026-06-06 |
| FUTBOLTECH CHSC - 2015 LIVERPOOL | u12 | M | NJ | 3 | 2026-06-28 |
| UCCA 2015 Navy | u12 | F | MO | 2 | 2026-08-22 |
| Javanon 2015 Black | u12 | M | KY | 2 | 2026-08-29 |
| Freehold SL - Freehold SL Cyclone | u11 | F | NJ | 2 | 2026-08-30 |
| 2016 COPA White | u11 | M | OR | 2 | 2026-08-30 |
| Sphinx Soccer Academy - Sphinx Soccer Academy 15/16/17 Elite-Black | u12 | M | MA | 1 | 2026-05-24 |
| Michigan Jaguars PRE MLS 2014 1-DA | u13 | M | MI | 1 | 2026-06-07 |
| Elkridge United EYO 2012 | u15 | M | MD | 1 | 2026-06-07 |
| Elkridge United EYO 2011 | u16 | M | MD | 1 | 2026-06-07 |
| NJ Stallions 2013 Wave EDP | u14 | F | NJ | 1 | 2026-06-20 |
| Dynamo | u11 | M | NY | 1 | 2026-06-28 |
| YMS ECNL RL 2011 | u16 | M | PA | 1 | 2026-07-16 |
| 2012 Academy Silver | u15 | M | MN | 1 | 2026-07-18 |
| Nationals Genesee 2012 Black NL | u15 | F | MI | 1 | 2026-08-21 |
| 2014 Navy 2 | u13 | F | MN | 1 | 2026-08-30 |
| TFA 2015 Elite | u12 | M | OH | 1 | 2026-08-30 |
| Midwest FC 2013G Elite | u14 | F | IL | 1 | 2026-08-30 |
| 2015 Pre-MLS Navy | u12 | M | FL | 1 | 2026-05-24 |
| Beadling 2015 South Red | u12 | M | PA | 1 | 2026-05-25 |
| 2014 Pre-Elite II | u13 | M | CO | 1 | 2026-05-25 |
| ONE FC 2014 PRE-MLS | u13 | M | FL | 1 | 2026-05-25 |
| PA Classics PRE MLS Next Lancaster 2014 | u13 | M | PA | 1 | 2026-05-30 |
| SoCal Reds FC - SoCal Reds GA 2012 | u15 | F | CA | 1 | 2026-05-31 |
| Inter Connecticut 2014 SL | u13 | M | CT | 1 | 2026-06-07 |
| Torpedoes U12 Red | u13 | M | NJ | 1 | 2026-06-07 |
| 2014 Regional Blue | u13 | M | ME | 1 | 2026-06-07 |
| CFC Ole 2014 Academy #1 | u13 | M | CT | 1 | 2026-06-07 |
| Elmbrook United - 2012 GA | u15 | F | WI | 1 | 2026-08-30 |

## TGS teams the queue cannot refresh (8)

These failed with `No scraper available for provider tgs and no GotSport alias found`.
Six had no fall games to fetch anyway, so nothing was lost this time. The cost is that
a user clicking "find missing game" on a TGS-only team gets a silent failure.