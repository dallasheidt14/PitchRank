# Vibe Marketing Skills v2 — Menu

Everything you can do with the skill pack. Use `/start-here` to scan your project and get routed, or invoke a skill directly by name or by saying what you want.

---

## One command to remember

```
/start-here
```

Scans your project, shows what exists, asks two questions if needed, and routes you to the right skill (or chains several).

---

## Skill menu (11 skills)

### Foundation (run first — builds brand memory)

| Skill | What you can do |
|-------|------------------|
| **/start-here** | Orchestrate, get a project scan, see what’s missing, run multi-skill workflows, “what should I do next” |
| **/brand-voice** | Extract or build a voice profile so every piece of content sounds like you. Modes: Extract (from existing content), Build (from scratch), Auto-Scrape (from a URL). |
| **/positioning-angles** | Find 3–5 market angles and hooks so your offer stands out. Output: `positioning.md`, optional 12-ad testing matrix. |

---

### Strategy (needs foundation)

| Skill | What you can do |
|-------|------------------|
| **/keyword-research** | Map content territory with the 6 Circles Method: seed keywords → SERP validation → clusters → prioritized content plan. Output: `keyword-plan.md`, content briefs. |
| **/lead-magnet** | Get lead magnet concepts (3–5 ideas) or build the full magnet (checklists, guides, templates, quiz questions). Output: `lead-magnet.md`, brief. |
| **/creative** (setup) | Define creative kit (brand colors, fonts, style) for all later visual work. Run when Replicate API is connected. |

---

### Execution (create the assets)

| Skill | What you can do |
|-------|------------------|
| **/direct-response-copy** | Write landing pages, sales copy, headlines, CTAs, emails, social posts that convert. Multiple variants + A/B suggestions. |
| **/seo-content** | Write long-form SEO articles and guides that rank and read like a human. SERP analysis, FAQ schema, publication-ready output to `./campaigns/content/`. |
| **/email-sequences** | Build welcome, nurture, conversion, launch, re-engagement, post-purchase sequences. Full copy + subject lines + timing + send-day recommendations. |
| **/newsletter** | Create newsletter editions in 6 formats (deep-dive, news briefing, curated links, personal essay, builder update, irreverent news). Subject line variants, send notes, save to `./campaigns/newsletters/`. |
| **/creative** | Produce images, video, and graphics. Five modes (see below). Uses voice profile + creative kit; can use Replicate or output briefs for any tool. |

---

### Distribution (after you have content)

| Skill | What you can do |
|-------|------------------|
| **/content-atomizer** | Turn one piece of content (blog, newsletter, podcast, video) into platform-optimized posts for LinkedIn, Twitter/X, Instagram, TikTok, YouTube Shorts, Threads, Bluesky, Reddit. |

---

## /creative — five production modes

| Mode | What it produces |
|------|-------------------|
| **Product Photo** | Studio-style product shots: lighting, composition, backgrounds. |
| **Product Video** | Short product demos, motion content, UGC-style clips. |
| **Social Graphics** | Feed images, stories, covers, carousels — platform-sized. |
| **Talking Head** | Presenter-style video with lip sync from script or audio. |
| **Ad Creative** | Performance ad variants, hook-format testing, ad matrices. |

---

## Say what you want → skill used

| You say… | Skill |
|----------|--------|
| “What should I do next” / “Help” / “Status” | /start-here |
| “Brand voice” / “Sound like me” / “Analyze my voice” | /brand-voice |
| “Positioning” / “Angle” / “Hook” / “Differentiate” | /positioning-angles |
| “Keyword research” / “Content strategy” / “What should I write” | /keyword-research |
| “Lead magnet” / “Freebie” / “Opt-in” / “Checklist” / “Template” | /lead-magnet |
| “Landing page” / “Sales copy” / “Headlines” / “CTA” | /direct-response-copy |
| “Blog post” / “SEO article” / “Guide” / “Long-form” | /seo-content |
| “Email sequence” / “Welcome emails” / “Nurture” / “Drip” | /email-sequences |
| “Newsletter” / “Weekly email” / “Substack” / “Beehiiv” | /newsletter |
| “Repurpose” / “Atomize” / “Social posts” / “Thread” / “Carousel” | /content-atomizer |
| “Image” / “Photo” / “Video” / “Graphic” / “Ad creative” / “Thumbnail” | /creative |

---

## Pre-built workflows (multi-skill)

Ask in plain language; the orchestrator chains the skills.

| You want… | Workflow |
|-----------|----------|
| **Starting from zero** | /brand-voice + /positioning-angles → foundation report → route by goal. |
| **Build my brand** | /brand-voice + /positioning-angles → /creative (setup) → creative-kit.md. |
| **Lead magnet funnel** | /lead-magnet → /direct-response-copy (landing page) → /email-sequences (delivery + welcome) → /content-atomizer (social promo). |
| **Content strategy** | /keyword-research → /seo-content (pillar) → /content-atomizer → /newsletter (format). |
| **Launch my product** | Full launch stack: copy, emails, landing page, ads (see /start-here for full steps). |
| **Blog post + social** | /seo-content → /content-atomizer. |
| **Newsletter + promote** | /newsletter → /content-atomizer. |

---

## Rough time (single skill)

| Task | Skill | Time |
|------|--------|------|
| Landing page copy | /direct-response-copy | ~20 min |
| Email sequence | /email-sequences | ~15 min |
| Social posts from one asset | /content-atomizer | ~10 min |
| Blog article | /seo-content | ~20 min |
| Ad images | /creative | ~10 min |
| Lead magnet (concept + build) | /lead-magnet | ~15 min |
| Newsletter edition | /newsletter | ~15 min |

---

## Where output lives

- **Brand memory:** `./brand/` (voice-profile.md, positioning.md, keyword-plan.md, creative-kit.md, assets.md, learnings.md)
- **Campaigns:** `./campaigns/{campaign-name}/` (emails, newsletters, content, social, ads)
- **Content:** `./campaigns/content/{keyword-slug}.md`
- **Newsletters:** `./campaigns/newsletters/{date}-{topic}.md`

---

## Coming in v2.1

- /paid-ads — Platform-specific ad copy  
- /audience-research — Deep buyer profile  
- /competitive-intel — Competitor teardowns  
- /landing-page — Full page architecture + copy  
- /cro — Conversion optimization audits  

---

## Version

Vibe Marketing Skills **v2.0** — 11 skills, 5 creative modes, shared brand memory.  
Menu generated for PitchRank. Path: `.claude/skills/skillsv2/skills-v2/`.
