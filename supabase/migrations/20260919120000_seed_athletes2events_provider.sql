-- EnhancedETLPipeline raises ValueError when this row is absent. One provider covers every
-- host club's subdomain (crossfire., somsports., ...): event and team ids are one platform-wide
-- sequence, so a team id never needs its subdomain to be unique.
INSERT INTO providers (code, name, base_url)
VALUES ('athletes2events', 'Athletes2Events', 'https://athletes2events.com')
ON CONFLICT (code) DO NOTHING;
