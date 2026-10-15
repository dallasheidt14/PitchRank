-- EnhancedETLPipeline raises ValueError when this row is absent. One provider covers every
-- tournament's subdomain (wfc., buckeyecup., ...): team ids are one platform-wide sequence, so a
-- team id never needs its subdomain to be unique.
INSERT INTO providers (code, name, base_url)
VALUES ('tourneycentral', 'Tourney Central', 'https://tourneycentral.com')
ON CONFLICT (code) DO NOTHING;
