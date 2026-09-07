# Staying top-of-mind with soccer parents — Google Ads plan

Verified against the live account on 2026-09-01.

**The goal:** when a youth soccer parent wonders where their kid's team ranks, PitchRank
is the name that comes to mind. Not "get a signup this week."

That is a brand-recall objective, and it is played differently from direct response.
Direct response asks *did this ad produce a signup today.* Recall asks *in three months,
does this parent type pitchrank.io without being asked.* The tactics below optimise for
the second question.

## Where things stand

Account id and login live in the operator's password manager, deliberately not here — this
repo is public and `.turbo/plans/` ships with it (CLAUDE.md § Improvement Backlog). Expert mode.

- Remarketing tag `AW-584157926` live site-wide since ~2026-06-20
  (`frontend/components/GoogleAds.tsx`, wired at `frontend/app/layout.tsx:152`).
- Google Analytics is linked (Data manager → Connected products: "1 linked").
- Conversion tracking created 2026-09-01: `subscription_completed` (primary) and
  `checkout_initiated` (secondary), imported from GA4.
- Zero campaigns, $0 ever spent.

Audience sizes today — Google needs 100 for Display, 1,000 for YouTube:

| Segment | YouTube | Display |
|---|---|---|
| All Users of Pitchrank | 3,700 | 2,700 |
| Heavy Rankings Users | 720 | 560 |
| 14 Day Returning Users | 260 | 160 |
| 7 Day Returning Users | 130 | too small |
| Compare/Prediction, Watchlist Engaged, Purchasers | 0 | 0 |

## The one strategic fact that shapes everything

**The list is small, so the constraint is people, not money.**

2,700 reachable people on Display. At $10/day — roughly $300/month at typical display
CPMs — that is on the order of 20–50 impressions per person per month. That is not
top-of-mind, that is harassment, and it actively damages the brand you are trying to
build.

Two consequences:

1. **Cap frequency and accept underspend.** Budget will not fully deliver. That is the
   campaign working correctly, not a fault to fix.
2. **The real lever on category ownership is list growth, not ad spend.** Retargeting
   only ever reaches people who already visited. It is the retention half. The awareness
   half is SEO and content, which is already the main investment. Retargeting makes sure
   the people who do arrive don't forget you — it cannot, on its own, make you famous.

## The core idea: sell the Monday refresh, not the product

Rankings recalculate every Monday (`calculate-rankings.yml`, Mon 12:30 UTC). That weekly
cadence is the single most valuable asset for a recall campaign, and it is currently
unused in marketing.

A banner that says "PitchRank — youth soccer rankings" is wallpaper. A banner that says
**"New rankings are live"** is news, and news gets clicked, and the click builds the
habit. Repeat it every week and the association forms on its own: *rankings update
Monday → PitchRank.*

That is the whole strategy in one line. Everything below serves it.

## The plan

### 1. Always-on Display, low and steady

Recall is built by duration, not intensity. $8–10/day running continuously beats
$50/day for two weeks, every time.

- **Type:** Display, standard (not the "Smart" preset — it hides the controls below)
- **Budget:** $10/day, running continuously
- **Bidding:** Maximize clicks with a max CPC cap around $0.60. Not Maximize
  conversions — there is not enough conversion volume yet to feed it.
- **Frequency cap:** 10 impressions per user per week. This is the most important
  setting on the page.
- **Location:** United States
- **Ad groups:**
  1. *Recent* → `14 Day Returning Users` + `Heavy Rankings Users` — these people are
     active; show them the Monday refresh message
  2. *Lapsed* → `All Users of Pitchrank` — a re-introduction rather than an update
- **Exclusion:** add `Purchasers of Pitchrank` once it works, so you stop paying to
  advertise at people already subscribing.

### 2. Rotate the creative weekly

Responsive Display Ads, refreshed each Monday. Keep the frame constant so it becomes
recognisable, change the number so it stays news.

Headlines (30 char max):
- New rankings are live
- Where does your team rank?
- Updated this Monday
- U9–U19 rankings, every week
- See your team's true rank

Long headline (90 max):
- Every youth soccer team in the country, re-ranked from real results every Monday

Descriptions (90 max):
- PitchRank rates U9–U19 boys and girls teams nationally and by state. Updated weekly.
- New results, new rankings, every Monday. See where your team stands right now.

Business name: PitchRank.
Images: 1200×628 landscape, 1200×1200 square, logos at 1200×1200 and 1200×300.
`frontend/public/logos/` and the OG image route are the starting point.

**Landing page: `/rankings`, or deeper into the parent's own state board.** These people
have already seen the pitch — send them to the thing itself, not the homepage.

### 3. Add a 6-second YouTube bumper (this is where recall is actually won)

Video sticks in a way banners do not, and 3,700 clears the 1,000-user YouTube minimum.
Bumpers are unskippable, sold cheaply on a CPM basis, and are designed by Google
specifically for frequency and recall — which is exactly this objective.

A bumper does not need production budget. Six seconds of the rankings table animating,
the logo, and one line of voice or text is enough. It only has to be recognisable.

Start it after Display has been running a month, so the two are not confounded.

### 4. Measure recall, not clicks

Clicks and cost-per-signup are the wrong scoreboard for this objective and will make a
working campaign look like a failure.

Watch instead, monthly:

- **Branded search volume in Search Console** — impressions and clicks for queries
  containing "pitchrank". This is the truest measure of top-of-mind there is, and it is
  already wired up in the internal analytics dashboard.
- **Direct traffic** in GA4 — people typing the URL or using a bookmark.
- **Returning visitor share** — the habit forming.
- Signups as a secondary read, not the verdict.

If branded searches climb over a quarter, it is working, regardless of what the click
metrics say.

### 5. Review points

- **Week 2:** confirm frequency is capping and spend is sane. Do not judge results yet.
- **Month 1:** creative rotation working? Any ad fatigue (CTR falling week over week)?
- **Month 3:** branded search trend. This is the real verdict. Rising → raise budget or
  add the bumper. Flat → the problem is list size, and the answer is traffic, not spend.

## Known gaps worth fixing (not blocking)

- **No signup event exists.** All 22 events in `frontend/lib/events.ts` are engagement
  and checkout events; none fires on account creation. Signups live only in
  `user_profiles.created_at`, so Google and GA4 have never seen one. A one-line
  `gtagEvent('sign_up', …)` at account creation would close it.
- **Three audiences are permanently empty** — `Watchlist Engaged`,
  `Compare/Prediction Users`, `Purchasers of Pitchrank` all read 0 and always will;
  their "Website visitors" URL rules never match. Rebuild them as GA4 audiences from the
  real events (`watchlist_added`, `compare_opened`, `subscription_completed`) and import.
  `Watchlist Engaged` is the loss that stings — someone who saved a team is the best
  retargeting audience on the site.

## The $500 that was passed on

Promotion `4YJ6D-MKMW3-FRE9` — spend $500 by **2026-09-11** to earn $500 credit,
redeemed 2026-07-13. Declined 2026-09-01 in favour of starting small; at $10/day the
threshold will not be met. Recorded so it reads as a deliberate choice later. It was
never free money — $500 of real spend to unlock $500 of credit, spent faster than a
first campaign could teach anything.
