# Beehiiv Nurture Sequence — Ready to Paste

This is the 7-email Report Card Lead Nurture sequence rewritten in Beehiiv-ready form. Each block has the **subject line**, **preheader**, **delay from enrollment** (or from prior email), and the **body markdown** you can paste straight into Beehiiv's Compose editor (markdown paste works in Beehiiv).

---

## How to use this file

1. In your Beehiiv automation `Report Card Lead Nurture` (`aut_db968c3b-7f99-410c-82cd-caf0d7763e50`), the trigger is **Add by API** — already configured.
2. For each email below: add a **Send Email** step → paste the subject, preheader, and body. Then add a **Wait** step before the next email with the delay listed.
3. **Merge tag for the team name:** I've used `{{team_name}}` as a placeholder. In Beehiiv's Compose editor, click the **merge tag picker** (usually a `{ }` icon) and pick `team_name` (the custom field you created). It'll insert Beehiiv's actual syntax — typically `{{ subscriber.custom_fields.team_name }}` — replace my `{{team_name}}` with that.
4. **State, age_group, gender custom fields** work the same way: `{{state}}`, `{{age_group}}`, `{{gender}}` placeholders → swap to Beehiiv's merge-tag syntax.
5. **Sender:** use Dallas's name + email so replies come back to a real human.

---

## ⚠️ One decision before you build

The PDF delivery email is already sent by **Resend** at the moment of form submission (Day 0, with the PDF attached). The Beehiiv automation enrolls the subscriber at the *same* moment.

**Recommendation:** skip Email 1 in the Beehiiv automation, OR delay it by 4–6 hours so it doesn't double-deliver alongside the Resend email. I've written Email 1 below assuming **a 4-hour delay** — it acknowledges the PDF was already sent and pivots to "here's how to read it." If you'd rather skip Email 1 entirely, start the Beehiiv automation at Email 2 (Day 2).

---

## Email 1 — Delivery follow-up (4 hours after enrollment)

**Subject:** A few minutes with your team's report card

**Preheader:** What to actually look at first

**Delay from enrollment:** 4 hours

**Body:**

```
Hey,

Your report card for **{{team_name}}** should be in your inbox by now. (If it's not, check spam — it's a PDF attachment from Resend.)

When you open it, look at these three things in order:

1. **PowerScore** — your team's overall rating, 0.000–1.000. Higher is better.
2. **National Rank + 30-day delta** — where you stand among the 126,000+ ranked teams, and which direction you're moving.
3. **Last 5** — the colored circles. Green = win, red = loss, gray = draw. The shape of recent form.

That's it for today. Over the next two weeks I'll send a few short emails on what else PitchRank can tell you about your team — and how parents use it to decide on clubs, tryouts, and league moves.

**Quick question:** what's the one thing you most want to know about {{team_name}}'s ranking? Hit reply — I read every one.

— Dallas, PitchRank

P.S. Rankings update every Monday. Your team's live numbers are always at https://www.pitchrank.io/rankings
```

---

## Email 2 — Why this exists (Day 2 from enrollment)

**Subject:** Why I built PitchRank

**Preheader:** A soccer parent who got tired of bad data

**Delay from previous:** 2 days (so this lands ~Day 2 from enrollment)

**Body:**

```
I'll keep this short.

I'm a soccer parent. Same as you. Practices on Tuesday and Thursday, games on Saturday, tournaments every other weekend.

A few years ago I wanted a simple answer: **is my kid on the right team?**

I checked GotSoccer. The rankings didn't make sense — teams that entered more tournaments ranked higher, regardless of how they actually played. A team that beat the #8 team twice didn't move.

I checked YSR. Better. Then it shut down.

So I built PitchRank.

One rating engine. Every league. Real game data — over 1.1 million games. Updated every Monday. No user-edited data, no tournament bonus points, no way to game it.

The question it answers is still simple:

**Where does your team really stand?**

That's it. That's why this exists.

— Dallas, PitchRank

P.S. If you haven't pulled up your team's live ranking yet → https://www.pitchrank.io/rankings
```

---

## Email 3 — How to read PowerScore (Day 4 from enrollment)

**Subject:** What your PowerScore actually means

**Preheader:** It's not just a rank — here's what it measures

**Delay from previous:** 2 days

**Body:**

```
Your report card has a number on it called **PowerScore**.

Here's what it actually measures — and why it matters more than rank alone.

**PowerScore is a composite of:**

- **Win quality** — beating a top-50 team counts more than beating a bottom-500 team.
- **Strength of schedule** — playing strong opponents raises your floor.
- **Recency** — last month's games matter more than September's.
- **Margin context** — a 3-0 win tells a different story than a 1-0 grind.

A team ranked #50 with a PowerScore of 0.72 playing ECNL is in a very different situation than a team ranked #50 with a 0.72 in a state league.

**The quick way to use it:**

- **PowerScore up + rank up** = your team is genuinely improving.
- **PowerScore up + rank flat** = everyone around you is also improving (tough group).
- **PowerScore flat + rank dropping** = new teams entering above you.

That kind of read takes 30 seconds on PitchRank and would take hours doing it manually.

Pull up your team's latest PowerScore → https://www.pitchrank.io/rankings

— PitchRank
```

---

## Email 4 — Cross-league comparison (Day 6 from enrollment)

**Subject:** ECNL or MLS NEXT? Here's what the data says

**Preheader:** Finally, a data-backed way to compare

**Delay from previous:** 2 days

**Body:**

```
The most common question I hear from parents:

**"Is ECNL better than MLS NEXT for my kid's age group?"**

Before PitchRank, nobody could answer this with data. You'd get opinions on forums, sideline whispers, and coaches with obvious conflicts of interest.

Now there's an answer.

PitchRank's rating engine is calibrated *across* leagues — same algorithm, same data window, same opponent-strength adjustments. That means an ECNL team at U14 with a PowerScore of 0.78 is directly comparable to an MLS NEXT team at U14 with a PowerScore of 0.78. Same scale. Same meaning.

You can answer questions like:

- Would my daughter's GA team compete in ECNL?
- Is our state-league team actually stronger than some ECNL teams in our group?
- Are we paying ECNL prices for state-league-level competition?

These are $10,000+ decisions. You deserve data, not opinions.

The free tier shows you rankings and PowerScore. **PitchRank+ ($6.99/mo)** unlocks the full Compare + Predict tools — head-to-head matchup analysis with predictions that are scary accurate.

Try it free for 7 days → https://www.pitchrank.io/upgrade

— PitchRank
```

---

## Email 5 — What the report card doesn't show (Day 8 from enrollment)

**Subject:** What your report card doesn't show you

**Preheader:** There's a full picture behind that PowerScore

**Delay from previous:** 2 days

**Body:**

```
Your report card showed you the highlights:

- {{team_name}}'s PowerScore
- National and state rank
- 30-day rank change
- Win-loss-draw + last 5

That's useful. But it's the summary, not the full picture.

**Here's what PitchRank+ unlocks:**

**Game History** — every game this season, with over- and underperformance highlights. See exactly which results boosted your rank and which dragged it down.

**Ranking History + Momentum** — your rank over time, recent momentum, and a goal-differential trajectory chart that shows the shape of your season.

**Team Insights** — Clutch Factor, Season Truth, persona analysis. The patterns inside your results that the raw W-L-D doesn't show.

**Compare + Predict** — head-to-head comparisons and matchup predictions that are scary accurate. Watchlist any team and get alerts when their rank moves.

You already spend $5,000–$15,000 a year on club soccer.

PitchRank+ is $6.99/mo. That's less than 0.1% of what you spend on club fees — for the tool that tells you if it's working.

Start your 7-day free trial → https://www.pitchrank.io/upgrade

— PitchRank
```

---

## Email 6 — Use cases (Day 10 from enrollment)

**Subject:** Three ways parents use PitchRank+

**Preheader:** Real decisions. Real data.

**Delay from previous:** 2 days

**Body:**

```
Three different parents. Three different decisions. Same tool.

**The Club Switcher**

Daughter on an ECNL team ranked #180. Used Compare + Predict to find a GA team ranked #45 in the same age group — at half the cost. Same level of competition, $6,000 less per year. Switched at tryouts.

**The Tryout Prepper**

Son's team disbanding. Pulled up every U14 team within 50 miles in PitchRank, compared PowerScores and game histories, walked into tryouts knowing exactly which clubs were worth the drive.

**The Validator**

Just needed to know her kid was on the right team. PitchRank+ showed her the team had climbed 30 spots in 90 days on the Ranking History chart. Screenshotted it, sent it to the parent group chat. Done.

Different needs. Same answer: **data you can trust.**

The report card gave you a snapshot. PitchRank+ gives you the full toolkit.

- Game history with performance highlights
- Ranking history + momentum
- Team Insights (Clutch Factor, Season Truth)
- Compare + Predict + watchlist alerts

**$6.99/mo. 7-day free trial. Cancel anytime.**

Try it free → https://www.pitchrank.io/upgrade

— PitchRank
```

---

## Email 7 — Direct pitch (Day 14 from enrollment)

**Subject:** Don't make a $10K club decision on a hunch

**Preheader:** See everything behind your team's ranking

**Delay from previous:** 4 days

**Body:**

```
Quick recap of what you've seen so far:

- Your team's report card (PowerScore, rank, last 5)
- How PowerScore actually works
- How to compare across leagues
- What PitchRank+ unlocks

Here's the honest case for upgrading:

**If you check rankings once a week** — PitchRank+ pays for itself in time saved. Watchlist alerts come to you. Comparisons are one click. No more refreshing GotSoccer.

**If tryout season is coming** — the Compare + Predict tool is worth 10x the subscription. See which clubs actually perform at your kid's age group before you commit $10,000+.

**If you just want to know where {{team_name}} stands** — you already have that for free. No pressure. The free report card works.

PitchRank+ is for the parent who wants the full picture before making the next club decision.

**$6.99/mo. $69.99/yr (saves $14). 7-day free trial.**

Start your free trial → https://www.pitchrank.io/upgrade

If PitchRank+ isn't for you, no worries. You'll keep getting weekly rankings updates every Monday. Your report card is always available.

Either way — thanks for being here. Rankings update Monday.

— Dallas, PitchRank
```

---

## After all 7 are pasted

1. **Save** the automation
2. **Activate** it (make sure it's not in Draft)
3. Send a real test enrollment (submit `/report-card` form with a fresh email) and verify the journey appears in Beehiiv
4. Wait a few hours, then check that Email 1 fires on schedule

Future tweaks worth considering:
- **A/B test subjects** — Beehiiv supports this on most plans. Especially for Email 1 (the one that decides whether they open anything else).
- **Sender warmup** — if this list grows fast, monitor your domain reputation. Consider sending Email 1 from a transactional sub-domain.
- **Reply tracking** — Email 1's "hit reply, I read every one" only works if replies actually reach a real inbox. Set the reply-to to a monitored address.
