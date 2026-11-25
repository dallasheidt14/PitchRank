# PitchRank Automation Suite

## Overview

The owner runs PitchRank alone, and too much of the week goes on noticing problems by hand and
repeating the same multi-step flows. A scheduled job goes red or quietly does nothing, and nobody
hears until a customer writes in. Customer emails sit in the inbox until a session is opened to
diagnose them. Every tournament import re-derives the same dry-run → review → execute → verify
steps, and status notes pile up "check after the next ranking run" items that only get checked
when someone remembers.

This project adds four automations. Each one ships as its own PR:

1. **Daily job check.** A GitHub Actions workflow reads the data each scheduled job should have
   changed and emails the owner when a job did not do its work.
2. **After-ranking follow-up.** A Tuesday-morning run on the owner's PC checks the open "after the
   run" items in the local status notes against the database, emails one summary and marks the
   confirmed items done.
3. **Customer-email triage.** A run on the owner's PC every two hours finds new customer emails,
   diagnoses each one read-only, saves a draft reply in Gmail and queues any fix or tournament
   import for one-line approval.
4. **Tournament import.** A skill that carries any of the four per-event importers from event URL
   to verified import, stopping for the owner's decisions. Its work is queued by the triage or by a
   dated watch list, and it runs in the owner's session.

**Bounds.** There is one operator (the owner). The only concurrent writers are the existing
scheduled jobs and the triage task, which writes only local files. This is a personal-tool rigor
tier: a missed alert costs a day, not data.

**Recovery by re-running, not bookkeeping.** The owner chose this on 2026-11-24, after three review
rounds kept finding new gaps inside crash-recovery machinery. Every step that is interrupted is
simply run again. No step keeps receipts, write-ahead states or exactly-once guarantees. A rerun
can leave a small, visible leftover, and those are accepted:

| Interrupted step | Visible leftover |
|---|---|
| Triage, after a draft was saved | A second draft in the thread, which the owner deletes (R34). |
| Sender, after an email was accepted | The summary is sent again, because an outbox file is deleted only after its send is accepted. |
| Follow-up, mid-way through note edits | An index line that lags its note. The next Tuesday run treats `after-run (confirmed …)` lines as done and corrects index lines that disagree with their note. |
| The owner's session, mid-way | Proposals and imports show again. Their fresh dry runs show what is already done. |

**The two PC tasks never overlap.** A wrapper that finds the other task's wrapper still running,
named in that task's PID file in the wrapper folder and alive, exits without running. The next
trigger retries.

**The safety line, enforced rather than promised:** no unattended run can write to the database,
run a script or hook, send email, or touch the owner's decisions. Every database write and every
script run happens in an interactive session after the owner says yes (R23, Design → Safety).

## Users

- **Owner/operator.** The only user. Wants problems surfaced without asking, and decisions handed
  over in the fewest steps. Reads summaries on a phone, in plain English, in Arizona time, with
  team links rather than IDs.
- **Customers** (indirect). Parents and coaches who email about a team. They benefit from faster,
  evidence-backed replies, but never receive anything the owner has not sent.

## Requirements

### Daily job check (build 1)

- **R1.** Once a day, the system shall check from the database and the GitHub API whether each
  scheduled job did its work, and email the owner only when at least one check fails.
- **R2.** A publication is complete when three things hold:
  - every `rankings_full` row has a non-null `last_calculated` no older than the most recent
    Monday 12:30 UTC ranking start;
  - the table is not empty;
  - its row count is at least 95% of the newest earlier `ranking_history` snapshot's count. On
    2026-11-24 that was 150,056 rows against 150,286 for 2026-11-23.

  The daily check shall flag the rankings as stale or partial when the publication is not complete
  and that Monday start is more than 30 hours old. Before then, it reports "awaiting this week's
  run" rather than passing. The every-row test is needed because the publisher stamps one timestamp
  on all records and upserts them in batches (`scripts/calculate_rankings.py:239`,
  `_save_batch_with_retry`). The newest timestamp therefore moves forward even if a later batch
  fails. The count test catches a run that never reached some teams. Dropped teams' rows are
  normally deleted each run. The cleanup only warns when it fails, though
  (`scripts/calculate_rankings.py:558`), so a stale-rows alert names both possible causes: a
  partial publish, or a failed cleanup of removed teams.
- **R3.** The expected-provider set shall be derived from the scheduled import workflows' YAML,
  never from import history. History drops a provider as soon as it breaks: YSSL has `build_logs`
  rows in only 2 of the last 26 weeks.
  - **Which workflows count.** A scheduled workflow counts if a step runs
    `import_games_enhanced.py <path> <provider>` (the provider is that argument), any other
    `scripts/import_*.py` (the provider is that script's `PROVIDER_CODE` constant, as in
    `import_yssl.py:102`, `import_demosphere.py:105` and `import_heartland.py:116`), or
    `process_missing_games.py` (`gotsport`).
  - **The test.** It fails when a scheduled workflow runs any `import_*.py` or the drainer but maps
    to no provider code.
  - **The flag.** A provider is flagged when, within its cadence plus 24 hours, it has neither a
    non-dry-run `build_logs` row nor a counted run (R7) of its mapped workflow. Rows whose
    `parameters->>'dry_run'` is `true` are ignored, because `_log_build_metrics` writes rows on dry
    runs too.
  - **Why a successful run also counts.** It covers a healthy run with nothing to import: YSSL
    returns before calling the logged importer when it has no records (`import_yssl.py:1387`).
- **R4.** The quiet-import rule: a provider in the R3 set that averaged 50 or more new games a week
  over the 4 weeks before the last two, and brought under 10% of that average in each of the last
  two 7-day windows, shall be flagged. Requiring two quiet weeks delays a real breakage by a week.
  In exchange, a single slow week never alerts. A season wind-down can still alert once (Demosphere
  would, the week of 2026-11-30), which is accepted.
- **R5.** The system shall flag a `scrape_requests` row in `processing` whose `processed_at` is more
  than 6 hours old. The processor sets `processed_at` at claim time (`process_missing_games.py:126`).
  It shall also flag the drainer as stalled when the oldest `pending` row is more than 2 hours old
  and no row reached status `completed` in the last 6 hours. `failed` rows do not count as progress,
  even though `completed_at` is set on them too.
- **R6.** The system shall read each workflow's cron entries from its YAML, never from a
  hand-written list, and compute each entry's due times.
  - **Daylight-saving pairs.** Two entries are merged into one due series only when they share the
    same days and minute and differ by exactly one hour. Every other entry is its own series.
    `tgs-score-reconcile.yml`'s `23 5 * * 2,5` is due Tuesday and Friday, and
    `compare-live-monitoring.yml`'s daily and Monday entries are two series.
  - **Daily or less often.** Such a series is flagged when no counted run (R7) of the workflow
    started within its interval plus 24 hours of a due time. The slack is needed because scheduled
    runs fire 7–12 hours late: `enqueue-active-teams` ran 7–11.6 hours after its cron every day of
    2026-11-18..24.
  - **More often than daily.** Such a series is not flagged on timing, because GitHub drops most of
    those runs: `backfill-unknown-team-names` fired 23 of 672 expected times that week. Their run
    counts appear in the weekly all-clear (R8).
  - **Disabled workflows.** Workflows GitHub reports as disabled are excluded from flags.
- **R7.** A **counted run** is a run on `main` in which some job concluded `success`, and in that
  job a **productive step** also concluded `success`.
  - **Workflows with a schedule guard** (a step with `id: guard`). A productive step is one whose
    YAML `if:` references `steps.guard.outputs`.
  - **Other workflows.** It is any step except setup steps (checkout, language setup, dependency
    install) and the steps GitHub adds itself (`Set up job`, `Post …`, `Complete job`).

  The guard rule is needed because the daylight-saving guard skips steps, not jobs, and each
  guarded workflow ends with an unguarded `Report results` step marked `if: always()`
  (`ut-scraper.yml:193`, `or-scraper.yml:194`, `wa-scraper.yml:186`). The inactive cron's run
  therefore ends `success` with its import skipped. Run 45215524977, the inactive UT run of
  2026-11-23, is the acceptance case: it must not count.

  **Series.** A scheduled run belongs to the series (R6) whose most recent due time precedes its
  start. A run satisfies and clears only its own series, so a daily capture cannot keep a missing
  Monday review green.

  The flags:
  - **Daily or less often.** For each series that runs daily or less often, the system shall flag
    a latest scheduled run on `main` that ended `failure`, `cancelled` or `timed_out`.
  - **Chain workflows.** For a workflow that dispatches its own next link, the same applies to the
    latest bot-dispatched link on `main`.
  - **More often than daily.** It flags `failure` only.
  - **Clearing.** A flag stays until a later counted run of that workflow; there is no 24-hour
    window.

  These rules mirror `.claude/hooks/session-start.sh`. That hook already detects chains, filters
  bot links to `main`, and treats `cancelled` as routine for frequent jobs. They catch the weekly
  ranking run, whose recent runs ended `cancelled` at the 6-hour runner cap after rankings were
  saved.
- **R8.** A separate weekly trigger (Tuesday 19:00 UTC, noon Arizona) shall send a short all-clear
  email, even when nothing failed. Its cron sits after R2's 30-hour mark (Tuesday 18:30 UTC), so the
  rankings line is normally decided rather than "awaiting". It carries one line per check, the
  more-than-daily run counts, the disabled workflows, and "awaiting" for any check not yet due. The
  daily and weekly triggers are told apart by `github.event.schedule`.
- **R9.** The email shall be plain English. Each problem leads with what broke, plus a date
  labelled with what it measures, derived from the data. Examples: "last counted run 2026-11-16",
  "oldest stuck request claimed 2026-10-05". Each problem carries a link to look at. A problem that
  persists is repeated daily. Because the check keeps no state, it never claims to know when a
  problem first began.
- **R10.** When run with `--dry-run` on the owner's PC, the system shall print the email it would
  send and send nothing. The workflow exposes no dry-run input and logs only counts, because
  Actions logs on this public repo are public. That includes the response body that `send_email`
  logs when Resend rejects a request (`src/utils/resend_email.py:36`), which build 1 suppresses
  on Actions.

### After-ranking follow-up (build 2)

- **R11.** The owner's PC shall start the follow-up every Tuesday at 7am Arizona. Further triggers
  at 11am, 3pm and 7pm exit at once when this week's run is already done (R12). A start missed
  because the PC was off or asleep runs as soon as the owner is next logged on.
- **R12.** Each run shall first apply the R2 completeness test immediately, without the 30-hour
  grace.
  - **Not complete.** It sends "ranking run not finished, checks skipped" and exits. The next
    Tuesday trigger tries again.
  - **Complete.** It runs R13–R14 and reports the week complete. The wrapper writes the done
    marker only after the summary email has been accepted (R33).

  R15 and R32 are evaluated on every run, before the completeness test. Their warnings lead the
  first email of the week that the sender accepts, whichever kind it is. The wrapper records that
  they went out, and later triggers do not repeat them.
- **R13.** The follow-up shall read the local status notes. An open item is a line beginning
  `after-run:` that states one checkable claim, for example
  `after-run: Tuzos Royals U10 appears on the AZ U10 board`. Notes written before this convention
  are read best-effort: their "next:" text mentioning a ranking run. Each item shall be checked
  read-only against the database and recorded as confirmed, still wrong (with the evidence) or not
  checkable.
- **R14.** The follow-up shall send one plain-English summary email with team links. For each
  confirmed item, it shall change the note's line to `after-run (confirmed YYYY-MM-DD): …` and update
  the note's `MEMORY.md` index line to match. It shall never change team data.
- **R15.** The follow-up shall confirm that the daily job check (build 1) had a counted run on at
  least 5 of the last 7 days, using the run history the wrapper supplies (Design → Key flows). It
  leads the week's first email with a warning when that fails or the history is unreadable.

### Customer-email triage (build 3)

- **R16.** Every two hours from 6am to 10pm Arizona, the owner's PC shall run the triage. A message
  is a customer message when it reaches the connected PitchRank inbox and its customer address
  comes from one of two places:
  - **From.** The ordinary case.
  - **Reply-To,** read from the raw message, when From is a PitchRank form sender
    (`feedback@mail.pitchrank.io` for site feedback, and the MatchBalance inquiry sender).

  A thread is eligible when its newest message that is not a draft is a customer message from the
  last 14 days that has not yet been handled (R34). PitchRank's own report senders and automated
  services (Stripe, newsletters, notification senders) are never customer messages. A form message
  with no Reply-To is recorded "handled, no reply address" with no draft, and is listed in that
  run's owner summary. Anonymous feedback may omit the email (`frontend/lib/email/feedback.ts:132`).
- **R17.** The triage shall handle at most 10 threads per run, oldest first. If a run is still
  going, the next scheduled start shall not begin. The wrapper stops a run that exceeds 25 minutes
  (R33).
- **R18.** For each thread, the triage shall sort the email into one of: team-data problem, missing
  games, tournament not imported, billing/account, or other. It diagnoses only from read-only
  database queries, following the evidence rules of the skill that owns the question:
  - **Duplicates** (`merging-duplicate-teams`): the shared opponents and dates in the two rows'
    games.
  - **Age group** (`correcting-team-age-groups`): this season's opponents, read by their names.
  - **State** (`assigning-team-states`): the evidence tiers short of the paid GotSport probe.
  - **Missing games:** the team's stored games against the dates and opponents the email names.
  - **Tournament not imported:** the email names an event on a supported host, and the team has
    no stored games from that host in the event's dates. Stored games cannot prove a Soccer Events
    Group event is missing, because they carry no event id. The triage therefore queues an import
    check (R28) instead of declaring the event missing.

  A question that needs a paid probe, Stripe, the provider's website or a script is marked
  "needs your session" with the evidence gathered so far, and its draft says the team is looking
  into it. Every billing/account email is in this group. The verdict comes from the evidence, never
  from the email's wording alone.
- **R19.** The triage shall save a draft reply in the customer's thread, addressed explicitly to
  the customer address from R16, that states what was found. It shall never send it. Where a fix
  or import is proposed, the draft describes it as pending.
- **R20.** The triage shall record each proposed data fix as a proposal. A proposal carries the
  thread link, the team link, the customer message it answers, the draft it saved, the evidence and
  the exact change it would make. Proposals hold no approval state, and the unattended runs cannot
  reach where approvals are kept (Data).
- **R21.** After each run that found something, the owner shall get a short summary email: threads
  handled, drafts saved, proposals and imports queued, items needing a session.
- **R22.** As the owner, I want to say "apply approved fixes" in a session and see every proposal at
  once, so that one yes or no each clears the queue.
  - **Checkout check.** The session first confirms that the skills and scripts it will run in
    `C:\PitchRank` match `origin/main`, using `git fetch` and then `git diff --quiet origin/main --`
    on those paths. Otherwise it stops and names the files that are behind. It never resets the
    owner's checkout.
  - **Live approval.** Approval comes only from the owner's live answer in that session, for the
    exact team and change displayed.
  - **Re-checked fixes.** Each approved fix first re-runs the owning skill's dry run. If its result
    differs from the proposal, the difference is shown and the owner is asked again.
  - **Writing.** The write goes through the owning skill's existing guarded path, which writes its
    own undo record. The session then records the decision as applied.
  - **Interruptions.** If a session stops before recording, the proposal simply shows again next
    time. Its fresh dry run then shows nothing left to change, and the owner marks it done (see
    "Recovery by re-running" under Bounds).
  - **Repeat reports.** When a proposal matches a team and change the owner declined before, the
    session shows the earlier decline and its date beside it. The triage never reads decisions, so
    a repeat report is expected and handled here.
  - **Draft follow-up.** After applying, the customer's reply is brought up to date. An unsent
    draft gets the update added below the owner's text, never replacing it. If the owner already
    sent the draft, a new follow-up draft is created in the thread.
- **R23.** An unattended run shall be unable to write to the database, run a script or hook, send
  email, or write anywhere except its allowed folders. This is enforced by how the run is launched
  (Design → Safety), not by its instructions. A probe runs at registration, and the wrapper runs it
  for each task until that task has one passing probe on the current Arizona date. It checks both
  directions:
  - **Must be denied:**
    - Bash;
    - a read of `C:\PitchRank\.env`;
    - a write outside the allowed folders;
    - a write to the decisions folder or to the wrapper's own folder;
    - a Gmail send;
    - any project hook output.
  - **Must succeed:**
    - a write to the task's state folder;
    - a read-only Supabase query;
    - a read of `watchlist.json`;
    - Gmail search, thread read and raw message read;
    - for build 2, a read and an edit of a probe file in the notes folder.
  - **Registration only:** the probe also creates one draft, which the registration script asks the
    owner to delete. Unattended runs cannot delete drafts, so the daily probe skips this check.

  A failed probe stops the run and alerts the owner (R33).

### Tournament import (build 4)

- **R24.** As the owner, I want to hand over an event URL from any of Tourney Central,
  Athletes2Events, Soccer Events Group or HTG Sports, so that the skill picks the right importer and
  runs its dry run.
  - Acceptance: the importer is chosen from the URL's host, and an unsupported host is reported,
    not guessed.
  - Acceptance: a Soccer Events Group URL is converted to the integer `--program-id` its importer
    requires (`scripts/import_soccereventsgroup_event.py:722`).
  - Acceptance: `--days-back` is computed from the event's own dates, not left at the default 14.
- **R25.** After the dry run, the skill shall build the owner's review sheet with a decision tab.
  It joins every source of evidence:
  - the importer's team report;
  - the importer's cross-age games, where it writes them;
  - the importer's held games, meaning the fixtures it would skip because a team is unmatched,
    with both provider team IDs. Build 4 adds a held-games CSV to each importer's dry run that does
    not write one;
  - the matched database team's stored age, gender and state.

  Each team that needs a person (unmatched, cross-age, wrong state, wrong gender) gets its own row,
  with its evidence and the fixtures the decision affects. Every cell holding provider-supplied text
  is written as literal text, never as a formula.
- **R26.** The skill shall turn the owner's decisions into the importer's own flags (`--leave-out`,
  `--state`, `--age`, `--gender`) and into hand links, following the R35 order. It shall show the
  exact commands before running them, and run `--execute` only on the owner's go-ahead.
  - **Importer flags.** Today only `import_tourneycentral_event.py` and `import_htgsports_event.py`
    take these flags. Build 4 adds the same four, with the same meaning, to
    `import_athletes2events_event.py` and `import_soccereventsgroup_event.py`.
  - **Hand links.** These go through a new guarded link step. It is a dry run by default, refuses an
    alias that already points elsewhere, and writes its undo record to
    `data/backups/<provider>_<event>_prelink/`, the convention the earlier hand-linked imports used.
  - **Unsupported decisions.** A decision the chosen importer cannot express holds the whole import.
    It is never dropped to make a command runnable.
- **R27.** After execute, whether it succeeded or failed, the skill shall check the database
  against the approved dry run (R35). It matches teams by provider team ID, because a new team's
  master ID differs between the dry run and the real insert. It then lists:
  - the approved fixtures that landed;
  - any that are missing;
  - any team or game for those provider team IDs that was not in the approved output.

  Undo uses the guarded steps' own records: the link step's and the importer's. If execute failed
  partway, the owner can re-run the dry run to see what remains.
- **R28.** When the triage (R18) finds a tournament on a supported host that may not be imported,
  it shall queue an import check for that event. The dry run and review sheet are built when the
  owner opens "apply approved fixes" (R30), not by the unattended run.
- **R29.** The skill shall keep a dated watch list of events to import later.
  - **Entries.** Each entry holds the event's full URL (Athletes2Events needs its subdomain as well
    as its numeric ID) and a run-after date. The date defaults to the day after the event's last
    day.
  - **Queueing.** On or after that date, the triage queues an import check for the entry. It does
    this in each run until one watch-list pass has completed on that Arizona date.
  - **What the owner decides.** The entry stays on the list until the owner, in the session,
    either removes it or gives it a new run-after date. A new date queues a fresh check on that
    date. There are no automatic closing rules: the owner reads the dry run and decides.
- **R30.** As the owner, I want "apply approved fixes" (R22) to also run the queued imports' dry
  runs and present their review sheets, so that one session clears both queues.

### Added during review

- **R31** (build 1). The system shall exit non-zero when any source cannot be read, or when an email
  it was required to send is not accepted (`send_email` returns `False`). An unreadable source is
  reported as "check incomplete", never as a pass.
- **R32** (build 2). The follow-up shall report the triage's last successful run from the triage's
  run records. If there was none in the last 24 hours, it shall warn.
- **R33** (builds 2 and 3). The wrapper, not Claude, owns each run's start and final outcome.
  - **Timeouts.** It stops `claude -p` at 25 minutes for the triage and 50 for the follow-up. Task
    Scheduler's own limits, 35 and 60 minutes, are only a backstop.
  - **Outcomes.** It records success, failure, timeout, failed probe or failed send in the run
    records. Recording happens after any email has been attempted.
  - **Alerts.** On anything but success, it emails the owner itself; that alert does not depend
    on Claude.
- **R34** (build 3). The triage shall track handled work by the customer message it answered, not
  by thread.
  - **Order.** It first saves the draft, then writes one record for the message in a single write.
    That record holds the proposals or a no-fix note, any import check, and the draft ID.
  - **When a message is handled.** A message is handled once its record exists. The session only
    ever sees complete records. A new customer message in an already-handled thread makes the
    thread eligible again.
  - **A run that dies mid-message.** Its message is redone by the next run, which may leave a
    second draft in the thread. That is accepted, and the owner deletes the extra one (see
    "Recovery by re-running" under Bounds).
- **R35** (build 4). The import runs in this order, which matches today's hand process:
  1. The owner decides from the review sheet (R25).
  2. Approved hand links are written through the guarded link step.
  3. The dry run is re-run with the decision flags. It now sees the links, and its output is the
     approved set.
  4. The owner approves that output.
  5. `--execute` runs immediately after.

  Because the importers fetch the event again at execute, R27 compares what landed against the
  approved output.

## Design

### Architecture

Two hosts, chosen by where the data lives:

- **GitHub Actions** (build 1). It needs only database and GitHub API access. The existing owner
  report `investigate_missing_game_requests.py` already runs there and sends through
  `src/utils/resend_email.send_email` to `ALERT_EMAIL`. GitHub's scheduler skips and delays runs,
  so build 2 checks that build 1 ran (R15).
- **The owner's PC via Windows Task Scheduler** (builds 2 and 3, and the R29 watch list). The
  status notes live only on this PC, the repo is public, and the Gmail connector and read-only
  Supabase connection are configured here. Two tasks start headless Claude Code (`claude -p`)
  through a PowerShell wrapper:
  - **"PitchRank after-ranking check":** Tuesday at 7am, 11am, 3pm and 7pm AZ, with
    run-after-missed-start on (R11–R12).
  - **"PitchRank inbox and imports":** every 2 hours, 6am–10pm AZ, with "do not start a new
    instance" on (R17). It works the watch list until one pass completes each day (R29).

  Both tasks run as the owner, and only when the owner is logged on, because the Gmail connector's
  credentials live in the owner's profile. Timeouts and outcomes belong to the wrapper (R33). A
  PowerShell registration script in the repo creates both tasks.

### Automation checkout

The tasks run from a dedicated clone at `C:\PitchRank-automation`, never from `C:\PitchRank`, for
two reasons:
- **The working checkout is the wrong revision.** It is often on a feature branch and weeks behind
  `origin/main`.
- **It carries a local permissions file.** Its `.claude/settings.local.json` allows Write and Edit
  everywhere, and on 2026-11-24 that overrode a folder-scoped allowance in a probe.

At each start, the wrapper does three things:
1. Runs `git fetch origin` and `git checkout --detach origin/main` in the clone.
2. Refuses to run, and alerts the owner (R33), if the clone is dirty, or if it or the user settings
   carry a broad Write/Edit/Bash allow.
3. Records the revision it ran.

Because it is a clone and not a worktree, the merged-worktree cleanup never touches it, and it adds
nothing to `git worktree list`. The clone needs no `.env`, Python environment or `node_modules`,
because the unattended runs execute nothing. Absolute paths in the prompts locate everything
outside it:
- **Status notes:** `C:\Users\Dallas Heidt\.claude\projects\C--PitchRank\memory\`, reached through
  `--add-dir`.
- **Local state:** `C:\PitchRank-automation\data\automation\`, which is gitignored, so a checkout
  leaves it alone.

### Components

| Component | Build | Consumer |
|---|---|---|
| `scripts/check_scheduled_jobs.py` (`--dry-run`) | 1 | the daily workflow |
| `.github/workflows/scheduled-jobs-check.yml` (daily cron + Tuesday 19:00 UTC all-clear cron, `actions: read`) | 1 | GitHub scheduler |
| Test: every scheduled import workflow maps to a provider code (R3) | 1 | CI |
| `.claude/skills/after-ranking-followup/SKILL.md` | 2 | the Tuesday task |
| `.claude/skills/customer-email-triage/SKILL.md` (unattended mode + "apply approved fixes" mode) | 3 | the 2-hourly task; the owner in a session |
| `.claude/skills/importing-tournament-events/SKILL.md` | 4 | the owner's "apply approved fixes" session; the owner directly |
| The four decision flags on the Athletes2Events and Soccer Events Group importers; a held-games CSV in every importer's dry run where missing | 4 | the import skill (R25, R26) |
| Guarded event link step (dry run by default, undo record) | 4 | the import skill (R26) |
| `scripts/local_automation/register_tasks.ps1`, the wrapper, the R23 probe, and the wrapper's sender step | 3 | the owner, once; every task start |

**The sender step** is a separate Python process the wrapper starts after `claude -p` exits:
- It loads `RESEND_API_KEY` and `ALERT_EMAIL` from `C:\PitchRank\.env` into its own process only,
  sends each outbox file through `send_email` to `ALERT_EMAIL`, and checks the returned Boolean.
- Claude's process never receives the key and never chooses the recipient.

The skills hold only generic procedure, so they are safe in the public repo. Everything specific to
a customer or a team stays local.

### Data

Unattended state lives under `C:\PitchRank-automation\data\automation\`, the only folder those runs
may write:

- `proposals/<customer-message-id>.json`: one complete record per handled customer message,
  written in a single write after its draft is saved. It holds the proposed fixes or a no-fix note,
  any import check, and the draft ID (R20, R34). Only the triage writes these.
- `imports/<provider>-<event-id>-<queued-date>.json`: one import check per event per day it was
  queued. It holds the event's full URL and the customer messages or watch-list entry that asked
  for it (R28, R29). The triage creates it, or rewrites it whole to add an origin. A later re-date
  creates a new file, so each check is decided once.
- `outbox/`: summary files for the sender step. The sender deletes each one only after its send is
  accepted.
- `result.json`: what this run finished (week complete, watch-list pass done), for the wrapper to
  record.

Wrapper-owned records live under `C:\PitchRank-automation\data\automation-wrapper\`. Claude can
read that folder, because it is inside the clone, but has no Edit rule for it, and R23 checks that
a write there is denied:
- `runs.jsonl`: each task's start, outcome and revision, passing probes, the watch-list passes and
  weekly warnings that `result.json` and the sender confirmed (R12, R23, R29, R32, R33).
- `<task>.pid`: the running wrapper's process ID, removed on exit, so the two tasks never overlap
  (Bounds).
- `github-runs.json`: build 1's last 7 days of runs, with branch, start time and conclusion,
  written with `gh` before `claude -p` starts. On any `gh` error it holds an explicit "unreadable"
  (R15).
- `followup-done-<ISO week>.marker`: written by the wrapper when the follow-up reported the week
  complete and the sender accepted the summary (R12).

Owner-only state lives under `C:\PitchRank\data\automation-decisions\`. That folder is outside every
unattended write scope, and R23 checks that a write to it is denied.
- `decisions.json`: the owner's yes, no or done per proposal and import check, with dates and the
  team and change each one covered (R22). Only the interactive session writes it.
- `watchlist.json`: events with their full URL and run-after date (R29). Only the interactive
  session writes it. The triage reads it through the single-file rule described under Safety.

Review sheets and undo records follow the existing `data/raw/<provider>/` and `data/backups/`
conventions in `C:\PitchRank`, where the interactive session runs.

Build 1 keeps no state. "Since when" and "still open" are derived on every run from the data and
the GitHub run history (R7, R9).

### Key flows

- **Daily check:**
  1. Query the rankings, `ranking_history`, `build_logs`, `games` and `scrape_requests`.
  2. List workflows and their runs (with jobs) through the GitHub API, and parse each YAML for its
     cron series and its provider mapping.
  3. Build the findings, and email if any finding exists. Exit non-zero on any unreadable source or
     a rejected send.
  4. The Tuesday trigger sends the all-clear.
- **Triage run:**
  1. The wrapper refreshes the clone, checks the settings, runs the probe if this task has no
     passing probe today, and writes `github-runs.json`.
  2. `claude -p` searches the inbox and skips handled messages and non-customer senders. For each
     thread it classifies the email and diagnoses read-only.
  3. Per message, it saves the Gmail draft, then writes the message's complete record (R34).
  4. If no watch-list pass has completed today, it works the watch list. It then writes the outbox
     summary and `result.json`.
  5. The wrapper runs the sender step, then records the outcome.
- **Follow-up run:** the wrapper prepares as above. `claude -p` evaluates R15 and R32, applies
  R12's completeness test, then runs R13–R14 if the publication is complete. The wrapper sends,
  records, and writes the done marker when R12 allows it.
- **Apply approved fixes (interactive, in `C:\PitchRank`):**
  1. Check the checkout (R22).
  2. Load the proposals and import checks with no decision yet. For each import, run its dry run
     and build its review sheet.
  3. Present everything, with any earlier decline shown beside a repeat.
  4. Work each yes: re-run the dry run and show any difference, run the guarded write, record it
     applied, and bring the draft up to date. Record each no.
- **Tournament import:**
  1. URL → importer by host (a Soccer Events Group URL → ProgramID).
  2. Dry run with an event-dated `--days-back`.
  3. Review sheet → owner decisions.
  4. Write the approved hand links (guarded, undoable).
  5. Re-run the dry run with the decision flags, and the owner approves that output.
  6. Execute.
  7. Check what landed against the approved output (R27).
  8. For a watch-list event, the owner removes it or re-dates it.

### Safety

Unattended runs (builds 2 and 3) are launched so that the forbidden actions are impossible, not
merely discouraged. `claude -p` runs with these flags:

- **`--permission-mode dontAsk`.** It denies every tool call not pre-approved.
- **`--settings '{"disableAllHooks": true}'`.** Project and user hooks would otherwise run their
  own commands. The clone inherits a SessionStart hook that runs `git` and Python, and post-edit
  hooks.
- **`--allowedTools`:**
  - the read-only Supabase tools;
  - `mcp__claude_ai_Gmail__search_threads`, `get_thread`, `get_message` (raw format, for
    Reply-To) and `create_draft`;
  - `Edit(./data/automation/**)`, which also governs the Write tool;
  - `Read(...)` on `C:\PitchRank\data\automation-decisions\watchlist.json` (triage only);
  - for build 2 only, `Edit(...)` on the notes folder reached through `--add-dir`.

  Plain `Read`, `Glob` and `Grep` are never listed. On 2026-11-24 a plain `Read` allowance let a
  headless run read a file outside its working directory. Without it, the same read was denied,
  while reads inside the working directory needed no allowance.
- **`--disallowedTools`:** `Bash`, `PowerShell`, every `mcp__supabase-write__*` tool, and Gmail
  `send_message`, `reply`, `forward`, `update_draft`, `delete_draft`, trash and label tools.

Drafts are updated only in the owner's session (R22). Reads work inside the clone, which is the
working directory, and inside the notes folder added with `--add-dir`. Outside them, the only
readable file is `watchlist.json`, through its single-file rule. `C:\PitchRank\.env` is
therefore unreadable, and R23 checks that.

**Verified on 2026-11-24**, from headless runs on this PC:
- **Writes were denied** under `dontAsk` with no allowance: a `touch` and a Write.
- **Read-only Bash was not.** `echo` ran, which is why Bash is disallowed outright. With
  `--disallowedTools Bash`, the run had no Bash tool at all.
- **A `Write(./state/**)` rule allowed nothing,** even inside the folder.
- **`Edit(./state/**)` allowed** a Write inside the folder and denied one outside it.
- **`--settings '{"disableAllHooks": true}'`** removed the project SessionStart hook's output; it
  appeared without the flag.
- **`C:\PitchRank`'s `settings.local.json`** overrode a folder rule. That is why the runs use the
  clone, and why the wrapper refuses broad allows.

Not yet verified, and covered by the R23 probe before builds 2 and 3 rely on them:
- `--add-dir` with an `Edit(...)` rule on the notes folder;
- a `Read(...)` rule on a single file outside the clone;
- Gmail raw-format reads;
- `create_draft` from a Task Scheduler start.

Further protections:
- **The database connection** is the project's Supabase MCP, launched with `--read-only`
  (`.mcp.json`). No unattended run gets a database key.
- **Email.** Owner email goes out only through the sender step, to the fixed `ALERT_EMAIL`.
  Customer replies only ever exist as Gmail drafts.
- **What leaves this PC.** Owner emails never include customer email addresses or long ID lists;
  they link to the Gmail thread and the team page instead. Build 1's Actions logs print counts
  only, and test fixtures use made-up IDs and addresses.

### Headless access (verified 2026-11-24)

From an interactive shell on this PC, `claude -p` reached the Gmail connector and the read-only
Supabase tools (`gmail: ok`, `supabase: ok`) without an interactive login. Task Scheduler runs it as
the same user in a different context, so build 3's first step runs the full R23 probe from a
registered task before anything else is built. Wrappers redirect stdin from the null device.
Without it, `claude -p` waits 3 seconds for input and prints a warning.

### One-time owner setup

- Add `RESEND_API_KEY` to `C:\PitchRank\.env`, for the sender step. Agents cannot edit `.env`.
  `ALERT_EMAIL` keeps its existing default.
- Run the registration script once. It creates the clone and both tasks, and runs the probe.

## MVP Scope

Ships in order:
1. **Build 1:** no PC dependency, immediate value.
2. **Build 4:** the importer changes, link step and skill the triage queues work for.
3. **Build 3:** the clone, wrapper, probe, sender step, triage and "apply approved fixes".
4. **Build 2:** reuses the clone, wrapper and sender step from build 3.

Deferred:
- Sending any customer reply automatically.
- Approving fixes by replying to an email.
- A read-only database key, which would let unattended runs execute scripts and import dry runs.
- Having importers replay the approved dry-run files at execute instead of fetching again. R27
  reports anything that differs.
- Crash-recovery bookkeeping: receipts, write-ahead states, exactly-once drafts and automatic
  watch-list closing. Dropped by the owner on 2026-11-24 in favour of "Recovery by re-running".
- Moving the PC tasks to a cloud routine.
- Alerting by Telegram.
