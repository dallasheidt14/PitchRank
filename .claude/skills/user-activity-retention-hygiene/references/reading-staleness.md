# Reading Staleness on User-Interest Teams

How to tell a team whose data is missing from a team that simply is not playing.

## Contents

- Grade Against the Season, Not the Calendar
- Date Clustering Confirms a Season End
- Missing Scores Are a Provider Gap
- TGS Teams Cannot Be Refreshed Through the Queue
- What Counts as a Defect

## Grade Against the Season, Not the Calendar

A youth soccer season runs Aug 1 - Jul 31, and most league play restarts in
September. Spring seasons end in May, summer is tournaments only, and ECNL
schedules wind down in June and July.

So in August and early September, the majority of teams have no game since June
or July and no fall fixture on record yet. That is the normal state, not a
warning. A staleness rule counted in days flags nearly all of them.

Use one full season as the threshold. A record that stops for more than 365 days
has skipped an entire year of play, which no off-season explains.

## Date Clustering Confirms a Season End

When a batch of teams all stop within a few days of each other, and those dates
are weekends, they hit a season end together rather than losing data together.

Check it directly before concluding anything is broken:

```python
from collections import Counter
Counter(r["last_game"] for r in rows if r["last_game"])
```

Several teams sharing one date is league scheduling. Data loss does not
synchronize across unrelated clubs in different states.

## Missing Scores Are a Provider Gap

Games on record with null `home_score` / `away_score` do not come back from
re-scraping. Measured over a full batch: 100 missing scores, one recovered.

The provider has not posted the result. Treat these as a reported count, not a
worklist, and note that anything from the last two weeks may still post on its
own.

## TGS Teams Cannot Be Refreshed Through the Queue

`process_missing_games` has no TGS scraper. A TGS team with no GotSport alias
fails with `No scraper available for provider 'tgs' and no GotSport alias found`,
and its data only refreshes when the weekly TGS event scrape happens to cover
its event.

These failures are expected and recur every run. Report them grouped, and check
whether the affected teams actually had anything to fetch before calling it a
data gap — a TGS team between seasons lost nothing.

## What Counts as a Defect

| Signal | Defect? | Why |
|---|---|---|
| No games at all | Yes | The team page shows nothing to a user who saved it |
| Only future fixtures, never played | Yes | Same, and the team may not exist at the provider |
| Nothing in over a year | Yes | Disbanded or renamed; confirm before reporting missing data |
| Playing this season, absent from `rankings_full` | Yes | Unless the last ranking run predates the team |
| Last game in Jun/Jul, no fall fixtures | No | Off-season |
| Games with no score | No | Provider has not posted the result |
| Last game on a season-end weekend | No | League scheduling |

A watchlisted team that is genuinely dormant is a UI problem rather than a
scraping one: a paying user is tracking a squad that no longer plays, and the
page should say so.
