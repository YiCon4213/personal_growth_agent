# Development Boundaries

## Repository Boundary

`personal_growth_agent/` is the independent Git repository and the only project area for ongoing development.

Allowed locations:

- `backend/`
- `frontend/`
- `infra/`
- `docs/`

Do not recreate dependencies on the historical parent project or modify files outside this repository.

## Current Product Boundary

- The application is local-first and uses the fixed user id `default_user`.
- Registration, login, authentication, authorization, and multi-user administration are not part of the current phase.
- The product may be deployed publicly later, so secrets, network boundaries, input validation, auditability, and migration safety must still be designed for deployment.
- Real LLM and real MCP credentials or endpoints must only be supplied through local environment configuration and must never be committed.

## Engineering Boundary

- Preserve the existing FastAPI, LangGraph, Next.js, PostgreSQL, and pgvector architecture unless a documented migration requires otherwise.
- Keep external integrations behind injectable service interfaces so tests can use fake LLM, embedding, and MCP clients.
- Do not describe deterministic test implementations as production LLM, semantic embedding, or standards-complete MCP support.
- Database schema changes for existing volumes require versioned migrations; Docker initialization SQL alone is not an upgrade mechanism.
- Scope each implementation session to one roadmap phase or one clearly defined vertical slice.

The current status and roadmap are maintained in `docs/CURRENT_STATE_AND_ROADMAP.md`.