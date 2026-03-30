-- Report card lead capture table
-- Stores email captures from the Free Team Report Card lead magnet
CREATE TABLE IF NOT EXISTS report_card_leads (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  email TEXT NOT NULL,
  team_id UUID NOT NULL,
  team_name TEXT NOT NULL,
  role TEXT,
  source TEXT DEFAULT 'report-card',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_rcl_email ON report_card_leads(email);
CREATE INDEX idx_rcl_team ON report_card_leads(team_id);

ALTER TABLE report_card_leads ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow anonymous inserts" ON report_card_leads
  FOR INSERT TO anon WITH CHECK (true);
