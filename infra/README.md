# Infra Boundary

Infrastructure files for the new project live here.

## Local Postgres + pgvector

Start the database from this directory:

```powershell
cd personal_growth_agent/infra
docker compose up -d
```

Use this backend environment value:

```text
DATABASE_URL=postgresql+psycopg://personal_growth_agent:personal_growth_agent_dev@localhost:5433/personal_growth_agent
```

The first container startup runs `migrations/001_init_pgvector.sql`, which enables `pgvector` and creates the initial tables for threads, messages, profile items, skills, MCP server metadata, approvals, RAG document metadata, and vector chunks.

`localhost:5433` is for processes running on the host. In the planned three-service Compose deployment, the backend container must connect through the Compose service address `postgres:5432`.

The initialization SQL only runs automatically for a new empty volume. Existing database volumes require versioned migrations when the schema changes.
