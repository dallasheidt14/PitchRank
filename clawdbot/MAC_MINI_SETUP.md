# Mac Mini Setup Guide for PitchRank + Clawdbot

Complete guide to setting up your dedicated Mac Mini as a 24/7 PitchRank automation server.

## Prerequisites

- Mac Mini (M1/M2/M3 recommended, Intel works too)
- macOS Sonoma or later
- Stable internet connection
- Your Supabase credentials
- Your preferred messaging platform (Telegram recommended)

## Step 1: Initial Mac Setup

### 1.1 System Preferences

```bash
# Prevent sleep (keep running 24/7)
sudo pmset -a sleep 0
sudo pmset -a disksleep 0
sudo pmset -a displaysleep 0

# Enable automatic login (optional but recommended for unattended operation)
# System Preferences > Users & Groups > Login Options > Automatic login

# Enable SSH for remote access
sudo systemsetup -setremotelogin on
```

### 1.2 Install Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Add to PATH (for Apple Silicon)
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

### 1.3 Install Required Tools

```bash
# Install Node.js (required for Clawdbot)
brew install node@22

# Install Python (for PitchRank scripts)
brew install python@3.11

# Install Git
brew install git

# Install useful utilities
brew install jq htop
```

## Step 2: Install Clawdbot

```bash
# Install Clawdbot globally
npm install -g clawdbot@latest

# Run the onboarding wizard
clawdbot onboard --install-daemon

# This will:
# - Create ~/.clawdbot/ directory
# - Set up the gateway daemon
# - Configure launchd for auto-start
```

## Step 3: Clone PitchRank

```bash
# Create workspace directory
mkdir -p ~/projects
cd ~/projects

# Clone PitchRank repository
git clone https://github.com/dallasheidt14/PitchRank.git
cd PitchRank

# Install Python dependencies
pip3 install -r requirements.txt

# Install Node dependencies (for frontend API if needed)
cd frontend && npm install && cd ..
```

## Step 4: Configure Environment

### 4.1 Create Environment File

```bash
# Copy example env file
cp .env.example .env.local

# Edit with your credentials
nano .env.local
```

Add these variables:
```env
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...your-service-role-key

# Clawdbot
CLAWDBOT_MODE=safe_writer
CLAWDBOT_ALERT_WEBHOOK=https://your-webhook-url

# GitHub (for triggering workflows)
GITHUB_TOKEN=ghp_...your-token
```

### 4.2 Configure Clawdbot

```bash
# Create Clawdbot config
mkdir -p ~/.clawdbot
cat > ~/.clawdbot/clawdbot.json << 'EOF'
{
  "agent": {
    "model": "anthropic/claude-sonnet-4",
    "fallback": "anthropic/claude-haiku-3"
  },
  "workspace": "~/projects/PitchRank",
  "channels": {
    "telegram": {
      "botToken": "YOUR_TELEGRAM_BOT_TOKEN"
    }
  },
  "cron": {
    "enabled": true,
    "timezone": "America/Denver"
  }
}
EOF
```

## Step 5: Set Up Telegram Bot (Recommended)

### 5.1 Create Telegram Bot

1. Open Telegram and message @BotFather
2. Send `/newbot`
3. Name it "PitchRank Agent" (or your preference)
4. Copy the bot token

### 5.2 Connect to Clawdbot

```bash
# Add Telegram channel
clawdbot channels add telegram --token YOUR_BOT_TOKEN

# Verify connection
clawdbot channels status
```

### 5.3 Start a Chat

1. Find your bot in Telegram
2. Send `/start`
3. The bot will ask for a pairing code
4. Approve the pairing: `clawdbot pairing approve telegram CODE`

## Step 6: Install PitchRank Skills

```bash
# Create skills directory
mkdir -p ~/clawd/skills/pitchrank

# Copy skill files from repo
cp ~/projects/PitchRank/clawdbot/SKILL.md ~/clawd/skills/pitchrank/
cp ~/projects/PitchRank/clawdbot/agents/*.md ~/clawd/skills/pitchrank/

# Create shared memory files
touch ~/clawd/pitchrank/status.md
touch ~/clawd/pitchrank/decisions.md
```

## Step 7: Configure Cron Jobs

```bash
# Make the config script executable
chmod +x ~/projects/PitchRank/clawdbot/cron-config.sh

# Run it to set up all scheduled tasks
~/projects/PitchRank/clawdbot/cron-config.sh

# Verify jobs are configured
clawdbot cron list
```

## Step 8: Start the System

```bash
# Start Clawdbot gateway (runs as daemon)
clawdbot gateway start

# Verify it's running
clawdbot doctor

# Check agent status
clawdbot status
```

## Step 9: Test the Setup

### 9.1 Test via Telegram

Send these messages to your bot:

```
status
```
Should return system status.

```
@hunter check pending requests
```
Should show pending scrape requests.

```
@doc run patrol
```
Should run data quality checks.

### 9.2 Test Scripts Directly

```bash
cd ~/projects/PitchRank

# Test data quality check
python clawdbot/check_data_quality.py --alert

# Test missing games processor (dry run)
python scripts/process_missing_games.py --dry-run --limit 3
```

## Step 10: Set Up Auto-Start

Clawdbot already configures launchd, but verify:

```bash
# Check if daemon is configured
launchctl list | grep clawdbot

# If not, manually load
launchctl load ~/Library/LaunchAgents/com.clawdbot.gateway.plist
```

## Monitoring & Maintenance

### View Logs

```bash
# Clawdbot logs
tail -f ~/.clawdbot/logs/gateway.log

# Cron job logs
tail -f ~/.clawdbot/logs/cron.log
```

### Check Status

```bash
# System health
clawdbot doctor

# Gateway status
clawdbot gateway status

# Cron jobs
clawdbot cron list
```

### Update Clawdbot

```bash
# Update to latest version
npm update -g clawdbot

# Restart gateway
clawdbot gateway restart
```

### Update PitchRank

```bash
cd ~/projects/PitchRank
git pull origin main
pip3 install -r requirements.txt
```

## Troubleshooting

### Clawdbot Not Starting

```bash
# Check for port conflicts
lsof -i :18789

# Restart gateway
clawdbot gateway stop
clawdbot gateway start
```

### Scripts Failing

```bash
# Check Python environment
which python3
python3 --version

# Verify Supabase connection
python3 -c "from supabase import create_client; import os; c = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_KEY')); print('Connected!')"
```

### Telegram Not Responding

```bash
# Check channel status
clawdbot channels status

# Re-authenticate
clawdbot channels login telegram
```

## Security Recommendations

1. **Enable FileVault** - Encrypt your disk
2. **Use a firewall** - Only allow necessary ports
3. **Keep secrets in .env.local** - Never commit credentials
4. **Enable 2FA on GitHub** - Protect your repository
5. **Use SSH keys** - For GitHub and remote access
6. **Regular updates** - Keep macOS and tools updated

## Quick Reference

| Command | Description |
|---------|-------------|
| `clawdbot status` | Show system status |
| `clawdbot gateway start` | Start the gateway |
| `clawdbot gateway stop` | Stop the gateway |
| `clawdbot cron list` | List scheduled jobs |
| `clawdbot doctor` | Run diagnostics |
| `clawdbot logs` | View recent logs |

## Daily Operation

Once set up, your Mac Mini will:

1. **6:00 AM** - Scout sends morning briefing
2. **Every 15 min** - Hunter processes scrape requests
3. **Every 4 hours** - Doc runs data quality patrol
4. **6:00 PM** - Scout sends evening summary
5. **Monday 9:30 AM** - Ranker checks if rankings need update

You interact via Telegram:
- Ask for status updates
- Approve data fixes
- Trigger manual operations
- Get alerts about issues

The system runs 24/7 while you focus on other things!
