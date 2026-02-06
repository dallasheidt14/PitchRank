-- Mission Chat Schema for Supabase
-- Run this in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS mission_chat (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  author TEXT NOT NULL, -- 'D H', 'orchestrator', 'codey', 'movy', etc.
  author_type TEXT DEFAULT 'human' CHECK (author_type IN ('human', 'agent')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_mission_chat_created_at ON mission_chat(created_at DESC);

-- Enable realtime
ALTER PUBLICATION supabase_realtime ADD TABLE mission_chat;
