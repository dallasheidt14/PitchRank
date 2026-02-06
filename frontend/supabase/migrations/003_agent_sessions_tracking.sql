-- Agent Sessions Tracking
-- Tracks active agent sessions for live status display

CREATE TABLE IF NOT EXISTS agent_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_key TEXT NOT NULL UNIQUE, -- OpenClaw session ID
  agent_name TEXT NOT NULL,
  task_description TEXT,
  status TEXT DEFAULT 'active' CHECK (status IN ('active', 'completed', 'error')),
  started_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  result TEXT, -- Success message or error details
  
  -- Indexes for fast lookups
  CONSTRAINT unique_active_session UNIQUE NULLS NOT DISTINCT (agent_name, session_key)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent_name ON agent_sessions(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_started_at ON agent_sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_active ON agent_sessions(agent_name, status) WHERE status = 'active';

-- Auto-update updated_at timestamp
CREATE TRIGGER update_agent_sessions_updated_at
    BEFORE UPDATE ON agent_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- View for active sessions (last 5 minutes)
CREATE OR REPLACE VIEW active_agent_sessions AS
SELECT 
  agent_name,
  session_key,
  task_description,
  started_at,
  updated_at,
  EXTRACT(EPOCH FROM (NOW() - started_at))::INTEGER AS duration_seconds
FROM agent_sessions
WHERE 
  status = 'active' 
  AND started_at > NOW() - INTERVAL '5 minutes'
ORDER BY started_at DESC;

-- Function to get agent status
CREATE OR REPLACE FUNCTION get_agent_status(p_agent_name TEXT)
RETURNS TABLE (
  is_active BOOLEAN,
  current_task TEXT,
  started_at TIMESTAMPTZ,
  duration_seconds INTEGER
) AS $$
BEGIN
  RETURN QUERY
  SELECT 
    TRUE as is_active,
    task_description,
    started_at,
    EXTRACT(EPOCH FROM (NOW() - started_at))::INTEGER
  FROM active_agent_sessions
  WHERE agent_name = p_agent_name
  LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Clean up old completed/error sessions (keep last 24h only)
CREATE OR REPLACE FUNCTION cleanup_old_sessions()
RETURNS void AS $$
BEGIN
  DELETE FROM agent_sessions
  WHERE status IN ('completed', 'error')
    AND completed_at < NOW() - INTERVAL '24 hours';
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE agent_sessions IS 'Tracks active and recent agent sessions for live status display in Mission Control';
COMMENT ON VIEW active_agent_sessions IS 'Shows agents that have been active in the last 5 minutes';
COMMENT ON FUNCTION get_agent_status IS 'Quick lookup for agent current status and task';
