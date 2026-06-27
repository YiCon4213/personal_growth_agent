# Current State and Roadmap

Last updated: 2026-06-27

## Product Goal

Personal Growth Agent is a local-first, single-user assistant built around LangGraph specialist agents. The current fixed user id is `default_user`. Authentication and multi-user management are intentionally deferred until the single-user product is stable.

The three core user journeys are:

1. A learning request is analyzed and turned into a practical, adjustable learning plan.
2. A fitness or health-related request is answered by the fitness agent with evidence retrieved from a professional RAG knowledge base and with appropriate safety boundaries.
3. A life request is analyzed by an LLM; when a suitable MCP tool is available, the life agent calls it with validated arguments and applies approval rules for risky actions.

The project is expected to support public deployment later. The target delivery form is a Docker Compose stack containing frontend, backend, and PostgreSQL with pgvector.

## Current Architecture

- Frontend: Next.js, React, TypeScript.
- Backend: FastAPI and SSE.
- Orchestration: LangGraph supervisor with learning, fitness, life, and general agents.
- Database: PostgreSQL 16 with pgvector, exposed to host development on `localhost:5433`.
- Persistence: threads, messages, RAG documents/chunks, MCP metadata/calls, approvals, profile candidates/items, and Skill candidates/items.
- Tests: deterministic unit, API, and end-to-end tests using fake external integrations where necessary.

## Current Reality Versus Target

| Area | Current implementation | Target implementation |
| --- | --- | --- |
| LLM | Keyword routing and deterministic response builders; SSE splits a completed response into simulated tokens | DeepSeek-backed reasoning and true token streaming through an injectable LLM service |
| Learning | Rule-based parsing and plan generation | LLM analysis with validated structured learning-plan output |
| Fitness | RAG retrieval plus deterministic response text | RAG evidence supplied to the LLM, cited answer, and health safety prompt |
| Embedding | Stable local hash vectors for tests; `EMBEDDING_MODEL` is currently metadata only | Real multilingual semantic embedding with consistent model and vector dimension |
| MCP | Simplified HTTP JSON-RPC POST for `tools/list` and `tools/call`; fake transport in tests | Official MCP client lifecycle with stdio and Streamable HTTP; legacy SSE only when needed |
| Time MCP | Not usable from its `uvx` stdio configuration yet | Launch through an official stdio client and call `get_current_time`/`convert_time` with schema-valid arguments |
| Skill | Deterministic summary every 10 user turns | LLM-generated structured reusable preference/decision template, still requiring user approval |
| Conversation | Threads and messages are stored, but there is no conversation CRUD UI/API and history is not supplied to the graph | Create/list/rename/delete conversations, view history, and load bounded history into LLM context |
| Docker | Compose currently starts PostgreSQL only | Frontend, backend, and PostgreSQL/pgvector started with one Compose command |

## Target Request Flow

```text
Browser
  -> Next.js frontend
  -> FastAPI chat/session API
  -> load conversation history, profile, Skill, and enabled MCP tools
  -> LangGraph supervisor
       -> learning agent -> DeepSeek -> structured learning plan
       -> fitness agent -> embedding search/pgvector -> DeepSeek grounded answer
       -> life agent -> DeepSeek tool decision -> MCP client -> approval when required
       -> general agent -> DeepSeek response
  -> persist messages and integration events
  -> stream SSE events to the frontend
```

## Planned Configuration

Secrets stay in `backend/.env` and never enter Git. Planned LLM settings are:

```env
DEEPSEEK_API_KEY=
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

The exact model remains configurable. Application startup should fail clearly when a required production integration is enabled without its configuration. Tests must inject fake providers and must not consume paid API calls.

## Implementation Phases

### Phase 1: Conversation Foundation and Real LLM

- Add conversation create/list/detail/rename/delete APIs and frontend navigation.
- Keep the fixed `default_user`; do not add authentication.
- Load a bounded number of previous messages into the graph.
- Add an injectable DeepSeek/OpenAI-compatible LLM service.
- Replace simulated SSE token splitting with real provider streaming.
- Convert learning-plan generation to validated structured output.
- Preserve deterministic fake LLM tests.

Acceptance: two consecutive messages in one conversation use history; a different conversation is isolated; DeepSeek produces a streamed learning answer; API failure and timeout states are visible and recoverable.

### Phase 2: Production RAG

- Introduce an embedding-provider interface and a real multilingual embedding implementation.
- Keep import and query embeddings on the same model and dimension.
- Add a versioned migration when vector dimension or schema changes.
- Re-embed all existing deterministic vectors; never mix hash and semantic vectors.
- Add browser multipart upload for Markdown, TXT, and text-based PDF.
- Build the fitness prompt from retrieved evidence and return citations.

Acceptance: a fitness answer is grounded in relevant uploaded material, unrelated questions do not produce false citations, and existing documents survive restarts.

### Phase 3: Standards-Compliant MCP and Time Tool

- Use the official MCP SDK behind the existing MCP service boundary.
- Implement stdio and Streamable HTTP transports with `initialize`, session lifecycle, `tools/list`, and `tools/call`.
- Store stdio configuration as command, args, environment, and optional working directory.
- Support the Time server using `uvx mcp-server-time --local-timezone=Asia/Shanghai` in local development.
- Replace heuristic argument generation with LLM tool calls validated against each tool input schema.
- Keep risk inference, approval, audit records, timeout handling, and exactly-once execution protections.

Acceptance: the LLM recognizes a time request, selects the Time tool, provides a valid IANA timezone, executes it, and presents the result; high-risk tools still require approval.

### Phase 4: Docker One-Command Startup

- Add backend and frontend Dockerfiles with production-oriented multi-stage builds where useful.
- Expand Compose to `frontend`, `backend`, and `postgres` services with health checks and dependency readiness.
- Use `postgresql+psycopg://...@postgres:5432/...` inside Compose; keep `localhost:5433` for host development.
- Add persistent database volume, environment examples, migration startup, and restart policies.
- Verify one-command startup from a clean machine-like environment.

Acceptance: `docker compose up --build` starts all three services, the browser can chat through the frontend, database data persists, and secrets are supplied externally.

### Phase 5: Public Deployment Hardening

- Add HTTPS/reverse-proxy deployment guidance, strict CORS/host settings, rate limits, request-size limits, structured logs, health/readiness endpoints, backups, and secret management.
- Restrict local stdio MCP commands to an allowlist; never accept arbitrary public command execution.
- Add authentication only as a separate later phase when multi-user access is intentionally introduced.

## Important Constraints

- Do not implement login or multi-user behavior during the fixed-user phase.
- Do not expose arbitrary filesystem paths or arbitrary stdio commands to public clients.
- Do not treat a chat-model key as an embedding configuration automatically.
- Do not hard-code provider model names, secrets, host paths, or production URLs.
- Do not remove the approval boundary when LLM tool calling replaces heuristic tool selection.
- Do not claim a phase is complete using only fake integrations; run a separate live integration acceptance test when credentials and servers are available.

## Verification Baseline

```powershell
cd backend
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider

cd ..\frontend
npm.cmd run lint
npx.cmd tsc --noEmit --incremental false
npm.cmd run build
```

For every future phase, report changed files, automated verification, live integrations that were or were not exercised, and remaining risks.