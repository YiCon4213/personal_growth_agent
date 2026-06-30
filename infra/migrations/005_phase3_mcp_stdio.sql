-- Phase 3: standards-compliant MCP stdio configuration.
-- Safe for existing PostgreSQL volumes; all new fields are nullable or have JSON defaults.

ALTER TABLE mcp_servers
  ADD COLUMN IF NOT EXISTS command varchar(260),
  ADD COLUMN IF NOT EXISTS args jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS env jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS working_directory text;

COMMENT ON COLUMN mcp_servers.command IS
  'Executable for official MCP stdio transport; validated against the application allowlist.';
COMMENT ON COLUMN mcp_servers.args IS
  'Ordered stdio server arguments.';
COMMENT ON COLUMN mcp_servers.env IS
  'Explicit stdio environment overrides; values are never returned by the API.';
COMMENT ON COLUMN mcp_servers.working_directory IS
  'Optional stdio server working directory.';
