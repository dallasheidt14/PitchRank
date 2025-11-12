# How to Find Your Supabase Database URL

## Step-by-Step Instructions

### 1. Open Supabase Dashboard
- Go to: https://app.supabase.com
- Sign in to your account

### 2. Select Your Project
- Click on your project (or create one if needed)

### 3. Navigate to Database Settings
- Click **Settings** (gear icon) in the left sidebar
- Click **Database** in the settings menu

### 4. Find Connection String
- Scroll down to the **"Connection String"** section
- You'll see several connection options:
  - **URI** (for API)
  - **Session** (for client apps)
  - **Direct Connection** ← **USE THIS ONE!**

### 5. Copy Direct Connection String
- Click on **"Direct Connection"** tab
- You'll see a connection string like:
  ```
  postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
  ```
- Click the **copy** button next to it

### 6. Get Your Database Password
**Important:** This is NOT your Supabase account login password! It's a separate database password.

If the connection string shows `[YOUR-PASSWORD]`, you need to:
- Scroll up to **"Database Password"** section (above Connection String)
- If you see your password displayed, copy it
- If you don't remember it, click **"Reset Database Password"**
- Copy the new password and replace `[YOUR-PASSWORD]` in the connection string

**Note:** The database password is set when you create your Supabase project. If you don't remember it, just reset it - it won't affect your existing data or API keys.

### 7. Add to Your Environment File
Add this line to your `.env.local` file:
```bash
DATABASE_URL=postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
```

## Alternative: Use Connection Pooling URL
If you see a "Connection Pooling" option, you can use that instead:
- Format: `postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres`
- Port `6543` = Connection Pooler (recommended for COPY)
- Port `5432` = Direct Connection (also works)

## Quick Visual Guide
```
Supabase Dashboard
├── Your Project
    ├── Settings (⚙️)
        ├── Database
            ├── Connection String Section
                ├── Direct Connection ← Click here!
                    └── Copy connection string
```

## Example Connection String
```
postgresql://postgres.abcdefghijklmnop:your-password-here@aws-0-us-east-1.pooler.supabase.com:6543/postgres
```

## Security Note
⚠️ **Never commit your DATABASE_URL to git!**
- It contains your database password
- Keep it in `.env.local` (which should be in `.gitignore`)
- Don't share it publicly

## Verify It Works
After adding DATABASE_URL to `.env.local`, test it:
```bash
python scripts/import_games_enhanced.py --help
```
If it doesn't show an error about missing DATABASE_URL, you're good!


