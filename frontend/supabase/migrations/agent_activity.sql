-- Agent Activity Table for Agent Communications Feed
-- Replaces local file reading with database storage for production compatibility

CREATE TABLE IF NOT EXISTS agent_activity (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_key TEXT,
  agent_name TEXT NOT NULL,
  agent_emoji TEXT DEFAULT '🤖',
  message_preview TEXT NOT NULL,
  full_message TEXT,
  message_type TEXT DEFAULT 'message', -- 'message', 'tool_call', 'spawn', 'complete', 'error'
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast reverse-chronological queries
CREATE INDEX IF NOT EXISTS idx_agent_activity_created_at ON agent_activity(created_at DESC);

-- Enable realtime for live updates in the UI
ALTER PUBLICATION supabase_realtime ADD TABLE agent_activity;

-- Add RLS policies (allow all for now, can be restricted later)
ALTER TABLE agent_activity ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all operations on agent_activity" ON agent_activity
  FOR ALL
  USING (true)
  WITH CHECK (true);
