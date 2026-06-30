# Docker Compose Operations

The Compose stack has three long-running services (`frontend`, `backend`, and `postgres`) plus a one-shot `migrate` job. Run commands from the repository root.

## One-command startup

1. Copy `backend/.env.example` to the uncommitted `backend/.env`.
2. Add provider credentials only to `backend/.env`. Keep `EMBEDDING_DIMENSION=1024`.
3. If the official npm registry is unreachable, set `NPM_REGISTRY` to an approved reachable mirror in the shell or uncommitted `infra/.env`.
4. Start and wait for the healthy stack:

```powershell
docker compose -f infra/docker-compose.yml up --build -d --wait
```

Open the frontend at `http://localhost:3000`. The backend health endpoint is `http://localhost:8000/api/v1/health`; PostgreSQL is exposed to host development on `localhost:5433`.

The frontend image bakes the internal rewrite target `http://backend:8000`. The backend container uses:

```text
postgresql+psycopg://personal_growth_agent:...@postgres:5432/personal_growth_agent
```

Compose defaults are suitable only for local development. Override ports and the database password through an uncommitted `infra/.env` based on `infra/.env.example`. If the password contains URL-reserved characters, provide a correctly percent-encoded `DATABASE_URL` customization before public deployment.

## Migration behavior

The `migrate` job runs after PostgreSQL is healthy and must finish before the backend starts. It:

- discovers numbered SQL files in `infra/migrations/`;
- serializes runners with a PostgreSQL advisory lock;
- records name and SHA-256 checksum in `schema_migrations`;
- refuses changed files that were already recorded;
- fingerprints legacy schemas so an existing compatible volume is baselined without destructively replaying migration 004.

New and existing volumes therefore use the same migration path. Do not edit an applied migration; add the next numbered file.

To inspect migration logs:

```powershell
docker compose -f infra/docker-compose.yml logs migrate
```

`docker compose down` keeps the named database volume. Do not add `--volumes` unless permanent data deletion is intentional.

## Database-only host development

```powershell
docker compose -f infra/docker-compose.yml up -d postgres --wait
```

Host processes continue to use:

```text
DATABASE_URL=postgresql+psycopg://personal_growth_agent:personal_growth_agent_dev@localhost:5433/personal_growth_agent
```

## Current live verification

On 2026-06-28, Phase 4 full-stack acceptance completed successfully:

- migrations 002 through 006 ran against a live pgvector PostgreSQL volume, migration 001 was safely baselined, rerun was idempotent, `rag_chunks.embedding` was `vector(1024)`, and migration records survived a PostgreSQL restart;
- backend and frontend images built successfully after registry connectivity was restored;
- frontend, backend, and PostgreSQL reported healthy, and the migration job confirmed migrations 001 through 006 were already applied;
- `http://localhost:3000` returned HTTP 200 and `http://localhost:8000/api/v1/health` returned `status=ok` with `environment=production`;
- browser use was confirmed by the user.

Credentialed DashScope/index-rebuild acceptance and remote Streamable HTTP remain separate pending items. Public deployment hardening belongs to Phase 5.