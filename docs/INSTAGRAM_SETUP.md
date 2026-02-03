# Instagram Setup Guide

> **Status:** Not configured. Requires Facebook Business setup.

## Prerequisites (D H must complete)

1. **Facebook Business Page** — Create or use existing
2. **Instagram Business/Creator Account** — Must be connected to the FB Page
3. **Facebook Developer App** — Create at [developers.facebook.com](https://developers.facebook.com)
4. **Add Instagram Graph API** — In your FB App, add the Instagram Graph API product

## Required Permissions

Your access token needs:
- `instagram_basic`
- `instagram_content_publish`
- `pages_read_engagement`

## Environment Variables

Add to `/Users/pitchrankio-dev/Projects/PitchRank/.env`:

```bash
INSTAGRAM_ACCESS_TOKEN=your_long_lived_access_token
INSTAGRAM_BUSINESS_ACCOUNT_ID=your_ig_business_account_id
```

## Getting the Account ID

1. Go to [Graph API Explorer](https://developers.facebook.com/tools/explorer/)
2. Select your app and generate a token
3. Query: `GET /me/accounts` to get your Page ID
4. Query: `GET /{page-id}?fields=instagram_business_account` to get IG Account ID

## Testing

```bash
cd /Users/pitchrankio-dev/Projects/PitchRank
python3 scripts/post_to_instagram.py --dry-run
```

## Usage

```bash
# Post with image URL (must be publicly accessible)
python3 scripts/post_to_instagram.py \
  --caption "🏆 This week's top movers! #YouthSoccer #PitchRank" \
  --image-url "https://pitchrank.io/api/infographic/movers"

# Preview without posting
python3 scripts/post_to_instagram.py --dry-run --caption "Test"
```

## Integration with Movy

Once configured, Movy's Wednesday Preview will auto-post:
- Weekend preview infographic
- Top movers infographic
- Big game matchups

---
*Last updated: 2026-02-03*
