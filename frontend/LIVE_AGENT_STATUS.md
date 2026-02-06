# 🔴 Live Agent Status - Implementation

## Problem Fixed

Agent Cards in Mission Control showed static "idle" status even when agents were actively running. Status was hardcoded from WORKING files that agents rarely updated.

## Solution

**Track active sessions in real-time using the database!**

When an agent spawns via OpenClaw, the agent-webhook creates a session record. Mission Control checks the database for sessions active in the last 5 minutes.

---

## Architecture

### 1. Database Table: `agent_sessions`

Tracks every agent session with:
- `session_key` - OpenClaw session ID (unique)
- `agent_name` - Which agent (codey, movy, etc.)
- `task_description` - What the agent is working on
- `status` - active | completed | error
- `started_at` - When the session began
- `updated_at` - Last activity timestamp
- `completed_at` - When it finished (null if active)

**View:** `active_agent_sessions`
- Shows agents active in the last 5 minutes
- Used by Mission Control status endpoint

**Function:** `get_agent_status(agent_name)`
- Quick lookup for a single agent's status

### 2. Agent Webhook Updates

`/app/api/agent-webhook/route.ts` now tracks sessions:

**On `spawn` action:**
- Creates `agent_sessions` record with status='active'
- Logs: `[AgentWebhook] Created session record for {agent}`

**On `progress` action:**
- Updates `updated_at` timestamp (keeps session "active")
- Updates `task_description` with latest progress

**On `complete` action:**
- Sets status='completed', completed_at=NOW()
- Stores result message

**On `error` action:**
- Sets status='error', completed_at=NOW()
- Stores error message

### 3. Mission Control Status Endpoint

`/app/api/mission-control/status/route.ts` now:

1. **Queries database** for active sessions (last 5 minutes)
2. **Creates a map** of agent_name → session data
3. For each agent:
   - ✅ **LIVE status**: Check database first
     - If session found → status='active'
     - Else → fall back to WORKING file
   - ✅ **LIVE task**: Show task from database if active
     - If session found → currentTask from database
     - Else → fall back to WORKING file

**Result:** Agent cards reflect REAL activity!

---

## How It Works (Flow)

### When an Agent Starts

1. **OpenClaw spawns agent** (e.g., Codey)
2. **Agent (or orchestrator) calls webhook:**
   ```bash
   curl -X POST /api/agent-webhook \
     -H "Content-Type: application/json" \
     -d '{
       "action": "spawn",
       "sessionKey": "abc-123-xyz",
       "agentName": "codey",
       "task": "Fix Mission Control bugs"
     }'
   ```
3. **Webhook creates database record:**
   ```sql
   INSERT INTO agent_sessions (
     session_key, agent_name, task_description, status
   ) VALUES (
     'abc-123-xyz', 'codey', 'Fix Mission Control bugs', 'active'
   );
   ```
4. **Mission Control refreshes** (every 30s)
5. **Status endpoint queries:**
   ```sql
   SELECT * FROM agent_sessions 
   WHERE status = 'active' 
     AND started_at > NOW() - INTERVAL '5 minutes';
   ```
6. **Finds Codey's session** → Shows "Active" with task!

### When Agent Reports Progress

```bash
curl -X POST /api/agent-webhook \
  -d '{"action": "progress", "sessionKey": "abc-123-xyz", ...}'
```
- Updates `updated_at` timestamp
- Keeps session in "active" window

### When Agent Finishes

```bash
curl -X POST /api/agent-webhook \
  -d '{"action": "complete", "sessionKey": "abc-123-xyz", "result": "All bugs fixed!"}'
```
- Sets status='completed', completed_at=NOW()
- Next status check won't show as active
- Card returns to "idle" (or WORKING file status)

---

## Database Schema

```sql
-- Migration: 003_agent_sessions_tracking.sql

CREATE TABLE agent_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_key TEXT NOT NULL UNIQUE,
  agent_name TEXT NOT NULL,
  task_description TEXT,
  status TEXT DEFAULT 'active' 
    CHECK (status IN ('active', 'completed', 'error')),
  started_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  result TEXT
);

-- View: active sessions (last 5 min)
CREATE VIEW active_agent_sessions AS
SELECT 
  agent_name,
  session_key,
  task_description,
  started_at,
  EXTRACT(EPOCH FROM (NOW() - started_at))::INTEGER AS duration_seconds
FROM agent_sessions
WHERE 
  status = 'active' 
  AND started_at > NOW() - INTERVAL '5 minutes';

-- Function: get single agent status
CREATE FUNCTION get_agent_status(p_agent_name TEXT)
RETURNS TABLE (
  is_active BOOLEAN,
  current_task TEXT,
  started_at TIMESTAMPTZ,
  duration_seconds INTEGER
);
```

---

## Testing

### 1. Manual Test via Webhook

```bash
# Start agent session
curl -X POST http://localhost:3000/api/agent-webhook \
  -H "Content-Type: application/json" \
  -d '{
    "action": "spawn",
    "sessionKey": "test-session-123",
    "agentName": "codey",
    "task": "Testing live status feature"
  }'

# Check Mission Control - should show Codey as "Active"
curl http://localhost:3000/api/mission-control/status | jq '.agents[] | select(.id=="codey")'

# Should see:
# "status": "active",
# "currentTask": "Testing live status feature"

# Complete the session
curl -X POST http://localhost:3000/api/agent-webhook \
  -H "Content-Type: application/json" \
  -d '{
    "action": "complete",
    "sessionKey": "test-session-123",
    "agentName": "codey",
    "task": "Testing complete",
    "result": "Test successful!"
  }'

# Check again - should show Codey as "Idle"
curl http://localhost:3000/api/mission-control/status | jq '.agents[] | select(.id=="codey")'
```

### 2. Check Database Directly

```sql
-- See all active sessions
SELECT * FROM active_agent_sessions;

-- Get Codey's status
SELECT * FROM get_agent_status('codey');

-- See all sessions (last 24h)
SELECT agent_name, status, task_description, started_at 
FROM agent_sessions 
WHERE started_at > NOW() - INTERVAL '24 hours'
ORDER BY started_at DESC;
```

### 3. Watch Live in Mission Control

1. Open Mission Control in browser
2. Open console (check for logs)
3. Trigger a test webhook spawn
4. Watch the agent card update from "idle" to "active"
5. Complete the webhook
6. Watch it return to "idle"

---

## Logs to Watch

### Agent Webhook
```
[AgentWebhook] spawn - codey (abc-123-x)
[AgentWebhook] Created session record for codey
[AgentWebhook] Updated progress for codey
[AgentWebhook] Marked session abc-123-x as completed
```

### Mission Control Status
```
[MissionControl] Found 2 active agent sessions
[MissionControl] Error fetching active sessions: <error>
```

---

## Benefits

✅ **Real-time status** - See agents working as it happens  
✅ **No manual updates** - Agents don't need to update WORKING files  
✅ **Historical tracking** - Can see what agents did recently  
✅ **Auto-cleanup** - Old sessions purged after 24h  
✅ **Fallback graceful** - Still works if database is down (uses WORKING files)  
✅ **Session correlation** - Can link status to tasks in task board  

---

## Future Enhancements

- **Duration display** - Show "Active for 3m 42s"
- **Progress bar** - Visual indicator of long-running tasks
- **Session history** - Click agent card to see recent sessions
- **Alerts** - Notify if agent stuck (active > 30 min)
- **Realtime updates** - Supabase Realtime subscription for instant updates

---

## Migration Required

⚠️ **Run this in Supabase SQL Editor:**

```
File: supabase/migrations/003_agent_sessions_tracking.sql
```

Creates:
- `agent_sessions` table
- `active_agent_sessions` view
- `get_agent_status()` function
- Auto-update trigger for `updated_at`
- Cleanup function for old sessions

---

## Files Modified

1. **`app/api/agent-webhook/route.ts`**
   - Added session creation on spawn
   - Added session updates on progress
   - Added session completion on complete/error
   - Added logging throughout

2. **`app/api/mission-control/status/route.ts`**
   - Added database query for active sessions
   - Added activeSessionMap logic
   - Changed status logic to check database first
   - Added logging

3. **`supabase/migrations/003_agent_sessions_tracking.sql`**
   - New migration file

---

**Status is now LIVE! 🔴**

Agents show as "Active" when they're actually running, with the real task they're working on. No more fake static status!
