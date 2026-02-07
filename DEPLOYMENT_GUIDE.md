# PitchRank Dashboard - Streamlit Cloud Deployment Guide

Deploy your PitchRank Settings Dashboard to Streamlit Cloud for free 24/7 hosting with automatic updates from GitHub.

## Quick Setup (5 minutes)

### Step 1: Push Your Code to GitHub ✅
**Already done!** Your dashboard code is on branch `claude/python-monitoring-dashboard-01TURubuH4Xg37TbkECy1F5u`

### Step 2: Sign Up for Streamlit Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Click "Sign up" and use your GitHub account
3. Authorize Streamlit Cloud to access your repositories

### Step 3: Deploy Your App

1. Click **"New app"** button
2. Fill in the deployment form:
   - **Repository**: `dallasheidt14/PitchRank`
   - **Branch**: `claude/python-monitoring-dashboard-01TURubuH4Xg37TbkECy1F5u` (or merge to main first)
   - **Main file path**: `dashboard.py`
3. Click **"Deploy!"**

**That's it!** Streamlit Cloud will:
- Install dependencies from `requirements.txt`
- Launch your dashboard
- Give you a public URL like `https://your-app-name.streamlit.app`

## Configuration

### Environment Variables (Optional)

If you need to configure any settings, add environment variables in Streamlit Cloud:

1. Go to your app settings (⚙️ icon)
2. Click "Secrets"
3. Add your variables in TOML format:

```toml
# Example secrets configuration
SUPABASE_URL = "your-url-here"
SUPABASE_KEY = "your-key-here"
ML_ALPHA = "0.15"
SOS_TRANSITIVITY_LAMBDA = "0.25"
```

**Note:** The dashboard is read-only (just viewing settings), so you likely don't need any secrets unless you want to override config values.

### App Settings

The app is pre-configured via `.streamlit/config.toml`:
- Theme colors matching your brand
- Optimized for web deployment
- Usage stats disabled

## Automatic Updates

Once deployed, Streamlit Cloud automatically redeploys when you:
1. Push changes to the configured branch
2. Merge pull requests to that branch

**No manual intervention needed!** Your dashboard stays up-to-date automatically.

## Recommended: Merge to Main Branch

For production use, merge your dashboard to the main branch:

```bash
# Create a pull request (recommended)
gh pr create --base main --head claude/python-monitoring-dashboard-01TURubuH4Xg37TbkECy1F5u --title "Add Settings Dashboard" --body "Streamlit-based UI for viewing all ranking engine parameters"

# Or merge directly
git checkout main
git merge claude/python-monitoring-dashboard-01TURubuH4Xg37TbkECy1F5u
git push origin main
```

Then update your Streamlit Cloud app to use the `main` branch.

## Access Control

### Public Dashboard (Default)
Anyone with the URL can view your dashboard. This is fine for:
- Read-only settings view
- Internal team sharing
- Public documentation

### Private Dashboard
To restrict access:
1. Go to app settings
2. Enable "Require viewers to log in"
3. Add authorized email addresses

## Custom Domain (Optional)

Streamlit Cloud apps get a free subdomain, but you can use your own:
1. Upgrade to Streamlit Cloud Pro (if needed)
2. Add your custom domain in settings
3. Configure DNS CNAME record

## Monitoring

### View Logs
1. Click "Manage app" in Streamlit Cloud
2. View real-time logs
3. Monitor resource usage

### Analytics
- Streamlit Cloud provides basic analytics
- View visitor count and resource usage
- Monitor app health

## Troubleshooting

### App Won't Start
**Check logs for errors:**
- Missing dependencies? Update `requirements.txt`
- Import errors? Verify file paths are correct
- Environment variables? Add them in Secrets

### App is Slow
**Optimize performance:**
- Streamlit Cloud provides 1 CPU / 800MB RAM on free tier
- Consider caching with `@st.cache_data` if you add data loading
- Current dashboard is lightweight and should run fast

### Can't Access Supabase
**If you need database access:**
1. Add Supabase credentials to Secrets (TOML format)
2. Ensure Supabase allows connections from Streamlit Cloud IPs
3. Or set `USE_LOCAL_SUPABASE=false` in secrets

## Free Tier Limits

Streamlit Cloud free tier includes:
- ✅ Unlimited public apps
- ✅ 1 GB memory per app
- ✅ Auto-deployment from GitHub
- ✅ Community support
- ❌ No custom authentication (use Pro for this)
- ❌ No custom domains (use Pro for this)

**Your dashboard easily fits in the free tier!**

## Alternative: Run Locally

If you prefer not to deploy, run locally:

```bash
# Install dependencies
pip install -r requirements.txt

# Run dashboard
streamlit run dashboard.py
```

Access at `http://localhost:8501`

## Support

- **Streamlit Docs**: [docs.streamlit.io](https://docs.streamlit.io)
- **Streamlit Cloud Docs**: [docs.streamlit.io/streamlit-cloud](https://docs.streamlit.io/streamlit-cloud)
- **Community Forum**: [discuss.streamlit.io](https://discuss.streamlit.io)

## Next Steps

After deploying:

1. **Bookmark the URL** - Share with your team
2. **Test all sections** - Navigate through all parameter views
3. **Verify settings** - Ensure all parameters match your configuration
4. **Share feedback** - Update dashboard based on team needs

## Example Public URL

After deployment, your dashboard will be accessible at:
```
https://pitchrank-settings.streamlit.app
```
(The exact URL depends on your app name)

---

**Ready to deploy?** Head to [share.streamlit.io](https://share.streamlit.io) and click "New app"!
