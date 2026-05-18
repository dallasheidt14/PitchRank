# PitchRank Lifecycle Emails — Copy

Companion to `docs/marketing/trial-onboarding-emails.md`. Covers the **6 remaining automations** in the lifecycle funnel. (Report Card Lead Nurture and Trial Onboarding are done.)

**Architecture reference:** `docs/superpowers/specs/2026-05-17-lifecycle-automation-flow.md`

## Global voice + setup rules (read once)

- **Tone:** expert peer, "the parent two years ahead." Direct, warm, data-backed. No hype, no soft-sell, no testimonials (we have none real).
- **Never say "Glicko-2"** → use **rating engine** or **13-layer algorithm**.
- **Never say "cohort"** → use **group**.
- **No PowerScore tier thresholds**, no college-outcome promises.
- **Only reference real features:** full rankings depth, **Compare** (head-to-head + win probability), **Watchlist + rank-change alerts**, **AI Insights** (Season Truth, consistency, persona), **Edit access** (merge dupes, fill missing games).
- **Mobile-first:** short paragraphs, bullets, bold the one phrase that matters per section.
- **Merge tags — Beehiiv single-fallback syntax only:** `{{ team_name | your team }}`, `{{ state | your state }}`, `{{ age_group | your age group }}`. **No Liquid filter chains** (`| default:`, `| prepend:`, `| append:` don't work on our Beehiiv plan).
- **No first-name personalization.** `first_name` isn't captured in PitchRank's funnel. Use plain "Hey —" or jump straight in.
- **All links:** `https://pitchrank.io/...`
- **Pricing:** $6.99/mo or $69.99/yr (~17% off). Trial is 7 days.

**Beehiiv setup tip:** Paste body into Beehiiv's rich-text editor. `**bold**` → bold, `##` → H2, bullets → bullets. Use the link button for links.

---

# 1. Non-Premium Drip — 4 emails

**Lifecycle state:** `free_drip`
**Trigger:** Report Card Lead Nurture finishes (final step sets `lifecycle = free_drip`, then enrolls via API).
**Per-step gate (every Send Email node):** `Attribute` → `lifecycle` → `is` → `free_drip`
**Audience context:** Already saw their team's Report Card + 7 nurture emails. Didn't start a trial. They know what PitchRank is — the job here is to surface a *use case* they haven't tried yet, then offer a clean way to try Premium.

---

## 1.1 Email 1 — Day 7

**Subject:** The one PitchRank habit that sticks

**Preview:** Most parents use rankings wrong. Here's the move that actually pays off.

**Body:**

A week ago you ran a report card on **{{ team_name | your team }}**. Useful — but a one-time check isn't where PitchRank earns its keep.

The parents who get the most out of it do one specific thing:

**They pick 3–5 teams that matter to them and watch all of them at once.**

Their kid's team. The rival across town. The club they're considering for next year's tryouts. The team they barely beat in September.

When all of those move week-to-week, you stop reading rankings as "who's #1" and start reading them as **a map of your own corner of the soccer world**.

That's a Watchlist. It's a Premium feature, but you can preview it with a free account:

**[Browse rankings →](https://pitchrank.io/rankings)**

Tomorrow's Monday update will refresh every PowerScore in the country. If you're going to look anyway, look at the 5 teams that actually matter to your family.

— Dallas
Founder, PitchRank

---

## 1.2 Email 2 — Day 14

**Subject:** A use case for {{ team_name | your team }} you probably haven't tried

**Preview:** Tryout season runs Apr–Jun. The data you'd want is already in PitchRank.

**Body:**

Quick one.

Most parents check rankings to validate the team they're on. But the highest-leverage use is the opposite — **using rankings to evaluate teams you're considering**.

Tryouts run April through June for most clubs. If you're even *thinking* about a switch (different club, playing up, different league), here's the 3-step workflow:

1. **Open Compare.** Put **{{ team_name | your team }}** on the left. Put the team you're considering on the right.
2. **Look at common opponents.** Did they play the same teams? If yes — who got the better result?
3. **Look at strength of schedule.** A 12-3 record against weak competition tells you less than 7-7 against monsters.

That's the conversation you have with your spouse before you fill out another club's application. Numbers instead of forum opinions.

Compare is locked behind Premium, but you can poke around the rankings to get a feel for who's in the conversation:

**[See where {{ team_name | your team }} ranks today →](https://pitchrank.io/rankings)**

If the tryout decision is real this year, I'd start a free trial in May. That's when the data is most useful.

— Dallas

---

## 1.3 Email 3 — Day 28

**Subject:** Worth a week of your time?

**Preview:** 7-day trial. No upfront charge. Cancel in one click.

**Body:**

Been a month since your report card. Wanted to put the trial offer on the table cleanly:

**7 days of full Premium.** No charge until day 8. Cancel before then in one click — no email, no "are you sure" loop.

What unlocks during the trial:

- **Full rankings depth** (instead of top 10 per state)
- **Compare** any two teams — common opponents, schedule strength, head-to-head win probability
- **Watchlist** — up to 5 teams with rank-change alerts
- **AI Insights** — Season Truth, consistency score, team persona for any team
- **Edit access** — flag a wrong game result or a duplicate team

If you've been waiting for a reason to look harder at **{{ team_name | your team }}** or the teams around them, this is the cheapest possible way to do it. $0 for a week.

**[Start your free trial →](https://pitchrank.io/upgrade)**

If you'd rather just keep the free version and the weekly newsletter, that's a fine answer too. The free tier stays useful.

— Dallas

---

## 1.4 Email 4 — Day 49

**Subject:** Last note from me

**Preview:** Keeping this short.

**Body:**

I'll stop hassling you after this one.

You've seen the report card, you've seen the use cases, and you know the trial is risk-free. If now isn't the moment — totally fine. Lots of parents come back during tryout season or right after a tough loss.

Three doors from here:

1. **[Try Premium free for 7 days →](https://pitchrank.io/upgrade)** — best moment is before a tryout, a tournament, or a club decision.
2. **[Keep getting the weekly newsletter](https://pitchrank.io)** — free, no further nudges. Just the Monday rankings + commentary.
3. **[Unsubscribe entirely](#unsubscribe)** — link's in the footer. No hard feelings.

Either way: thanks for trying PitchRank in the first place. If you ever want to send feedback or a feature request, hit reply — real inbox.

— Dallas
Founder, PitchRank
pitchrank.io

---

# 2. Paid Drip — 2 emails

**Lifecycle state:** `paid`
**Trigger:** Webhook fires on first `invoice.paid` after trial→active (or past_due→active recovery).
**Per-step gate:** `Attribute` → `lifecycle` → `is` → `paid`
**Audience context:** Just converted from the 7-day trial. Got the full Trial Onboarding sequence. Card was charged $6.99 yesterday-ish. They liked it enough to stay. The job: get them to discover the under-used features (AI Insights especially), then ask for feedback before first renewal.

---

## 2.1 Email 1 — Day 7

**Subject:** The Premium feature you probably skipped

**Preview:** Most trial users never opened it. It's the best one.

**Body:**

You stuck with Premium — thank you.

Quick honest data point: most trial users spend their week in Rankings + Compare and never open the feature I'm most proud of. So I want to put it directly on your radar.

**AI Insights.** It lives on every team page, below the games.

Three things it tells you about any team:

- **Season Truth.** A plain-English read of whether the record matches the underlying play. Some 10-4 teams are actually struggling. Some 6-8 teams are quietly good.
- **Consistency.** Are they steady, or are they the team that beats #5 one weekend and loses to #45 the next?
- **Persona.** A read on the team's identity — high-scoring + leaky, defensive grinder, big-game team, etc.

Easiest way to see it work: pull up the team you watch most.

**[Open AI Insights →](https://pitchrank.io/rankings)**

Try it on a team you *know* well first — it's a faster way to calibrate whether the read matches reality. Then run it on a team you're scouting.

— Dallas

---

## 2.2 Email 2 — Day 21

**Subject:** 3 weeks in — what's missing?

**Preview:** Real question. Hit reply.

**Body:**

You're about a week out from your first monthly renewal. Before that hits, I want to ask one question:

**What's missing from PitchRank that would make it noticeably more useful to you?**

A view we don't have. A stat that's hidden too many clicks deep. A league we cover badly. A use case you came in expecting and didn't find.

Hit reply — goes to a real inbox, I read every one. The roadmap moves based on what paying parents ask for, and 3-week-in feedback is the most useful kind.

A few that came in last quarter and are already shipping or shipped:

- Edit access for parents to flag duplicate teams (live)
- Win probability in Compare (live)
- Faster mobile load times (live)
- Email alerts on Watchlist movement (live)

If you've got nothing to flag and PitchRank's working for you — that's a useful data point too. Just say "all good."

— Dallas
Founder, PitchRank

---

# 3. Dunning / Update Card — 3 emails

**Lifecycle state:** `past_due`
**Trigger:** Webhook fires on `invoice.payment_failed`.
**Per-step gate:** `Attribute` → `lifecycle` → `is` → `past_due`
**Exit condition:** When invoice succeeds on retry, webhook flips `lifecycle = paid` and per-step gate auto-skips remaining emails.
**Audience context:** Card on file failed. Could be expired card, fraud-block, insufficient funds, or moved bank. They're an existing paying customer — no marketing, just the action.

**Payment link merge tag:** All three Dunning emails use `{{ last_failed_invoice_url | https://billing.stripe.com/p/login/fZu7sM2PO4AfgSQcKjgUM00 }}`. The webhook writes Stripe's per-invoice "pay this invoice" URL to this custom field on enrollment — one-click, no portal navigation. Fallback is the static Stripe Customer Portal login link.

**Before activating:**
1. Create `last_failed_invoice_url` custom field in Beehiiv (Settings → Custom Fields → Add → text type). Empty custom fields are hidden from dropdowns; the webhook will populate it from the first dunning event, but the field must exist first.
2. Grab the static Stripe Customer Portal login URL: Stripe Dashboard → Settings → Billing → Customer portal → enable "Login link" → copy URL (format `https://billing.stripe.com/p/login/<key>`).
3. Replace every `fZu7sM2PO4AfgSQcKjgUM00` in the three Dunning emails with that URL.

---

## 3.1 Email 1 — Day 0 (immediate)

**Subject:** Your card on file just declined

**Preview:** Fix it in one click. Your subscription stays active.

**Body:**

Heads up — your card on file just declined when we tried to renew your PitchRank Premium subscription.

Could be anything: expired card, new card number, bank fraud flag, low balance. We'll automatically retry over the next few days, but the fastest fix is updating it yourself:

**[Update payment method →]({{ last_failed_invoice_url | https://billing.stripe.com/p/login/fZu7sM2PO4AfgSQcKjgUM00 }})**

Takes about 60 seconds. Premium stays on the whole time.

If you've decided to cancel, that's a fine outcome too — just let it lapse and Stripe will close the subscription on its own. No action needed from you.

— Dallas
Founder, PitchRank

---

## 3.2 Email 2 — Day 5

**Subject:** Still showing a payment issue

**Preview:** A few more retry attempts before the subscription closes.

**Body:**

Your card hasn't gone through yet. Stripe is still retrying — you've got roughly **two more weeks** before the subscription closes automatically.

If this is just a card-on-file issue:

**[Update payment method →]({{ last_failed_invoice_url | https://billing.stripe.com/p/login/fZu7sM2PO4AfgSQcKjgUM00 }})**

If you've moved to a new card or bank since signing up, that's almost always the cause.

If you're not sure you want to keep PitchRank, totally fine — let it lapse. You'll keep free-tier access (basic rankings, weekly newsletter). The only things that turn off are Compare, Watchlist, AI Insights, and full rankings depth.

— Dallas

---

## 3.3 Email 3 — Day 14

**Subject:** Last automatic retry

**Preview:** A few days until your subscription closes.

**Body:**

Quick note: Stripe is on its **final retry window** for your Premium subscription. After this, the subscription closes and you'll drop back to the free tier.

If you want to keep Premium, here's the one-click fix:

**[Update payment method →]({{ last_failed_invoice_url | https://billing.stripe.com/p/login/fZu7sM2PO4AfgSQcKjgUM00 }})**

If you'd rather end Premium and stay on the free tier — that's the default outcome if you do nothing. No need to email me, no cancel button to find. Stripe just stops retrying.

Either way: thanks for the time you've been on Premium. If there's a reason you've let it lapse on purpose (price, missing feature, switched platforms), I'd genuinely like to know — hit reply.

— Dallas
Founder, PitchRank

---

# 4. Cancellation Save — 2 emails

**Lifecycle state:** `canceling`
**Trigger:** Webhook fires on `customer.subscription.updated` with `cancel_at_period_end = true`.
**Per-step gate:** `Attribute` → `lifecycle` → `is` → `canceling`
**Exit condition:** If they reactivate (toggle off), webhook flips `lifecycle = paid` and per-step gate auto-skips remaining emails.
**Audience context:** They clicked cancel — Premium is set to end at period end. They still have full access until then. The job: soft check-in, surface what turns off, offer reactivation in one click. Do not beg.

**Reactivation link:** Both Cancellation Save emails link to the static Stripe Customer Portal login URL (same one used as the Dunning fallback). Replace every `fZu7sM2PO4AfgSQcKjgUM00` with your `https://billing.stripe.com/p/login/<key>` URL before activating.

---

## 4.1 Email 1 — Day 0 (immediate)

**Subject:** Got your cancel — quick note

**Preview:** Premium runs until period end. Reactivate anytime.

**Body:**

Heard you canceled. No hard feelings — Premium stays on until the end of your current billing period, so use it while you've got it.

Two things worth knowing before then:

**1. What turns off when the period ends:**
- Full rankings depth (drops to top 10 per state)
- Compare (head-to-head win probability)
- Watchlist + rank-change alerts
- AI Insights
- Edit access

**2. Reactivation is one click.** No re-entering card info, no friction. If you change your mind any time before the period ends:

**[Reactivate Premium →](https://billing.stripe.com/p/login/fZu7sM2PO4AfgSQcKjgUM00)**

And if there's a specific reason you canceled (price, missing feature, switched to something else, just don't use it enough), I'd genuinely like to hear it. **Hit reply.** Real inbox, every reply lands with me.

The roadmap moves because of what people tell us when they leave.

— Dallas
Founder, PitchRank

---

## 4.2 Email 2 — Day 5

**Subject:** Premium ends soon — last chance to flip the switch

**Preview:** No pressure. Just making sure you saw the reactivation link.

**Body:**

Premium wraps in a few days for you. After that you're on the free tier — still useful for a quick rank check, but Compare, Watchlist, and AI Insights all go dark.

If you canceled because **PitchRank wasn't worth $6.99/mo** to you — fair. Use the free tier and the newsletter; that's what they're there for.

If you canceled because **you weren't using it enough** — that's the most common reason, and the fix is one feature, not the whole product. Pick one team you actually care about, add it to Watchlist, and you'll get a Monday email when its rank moves. That single thing keeps most parents engaged.

**[Reactivate Premium →](https://billing.stripe.com/p/login/fZu7sM2PO4AfgSQcKjgUM00)**

**[Or just let it end](https://pitchrank.io)** — no further emails like this. You'll get the regular weekly newsletter on the free tier.

— Dallas

---

# 5. Trial Cancel Drip — 2 emails

**Lifecycle state:** `trial_canceled`
**Trigger:** Webhook fires on `customer.subscription.deleted` while prior status was `trialing`.
**Per-step gate:** `Attribute` → `lifecycle` → `is` → `trial_canceled`
**Audience context:** Bailed during the 7-day trial — never got billed. Maybe didn't see value, maybe got distracted, maybe wrong moment. The job: one honest "what stopped you?" email, then a soft "come back when you're ready" — no hard sell.

---

## 5.1 Email 1 — Day 1

**Subject:** You canceled the trial — quick honest question

**Preview:** No pitch. One question.

**Body:**

You canceled your trial yesterday. No charge, no hard feelings.

Before I let you go: **what stopped you?**

Not asking to talk you out of it. Asking because trial-cancelers tell us what's broken faster than anyone else does, and I read every reply.

Useful answers are usually one of:

- "Couldn't figure out how to do X."
- "You don't cover [my league / my state / my age group] well."
- "Too expensive for what it does."
- "I signed up at the wrong moment in the season."
- "Couldn't find my team."
- "Tried it once, forgot it existed."

No reply is fine too. But if you've got 30 seconds — hit reply with even one sentence.

— Dallas
Founder, PitchRank

---

## 5.2 Email 2 — Day 7

**Subject:** Come back when the timing's right

**Preview:** Best moments to retry PitchRank.

**Body:**

A week ago you tried PitchRank and decided it wasn't the right time. Totally fair — timing is a real thing in youth soccer.

If you ever want to retry, these are the three moments most parents say it actually clicks:

- **Before tryouts (Apr–Jun)** — when you're deciding between clubs or leagues
- **Before a big tournament** — when you want to scout the bracket
- **After a confusing result** — when "wait, who is this team?" finally pushes you to look

The trial doesn't expire. Same 7 days, same risk-free terms, whenever you want.

**[Restart your trial →](https://pitchrank.io/upgrade)**

In the meantime, the **weekly newsletter** stays free and is genuinely useful on its own.

— Dallas
Founder, PitchRank

---

# 6. Paid Win-Back — 3 emails

**Lifecycle state:** `paid_canceled`
**Trigger:** Webhook fires on `customer.subscription.deleted` while prior status was `active`/`past_due`, OR on `charge.refunded`.
**Per-step gate:** `Attribute` → `lifecycle` → `is` → `paid_canceled`
**Audience context:** They paid for a while, then left (or refunded). They *know* the product. Don't reintroduce it — acknowledge they left, ask why, surface what's changed, then offer a clean way back. Reserve the discount for Email 3 only.

---

## 6.1 Email 1 — Day 3

**Subject:** Sorry to see you go — one question

**Preview:** What would've kept you?

**Body:**

You canceled Premium a few days ago after being on the paid plan for a while. Wanted to ask one thing, honestly:

**What would've kept you?**

Most "why did you cancel?" surveys are pointless — multiple choice, the right answer isn't there. So I'm just going to ask in plain English.

Common ones I've heard from past cancelers:

- "Stopped using it after [the season ended / my kid switched sports / we picked a club]"
- "The data on [my league / my age group] wasn't great"
- "$6.99/mo adds up — too many subscriptions"
- "I wanted [feature] and it wasn't there"
- "It was great, just didn't need it anymore"

Hit reply with whichever it was (or something I didn't list). I read every one — leavers' feedback shapes the roadmap more than current users'.

— Dallas
Founder, PitchRank

---

## 6.2 Email 2 — Day 14

**Subject:** What's changed at PitchRank since you left

**Preview:** Short list. No pitch yet.

**Body:**

Two weeks since you canceled. Couple of things have moved since then that might be relevant:

- **AI Insights** got a refresh — Season Truth, consistency, and persona are now on every team page
- **Watchlist alerts** are now weekly emails, not in-app only
- **Edit access** lets you flag wrong game results or duplicate teams directly
- **Compare** added head-to-head win probability based on the full rating engine

Not asking you to come back yet. Just making sure you know what you'd actually get if you did.

If you want to take a fresh look:

**[See what's live →](https://pitchrank.io)**

— Dallas

---

## 6.3 Email 3 — Day 30

**Subject:** A way back if you want it

**Preview:** Yearly is now ~17% off — and you can re-trial first.

**Body:**

Last email from the win-back sequence.

If you want to give PitchRank another look, two paths:

**1. Free 7-day trial** — same terms as before. No charge until day 8, cancel in one click.
**[Restart your trial →](https://pitchrank.io/upgrade)**

**2. Switch to yearly and lock in the lower rate.** $69.99/yr is **~17% off** versus monthly. If you canceled mostly because of recurring monthly billing fatigue, yearly is the cleaner answer.
**[Switch to yearly →](https://pitchrank.io/upgrade?plan=yearly)**

That's it. After this email I'll stop nudging — you'll only hear from me through the regular newsletter (free) unless you re-trial.

Thanks for the time you spent on Premium. The product is better because of it.

— Dallas
Founder, PitchRank
pitchrank.io

---

# Metrics to watch after launch

Same dashboard as Trial Onboarding. Per-automation targets:

| Automation | Key metric | Target |
|---|---|---|
| Non-Premium Drip | Trial start rate (any email click → /upgrade) | >3% |
| Paid Drip | Email 2 reply rate | >5/100 |
| Dunning | Card-update rate by Day 14 | >40% |
| Cancellation Save | Reactivation rate by period end | >5% |
| Trial Cancel Drip | Email 1 reply rate | >8/100 |
| Paid Win-Back | Email 3 → trial restart | >2% |

Unsubscribe ceiling: **<2% per email** across every automation. Above that → revisit cadence, not copy.

# Activation order

Per spec §9: automations are in Draft. Activate each one **only after** its copy is reviewed and pasted in. Order suggestion (lowest-risk first):

1. **Dunning** — pure transactional, hardest to get wrong
2. **Cancellation Save** — small audience, immediate revenue impact
3. **Paid Drip** — small audience (only post-trial converters), low risk
4. **Trial Cancel Drip** — soft, hit-reply
5. **Paid Win-Back** — has a discount lever in Email 3; activate after the three above are clean
6. **Non-Premium Drip** — largest audience downstream of report-card form; activate last after others are calibrated
