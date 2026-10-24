#!/bin/sh
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE steel_mcp LOGIN PASSWORD '${MCP_DB_PASSWORD}';
GRANT CONNECT ON DATABASE steel_market TO steel_mcp;
GRANT USAGE ON SCHEMA public TO steel_mcp;
ALTER DEFAULT PRIVILEGES FOR ROLE steel_agent IN SCHEMA public GRANT SELECT ON TABLES TO steel_mcp;
SQL
