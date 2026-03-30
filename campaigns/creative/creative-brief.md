---
type: creative-brief
campaign: pitchrank-launch-creative
date: 2026-03-30
model: google/nano-banana-pro (via Replicate)
brand_colors: "#0B5345 (Forest Green), #F4D03F (Electric Yellow), #0f1419 (Dark), #ffffff (White)"
typography: "Oswald (headlines), DM Sans (body)"
status: draft
---

# PitchRank Creative Brief

## Brand Kit Reference
- Primary: #0B5345 (Forest Green)
- Accent: #F4D03F (Electric Yellow)
- Dark: #0f1419
- Text: #1a1a1a (light bg), #f8fafc (dark bg)
- Headlines: Oswald, bold, condensed, uppercase
- Body: DM Sans, clean, readable
- Mood: Confident, clear, athletic. Premium but accessible.
- Avoid: Clip art, neon, cartoon, corporate blue/gray

---

## Asset 1: Blog Hero Image — "Youth Soccer Rankings by State"

**Purpose:** Hero image for the pillar SEO article
**Dimensions:** 16:9 (1200x675 or similar)
**Where it lives:** Blog post header, social share image (og:image)

**Replicate Prompt:**
```
Aerial view of a youth soccer field at golden hour, vibrant green grass
with white line markings, a translucent USA map overlay showing all 50
states with subtle data visualization dots in electric yellow (#F4D03F)
concentrated in California Texas and Florida, deep forest green
(#0B5345) color grading, athletic premium feel, clean modern sports
data aesthetic, no people visible, cinematic depth of field,
16:9 composition, photorealistic
```

**Alternate Prompt (more abstract):**
```
Abstract data visualization of the United States, 50 states rendered
as a clean minimal map with glowing dots representing youth soccer
teams, brighter clusters in California Texas Florida New York, dark
forest green (#0B5345) background, electric yellow (#F4D03F) data
points and connection lines between states, modern sports analytics
aesthetic, clean geometric style, no text, 16:9 composition
```

---

## Asset 2: Instagram Carousel Cover Slide

**Purpose:** Cover slide for the "Rankings by State" carousel
**Dimensions:** 1:1 (1080x1080)

**Replicate Prompt:**
```
Bold modern sports graphic, deep forest green (#0B5345) background,
text "YOUTH SOCCER RANKINGS BY STATE" in bold condensed white
sans-serif font centered in frame, electric yellow (#F4D03F) accent
line beneath the text, subtle soccer field line pattern in background
at low opacity, clean athletic editorial design, no photos, minimal
and bold, 1:1 square composition
```

---

## Asset 3: Instagram Carousel — Stats Slide

**Purpose:** "By the Numbers" slide for carousel
**Dimensions:** 1:1 (1080x1080)

**Replicate Prompt:**
```
Clean data infographic style graphic, white background, three large
numbers stacked vertically: text "25,000+" in bold forest green
(#0B5345), text "50 STATES" in bold forest green, text "EVERY MONDAY"
in bold electric yellow (#F4D03F), each number has a thin horizontal
line separator, modern sans-serif typography, clean minimal sports
analytics aesthetic, 1:1 square composition
```

---

## Asset 4: Social Share / Open Graph Image

**Purpose:** Default og:image for pitchrank.io pages and social shares
**Dimensions:** 2:1 (1200x600)

**Replicate Prompt:**
```
Premium sports brand banner, deep forest green (#0B5345) background
with subtle diagonal stripe pattern, text "PITCHRANK" in large bold
white condensed font top center, text "Rankings You Can Trust" in
electric yellow (#F4D03F) below, subtle soccer ball texture at very
low opacity in background, clean athletic premium feel, no photos,
2:1 wide composition
```

---

## Asset 5: Ad Creative — Landing Page (Meta/Instagram)

**Purpose:** Paid social ad driving to landing page
**Dimensions:** 4:5 (1080x1350) for Instagram feed ads

**Variant A: Data-Forward**
```
Modern sports data graphic, deep forest green (#0B5345) background,
large bold white text "25,000+ TEAMS" at top, text "RANKED EVERY
MONDAY" in electric yellow (#F4D03F) below, subtle ranking table
visualization in background showing numbered rows fading out, clean
bold sans-serif typography, athletic premium feel, no photos, 4:5
portrait composition
```

**Variant B: Question Hook**
```
Bold typographic ad graphic, white background, large text "DO YOU
KNOW WHERE YOUR TEAM STANDS?" in dark forest green (#0B5345) bold
condensed font, electric yellow (#F4D03F) underline accent on
"YOUR TEAM", small text "pitchrank.io" at bottom in green, clean
minimal modern design, no photos, 4:5 portrait composition
```

**Variant C: Competitive**
```
Split comparison graphic, left half deep forest green (#0B5345)
with white text "THEIR RANKINGS" and crossed out items "Tournament
points" "User-edited data" "Single league", right half white with
forest green text "OUR RANKINGS" and checkmarked items "Real game
data" "13-layer algorithm" "Every league", electric yellow (#F4D03F)
divider line in center, bold sans-serif typography, 4:5 portrait
composition
```

---

## Asset 6: TikTok Thumbnail

**Purpose:** Thumbnail for TikTok videos about state rankings
**Dimensions:** 9:16 (1080x1920)

**Replicate Prompt:**
```
Bold vertical social media thumbnail, deep forest green (#0B5345)
background, large white bold condensed text "TOP 5 STATES" at top,
text "FOR YOUTH SOCCER" below in electric yellow (#F4D03F), large
"#1" with a gold trophy emoji graphic below, energetic sports feel,
bold and attention-grabbing, no photos, 9:16 vertical composition
```

---

## Asset 7: Email Header Banner

**Purpose:** Top banner for Beehiiv weekly newsletter
**Dimensions:** 3:1 (600x200)

**Replicate Prompt:**
```
Clean email header banner, deep forest green (#0B5345) background
with subtle diagonal stripe texture, text "PITCHRANK" in white bold
condensed font left-aligned, text "WEEKLY" in electric yellow
(#F4D03F) next to it, minimal clean athletic design, no photos,
3:1 wide banner composition
```

---

## Generation Instructions

### Using Replicate API (Python):

```python
import replicate

output = replicate.run(
    "google/nano-banana-pro",
    input={
        "prompt": "YOUR PROMPT HERE",
        "aspect_ratio": "16:9",  # or 1:1, 4:5, 9:16, 2:1, 3:1
        "num_outputs": 1,
        "output_format": "png",
    }
)
print(output)  # Returns URL to generated image
```

### Cost Estimate:
- 7 assets x ~$0.03 each = ~$0.21 total
- Variants/iterations: budget $1-2 for the full set

### Iteration Workflow:
1. Generate first pass with prompts above
2. Review for brand consistency (colors, mood, no clip art)
3. Adjust prompt if needed (add/remove details)
4. Generate 2-3 variants of best performers
5. Pick winners, save to `campaigns/creative/final/`
