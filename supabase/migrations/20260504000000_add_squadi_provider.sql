-- Add SQUADI as a registered provider so enhanced_pipeline._ensure_initialized()
-- can resolve provider_id by code lookup. Idempotent via ON CONFLICT.

INSERT INTO providers (code, name, base_url)
VALUES ('squadi', 'Squadi', 'https://api.us.squadi.com')
ON CONFLICT (code) DO NOTHING;
