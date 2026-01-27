# Complete Mac Mini Setup Guide for PitchRank + Clawdbot

A step-by-step guide from unboxing your Mac Mini to having a fully automated PitchRank system.

---

## Table of Contents
1. [Before You Start](#before-you-start)
2. [Phase 1: Unboxing & Initial Setup](#phase-1-unboxing--initial-setup)
3. [Phase 2: System Configuration](#phase-2-system-configuration)
4. [Phase 3: Install Development Tools](#phase-3-install-development-tools)
5. [Phase 4: Install Clawdbot](#phase-4-install-clawdbot)
6. [Phase 5: Clone PitchRank](#phase-5-clone-pitchrank)
7. [Phase 6: Set Up Telegram Bot](#phase-6-set-up-telegram-bot)
8. [Phase 7: Configure Everything](#phase-7-configure-everything)
9. [Phase 8: Install Skills](#phase-8-install-skills)
10. [Phase 9: Set Up Scheduled Tasks](#phase-9-set-up-scheduled-tasks)
11. [Phase 10: Test Everything](#phase-10-test-everything)
12. [Phase 11: Security Hardening](#phase-11-security-hardening)
13. [Ongoing Maintenance](#ongoing-maintenance)

---

## Before You Start

### Do I Need Separate Accounts?

**Apple ID**: **YES, create a dedicated Apple ID**
- Reason: Keeps this machine isolated from your personal Apple ecosystem
- Email: Create something like `pitchrank-server@gmail.com` or `pitchrank@yourdomain.com`
- This Apple ID will only be used for this Mac Mini

**Email Account**: **YES, create a dedicated email**
- Use for: Apple ID, GitHub notifications, error alerts
- Suggestion: `pitchrank-automation@gmail.com`
- Keep credentials in a password manager

**GitHub Account**: **Use your existing account**
- You already have the PitchRank repo there
- Just create a Personal Access Token for this machine

### What You'll Need Ready

Before starting, gather these:

| Item | Where to Get It | Notes |
|------|-----------------|-------|
| Supabase URL | Supabase Dashboard → Settings → API | `https://xxx.supabase.co` |
| Supabase Service Role Key | Supabase Dashboard → Settings → API | Starts with `eyJ...` |
| GitHub Personal Access Token | GitHub → Settings → Developer Settings → PAT | Need `repo` scope |
| Anthropic API Key | console.anthropic.com | For Claude models |
| Your phone with Telegram | App Store / Play Store | For notifications |

### Hardware Setup

- **Location**: Somewhere with good ventilation, stable power
- **Network**: Ethernet recommended (more reliable than WiFi for 24/7)
- **UPS** (optional but recommended): Protects against power outages

---

## Phase 1: Unboxing & Initial Setup

### Step 1.1: Physical Setup
1. Unbox Mac Mini
2. Connect to monitor, keyboard, mouse (temporarily - you can remove later)
3. Connect Ethernet cable (recommended) or prepare WiFi
4. Connect power and turn on

### Step 1.2: macOS Setup Assistant

When the Mac starts, you'll go through the setup wizard:

1. **Select Your Country**: United States (or yours)

2. **Written and Spoken Languages**: English

3. **Accessibility**: Skip (click "Not Now")

4. **Select Your Wi-Fi Network**:
   - If using Ethernet, skip this
   - If using WiFi, connect now

5. **Data & Privacy**: Click Continue

6. **Migration Assistant**:
   - Select **"Don't transfer any information now"**
   - This is a fresh server, no migration needed

7. **Sign In with Your Apple ID**:
   - Click **"Set Up Later"** or use your NEW dedicated Apple ID
   - If creating new: use `pitchrank-server@gmail.com` (or your choice)

8. **Terms and Conditions**: Agree

9. **Create a Computer Account**:
   ```
   Full Name: PitchRank Server
   Account Name: pitchrank
   Password: [strong password - save in password manager]
   Hint: Leave blank
   ```

10. **Express Set Up**: Click **"Customize Settings"**
    - Location Services: OFF (server doesn't need it)
    - Analytics: OFF
    - Screen Time: OFF

11. **Choose Your Look**: Dark mode (easier on eyes if you remote in)

12. **Setup Complete!**

### Step 1.3: First Login

You're now at the desktop. Open **Terminal** (Cmd+Space, type "Terminal").

---

## Phase 2: System Configuration

### Step 2.1: Prevent Sleep (Critical for 24/7 Operation)

Open Terminal and run:

```bash
# Prevent all sleep modes
sudo pmset -a sleep 0
sudo pmset -a disksleep 0
sudo pmset -a displaysleep 0
sudo pmset -a hibernatemode 0

# Verify settings
pmset -g
```

### Step 2.2: Enable Automatic Login

This ensures the Mac starts up and logs in automatically after power outages.

1. Open **System Settings** (Apple menu → System Settings)
2. Go to **Users & Groups**
3. Click the **ⓘ** next to your user
4. Enable **"Log in automatically"**
5. Enter your password

### Step 2.3: Enable Remote Access (SSH)

So you can manage the Mac from anywhere:

```bash
# Enable SSH
sudo systemsetup -setremotelogin on

# Verify
sudo systemsetup -getremotelogin
# Should say: Remote Login: On
```

Test from another computer:
```bash
ssh pitchrank@[mac-mini-ip-address]
```

### Step 2.4: Enable Screen Sharing (Optional)

For visual remote access:

1. System Settings → General → Sharing
2. Enable **Screen Sharing**
3. Click the **ⓘ** to configure who can connect

### Step 2.5: Set Static IP (Recommended)

This makes it easier to always find your Mac Mini:

1. System Settings → Network
2. Click your connection (Ethernet or Wi-Fi)
3. Click **Details...**
4. Go to **TCP/IP**
5. Configure IPv4: **Manually**
6. Set a static IP like `192.168.1.100` (check your router's range)
7. Set Router and DNS to your router's IP

### Step 2.6: Set Computer Name

```bash
# Set a recognizable name
sudo scutil --set ComputerName "PitchRank-Server"
sudo scutil --set LocalHostName "pitchrank-server"
sudo scutil --set HostName "pitchrank-server"
```

### Step 2.7: Disable Unnecessary Features

```bash
# Disable Spotlight indexing (saves CPU)
sudo mdutil -a -i off

# Disable App Nap
defaults write NSGlobalDomain NSAppSleepDisabled -bool YES
```

---

## Phase 3: Install Development Tools

### Step 3.1: Install Xcode Command Line Tools

```bash
xcode-select --install
```
Click "Install" in the popup, wait for completion (~5 min).

### Step 3.2: Install Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the prompts. When done, add to PATH:

```bash
# For Apple Silicon (M1/M2/M3/M4)
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"

# Verify
brew --version
```

### Step 3.3: Install Required Packages

```bash
# Install all required tools
brew install node@22 python@3.11 git jq htop wget

# Link Node 22
brew link node@22

# Verify installations
node --version   # Should be v22.x.x
python3 --version # Should be 3.11.x
git --version
```

### Step 3.4: Configure Git

```bash
git config --global user.name "PitchRank Server"
git config --global user.email "pitchrank-automation@gmail.com"
```

### Step 3.5: Set Up SSH Key for GitHub

```bash
# Generate SSH key
ssh-keygen -t ed25519 -C "pitchrank-automation@gmail.com"
# Press Enter for default location
# Enter a passphrase (or leave empty for automation)

# Start SSH agent
eval "$(ssh-agent -s)"

# Add key to agent
ssh-add ~/.ssh/id_ed25519

# Copy public key
cat ~/.ssh/id_ed25519.pub
```

Now add this key to GitHub:
1. Go to github.com → Settings → SSH and GPG keys
2. Click "New SSH key"
3. Paste the key
4. Name it "PitchRank Server"

Test:
```bash
ssh -T git@github.com
# Should say: Hi username! You've successfully authenticated
```

---

## Phase 4: Install Clawdbot

### Step 4.1: Install Clawdbot

```bash
# Install globally
npm install -g clawdbot@latest

# Verify
clawdbot --version
```

### Step 4.2: Run Onboarding

```bash
clawdbot onboard --install-daemon
```

This will:
- Create `~/.clawdbot/` directory
- Set up the gateway daemon
- Configure launchd for auto-start
- Ask for your Anthropic API key

When prompted for API key, enter your Anthropic key.

### Step 4.3: Verify Installation

```bash
clawdbot doctor
```

Should show all green checkmarks.

---

## Phase 5: Clone PitchRank

### Step 5.1: Create Project Directory

```bash
mkdir -p ~/projects
cd ~/projects
```

### Step 5.2: Clone Repository

```bash
git clone git@github.com:dallasheidt14/PitchRank.git
cd PitchRank
```

### Step 5.3: Set Up Python Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Step 5.4: Create Environment File

```bash
# Copy template
cp .env.example .env.local

# Edit with your credentials
nano .env.local
```

Add these values:

```env
# Supabase (REQUIRED)
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# GitHub (for workflow triggers)
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx

# Clawdbot
CLAWDBOT_MODE=safe_writer

# Anthropic (if not set globally)
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
```

Save and exit (Ctrl+X, Y, Enter).

### Step 5.5: Test Database Connection

```bash
source venv/bin/activate
python3 -c "
from dotenv import load_dotenv
load_dotenv('.env.local')
from supabase import create_client
import os
client = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))
result = client.table('teams').select('team_id_master', count='exact').limit(1).execute()
print(f'✅ Connected! Found {result.count} teams')
"
```

---

## Phase 6: Set Up Telegram Bot

### Step 6.1: Create Bot with BotFather

1. Open Telegram on your phone
2. Search for `@BotFather`
3. Start a chat and send `/newbot`
4. Follow prompts:
   - **Name**: `PitchRank Agent` (display name)
   - **Username**: `pitchrank_agent_bot` (must end in `bot`)
5. **Save the token** BotFather gives you (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### Step 6.2: Configure Bot Settings (Optional but Recommended)

Still in BotFather:
```
/setdescription
@pitchrank_agent_bot
24/7 automation agent for PitchRank youth soccer rankings

/setabouttext
@pitchrank_agent_bot
Manages data scraping, quality, and rankings for PitchRank
```

### Step 6.3: Connect to Clawdbot

On your Mac Mini:

```bash
# Add Telegram channel with your bot token
clawdbot channels add telegram --token "YOUR_BOT_TOKEN_HERE"

# Verify
clawdbot channels status
```

### Step 6.4: Pair Your Phone

1. On your phone, open Telegram
2. Find your bot (search for `@pitchrank_agent_bot`)
3. Send `/start`
4. You'll receive a pairing code

On Mac Mini:
```bash
clawdbot pairing list
# Find the pending code

clawdbot pairing approve telegram YOUR_PAIRING_CODE
```

### Step 6.5: Test Communication

On your phone, send to the bot:
```
hello
```

You should get a response from Clawdbot!

---

## Phase 7: Configure Everything

### Step 7.1: Create Clawdbot Config

```bash
cat > ~/.clawdbot/clawdbot.json << 'EOF'
{
  "agent": {
    "model": "anthropic/claude-sonnet-4",
    "fallback": "anthropic/claude-haiku-3"
  },
  "workspace": "~/projects/PitchRank",
  "channels": {
    "telegram": {
      "enabled": true
    }
  },
  "cron": {
    "enabled": true,
    "timezone": "America/Denver"
  },
  "security": {
    "dmPolicy": "paired",
    "sandbox": {
      "mode": "non-main"
    }
  }
}
EOF
```

### Step 7.2: Restart Gateway

```bash
clawdbot gateway restart
clawdbot status
```

---

## Phase 8: Install Skills

### Step 8.1: Create Skills Directory

```bash
mkdir -p ~/.clawdbot/skills/pitchrank
```

### Step 8.2: Copy PitchRank Skills

```bash
# Copy main skill files
cp ~/projects/PitchRank/clawdbot/SKILL.md ~/.clawdbot/skills/pitchrank/
cp ~/projects/PitchRank/clawdbot/SOUL.md ~/.clawdbot/skills/pitchrank/
cp ~/projects/PitchRank/clawdbot/TOOLS.md ~/.clawdbot/skills/pitchrank/

# Copy agent skills
mkdir -p ~/.clawdbot/skills/pitchrank/agents
cp ~/projects/PitchRank/clawdbot/agents/*.md ~/.clawdbot/skills/pitchrank/agents/

# Copy additional skills
cp -r ~/projects/PitchRank/clawdbot/skills/* ~/.clawdbot/skills/
```

### Step 8.3: Verify Skills Loaded

```bash
clawdbot skills list
```

Should show `pitchrank`, `coder`, `cleaner`, `scraper`, `supabase`.

---

## Phase 9: Set Up Scheduled Tasks

### Step 9.1: Create Cron Jobs

```bash
# Process scrape requests every 15 minutes
clawdbot cron add \
  --name "pitchrank-scraper" \
  --cron "*/15 * * * *" \
  --tz "America/Denver" \
  --session isolated \
  --system-event "Check and process pending scrape requests from the scrape_requests table. Use @scraper skill." \
  --wake now

# Data quality patrol every 4 hours
clawdbot cron add \
  --name "pitchrank-patrol" \
  --cron "0 */4 * * *" \
  --tz "America/Denver" \
  --session isolated \
  --system-event "Run data quality patrol. Check for age mismatches, missing state codes, and potential duplicates. Use @cleaner skill. Send summary to Dallas." \
  --wake now

# Morning briefing at 7 AM MT
clawdbot cron add \
  --name "pitchrank-morning" \
  --cron "0 7 * * *" \
  --tz "America/Denver" \
  --session main \
  --system-event "Good morning Dallas! Send daily briefing: overnight activity, pending items, system health, any issues. Keep it concise." \
  --wake now

# Evening summary at 6 PM MT
clawdbot cron add \
  --name "pitchrank-evening" \
  --cron "0 18 * * *" \
  --tz "America/Denver" \
  --session main \
  --system-event "Send evening summary: today's activity, games imported, issues fixed, anything pending approval." \
  --wake now
```

### Step 9.2: Verify Cron Jobs

```bash
clawdbot cron list
```

---

## Phase 10: Test Everything

### Step 10.1: Test via Telegram

Send these messages to your bot:

1. **Basic test**:
   ```
   status
   ```
   Should respond with system status.

2. **Test scraper**:
   ```
   @scraper check pending requests
   ```
   Should show pending scrape requests.

3. **Test cleaner**:
   ```
   @cleaner run patrol --dry-run
   ```
   Should scan for data quality issues.

4. **Test coder**:
   ```
   @coder what scripts are available?
   ```
   Should list available PitchRank scripts.

### Step 10.2: Test Scripts Directly

```bash
cd ~/projects/PitchRank
source venv/bin/activate

# Test data quality check
python scripts/fix_team_age_groups.py --dry-run

# Test scraper (dry run)
python scripts/process_missing_games.py --dry-run --limit 3
```

### Step 10.3: Test Cron Jobs

```bash
# Trigger a job manually
clawdbot cron trigger pitchrank-patrol
```

---

## Phase 11: Security Hardening

### Step 11.1: Enable FileVault (Disk Encryption)

1. System Settings → Privacy & Security → FileVault
2. Turn On FileVault
3. **Save the recovery key somewhere safe!**

### Step 11.2: Enable Firewall

1. System Settings → Network → Firewall
2. Turn On Firewall
3. Click Options:
   - Block all incoming connections: OFF
   - Enable stealth mode: ON

### Step 11.3: Secure SSH

```bash
# Edit SSH config
sudo nano /etc/ssh/sshd_config

# Add/modify these lines:
PermitRootLogin no
PasswordAuthentication no  # Only if you've set up SSH keys
MaxAuthTries 3
```

Restart SSH:
```bash
sudo launchctl unload /System/Library/LaunchDaemons/ssh.plist
sudo launchctl load /System/Library/LaunchDaemons/ssh.plist
```

### Step 11.4: Set Up Automatic Updates

1. System Settings → General → Software Update
2. Enable automatic updates

---

## Ongoing Maintenance

### Daily (Automated)
- ✅ Scrape requests processed every 15 min
- ✅ Data quality patrol every 4 hours
- ✅ Morning/evening summaries

### Weekly
- Check Telegram for any alerts you missed
- Review the week's activity

### Monthly
```bash
# Update Clawdbot
npm update -g clawdbot
clawdbot gateway restart

# Update PitchRank
cd ~/projects/PitchRank
git pull origin main
source venv/bin/activate
pip install -r requirements.txt

# Update macOS
# System Settings → Software Update
```

### If Something Goes Wrong

```bash
# Check status
clawdbot doctor
clawdbot gateway status

# View logs
tail -100 ~/.clawdbot/logs/gateway.log
tail -100 ~/.clawdbot/logs/cron.log

# Restart everything
clawdbot gateway restart

# If all else fails
clawdbot gateway stop
rm -rf ~/.clawdbot/cache/*
clawdbot gateway start
```

---

## Quick Reference Card

### Important Paths
| What | Path |
|------|------|
| PitchRank code | `~/projects/PitchRank` |
| Environment file | `~/projects/PitchRank/.env.local` |
| Clawdbot config | `~/.clawdbot/clawdbot.json` |
| Skills | `~/.clawdbot/skills/` |
| Logs | `~/.clawdbot/logs/` |

### Essential Commands
| Command | What it does |
|---------|--------------|
| `clawdbot status` | Show system status |
| `clawdbot doctor` | Run diagnostics |
| `clawdbot gateway start/stop/restart` | Control the gateway |
| `clawdbot cron list` | List scheduled jobs |
| `clawdbot channels status` | Check Telegram connection |
| `clawdbot logs` | View recent activity |

### Telegram Commands
| Message | What happens |
|---------|--------------|
| `status` | Get system status |
| `@scraper check requests` | See pending scrapes |
| `@cleaner run patrol` | Check data quality |
| `@coder help` | Get coding help |
| `FIX-AGE` | Approve age fixes |
| `CONFIRM-[action]` | Confirm an action |

---

## You're Done! 🎉

Your Mac Mini is now:
- Running 24/7
- Automatically processing scrape requests
- Monitoring data quality
- Sending you daily briefings
- Waiting for your commands via Telegram

Disconnect the monitor/keyboard/mouse - you can manage everything remotely now!

---

## Support

If you run into issues:
1. Check the logs: `clawdbot logs`
2. Run diagnostics: `clawdbot doctor`
3. Restart gateway: `clawdbot gateway restart`

For PitchRank-specific issues, check:
```bash
cd ~/projects/PitchRank
source venv/bin/activate
python scripts/[relevant_script].py --dry-run
```
