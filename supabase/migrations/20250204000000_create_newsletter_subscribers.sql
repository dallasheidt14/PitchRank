-- Create newsletter_subscribers table
CREATE TABLE IF NOT EXISTS newsletter_subscribers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL UNIQUE,
  subscribed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  source TEXT NOT NULL DEFAULT 'blog',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add index on email for fast lookups
CREATE INDEX IF NOT EXISTS idx_newsletter_subscribers_email ON newsletter_subscribers(email);

-- Add index on subscribed_at for sorting
CREATE INDEX IF NOT EXISTS idx_newsletter_subscribers_subscribed_at ON newsletter_subscribers(subscribed_at DESC);

-- Enable Row Level Security
ALTER TABLE newsletter_subscribers ENABLE ROW LEVEL SECURITY;

-- Create policy to allow inserts (anyone can subscribe)
CREATE POLICY "Allow public inserts" ON newsletter_subscribers
  FOR INSERT
  TO anon, authenticated
  WITH CHECK (true);

-- Create policy to allow authenticated users to read (for admin purposes)
CREATE POLICY "Allow authenticated reads" ON newsletter_subscribers
  FOR SELECT
  TO authenticated
  USING (true);

-- Add comment for documentation
COMMENT ON TABLE newsletter_subscribers IS 'Stores newsletter subscriber emails from various sources (blog, landing page, etc.)';
