# Agent Communications Migration to Supabase

## Summary
Successfully migrated the Agent Communications feed from local file reading to Supabase database storage for production compatibility.

## Changes Made

### 1. Created Supabase Table
- **File:** `supabase/migrations/agent_activity.sql`
- Created `agent_activity` table with realtime enabled
- Added index for fast reverse-chronological queries
- Enabled RLS with permissive policy

### 2. Updated API Routes

#### `/api/agent-activity/route.ts`
- **Before:** Read JSONL files from `~/.openclaw/agents/main/sessions/`
- **After:** Query Supabase `agent_activity` table
- Added POST endpoint to accept new activity logs
- Removed file system dependencies (works on Vercel)

#### `/api/agent-webhook/route.ts`
- Added agent emoji mapping helper
- Insert to `agent_activity` on spawn events
- Insert to `agent_activity` on complete events
- Insert to `agent_activity` on error events
- All inserts include proper emoji, message preview, and full message

### 3. Updated Frontend Component

#### `components/agent-comms-feed.tsx`
- **Before:** Poll API every 30 seconds
- **After:** Subscribe to Supabase Realtime for instant updates
- Removed polling interval
- Added realtime subscription with proper cleanup
- New messages appear instantly without refresh

## Testing Checklist
- [ ] Run SQL migration in Supabase dashboard
- [ ] Verify table exists with correct schema
- [ ] Test agent spawn webhook → check agent_activity table
- [ ] Test agent complete webhook → check agent_activity table
- [ ] Test Agent Comms feed loads existing messages
- [ ] Test realtime updates appear instantly
- [ ] Deploy to Vercel and verify no file system errors

## Deployment Steps
1. Copy SQL from `supabase/migrations/agent_activity.sql`
2. Run in Supabase SQL Editor
3. Push to production: `git push origin main`
4. Vercel will auto-deploy
5. Test Agent Communications feed on production

## Commit
✅ Committed: `ba25430` - "feat: Store agent activity in Supabase for production"
