# Canonical Tag Audit - Search Console Issues

**Date:** 2026-02-08  
**Issue:** Google Search Console reporting duplicate pages without user-selected canonical tags

## Problems Identified

### 1. Inconsistent Canonical URL Format
Some pages use **relative paths** while others use **absolute URLs**. Google Search Console prefers absolute canonical URLs with full domain.

**Pages with relative canonicals (NEED FIXING):**
- `/blog/page.tsx` → uses `/blog` (should be `https://pitchrank.io/blog`)
- `/methodology/page.tsx` → uses `/methodology` (should be `https://pitchrank.io/methodology`)
- `/compare/page.tsx` → uses `/compare` (should be absolute or removed since noindex)

**Pages with correct absolute canonicals:**
- `/rankings/[region]/[ageGroup]/[gender]/page.tsx` ✅
- `/rankings/layout.tsx` ✅
- `/blog/[slug]/page.tsx` ✅
- `/teams/[id]/page.tsx` ✅
- Root `/layout.tsx` ✅

### 2. Auth-Gated Pages
Pages with `robots: { index: false }` still define canonical tags. These pages shouldn't be indexed at all, so canonical tags are unnecessary (though not harmful).

**Auth-gated pages:**
- `/compare/page.tsx` - noindex + canonical (canonical can be removed or kept as absolute)
- `/teams/[id]/page.tsx` - noindex + canonical (canonical should stay for proper merged team redirects)
- `/watchlist/page.tsx` - likely should be noindex (client component, no metadata found)

## Root Cause
The issue stems from mixing relative and absolute canonical URLs. Next.js `alternates.canonical` accepts both, but Google prefers absolute URLs for clarity.

## Solution

### Fix Required
Convert all relative canonical URLs to absolute URLs using the pattern:
```typescript
const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';
alternates: {
  canonical: `${baseUrl}/path`,
}
```

### Files to Update
1. `frontend/app/blog/page.tsx` - Change `/blog` to `${baseUrl}/blog`
2. `frontend/app/methodology/page.tsx` - Change `/methodology` to `${baseUrl}/methodology`
3. `frontend/app/compare/page.tsx` - Change `/compare` to `${baseUrl}/compare` (or remove since noindex)

## Testing
After deployment:
1. Check rendered HTML `<link rel="canonical">` tags for absolute URLs
2. Submit sitemap to Google Search Console
3. Monitor "Duplicate pages without user-selected canonical" errors (should decrease)
4. Verify in Search Console > Coverage that alternate pages are properly handled

## Notes
- Sitemap (`frontend/app/sitemap.ts`) already excludes auth-gated pages ✅
- Dynamic ranking pages already use absolute canonical URLs ✅
- This fix is in Codey's trust zone (bug fix with clear error → solution path)
