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

A new empty volume runs migrations `001` through `005` in filename order. Migration `001_init_pgvector.sql`, which enables `pgvector` and creates the initial tables for threads, messages, profile items, skills, MCP server metadata, approvals, RAG document metadata, and vector chunks.

`localhost:5433` is for processes running on the host. In the planned three-service Compose deployment, the backend container must connect through the Compose service address `postgres:5432`.

The initialization SQL only runs automatically for a new empty volume. Existing database volumes require versioned migrations when the schema changes.


## Existing volume upgrade for Phase 2

```powershell
Get-Content infra/migrations/003_phase2_advanced_rag.sql | docker compose -f infra/docker-compose.yml exec -T postgres psql -U personal_growth_agent -d personal_growth_agent
Get-Content infra/migrations/004_dashscope_embedding_1024.sql | docker compose -f infra/docker-compose.yml exec -T postgres psql -U personal_growth_agent -d personal_growth_agent
```

Migration 003 adds embedding provider/model version/dimension and content-hash metadata. Migration 004 clears incompatible vectors and changes pgvector from 1536 to the DashScope `text-embedding-v3` target of 1024 dimensions. Configure DashScope, start the backend, and call `POST /api/v1/rag/documents/rebuild-index` before expecting legacy documents to participate in retrieval.

## Existing volume upgrade for Phase 3

Run infra/migrations/005_phase3_mcp_stdio.sql against the existing personal_growth_agent database before using stdio servers.

Migration 005 adds stdio command, ordered arguments, environment overrides, and optional working directory to MCP server records. Environment values are stored for process launch but are not returned by the MCP server API.
