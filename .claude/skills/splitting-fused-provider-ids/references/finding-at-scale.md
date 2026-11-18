# Finding fused rows at scale

Find rows that hold two squads of one provider across the database, then give each row the SKILL.md treatment. Sections 1 and 2 only read; every write goes through SKILL.md Step 5 or the skill a section names, dry run first.

## 1. Detect

A row is a candidate when two of its provider ids, from one provider, each played on two or more of the same dates this season against different opponent rows, at different events, with different scores. Resolve merges on both sides first. GotSport leaves `event_name` NULL from 2026-08-01 (SincSports always does) and keeps a competition label in `games.competition`, so compare `COALESCE(event_name, competition)`. That label is often generic (`League`, `State Cup`) and shared by unrelated events, so the event test misses some candidates; it does not invent them.

```sql
WITH s AS (
  SELECT game_date, provider_id, COALESCE(event_name, competition) AS ev, home_team_master_id AS team,
         home_provider_id AS pid, away_team_master_id AS opp, home_score AS own, away_score AS os
  FROM games WHERE game_date >= '<season start>' AND game_date <= current_date AND NOT coalesce(is_excluded, false) AND home_score IS NOT NULL
  UNION ALL
  SELECT game_date, provider_id, COALESCE(event_name, competition), away_team_master_id,
         away_provider_id, home_team_master_id, away_score, home_score
  FROM games WHERE game_date >= '<season start>' AND game_date <= current_date AND NOT coalesce(is_excluded, false) AND home_score IS NOT NULL
), r AS (
  SELECT s.*, COALESCE(m.canonical_team_id, s.team) AS row_id, COALESCE(mo.canonical_team_id, s.opp) AS opp_row
  FROM s LEFT JOIN team_merge_map m ON m.deprecated_team_id = s.team
         LEFT JOIN team_merge_map mo ON mo.deprecated_team_id = s.opp
  WHERE s.team IS NOT NULL AND lower(trim(coalesce(s.pid, ''))) NOT IN ('', 'none', 'null')
)
SELECT a.row_id, a.provider_id, a.pid AS pid_a, b.pid AS pid_b, count(DISTINCT a.game_date) AS days
FROM r a JOIN r b ON a.row_id = b.row_id AND a.provider_id = b.provider_id AND a.game_date = b.game_date
 AND a.pid < b.pid AND a.opp_row IS DISTINCT FROM b.opp_row
 AND a.ev IS DISTINCT FROM b.ev AND (a.own, a.os) IS DISTINCT FROM (b.own, b.os)
GROUP BY 1, 2, 3, 4 HAVING count(DISTINCT a.game_date) >= 2;
```

It runs inside the MCP server's two-minute cap. Each line is a pair of ids, so a row with three ids appears once per clashing pair. The query leaves out clashes within one event (two brackets of one tournament, or one fixture recorded against two copies of an opponent), which are weaker evidence; when widening it, report those rows separately.

## 2. Confirm each pair at the provider

For GotSport, read every id's `team_details` through `TeamDetailsPacer.get` in `src/utils/gotsport_team_details.py`, which spaces requests three seconds apart and waits out one block. It returns the raw response, including the last 403 when it gives up, so treat 404 as no team, stop on any other status but 200, and read `name`, `club_name`, `display_age_group`, `display_gender` and `team_association` as `TeamDetailsResolver.resolve` maps them. For other providers, read each id's own name per SKILL.md Step 2 (TGS through Step 1's `get_games_for_flight`).

A pair is two squads when the provider's ages or genders differ, or its names differ by a squad word (Step 2). Hold a pair the provider names identically; the same-day games say two squads and the names do not.

## 3. Decide each moving id

Hold the whole row when its own `teams.provider_team_id` played no game this season or belongs to another provider: nothing can be measured against it. Otherwise consider only ids that clash with the row's own id; an id that never clashed with it stays. Then, in order:

- **Hold** when the provider's club or state disagrees with the row's, it gives no team name, or its age conflicts with a band or U-age in its own name.
- **Existing row**: a live row for the squad on any provider is the target (`--to-existing`). Look for one by club, age, gender and the provider's exact team name; it is often the squad's SincSports row, empty this season because the squad's games went to the fused row. Run Step 4's duplicate-fixtures check against it.
- **Merge**: a deprecated row holding the id, merged into this row, means the merge brought it in. Run the reuse check in SKILL.md's intro, and leave the merge when it shows the absorbed row was the kept squad's own. Otherwise, when `team_merge_map.merged_by` names a person rather than a job (`pitchrank-bot`, `cleany-auto`, `pitchrank-operator`), show the owner the evidence and ask before reverting. Revert under `merging-duplicate-teams` "Splitting a fused row", then move the id's games filed on the row since the merge back to the restored row.
- **New row** otherwise: the provider's name, age and gender, and the fused row's club and state. The owner chose this for provider-confirmed squads (2026-11-18: "each other id gets its own new team, named and aged from GotSport"), in place of Step 3's sibling naming.

## 4. Older games

Move an id's games from before Aug 1 only when that season also shows the two ids apart, by a day meeting Section 1's test or a head-to-head between them. Leave the rest in place and count them in the record.

## 5. Kept rows

- **Name**: the kept row often wears a moved squad's name. Compare its name with every id's current provider name by similarity, not exact match, since the copied name can differ by a suffix or a format change; rename under Step 5.
- **Unscored fixtures**: hide them per Step 4, skipping any whose same-pair twin is not also being hidden (`supabase-pitchrank`, "Bulk `is_excluded` updates").
- **Age**: send rows that held two cohorts through `correcting-team-age-groups`, as Step 6 says.
