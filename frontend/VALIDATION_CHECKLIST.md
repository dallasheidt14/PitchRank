# Phase 5 Validation Checklist

Use this checklist when performing manual validation against the live deployment at https://pitchrank-pi.vercel.app

## Quick Start

1. Open the live site: https://pitchrank-pi.vercel.app
2. Open Chrome DevTools (F12)
3. Go through each section below and check off items as you verify them
4. Record any issues found in the validation report

---

## 1. Environment Variables

### Vercel Dashboard
- [ ] Go to Vercel → Project → Settings → Environment Variables
- [ ] Verify `NEXT_PUBLIC_SUPABASE_URL` exists and equals `https://pfkrhmprwxtghtpinrot.supabase.co`
- [ ] Verify `NEXT_PUBLIC_SUPABASE_ANON_KEY` exists
- [ ] Check Production, Preview, and Development environments

### Browser Console
- [ ] Open https://pitchrank-pi.vercel.app
- [ ] Open DevTools → Console tab
- [ ] Look for any "Missing Supabase environment variables" errors
- [ ] **Result:** [ ] No errors | [ ] Errors found (describe below)

### Network Requests
- [ ] Open DevTools → Network tab
- [ ] Filter by "supabase"
- [ ] Refresh page
- [ ] Verify all requests return 200 OK
- [ ] Click on a request → Check Response tab → Verify JSON data
- [ ] **Result:** [ ] All 200 OK | [ ] Errors found (describe below)

---

## 2. CORS & Network

### Network Tab
- [ ] Filter Network tab by "supabase"
- [ ] Click on a request → Headers tab
- [ ] Verify `Access-Control-Allow-Origin` header is present
- [ ] **Result:** [ ] Header present | [ ] Missing

### Console Errors
- [ ] Check Console tab for CORS errors (red errors)
- [ ] Look for messages like "blocked by CORS policy"
- [ ] **Result:** [ ] No CORS errors | [ ] CORS errors found (describe below)

### Supabase Dashboard
- [ ] Go to Supabase Dashboard → Settings → API
- [ ] Verify "Enable Data API" toggle is ON
- [ ] **Result:** [ ] Enabled | [ ] Disabled

---

## 3. Build Verification

### Vercel Dashboard
- [ ] Go to Vercel → Project → Deployments
- [ ] Click on latest deployment
- [ ] Review Build Logs
- [ ] Verify "Build completed successfully" message
- [ ] Check for TypeScript errors
- [ ] Check for ESLint warnings
- [ ] **Result:** [ ] Build successful | [ ] Build failed (describe below)

### Live Site
- [ ] Visit https://pitchrank-pi.vercel.app
- [ ] Verify page loads (no white screen)
- [ ] Check Console for hydration errors
- [ ] **Result:** [ ] Loads correctly | [ ] Errors found (describe below)

---

## 4. Page Functionality

### Home Page (/)
- [ ] Visit home page
- [ ] Verify "Featured Rankings" card shows top 10 teams
- [ ] Verify teams have rank numbers
- [ ] Verify rank change indicators (arrows) appear
- [ ] Click on a team → Verify navigation works
- [ ] **Result:** [ ] All working | [ ] Issues found (describe below)

### Rankings Page (/rankings/national/u12/Male)
- [ ] Navigate to rankings page
- [ ] Verify table loads with data
- [ ] Click column headers → Verify sorting works
- [ ] Hover over "Power Score" → Verify tooltip appears
- [ ] Click on a team name → Verify navigation works
- [ ] **Result:** [ ] All working | [ ] Issues found (describe below)

### Team Detail Page (/teams/[id])
- [ ] Navigate to a team detail page
- [ ] Verify team header displays
- [ ] Verify trajectory chart renders (may take a moment)
- [ ] Verify momentum meter animates
- [ ] Verify game history table loads
- [ ] **Result:** [ ] All working | [ ] Issues found (describe below)

### Compare Page (/compare)
- [ ] Navigate to compare page
- [ ] Select Team 1 from dropdown
- [ ] Select Team 2 from dropdown
- [ ] Verify side-by-side comparison cards appear
- [ ] Verify bar chart renders below
- [ ] **Result:** [ ] All working | [ ] Issues found (describe below)

### Movers Page (/movers)
- [ ] Navigate to movers page
- [ ] Verify filters work (Region, Age Group, Gender)
- [ ] Change filters → Verify table updates
- [ ] Verify sparkline charts render in Trajectory column
- [ ] **Result:** [ ] All working | [ ] Issues found (describe below)

### Methodology Page (/methodology)
- [ ] Navigate to methodology page
- [ ] Verify static content loads
- [ ] Check Network tab → Verify no unnecessary API calls
- [ ] **Result:** [ ] All working | [ ] Issues found (describe below)

### 404 Page
- [ ] Visit invalid route (e.g., /invalid-page-12345)
- [ ] Verify custom 404 page renders
- [ ] Click "Return to Home" → Verify navigation works
- [ ] **Result:** [ ] All working | [ ] Issues found (describe below)

---

## 5. Lighthouse Audit

### Desktop Audit
- [ ] Open https://pitchrank-pi.vercel.app
- [ ] Open DevTools → Lighthouse tab
- [ ] Select "Desktop" and all categories
- [ ] Click "Generate report"
- [ ] Record scores:

| Metric | Score |
|--------|-------|
| Performance | ___ |
| Accessibility | ___ |
| Best Practices | ___ |
| SEO | ___ |
| LCP | ___ ms |
| CLS | ___ |
| TBT | ___ ms |
| Speed Index | ___ ms |

### Mobile Audit
- [ ] Select "Mobile" and all categories
- [ ] Click "Generate report"
- [ ] Record scores:

| Metric | Score |
|--------|-------|
| Performance | ___ |
| Accessibility | ___ |
| Best Practices | ___ |
| SEO | ___ |
| LCP | ___ ms |
| CLS | ___ |
| TBT | ___ ms |
| Speed Index | ___ ms |

### Issues Found
- [ ] List any performance issues flagged by Lighthouse
- [ ] List any accessibility issues
- [ ] List any best practices issues
- [ ] List any SEO issues

---

## 6. Branding & Metadata

### Visual Checks
- [ ] Check browser tab → Verify favicon displays
- [ ] Verify light mode logo appears (default)
- [ ] Click theme toggle → Verify dark mode logo appears
- [ ] Check Network tab → Verify no 404s for `/logos/*` files
- [ ] **Result:** [ ] All correct | [ ] Issues found (describe below)

### Meta Tags
- [ ] Open DevTools → Elements tab
- [ ] Expand `<head>` section
- [ ] Verify `<title>` contains "PitchRank"
- [ ] Verify `<meta name="description">` exists
- [ ] Verify `<meta property="og:title">` exists
- [ ] Verify `<meta property="og:description">` exists
- [ ] Verify `<meta property="og:image">` exists
- [ ] **Result:** [ ] All present | [ ] Missing tags (list below)

### Social Preview Test
- [ ] Visit https://www.opengraph.xyz/
- [ ] Enter URL: https://pitchrank-pi.vercel.app
- [ ] Verify preview shows correct title, description, and image
- [ ] **Result:** [ ] Correct | [ ] Issues found (describe below)

---

## 7. Accessibility

### Keyboard Navigation
- [ ] Press Tab repeatedly → Verify focus moves logically
- [ ] Verify focus rings are visible on all interactive elements
- [ ] Press Enter on links → Verify navigation works
- [ ] Press Space on buttons → Verify actions work
- [ ] **Result:** [ ] All working | [ ] Issues found (describe below)

### ARIA & Semantic HTML
- [ ] Open DevTools → Elements tab
- [ ] Search for elements with `aria-label` → Verify they exist
- [ ] Check charts → Verify they have `aria-label` or descriptions
- [ ] Check images → Verify they have `alt` attributes
- [ ] **Result:** [ ] All present | [ ] Missing attributes (list below)

### Screen Reader (Optional)
- [ ] Enable screen reader (NVDA/JAWS/VoiceOver)
- [ ] Navigate through pages
- [ ] Verify all content is announced correctly
- [ ] **Result:** [ ] All working | [ ] Issues found (describe below)

---

## 8. Error Handling

### Network Errors
- [ ] Open DevTools → Network tab
- [ ] Set throttling to "Offline"
- [ ] Refresh page
- [ ] Verify error message displays (not blank screen)
- [ ] Set throttling back to "Online"
- [ ] **Result:** [ ] Handles gracefully | [ ] Issues found (describe below)

### Invalid Routes
- [ ] Visit /teams/invalid-id-12345
- [ ] Verify error message displays
- [ ] **Result:** [ ] Handles gracefully | [ ] Issues found (describe below)

### Console Errors
- [ ] Check Console tab for red errors
- [ ] Verify no uncaught promise rejections
- [ ] Verify no React errors
- [ ] **Result:** [ ] No errors | [ ] Errors found (list below)

### Loading States
- [ ] Navigate to pages with data
- [ ] Verify loading skeletons/spinners appear
- [ ] **Result:** [ ] Present | [ ] Missing

### Empty States
- [ ] Test with filters that return no results
- [ ] Verify "No data" messages appear
- [ ] **Result:** [ ] Present | [ ] Missing

---

## Issues Found

Document any issues found during validation:

### Critical Issues
1. 
2. 
3. 

### Medium Priority Issues
1. 
2. 
3. 

### Low Priority Issues
1. 
2. 
3. 

---

## Final Validation Status

- [ ] All checks passed
- [ ] Issues found (see above)
- [ ] Ready for production
- [ ] Needs fixes before launch

**Validated By:** _______________  
**Date:** _______________  
**Notes:** _______________

