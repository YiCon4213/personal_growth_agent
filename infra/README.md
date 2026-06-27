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
DATABASE_URL=postgresql+psycopg://personal_growth_agent:personal_growth_agent_dev@localhost:5432/personal_growth_agent
```

The first container startup runs `migrations/001_init_pgvector.sql`, which enables `pgvector` and creates the initial tables for threads, messages, profile items, skills, MCP server metadata, RAG document metadata, and vector chunks.

This subtask only establishes the data layer. RAG document ingestion and vector search are intentionally left for the later RAG subtask.
