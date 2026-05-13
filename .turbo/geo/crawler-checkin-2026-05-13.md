# AI Crawler Check-In — 2026-05-13

14 days post-merge of PR #697 (commit e6b89aab8, 2026-04-29).

---

## robots.txt status

**PASS — confirmed via git + Vercel deployment history**

All 13 target AI crawlers have `Allow: /` in `frontend/public/robots.txt`. Auth-gated
routes (`/teams/`, `/watchlist`, `/compare`, `/login`, `/signup`, `/upgrade`,
`/auth/`, `/mission-control`, `/api/`, `/test`) are consistently blocked for all UAs.
Bytespider retains `Disallow: /`.

Full UA coverage verified:

| User-Agent | Allow: / | Disallow: auth routes |
|---|---|---|
| GPTBot | ✅ | ✅ |
| ChatGPT-User | ✅ | ✅ |
| OAI-SearchBot | ✅ | ✅ |
| ClaudeBot | ✅ | ✅ |
| anthropic-ai | ✅ | ✅ |
| Claude-User | ✅ | ✅ |
| Claude-SearchBot | ✅ | ✅ |
| PerplexityBot | ✅ | ✅ |
| Perplexity-User | ✅ | ✅ |
| Google-Extended | ✅ | ✅ |
| Applebot-Extended | ✅ | ✅ |
| cohere-ai | ✅ | ✅ |
| meta-externalagent | ✅ | ✅ |

**Deployment verification:** The file was introduced in commit `e6b89aab8` (merged to main
2026-04-29). Every subsequent production deploy has been from main. Most recent production
deploy: `dpl_6347p7RW5zuVnaVwkFJUzHQtFTbH` (commit `b12ca9cb`, 2026-05-13). The
robots.txt changes have been live since day zero of merge.

**Note on live curl:** `curl https://www.pitchrank.io/robots.txt` was blocked by the agent
sandbox (external network not in allowlist). Confirmation rests on git + Vercel deployment
chain above. Dallas should run the curl locally to complete the record — see Manual checks
below.

---

## Crawler activity (14 days post-merge)

**UNABLE TO CONFIRM per-bot via automated tools in this environment.**

| UA | Hits | First seen | Last seen | Paths sampled |
|----|------|------------|-----------|---------------|
| (all) | — | — | — | — |

**Why no data:** Vercel's `get_runtime_logs` MCP tool returns HTTP request records but
**does not include the User-Agent header**. Static files (robots.txt, sitemap.xml) served
from `frontend/public/` never generate runtime log entries at all — they are served
directly by Vercel's CDN edge without invoking any serverless function. There is no way to
filter runtime logs by UA string.

**Indirect signal — possible systematic crawl detected:**

Runtime logs for 2026-05-13 show a burst of 20+ Ohio rankings pages hit in ≤2 seconds
(16:57:53–16:57:54 UTC):

```
16:57:53  GET /rankings/oh/u10/male      200
16:57:53  GET /rankings/oh/u10/female    200
16:57:53  GET /rankings/oh/u11/male      200
16:57:53  GET /rankings/oh/u11/female    200
16:57:53  GET /rankings/oh/u12/male      200
16:57:53  GET /rankings/oh/u12/female    200
16:57:53  GET /rankings/oh/u13/male      200
16:57:53  GET /rankings/oh/u13/female    200
16:57:53  GET /rankings/oh/u14/female    200
16:57:53  GET /rankings/oh/u14/male      200
16:57:53  GET /rankings/oh/u15/male      200
16:57:53  GET /rankings/oh/u15/female    200
16:57:54  GET /rankings/oh/u13/female    200
16:57:54  GET /rankings/oh/u14/male      200  (×3)
16:57:54  GET /rankings/oh/u14/female    200  (×4)
16:57:54  GET /rankings/oh/u15/male      200  (×3)
16:57:54  GET /rankings/oh/u15/female    200  (×4)
16:57:54  GET /rankings/oh/u16/male      200  (×3)
16:57:54  GET /rankings/oh/u16/female    200  (×4)
```

This pattern — systematic sweep of all age groups within a single state in <2 seconds — is
characteristic of an AI web crawler doing structured discovery. It cannot be attributed to
a specific UA without log drain data. The same session also hit `/` and `/rankings`.

Other traffic in the window: `/blog`, `/blog/new-jersey-youth-soccer-rankings` (200),
`/rankings/tx/u15/male`, `/rankings/il/u18/female`, `/rankings/ak/u12/female`,
`/rankings/wy` — geographic diversity consistent with indexing behavior.

---

## Crawlers NOT yet observed

All 13 target UAs are in the "not yet confirmed" column due to the log access gap, not
because they have been confirmed absent. The gap is a tooling limitation, not evidence of
non-crawling.

---

## Failure-mode interpretation

**robots.txt: PASS** — no failure mode here. The file deployed correctly with PR #697 and
has been live on production for 14 days across every production deploy.

**Crawler UA data: TOOLING GAP, not a site failure.**

The inability to confirm per-bot activity is because:
1. Vercel runtime logs do not expose User-Agent headers
2. Static CDN responses (robots.txt, sitemap.xml, most public pages via ISR) never
   produce runtime log entries
3. No log drain was configured to export access logs to an external system

This is not a WAF block, a firewall issue, or a slow-discovery problem. The robots.txt is
correct and discoverable. Whether bots are actually fetching it requires access logs, which
Vercel only exposes via Log Drains.

The Ohio age-group burst is a positive signal. If that traffic were bot-sourced (likely),
it means at least one crawler is already systematically indexing `/rankings/*` pages.

---

## Next steps

**Priority 1 — Get proper log drain access (blocks all future crawler verification):**

1. In the Vercel dashboard → pitchrank project → Settings → Log Drains, configure a drain
   to Axiom, Datadog, or any sink that supports querying by User-Agent. Even a free Axiom
   tier captures enough to answer "is GPTBot fetching us?"

2. Once live, run this query (Axiom example):
   ```
   ['vercel-logs']
   | where host == "www.pitchrank.io"
   | where userAgent contains_cs "GPTBot" or userAgent contains_cs "ClaudeBot"
       or userAgent contains_cs "PerplexityBot" or userAgent contains_cs "OAI-SearchBot"
   | summarize count() by userAgent, bin_auto(timestamp)
   ```

**Priority 2 — Confirm live robots.txt locally (5-minute task):**

```bash
curl -s -A 'Mozilla/5.0' "https://www.pitchrank.io/robots.txt?cb=$(date +%s)" | grep -A3 "GPTBot\|ClaudeBot\|PerplexityBot"
```

Expected output for each: `Allow: /` (not `Disallow: /`).

**Priority 3 — Check Google Search Console for crawl anomalies:**

GSC → Coverage → Crawl Stats shows Googlebot activity. While Google-Extended (the AI
training crawler) is separate from Googlebot, any unusual 429 or 403 on public pages would
surface here and indicate a WAF issue affecting all crawlers.

**Priority 4 — Consider adding an X-Robots-Tag: none guard on /api/ routes** to reinforce
the robots.txt Disallow for crawlers that don't check robots.txt before hitting API
endpoints. Not urgent — robots.txt disallows are sufficient for compliant bots.

---

## Manual checks still needed

Vercel log access was not available in the agent environment. Dallas should run these
locally:

### 1. Verify live robots.txt

```bash
# Confirm all AI crawlers show Allow: /
curl -s -A 'Mozilla/5.0' "https://www.pitchrank.io/robots.txt?cb=$(date +%s)"

# Spot-check specific UAs
curl -s "https://www.pitchrank.io/robots.txt" | grep -B1 -A8 "User-agent: GPTBot"
curl -s "https://www.pitchrank.io/robots.txt" | grep -B1 -A8 "User-agent: ClaudeBot"
curl -s "https://www.pitchrank.io/robots.txt" | grep -B1 -A8 "User-agent: PerplexityBot"
```

### 2. Vercel runtime logs (requires Vercel CLI locally)

```bash
# Install if not present
npm i -g vercel

# Stream recent production logs
vercel logs https://www.pitchrank.io --since 14d --output json | \
  jq 'select(.userAgent | test("GPTBot|ClaudeBot|PerplexityBot|OAI-SearchBot|anthropic-ai|Google-Extended"))'
```

Note: Vercel runtime logs still do not capture static CDN responses. If the above returns
nothing, it does NOT mean bots aren't crawling — it means you need a log drain.

### 3. Set up Axiom log drain (recommended, free tier sufficient)

- Vercel dashboard → pitchrank → Settings → Log Drains → Add Drain
- Endpoint: your Axiom ingest URL
- Sources: ☑ Static, ☑ Edge, ☑ Serverless
- After 24h, query for AI bot UAs

### 4. Google Search Console crawl stats

- GSC → pitchrank.io property → Settings → Crawl Stats
- Look for: total requests, by response, by file type
- A healthy site at this stage should show 0 blocked requests on public pages

---

*Report generated by Claude Code agent, 2026-05-13.*
*Commit in scope: e6b89aab8 (PR #697, merged 2026-04-29).*
