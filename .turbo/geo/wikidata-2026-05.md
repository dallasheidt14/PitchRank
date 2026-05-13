# PitchRank — Wikidata Entity Draft (2026-05-13)

This is the property sheet to use when creating the PitchRank Wikidata item. Wikidata Q-numbers are the canonical entity ID that Wikipedia, AI engines, and Google's Knowledge Graph all consume. Creating one is free, takes ~15 min, and survives if Wikipedia later rejects an article draft.

## Step 1 — Create the item

1. Go to https://www.wikidata.org/wiki/Special:NewItem
2. **Label (English):** `PitchRank`
3. **Description (English):** `independent ranking platform for U.S. youth soccer teams`
4. **Aliases (English):** `pitchrank.io`, `Pitch Rank`
5. Click **Create** — you'll get a Q-number (e.g., Q12345678). Note it.

## Step 2 — Add statements (one per property)

Use the "+ Add statement" button on the item page. Reference each statement to a verifiable source (own website is OK for P856; other claims need third-party press or the site's own about page).

| Property | Value | Notes |
|---|---|---|
| **P31** (instance of) | `website` (Q35127) | Use the Wikidata search; pick the exact item |
| **P31** (instance of) | `online sports ranking system` (Q104637332) | Second value for P31 — multiple instances allowed |
| **P856** (official website) | `https://pitchrank.io` | Reference: itself |
| **P571** (inception) | `2024` (or your actual launch year) | Set point-in-time precision to year |
| **P127** (owned by) | `Dallas Heidt` — create a Person item for yourself first if needed | Optional; skip if you'd rather not link a personal item |
| **P407** (language of work or name) | `English` (Q1860) | |
| **P137** (operator) | (same person/entity as P127) | |
| **P407** (language of work) | `English` (Q1860) | |
| **P1476** (title) | `PitchRank` (English) | |
| **P2002** (X username) | (your handle, if applicable) | Skip if none |
| **P2013** (Facebook ID) | (if applicable) | Skip if none |
| **P1830** (owner of) | (skip unless you own subsidiaries) | |

### Topical "about" / "main subject" links

These cross-link PitchRank to the broader entity graph that AI engines and Wikipedia already know about. Search for each on Wikidata and link the Q-number that matches.

| Property | Linked entity | Q-number |
|---|---|---|
| **P361** (part of) | youth association football in the United States | search "youth soccer United States" |
| **P921** (main subject) | youth association football | (search) |
| **P921** (main subject) | sports rating system | (search) |
| **P2283** (uses) | Glicko rating system | Q5566731 (verify by searching "Glicko") |

### Optional: link to engine details

If you want Wikidata's structured data to reflect that PitchRank uses Glicko-2 specifically:

| Property | Value |
|---|---|
| **P2283** (uses) | Glicko-2 rating system (Q5566731 — the parent "Glicko" item covers both, or search for a "Glicko-2" item; create one if missing) |

⚠️ Do **not** use the "Glicko-2" name in PitchRank's own user-facing content (per existing brand convention — say "rating engine" or "rating algorithm"). Wikidata is the one place where the technical term is appropriate, because it's a structured-data graph for AI engines, not consumer content.

## Step 3 — After creation

1. Paste the assigned **Q-number** below this line:

```
PitchRank Q-number: Q______
Created: 2026-05-_
By: Dallas Heidt
```

2. Add the Q-number to `frontend/components/AuthorEntitySchema.tsx` as a `sameAs` reference in the Organization schema (this signals AI crawlers that the Wikidata entity is canonical):

```tsx
sameAs: [
  "https://www.wikidata.org/wiki/Q______",
  "https://pitchrank.io",
  // existing entries...
]
```

3. Submit the item to https://search.google.com/test/rich-results with our homepage URL — Google's Knowledge Graph picks up the new sameAs link and may surface PitchRank as a verified entity within ~2 weeks.

## Why this matters for GEO

- **Wikipedia eligibility:** A Wikidata item is a prerequisite for a Wikipedia article. Even if the article gets rejected, the Wikidata item persists and AI engines still cite it.
- **AI grounding:** Perplexity, ChatGPT search, and Gemini all use Wikidata as a structured "what is this entity" signal. A linked Q-number means the engine doesn't have to guess.
- **Knowledge Graph eligibility:** Google's Knowledge Graph reads `sameAs: wikidata.org/wiki/Q...` from JSON-LD as a strong signal. This is the missing link from our Week 5 author entity work.

## Risk assessment

- **Article-for-Deletion risk:** Wikidata items have a lower notability bar than Wikipedia articles. As long as the entity is verifiable (which a live website is), the item survives.
- **Vandalism risk:** Low; new items get auto-watchlisted and other editors will revert obvious vandalism.
- **Time cost:** ~15 min to create, ~5 min to link from JSON-LD.

## Next

After the Q-number is assigned, the Wikipedia eligibility audit (`wikipedia-eligibility-2026-05.md`) determines whether to attempt a full article or wait for more press coverage first.
