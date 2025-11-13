-- Create table for tracking user-initiated scrape requests
-- This table stores requests from users to fetch missing game data

CREATE TABLE IF NOT EXISTS scrape_requests (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  team_id_master UUID REFERENCES teams(team_id_master),
  team_name TEXT,
  provider_id UUID,
  provider_team_id TEXT,
  game_date DATE NOT NULL,
  status TEXT DEFAULT 'pending',
  request_type TEXT DEFAULT 'missing_game',
  requested_at TIMESTAMPTZ DEFAULT NOW(),
  processed_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  error_message TEXT,
  games_found INTEGER
);

-- Add indexes for efficient querying
CREATE INDEX idx_scrape_requests_status ON scrape_requests(status);
CREATE INDEX idx_scrape_requests_pending ON scrape_requests(status) WHERE status = 'pending';

-- Enable Row Level Security (RLS) on scrape_requests table
ALTER TABLE scrape_requests ENABLE ROW LEVEL SECURITY;

-- Allow anyone to insert (for user submissions)
CREATE POLICY "Enable insert for all users" ON scrape_requests
  FOR INSERT WITH CHECK (true);

-- Only service role can update (for Python processor)
CREATE POLICY "Service role update" ON scrape_requests
  FOR UPDATE USING (auth.role() = 'service_role');

-- Allow read access for all users (adjust based on requirements)
CREATE POLICY "Enable read for authenticated users" ON scrape_requests
  FOR SELECT USING (true);

