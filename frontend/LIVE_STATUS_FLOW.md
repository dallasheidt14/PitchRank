# 🔴 Live Agent Status - Visual Flow

## Before (Static Status) ❌

```
Agent spawns → Does work → Finishes
                  ↓
           WORKING-agent.md 
          (rarely updated)
                  ↓
         Mission Control reads
                  ↓
          Shows "idle" 😞
```

**Problem:** Mission Control has no idea agents are running!

---

## After (Live Status) ✅

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent Lifecycle                           │
└─────────────────────────────────────────────────────────────┘

1. SPAWN
   ┌────────────┐
   │ OpenClaw   │ spawns agent (Codey, Movy, etc.)
   │  Agent     │
   └──────┬─────┘
          │
          ↓ POST /api/agent-webhook
   ┌──────────────────────────────────────┐
   │ action: "spawn"                      │
   │ sessionKey: "abc-123-xyz"            │
   │ agentName: "codey"                   │
   │ task: "Fix Mission Control bugs"    │
   └──────┬───────────────────────────────┘
          │
          ↓ Creates record
   ┌──────────────────────────────────────┐
   │      agent_sessions table            │
   │  --------------------------------    │
   │  session_key: abc-123-xyz            │
   │  agent_name: codey                   │
   │  task: Fix Mission Control bugs      │
   │  status: active ← 🔴                 │
   │  started_at: NOW()                   │
   └──────────────────────────────────────┘


2. MISSION CONTROL CHECKS (every 30s)
   ┌────────────────────┐
   │  Browser requests  │
   │ /mission-control   │
   └─────────┬──────────┘
             │
             ↓ GET /api/mission-control/status
   ┌──────────────────────────────────────┐
   │  Query: SELECT * FROM agent_sessions │
   │  WHERE status = 'active'             │
   │    AND started_at > NOW() - 5min     │
   └─────────┬────────────────────────────┘
             │
             ↓ Found codey session!
   ┌──────────────────────────────────────┐
   │  Agent Card shows:                   │
   │  ┌────────────────────────────────┐  │
   │  │ 💻 Codey                       │  │
   │  │ Engineering                    │  │
   │  │                                │  │
   │  │ 🟢 Active                      │  │
   │  │ Running: Fix Mission Control   │  │
   │  │          bugs                  │  │
   │  └────────────────────────────────┘  │
   └──────────────────────────────────────┘


3. PROGRESS UPDATE (optional)
   ┌────────────┐
   │   Agent    │ sends progress
   └──────┬─────┘
          │
          ↓ POST /api/agent-webhook
   ┌──────────────────────────────────────┐
   │ action: "progress"                   │
   │ sessionKey: "abc-123-xyz"            │
   │ agentName: "codey"                   │
   │ result: "Fixed bug #1, working on #2"│
   └──────┬───────────────────────────────┘
          │
          ↓ Updates record
   ┌──────────────────────────────────────┐
   │      agent_sessions table            │
   │  --------------------------------    │
   │  session_key: abc-123-xyz            │
   │  agent_name: codey                   │
   │  task: Fixed bug #1, working on #2   │
   │  status: active ← Still 🔴           │
   │  updated_at: NOW() ← Refreshed!      │
   └──────────────────────────────────────┘


4. COMPLETE
   ┌────────────┐
   │   Agent    │ finishes work
   └──────┬─────┘
          │
          ↓ POST /api/agent-webhook
   ┌──────────────────────────────────────┐
   │ action: "complete"                   │
   │ sessionKey: "abc-123-xyz"            │
   │ agentName: "codey"                   │
   │ result: "All bugs fixed! 🎉"         │
   └──────┬───────────────────────────────┘
          │
          ↓ Updates record
   ┌──────────────────────────────────────┐
   │      agent_sessions table            │
   │  --------------------------------    │
   │  session_key: abc-123-xyz            │
   │  agent_name: codey                   │
   │  task: All bugs fixed! 🎉            │
   │  status: completed ← ✅              │
   │  completed_at: NOW()                 │
   │  result: All bugs fixed! 🎉          │
   └──────────────────────────────────────┘


5. MISSION CONTROL UPDATES (next 30s check)
   ┌────────────────────┐
   │  Browser requests  │
   │ /mission-control   │
   └─────────┬──────────┘
             │
             ↓ GET /api/mission-control/status
   ┌──────────────────────────────────────┐
   │  Query: SELECT * FROM agent_sessions │
   │  WHERE status = 'active'             │
   │    AND started_at > NOW() - 5min     │
   └─────────┬────────────────────────────┘
             │
             ↓ No active session found!
   ┌──────────────────────────────────────┐
   │  Falls back to WORKING file          │
   │                                      │
   │  Agent Card shows:                   │
   │  ┌────────────────────────────────┐  │
   │  │ 💻 Codey                       │  │
   │  │ Engineering                    │  │
   │  │                                │  │
   │  │ ⚪ Idle                        │  │
   │  │ On-demand                      │  │
   │  └────────────────────────────────┘  │
   └──────────────────────────────────────┘
```

---

## Key Points

### 5-Minute Active Window
- Sessions are "active" if started within last 5 minutes
- Progress updates refresh the `updated_at` timestamp
- Long-running tasks stay active as long as they send progress

### Graceful Degradation
- If database query fails → falls back to WORKING files
- If no active session found → shows WORKING file status
- Never breaks Mission Control!

### Real-Time Updates
- Mission Control refreshes every 30 seconds
- Shows latest status from database
- No manual updates needed

---

## Example Timeline

```
00:00  Agent spawns → Creates session → Status: ACTIVE 🔴
00:30  Mission Control checks → Finds session → Shows ACTIVE
01:00  Mission Control checks → Still active → Shows ACTIVE
01:30  Agent progress update → Refreshes timestamp → Still ACTIVE
02:00  Mission Control checks → Still active → Shows ACTIVE
02:15  Agent completes → Marks completed → Status: COMPLETED ✅
02:30  Mission Control checks → No active session → Shows IDLE ⚪
```

---

## Database View (active_agent_sessions)

```sql
-- Automatically filters to last 5 minutes
SELECT 
  agent_name,
  task_description,
  started_at,
  EXTRACT(EPOCH FROM (NOW() - started_at))::INTEGER AS duration_seconds
FROM agent_sessions
WHERE 
  status = 'active' 
  AND started_at > NOW() - INTERVAL '5 minutes'
ORDER BY started_at DESC;

-- Example result:
 agent_name |        task_description         | started_at | duration_seconds
------------+---------------------------------+------------+------------------
 codey      | Fix Mission Control bugs        | 14:23:10   | 127
 movy       | Generate weekly movers report   | 14:21:45   | 212
```

---

## API Endpoints Used

### POST /api/agent-webhook
- `spawn` - Create session
- `progress` - Update session
- `complete` - Mark done
- `error` - Mark failed

### GET /api/mission-control/status
- Queries `agent_sessions` for active sessions
- Maps to agent configs
- Falls back to WORKING files
- Returns full dashboard data

---

## Benefits

✅ **Real-time visibility** - See agents working live  
✅ **No manual updates** - Agents don't touch WORKING files  
✅ **Historical tracking** - See what agents did recently  
✅ **Task correlation** - Link sessions to task board  
✅ **Auto-cleanup** - Old sessions purged after 24h  
✅ **Graceful fallback** - Works even if DB is down  

---

## Future Ideas

- **Duration display:** "Active for 3m 42s"
- **Progress bars:** Visual indicator for long tasks
- **Session history:** Click card to see recent runs
- **Stuck detection:** Alert if active > 30 min
- **Realtime sync:** Supabase Realtime for instant updates

---

**Status is now LIVE! No more fake "idle"! 🔴**
