# How GitHub Actions Imports Games (Explained Simply)

## 🎯 The Big Picture

Imagine you have a **giant address book** (the database) with all the soccer teams. When new games come in, you need to figure out which teams played in each game. It's like matching names on a scorecard to names in your address book.

---

## 📋 Step-by-Step: What Happens When GitHub Actions Runs

### Step 1: The Robot Goes Shopping 🛒
**What happens:** GitHub Actions (our robot) runs automatically every week
- For Modular11: Every Sunday night at 11pm
- For GotSport: Every Monday morning

**What it does:** 
- Goes to the website (like Modular11.com)
- Collects all the new game scores from the last 7 days
- Saves them in a CSV file (like a spreadsheet)

**Think of it like:** A robot going to the store and buying groceries (collecting game data)

---

### Step 2: The Robot Brings Home the Groceries 📦
**What happens:** The robot has a CSV file with games like:
```
Team: "ALBION SC Las Vegas U14 AD" 
Team ID: 456
Opponent: "Sparta United U14 AD"
Opponent ID: 1350
Score: 0-2
Date: 1/10/2026
```

**What it does:** 
- Reads the CSV file
- For each game, it needs to find the teams in the database

**Think of it like:** Unpacking groceries and checking if you already have them in your pantry

---

### Step 3: The Matching Game 🎮

This is where it gets interesting! For each team in each game, the robot tries **3 different strategies** to find the team in the database:

#### Strategy 1: The Fast Lane ⚡ (Tier 1 - Direct ID Match)

**What it looks for:**
- A team with `match_method = 'direct_id'` 
- This is like having a **VIP pass** - instant match!

**How it works:**
1. Game says: "Team ID is 456, age is U14, division is AD"
2. Robot tries to find: `456_U14_AD` with `match_method = 'direct_id'`
3. If found ✅ → **INSTANT MATCH!** (fastest, like 1 millisecond)

**The Problem:** 
- If the alias has `match_method = 'import'` instead of `'direct_id'`
- The robot **skips** Strategy 1 completely
- It goes to Strategy 2 (slower)

**Think of it like:** 
- VIP pass = `direct_id` (fast lane, no waiting)
- Regular ticket = `import` (slow lane, have to wait)

---

#### Strategy 2: The Regular Lane 🚶 (Tier 2 - Any Approved Alias)

**What it looks for:**
- A team with `match_method = 'import'` OR `'direct_id'` OR anything
- As long as `review_status = 'approved'`

**How it works:**
1. Game says: "Team ID is 456, age is U14, division is AD"
2. Robot tries to find: `456_U14_AD` with ANY `match_method` (but must be approved)
3. If found ✅ → **MATCH!** (slower, like 10 milliseconds)

**The Problem:**
- This is slower than Strategy 1
- If there are multiple matches, it might pick the wrong one
- It tries IDs in order: `456_U14_AD`, then `456_U14`, then `456_AD`, then `456`

**Think of it like:**
- Regular ticket line (slower, but still works)
- Might have to check multiple options

---

#### Strategy 3: The Fuzzy Search 🔍 (Tier 3 - Name Matching)

**What it looks for:**
- No exact ID match found
- Tries to match by team name similarity

**How it works:**
1. Game says: "Team name is 'ALBION SC Las Vegas U14 AD'"
2. Robot searches all U14 teams
3. Calculates how similar names are (like spell-check)
4. If similarity ≥ 90% → Auto-match ✅
5. If similarity 75-90% → Put in review queue ⏳
6. If similarity < 75% → Reject ❌

**Think of it like:**
- Asking "Do you know someone named 'Bob'?" 
- And checking if any "Bob" in your address book matches

---

## 🐛 The Bug We Found

### What Was Wrong:

Your team alias `456_U14_AD` had:
- ✅ `review_status = 'approved'` (good!)
- ❌ `match_method = 'import'` (bad!)

### What This Meant:

1. **Strategy 1 (Fast Lane)** looked for `match_method = 'direct_id'`
   - Didn't find it (because it was `'import'`)
   - Skipped to Strategy 2

2. **Strategy 2 (Regular Lane)** found `456_U14_AD` 
   - But it also tried other IDs like `456_U13_AD` (wrong age!)
   - Sometimes matched to the WRONG team (U13 instead of U14)

### Why It Happened:

When teams are imported via `import_teams_enhanced.py`, they get `match_method = 'direct_id'` ✅

But when teams are created **during game imports** (automatically), they get `match_method = 'import'` ❌

### The Fix:

We changed `456_U14_AD` from `match_method = 'import'` to `match_method = 'direct_id'`

Now Strategy 1 will find it instantly! ⚡

---

## 🔄 Current GitHub Actions Process (After Fix)

### For Modular11:

1. **Scrape** (every Sunday 11pm):
   ```bash
   scrapy crawl modular11_schedule
   ```
   - Gets games from last 7 days
   - Saves to CSV

2. **Import**:
   ```bash
   python scripts/import_games_enhanced.py "$CSV_FILE" modular11 --summary-only
   ```
   - Reads CSV
   - For each game:
     - Validates data
     - Tries to match teams (Strategy 1 → 2 → 3)
     - If teams match → saves game ✅
     - If teams don't match → creates new team or puts in review queue

3. **Result:**
   - Games saved to database
   - Teams matched (now using Strategy 1 for `direct_id` aliases!)
   - Summary report generated

---

## 📊 Summary: Why Match Method Matters

| Match Method | Strategy Used | Speed | Reliability |
|-------------|--------------|-------|-------------|
| `direct_id` | Strategy 1 (Fast Lane) | ⚡⚡⚡ Very Fast | ✅✅✅ Very Reliable |
| `import` | Strategy 2 (Regular Lane) | ⚡⚡ Slower | ⚠️⚠️ Can Match Wrong Team |
| `fuzzy_auto` | Strategy 3 (Fuzzy Search) | ⚡ Slowest | ⚠️ Less Reliable |

---

## 🎓 Key Takeaway

**Before Fix:**
- Alias had `match_method = 'import'`
- Robot skipped fast lane → used slow lane
- Sometimes matched wrong team (U13 instead of U14)

**After Fix:**
- Alias has `match_method = 'direct_id'`
- Robot uses fast lane → instant match
- Always matches correct team (U14) ✅

---

## 🔧 What We Should Do Next

1. **Update all Modular11 aliases** from `'import'` to `'direct_id'`
   - This will make ALL future imports faster and more accurate
   - Script: `fix_modular11_aliases.py` (needs to be run)

2. **Fix the incorrectly matched games**
   - Games that matched to U13 teams need to be updated
   - Either delete and re-import, or manually fix the team IDs

3. **Update the code** so new teams created during imports get `'direct_id'` instead of `'import'`
   - This prevents the problem from happening again

---

## 💡 Simple Analogy

**Think of it like a library:**

- **Strategy 1 (`direct_id`)**: You know the exact book ISBN → instant find! 📚
- **Strategy 2 (`import`)**: You know part of the title → search catalog → might find wrong book 📖
- **Strategy 3 (Fuzzy)**: You only remember "something about soccer" → browse shelves → slowest 🔍

The bug was like having the ISBN but the librarian only checking Strategy 2, so sometimes grabbing the wrong book!

