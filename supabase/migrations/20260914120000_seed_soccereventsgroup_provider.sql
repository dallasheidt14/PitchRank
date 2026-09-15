-- scripts/import_soccereventsgroup_event.py exits before matching a team, dry run included,
-- and EnhancedETLPipeline raises ValueError, when this row is absent.
INSERT INTO providers (code, name, base_url)
VALUES ('soccereventsgroup', 'Soccer Events Group', 'https://www.soccereventsgroup.com')
ON CONFLICT (code) DO NOTHING;
