# Vercel Environment Variables Setup Guide

This guide will walk you through adding all required environment variables to your Vercel project.

## 📋 Prerequisites

- ✅ You have your Stripe Secret Key
- ✅ You have your Stripe Publishable Key
- ✅ You have access to your Vercel project

## 🚀 Step-by-Step Instructions

### Step 1: Access Your Vercel Project

1. **Go to Vercel Dashboard**
   - Visit https://vercel.com/dashboard
   - Log in if needed

2. **Select Your Project**
   - Find and click on your **PitchRank** project
   - If you don't see it, make sure you're in the correct team/account

### Step 2: Navigate to Environment Variables

1. **Go to Project Settings**
   - Click on the **Settings** tab (top navigation)
   - Or click the **Settings** button in the project overview

2. **Open Environment Variables**
   - In the left sidebar, click **Environment Variables**
   - You'll see a list of existing variables (if any)

### Step 3: Add Environment Variables

For each variable below, follow these steps:

1. **Click "Add New"** or the **+** button
2. **Enter the Key** (variable name)
3. **Enter the Value** (your actual key/value)
4. **Select Environments** (Production, Preview, Development - select all that apply)
5. **Click "Save"**

---

## 📝 Variables to Add

### 1. Supabase Variables (If not already set)

**Variable 1:**
- **Key:** `NEXT_PUBLIC_SUPABASE_URL`
- **Value:** Your Supabase project URL (e.g., `https://xxxxx.supabase.co`)
- **Environments:** ✅ Production, ✅ Preview, ✅ Development

**Variable 2:**
- **Key:** `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- **Value:** Your Supabase anon key (starts with `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`)
- **Environments:** ✅ Production, ✅ Preview, ✅ Development

**Variable 3:**
- **Key:** `SUPABASE_SERVICE_ROLE_KEY`
- **Value:** Your Supabase service role key (starts with `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`)
- **Environments:** ✅ Production, ✅ Preview, ✅ Development
- **⚠️ Important:** This is sensitive - make sure it's not exposed in client code

---

### 2. Stripe Variables (You have these!)

**Variable 4:**
- **Key:** `STRIPE_SECRET_KEY`
- **Value:** Your Stripe Secret Key (starts with `sk_live_...` or `sk_test_...`)
- **Environments:** ✅ Production, ✅ Preview, ✅ Development
- **⚠️ Important:** Use `sk_live_...` for Production, `sk_test_...` for Preview/Development

**Variable 5:**
- **Key:** `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`
- **Value:** Your Stripe Publishable Key (starts with `pk_live_...` or `pk_test_...`)
- **Environments:** ✅ Production, ✅ Preview, ✅ Development
- **⚠️ Important:** Use `pk_live_...` for Production, `pk_test_...` for Preview/Development

**Variable 6:**
- **Key:** `STRIPE_WEBHOOK_SECRET`
- **Value:** Your Stripe Webhook Signing Secret (starts with `whsec_...`)
- **Environments:** ✅ Production, ✅ Preview, ✅ Development
- **📝 Note:** You'll get this after setting up the webhook in Stripe Dashboard

---

### 3. Stripe Price IDs (Get these from Stripe Dashboard)

**Variable 7:**
- **Key:** `STRIPE_PRICE_MONTHLY`
- **Value:** Your monthly price ID (starts with `price_...`)
- **Environments:** ✅ Production, ✅ Preview, ✅ Development
- **📝 Note:** Create the product in Stripe first, then copy the Price ID

**Variable 8:**
- **Key:** `NEXT_PUBLIC_STRIPE_PRICE_MONTHLY`
- **Value:** Same as above - your monthly price ID (starts with `price_...`)
- **Environments:** ✅ Production, ✅ Preview, ✅ Development

**Variable 9:**
- **Key:** `STRIPE_PRICE_YEARLY`
- **Value:** Your yearly price ID (starts with `price_...`)
- **Environments:** ✅ Production, ✅ Preview, ✅ Development

**Variable 10:**
- **Key:** `NEXT_PUBLIC_STRIPE_PRICE_YEARLY`
- **Value:** Same as above - your yearly price ID (starts with `price_...`)
- **Environments:** ✅ Production, ✅ Preview, ✅ Development

---

### 4. Site URL

**Variable 11:**
- **Key:** `NEXT_PUBLIC_SITE_URL`
- **Value:** Your production URL (e.g., `https://pitchrank.io`)
- **Environments:** ✅ Production
- **For Preview/Development:** You can use `https://your-project.vercel.app` or leave it for Vercel to auto-detect

---

## 🎯 Quick Checklist

After adding all variables, verify:

- [ ] All 11 variables are added
- [ ] Each variable has the correct key name (case-sensitive!)
- [ ] Production environment is selected for all variables
- [ ] Preview/Development environments selected where appropriate
- [ ] No typos in variable names
- [ ] Values are correct (especially Price IDs)

---

## 🔄 After Adding Variables

### 1. Redeploy Your Application

After adding environment variables, you need to redeploy:

1. **Go to Deployments tab**
2. **Click the three dots (⋯) on your latest deployment**
3. **Select "Redeploy"**
4. **Or push a new commit to trigger a new deployment**

**⚠️ Important:** Environment variables are only available to new deployments. Existing deployments won't have access to newly added variables.

### 2. Verify Variables Are Loaded

1. **Check deployment logs** - Look for any errors about missing environment variables
2. **Test your application** - Try accessing `/upgrade` page
3. **Check browser console** - Look for any client-side errors

---

## 🎨 Visual Guide

### Adding a Variable in Vercel:

```
Settings → Environment Variables → Add New

┌─────────────────────────────────────┐
│ Key: STRIPE_SECRET_KEY              │
│ Value: [Your secret key here]        │
│                                      │
│ Environments:                        │
│ ☑ Production                        │
│ ☑ Preview                            │
│ ☑ Development                        │
│                                      │
│ [Save] [Cancel]                      │
└─────────────────────────────────────┘
```

---

## 🔍 Finding Missing Values

### If you need to find any values:

**Supabase:**
- Go to https://supabase.com/dashboard
- Select your project
- Settings → API
- Copy the values from there

**Stripe Price IDs:**
- Go to https://dashboard.stripe.com/products
- Click on "PitchRank Premium" product
- Click on each price
- Copy the Price ID (starts with `price_`)

**Stripe Webhook Secret:**
- Go to https://dashboard.stripe.com/webhooks
- Click on your webhook endpoint
- Click "Reveal" next to "Signing secret"
- Copy the value (starts with `whsec_`)

---

## ⚠️ Important Notes

1. **Case Sensitivity:** Variable names are case-sensitive. Make sure they match exactly:
   - ✅ `STRIPE_SECRET_KEY`
   - ❌ `stripe_secret_key` or `Stripe_Secret_Key`

2. **NEXT_PUBLIC_ Prefix:** Variables starting with `NEXT_PUBLIC_` are exposed to the browser. Only use this prefix for values that are safe to expose.

3. **Secret Keys:** Never add `STRIPE_SECRET_KEY` or `SUPABASE_SERVICE_ROLE_KEY` with `NEXT_PUBLIC_` prefix - these should remain server-side only.

4. **Different Keys for Different Environments:**
   - You can use different Stripe keys for Production vs Preview
   - Production should use `sk_live_...` and `pk_live_...`
   - Preview/Development can use `sk_test_...` and `pk_test_...`

5. **Redeploy Required:** After adding variables, you must redeploy for them to take effect.

---

## 🐛 Troubleshooting

### Variables not working?

1. **Check spelling** - Variable names must match exactly
2. **Redeploy** - Variables only work in new deployments
3. **Check environment selection** - Make sure you selected the right environments
4. **Check logs** - Look at deployment logs for errors

### Still having issues?

- Verify all variable names match the code exactly
- Check that values don't have extra spaces or quotes
- Make sure you're looking at the correct Vercel project
- Try redeploying after double-checking everything

---

## ✅ Final Checklist

Before considering setup complete:

- [ ] All 11 environment variables added to Vercel
- [ ] All variables have correct values
- [ ] Production environment selected for all
- [ ] Application redeployed
- [ ] Tested `/upgrade` page loads
- [ ] Tested checkout flow (use test mode first!)
- [ ] Webhook configured in Stripe Dashboard
- [ ] Webhook secret added to Vercel

---

## 📚 Additional Resources

- [Vercel Environment Variables Docs](https://vercel.com/docs/concepts/projects/environment-variables)
- [Next.js Environment Variables](https://nextjs.org/docs/app/building-your-application/configuring/environment-variables)












