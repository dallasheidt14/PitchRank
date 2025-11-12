# PitchRank Frontend Deployment Guide

This guide covers deploying the PitchRank frontend to Vercel and validating the production build.

## Prerequisites

- Vercel account (sign up at https://vercel.com)
- GitHub repository connected to Vercel
- Supabase project with database populated

## Deployment Steps

### 1. Connect Repository to Vercel

1. Go to https://vercel.com/new
2. Import your GitHub repository (`PitchRank`)
3. Select the `frontend` folder as the root directory
4. Framework preset: **Next.js** (auto-detected)

### 2. Configure Environment Variables

In Vercel project settings → Environment Variables, add:

```
NEXT_PUBLIC_SUPABASE_URL=https://pfkrhmprwxtghtpinrot.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key_here
NEXT_PUBLIC_SITE_URL=https://pitchrank-pi.vercel.app
```

**Important:**
- Set these for **Production**, **Preview**, and **Development** environments
- Use your actual Supabase anon key (found in Supabase Dashboard → Settings → API)
- Update `NEXT_PUBLIC_SITE_URL` to match your actual Vercel deployment URL

### 3. Deploy

1. Click "Deploy"
2. Wait for build to complete (typically 2-3 minutes)
3. Verify build logs show "Build completed successfully"
4. Visit the deployment URL provided by Vercel

### 4. Verify Deployment

Follow the validation checklist in `VALIDATION_CHECKLIST.md`:

1. ✅ Check environment variables are loaded
2. ✅ Verify Supabase connection works
3. ✅ Test all pages load correctly
4. ✅ Run Lighthouse audit
5. ✅ Verify branding and metadata
6. ✅ Test accessibility
7. ✅ Verify error handling

## Post-Deployment Configuration

### Enable Vercel Analytics (Optional)

1. Go to Vercel → Project → Settings → Analytics
2. Enable "Web Analytics"
3. This provides performance metrics and user analytics

### Configure Custom Domain (Optional)

1. Go to Vercel → Project → Settings → Domains
2. Add your custom domain (e.g., `pitchrank.com`)
3. Follow DNS configuration instructions
4. Update `NEXT_PUBLIC_SITE_URL` environment variable

### Set Up Error Tracking (Optional)

Consider adding error tracking:

1. **Sentry:**
   ```bash
   npm install @sentry/nextjs
   npx @sentry/wizard@latest -i nextjs
   ```

2. **Vercel Log Drains:**
   - Go to Vercel → Project → Settings → Log Drains
   - Configure external logging service

## Troubleshooting

### Build Fails

**Issue:** Build fails with TypeScript errors
- **Solution:** Run `npm run build` locally first to catch errors
- Check `tsconfig.json` configuration

**Issue:** Build fails with missing environment variables
- **Solution:** Ensure all `NEXT_PUBLIC_*` variables are set in Vercel
- Variables must be set before deployment

### Runtime Errors

**Issue:** "Missing Supabase environment variables" error
- **Solution:** Verify environment variables are set in Vercel dashboard
- Check that variables are set for the correct environment (Production/Preview)

**Issue:** CORS errors in browser console
- **Solution:** Verify Supabase Data API is enabled
- Check CORS settings in Supabase Dashboard → Settings → API
- Run SQL fix if needed (see validation report)

**Issue:** Pages return 404
- **Solution:** Check that routes are properly configured
- Verify dynamic routes use correct syntax (`[param]`)

### Performance Issues

**Issue:** Slow page loads
- **Solution:** Check Lighthouse audit for specific issues
- Verify images use Next.js Image component
- Check for large JavaScript bundles
- Enable Vercel Analytics to monitor performance

## Monitoring

### Vercel Analytics

- View page views, unique visitors, and performance metrics
- Monitor Core Web Vitals (LCP, CLS, FID)
- Track errors and performance issues

### Supabase Logs

- Monitor API request logs in Supabase Dashboard
- Check for failed queries or rate limiting
- Review error logs for debugging

## Rollback

If deployment has issues:

1. Go to Vercel → Project → Deployments
2. Find the previous working deployment
3. Click "..." → "Promote to Production"
4. This instantly rolls back to the previous version

## Continuous Deployment

Vercel automatically deploys on:
- Push to `main` branch → Production deployment
- Push to other branches → Preview deployment
- Pull requests → Preview deployment with comments

## Environment-Specific Configuration

### Production
- Uses production Supabase database
- Full error tracking enabled
- Analytics enabled
- Custom domain configured

### Preview
- Uses production Supabase database (or separate preview DB)
- Preview URLs for testing
- Same environment variables as production

### Development
- Local development with `.env.local`
- Hot reload enabled
- Development tools enabled

## Security Checklist

- [ ] Environment variables are not committed to git
- [ ] Supabase anon key has proper RLS policies
- [ ] No sensitive data exposed in client-side code
- [ ] API routes are properly secured (if using)
- [ ] CORS is properly configured

## Performance Optimization

- [ ] Images optimized using Next.js Image component
- [ ] Fonts loaded efficiently (using `next/font`)
- [ ] JavaScript bundles minimized
- [ ] Static pages use ISR where appropriate
- [ ] API calls are cached with React Query

## Accessibility Checklist

- [ ] All interactive elements have focus states
- [ ] ARIA labels present on charts and complex components
- [ ] Keyboard navigation works throughout
- [ ] Screen reader tested (optional but recommended)
- [ ] Color contrast meets WCAG AA standards

## Support

For issues or questions:
1. Check Vercel documentation: https://vercel.com/docs
2. Check Next.js documentation: https://nextjs.org/docs
3. Review validation report: `PHASE_5_VALIDATION_REPORT.md`
4. Check validation checklist: `VALIDATION_CHECKLIST.md`

---

**Last Updated:** [Date]  
**Deployment URL:** https://pitchrank-pi.vercel.app  
**Status:** ✅ Ready for Production

