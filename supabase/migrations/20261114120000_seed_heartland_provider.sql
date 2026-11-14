-- EnhancedETLPipeline raises ValueError when this row is absent. One provider covers every
-- season of the Heartland Soccer Association's Premier league (heartlandsoccer.net).
INSERT INTO providers (code, name, base_url)
VALUES ('heartland', 'Heartland Soccer', 'https://heartlandsoccer.net')
ON CONFLICT (code) DO NOTHING;
