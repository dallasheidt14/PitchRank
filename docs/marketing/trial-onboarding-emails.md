# Trial Onboarding — Email Copy

**Automation:** Trial Onboarding (Beehiiv)
**Trigger:** `Added by API` — webhook fires `enrollInAutomation` when Stripe `checkout.session.completed` arrives with `subscription.status = trialing`
**Per-step gate (on every Send Email node):** `Attribute` → `Custom Field` → `lifecycle` → `is` → `trialing`
**Length:** 7 emails over 7 days
**Goal:** Convert trial → paid subscriber before Stripe auto-charges on Day 8

## Voice + content rules

- Tone: expert peer, "the parent two years ahead." Direct, warm, data-backed.
- Never say "Glicko-2" → use **rating engine** or **13-layer algorithm**.
- Never say "cohort" → use **group**.
- No invented testimonials, no PowerScore tier thresholds, no college-outcome promises.
- Only reference real Premium features: **full rankings depth**, **Compare** (two teams + win probability), **Watchlist + rank-change alerts**, **AI Insights** (Season Truth, consistency, persona), **Edit access** (merge dupes, fill games).
- Mobile-first: short paragraphs, bullets, bold for the one phrase that matters per section.

## Beehiiv merge tags

Beehiiv syntax: `{{ field_name | fallback_value }}`. Case-sensitive. Single fallback only (no Liquid filter chains).

| Placeholder in this doc | Beehiiv tag to paste | Notes |
|---|---|---|
| `{{team_name | your team}}` | `{{team_name | your team}}` | Custom field written by our `/report-card` API. Empty for trial users who didn't come through report-card. |
| `{{state | }}` | `{{state | }}` | Same — report-card lead only. |
| `{{age_group | their age group}}` | `{{age_group | their age group}}` | Same. |

**Why no `first_name`:** we don't capture first names anywhere in the funnel today. Skip personal salutations — use plain `Hey —` or no greeting.

**Beehiiv setup tip:** Paste the body into Beehiiv's rich-text editor. `**bold**` renders as bold; `##` as H2; bullets render automatically. For merge tags, either paste the tag literally OR click Beehiiv's **Personalize** button (looks like `{}`) and pick the field — both work.

---

## Email 1 — Welcome + first step

**Send:** Immediately (Day 0)

**Subject:** You're in. Here's where to start.

**Preview:** Your 7-day trial just unlocked the full PitchRank — let's get one quick thing set up.

**Body:**

Hey —

You just unlocked the full version of PitchRank for **7 days**. No payment for the next 7 days, and you can cancel anytime before then.

Here's the one thing worth doing in the next 5 minutes: **find your team and add it to your Watchlist.**

That single step turns on everything Premium actually does for you:

- Weekly rank-change alerts when your team moves
- Head-to-head comparisons against any opponent in the country
- AI Insights — including Season Truth (what their record would look like with average luck), consistency profile, and team persona

**[Find your team →](https://pitchrank.io/rankings)**

If you already have a few teams in mind (your kid's team, the rival across town, the club you're considering for tryouts), add all of them. Comparisons get more interesting with more teams to compare.

I'll send a quick "3 things most parents miss" email tomorrow. Reply to this one if you hit anything weird — it goes to a real inbox.

— Dallas
Founder, PitchRank

---

## Email 2 — Activation: the 3 features people miss

**Send:** Day 1

**Subject:** 3 things most parents miss in their first week

**Preview:** The features that turn PitchRank from "ranking site" into "every-Sunday-night habit."

**Body:**

Most people sign up, check their team's rank, and close the tab.

That's like buying a Swiss Army knife to open one envelope. Here are the three features that actually earn the $6.99/mo:

### 1. Compare any two teams, side-by-side

Pick your team. Pick the team across town. PitchRank shows you both PowerScores, common opponents, strength-of-schedule difference, and head-to-head win probability.

It's the answer to *"should we move clubs?"* with actual numbers instead of parking-lot opinions.

**[Try Compare →](https://pitchrank.io/compare)**

### 2. Watchlist with rank-change alerts

Your kid's team, their two biggest rivals, the team you're scouting for next season's tryouts. Watchlist tracks them all and emails you when rankings shift week-over-week.

Most parents add 2 teams. The parents who actually use PitchRank week-over-week add more.

### 3. AI Insights — Season Truth, consistency, and persona

This is the one nobody finds on their own. Open any team profile and look for the Insights section:

- **Season Truth:** what the team's record *would* look like with average luck (i.e., did they earn their wins or get bailed out by a hot keeper?)
- **Consistency:** are they steady or streaky? Matters for tournament prep.
- **Persona:** the team's identity in one phrase ("defensive grinder," "high-press chaos," etc.)

It's the closest thing to a scouting report you'll get without paying a coach.

**[Open your team's profile →](https://pitchrank.io/rankings)**

That's it. Reply if you want me to point you at a feature I didn't cover.

— Dallas

---

## Email 3 — How to use it on game day

**Send:** Day 2

**Subject:** A 60-second game-day workflow

**Preview:** What to check before your kid steps on the field.

**Body:**

Here's the routine I run before every one of my kid's games. Whole thing takes a minute on my phone in the parking lot.

**1. Pull up the opponent's profile.**
Search their club name. Their PowerScore tells you the level of game to expect (higher = stronger team).

**2. Check common opponents.**
PitchRank shows teams both sides have played. If they crushed a team you barely beat, brace yourself. If they lost to a team you beat 4-0, you've got an edge.

**3. Look at recent form.**
Last 5 games. A team trending up is a different problem than a team that peaked in September.

**4. (Premium) Run a Compare.**
Pull up both teams in Compare. Head-to-head win probability comes from the full rating engine — not just "they're ranked higher."

That's it. Four data points. Way more signal than scrolling Instagram for their tournament photos.

**[Pull up your team →](https://pitchrank.io/rankings)**

Save the Compare page to your home screen if you do this enough. Faster than the app.

— Dallas

---

## Email 4 — Personalized rivals

**Send:** Day 3

**Subject:** Who actually beats {{team_name | your team}}?

**Preview:** A look at the teams in your group worth watching.

**Body:**

Quick one.

You signed up with **{{team_name | your team}}**. Here's what's interesting about their group:

- The full **{{age_group | their age group}}** rankings update every Monday from real game data — not tournament entries, not parent voting.
- Teams within the same PowerScore range are usually competitive. Big PowerScore gaps usually show up on the scoreboard.
- **Strength of schedule** matters more than raw record. A 12-3 team that played weak competition is rated lower than a 7-7 team that played up.

**[See where {{team_name | your team}} ranks today →](https://pitchrank.io/rankings)**

Two ideas while you're in there:

1. **Add their next opponents to your Watchlist** so you get alerted when those teams move
2. **Compare them to the rival you secretly want to beat** — Compare shows you exactly where the gap is (attack? defense? schedule strength?)

Halfway through your trial. The Compare feature alone is what most parents end up keeping us for.

— Dallas

---

## Email 5 — Day 5 check-in

**Send:** Day 5

**Subject:** 2 days left on your trial

**Preview:** Quick check-in. Anything you wish PitchRank did that it doesn't?

**Body:**

Hey —

You're 5 days in. Your trial ends in 2 days, and after that it's **$6.99/mo** (or $69.99/yr — ~17% off if you want to lock it in).

Before that decision lands on you, two things:

**1. If you haven't actually used the Premium features yet, this is the moment.**
Compare is the #1 thing parents end up paying for. If you've only checked your team's rank, you haven't really tried PitchRank. **[Compare your team vs. anyone →](https://pitchrank.io/compare)**

**2. If something's missing, tell me.**
Reply to this email. Real inbox, I read every one. The roadmap moves based on what parents actually ask for, and trial users are who I most want to hear from.

No pressure email tomorrow. Just wanted to check in before the trial wraps.

— Dallas

---

## Email 6 — Day 6 conversion push

**Send:** Day 6

**Subject:** Tomorrow your trial ends. Here's what changes.

**Preview:** What you keep, what you lose, and the annual option if it makes sense.

**Body:**

Heads up — your trial wraps **tomorrow**.

If you do nothing, your card on file gets charged **$6.99** and Premium continues. If you want to cancel, you can do it in one click before then (link below).

Quick side-by-side on what changes if you let it lapse:

| Feature | Free | Premium |
|---|---|---|
| Team rankings | ✓ | ✓ |
| State rankings (full depth) | Top 10 only | ✓ Full list |
| Compare two teams | — | ✓ |
| Watchlist + rank-change alerts | — | ✓ |
| AI Insights (Season Truth, consistency, persona) | — | ✓ |
| Edit access (merge dupes, fill missing games) | — | ✓ |

The free tier stays useful for a quick rank check. The reason people keep paying is the **Compare + Watchlist** combo — there's no other place to do that across ECNL, MLS NEXT, GA, NPL, and state leagues in one view.

**[Keep Premium →](https://pitchrank.io/upgrade)** *(or [switch to yearly](https://pitchrank.io/upgrade?plan=yearly) for $69.99 — ~17% off)*

**[Cancel before charge →](https://pitchrank.io/account)**

— Dallas

---

## Email 7 — Last call

**Send:** Day 7

**Subject:** Last call before your trial ends

**Preview:** A few hours left. Two paths from here.

**Body:**

Trial ends tonight.

Two paths from here:

**1. Do nothing → Premium continues.** Card gets charged $6.99/mo (or $69.99/yr if you swap to yearly). Cancel anytime in one click.

**2. Cancel now → goes back to Free.** Rankings stay; Compare, Watchlist, AI Insights, and Edit access turn off.

If you've used Compare even twice in the last week, the math is pretty obvious — it's less than the cost of one bad tournament concession-stand lunch per month.

**[Stay on Premium →](https://pitchrank.io/upgrade)**

**[Switch to yearly (save 17%) →](https://pitchrank.io/upgrade?plan=yearly)**

**[Cancel →](https://pitchrank.io/account)**

Either way — thanks for trying it. If you have feedback (kept it? canceled it? why?), hit reply. The product moves because of what parents like you tell me.

— Dallas
Founder, PitchRank
pitchrank.io

---

## Metrics to watch (after launch)

| Metric | Target | Beehiiv view |
|---|---|---|
| Open rate (each email) | >45% | Per-email stats |
| Click rate (Email 2, 3, 4 — activation emails) | >8% | Per-email stats |
| Click rate (Email 6, 7 — conversion emails) | >12% | Per-email stats |
| Trial → paid conversion | TBD baseline | Stripe + GA4 |
| Unsubscribe rate | <2% per email | Per-email stats |
| Replies | >5/100 sends | Inbox |

If Email 2 click rate is below 5%, the "3 features" framing isn't landing — A/B test against a version that names the team. If Email 6 click rate is below 8%, the comparison table isn't pulling weight — try a single bold CTA + short bullet list instead.
