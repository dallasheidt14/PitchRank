# Favicon Optimization Instructions

## Current Issue
The current `favicon.ico` is **943KB** - this is extremely oversized for a favicon.
A properly optimized favicon should be **< 50KB** total.

## Impact
- Every user downloads 943KB on first page load
- Slows initial page load, especially on mobile/slow connections
- Wastes bandwidth

## How to Optimize

### Option 1: Online Tool (Easiest)
1. Go to https://realfavicongenerator.net/
2. Upload one of your SVG logos (pitchrank-logo-white.svg or pitchrank-symbol.svg)
3. Generate favicon package
4. Download and extract
5. Replace `favicon.ico` in this directory
6. Expected size: 15-40KB

### Option 2: Using ImageMagick (Command Line)
```bash
# Install ImageMagick if needed
# Ubuntu/Debian: sudo apt-get install imagemagick
# Mac: brew install imagemagick

# Create optimized multi-size favicon
convert pitchrank-symbol.svg \
  -define icon:auto-resize=256,128,64,48,32,16 \
  -compress JPEG \
  -quality 85 \
  favicon.ico

# Should result in ~30-50KB file
```

### Option 3: Using favicon.io
1. Go to https://favicon.io/favicon-converter/
2. Upload your logo SVG or PNG (preferably square)
3. Download generated package
4. Replace `favicon.ico` with the one from the download

## Verification
After optimization, check file size:
```bash
ls -lh favicon.ico
# Should show ~30-50KB, not 943KB
```

## Expected Results
- **Before:** 943KB favicon
- **After:** 30-50KB favicon
- **Savings:** ~900KB per user
- **Impact:** Faster initial page loads, better mobile experience

## Next Steps
1. Optimize favicon using one of the methods above
2. Test in browser (hard refresh with Cmd/Ctrl + Shift + R)
3. Verify icon displays correctly in browser tab
4. Commit the optimized file
