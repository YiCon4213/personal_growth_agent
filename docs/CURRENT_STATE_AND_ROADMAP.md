# Current State and Roadmap

Last updated: 2026-06-28

## Documentation Lifecycle

This document is the living source of truth, not a one-time plan. At the end of every phase:

- move completed capabilities from target state to current state;
- record live integrations that were actually verified and those that remain simulated;
- update schema, configuration, API, deployment, and known-risk notes;
- revise the next phase when earlier implementation decisions change its prerequisites;
- update `docs/NEW_SESSION_CONTEXT.md` before starting the next development session.

When this document conflicts with an old conversation or task breakdown, the verified repository code and the latest version of this document take precedence.

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
| LLM | General, learning, and grounded fitness answers use the injectable DeepSeek/OpenAI-compatible service. The life agent now sends provider tools and consumes tool_calls; tests inject FakeLLM. | Continue evaluation and prompt hardening; credentialed MCP tool selection remains a live acceptance item. |
| Learning | DeepSeek generates a Pydantic-validated structured plan, followed by a streamed natural-language answer; deterministic builders remain as test/fallback fixtures outside the production chat path. | Continue evaluation and prompt hardening. |
| Fitness | An explicit advanced RAG LangGraph fuses dense and BM25 ranks with RRF, applies a relevance gate, and returns at most three evidence chunks; the LLM receives only that evidence and a citation/safety prompt. | Run DashScope and pgvector live acceptance, then build the planned RAG evaluation corpus. |
| Embedding | Production uses the native DashScope SDK with `text-embedding-v3`, explicit 1024-dimensional dense output, document/query text types, batching, retries, concurrency limits, and content-hash caching. Deterministic vectors exist only in the injected test fake. | Complete a credentialed DashScope live check and pgvector migration/rebuild acceptance. |
| MCP | Official Python SDK lifecycle with stdio, Streamable HTTP, and legacy SSE; schema validation, command allowlist, audit records, and approval locking are implemented. | Live-test a remote Streamable HTTP server and add production observability during hardening. |
| Time MCP | uvx mcp-server-time was live-verified through the official stdio client; get_current_time and convert_time both succeeded. | Keep the server local and allowlisted; package availability remains an operational dependency. |
| Skill | Deterministic summary every 10 user turns | LLM-generated structured reusable preference/decision template, still requiring user approval |
| Conversation | Create/list/detail/rename/delete APIs and frontend navigation are implemented; bounded same-thread history is passed into LangGraph and the LLM. | Add richer search/archival only in a later scoped phase. |
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

## LLM Configuration

Secrets stay in `backend/.env` and never enter Git. Current LLM settings are:

```env
DEEPSEEK_API_KEY=
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

The exact model remains configurable. Application startup should fail clearly when a required production integration is enabled without its configuration. Tests must inject fake providers and must not consume paid API calls.

## Implementation Phases

### Phase 1: Conversation Foundation and Real LLM

Implementation status (2026-06-27): completed in the application code and covered by FakeLLM automation. A separate DeepSeek live check validated structured output and provider streaming. The local .env must use the OpenAI-compatible base URL https://api.deepseek.com.

- Add conversation create/list/detail/rename/delete APIs and frontend navigation.
- Keep the fixed `default_user`; do not add authentication.
- Load a bounded number of previous messages into the graph.
- Add an injectable DeepSeek/OpenAI-compatible LLM service.
- Replace simulated SSE token splitting with real provider streaming.
- Convert learning-plan generation to validated structured output.
- Preserve deterministic fake LLM tests.

Acceptance: two consecutive messages in one conversation use history; a different conversation is isolated; DeepSeek produces a streamed learning answer; API failure and timeout states are visible and recoverable.

### Phase 2: External Embedding API and Advanced RAG Agent

Implementation status (2026-06-27): application implementation uses DashScope `text-embedding-v3` at an explicit 1024 dimensions and direct RRF final ranking. Independent reranking was intentionally removed by product decision. Credentialed DashScope calls and a PostgreSQL/pgvector migration run were not performed in this session, so live acceptance remains pending.

The production embedding path calls DashScope through its official Python SDK using `DASHSCOPE_API_KEY` and `DASHSCOPE_BASE_URL`. The deterministic hash provider remains available only as an injected test fake.

Indexing requirements:

- Add an async, batch-capable embedding-provider interface with API key, base URL, model, timeout, retry, and dimension settings.
- Split imported documents into stable chunks, call the external embedding API in batches, and store vectors in pgvector.
- Store embedding provider/model/version/dimension and a content hash so stale vectors can be detected and rebuilt.
- Keep document and query embeddings on exactly the same model and dimension.
- Add a versioned migration when vector dimension or index schema changes.
- Re-embed all existing deterministic vectors; never mix hash and semantic vectors in one active index.
- Add browser multipart upload for Markdown, TXT, and text-based PDF.

The user query, including a history-aware standalone version when needed, is sent to the same embedding API for dense retrieval. The advanced RAG flow is orchestrated as an explicit LangGraph subgraph. The graph exposes the complete pipeline, while `analyze_query` uses conditional routing to skip decomposition or HyDE for simple queries when those steps would add cost without retrieval value:

1. `analyze_query`: determine whether retrieval is required and extract constraints.
2. `rewrite_query`: rewrite ambiguous or conversational input into a standalone retrieval query.
3. `decompose_query`: split a multi-part question into focused subqueries.
4. `generate_hyde`: generate one or more hypothetical answer passages and embed them as additional semantic queries.
5. `dense_retrieve`: run pgvector cosine retrieval for the original query, rewritten query, subqueries, and HyDE variants.
6. `sparse_retrieve`: run BM25 keyword retrieval over the same user-scoped chunk corpus.
7. `deduplicate_candidates`: merge identical chunk ids while retaining provenance and per-route ranks.
8. `rrf_fuse`: combine dense and sparse ranked lists with Reciprocal Rank Fusion.
9. `select_context`: keep RRF order, reject candidates without either a BM25 match or the configured minimum dense score, and return the highest-ranked three distinct chunks.
10. `generate_grounded_answer`: let the LLM answer only from those results, include citations, and clearly report insufficient evidence.

RRF is both the multi-route fusion stage and the final ordering strategy for the current product decision. No independent reranking API is called. A relevance gate based on BM25 participation or minimum dense cosine score prevents RRF from returning arbitrary low-relevance candidates.

Operational requirements:

- Enforce `user_id=default_user` and optional document filters in both dense and sparse retrieval.
- Keep sparse retrieval behind a replaceable interface. For the single-user three-service architecture, the initial BM25 implementation may use LangChain `BM25Retriever`/`rank_bm25` over database chunks with a cached index and explicit invalidation after document changes; do not describe ordinary PostgreSQL full-text ranking as BM25.
- Keep per-stage candidate limits configurable; return exactly the final top three evidence chunks to the answer model.
- Record rewritten queries, subqueries, HyDE text, retrieval route, raw ranks, RRF score, dense score, BM25 participation, model versions, and latency for debugging without logging secrets.
- Add timeouts, bounded retries, concurrency limits, and batch-size controls for external APIs.
- Cache embeddings by model plus content hash where safe.
- Define a deterministic evaluation set covering semantic matches, exact-keyword matches, multi-part questions, conversational questions, and no-answer cases.

Acceptance: uploaded documents are embedded through configured DashScope `text-embedding-v3`; dense and BM25 routes both contribute candidates; RRF ranking and the relevance gate are observable; only the final top three chunks reach the LLM; answers cite relevant evidence; unrelated questions do not produce false citations; existing documents survive restarts; and fake providers keep automated tests offline.

#### Phase 2 verification and residual risks

- Added an injectable async wrapper around the official DashScope SDK. Offline contract tests monkeypatch the SDK and never use real credentials or quota.
- Added stable chunk/content hashes, provider/model/version/dimension metadata, cache reuse, stale-index filtering, `003_phase2_advanced_rag.sql`, and `004_dashscope_embedding_1024.sql`. Migration 004 clears old vectors, changes pgvector to `vector(1024)`, and requires explicit rebuild.
- Added browser multipart upload for Markdown, TXT, and text-based PDF with a 10 MiB request limit. Scanned/image-only PDF OCR is intentionally not implemented.
- Added the explicit conditional RAG subgraph: query analysis, history rewrite, optional decomposition/HyDE, dense retrieval, replaceable in-process Okapi BM25, deduplication, direct RRF ordering, relevance gating, Top 3 selection, and grounded streamed answer preparation.
- Trace metadata records filters, rewritten/subqueries/HyDE queries, route ranks, RRF/dense scores, BM25 participation, provider model version, selected chunk ids, and latency without secrets.
- Independent reranking is intentionally absent. RRF candidates need either a BM25 match or dense cosine score at/above `RAG_MIN_DENSE_SCORE` before they may be cited.
- Automated verification: full backend suite, frontend lint, TypeScript check, and production build pass. Exact current counts are recorded in the implementation handoff rather than treated as a permanent architecture fact.
- Live verification not completed: no DashScope request was sent, and Docker Desktop was unavailable, so migrations `003`/`004` and PostgreSQL pgvector SQL were not executed against a live database. Compose configuration and migration mounting are verified statically.
- The application and migration target is `vector(1024)`, matching explicit `text-embedding-v3` output. The private local `.env` must set or remove any old `EMBEDDING_DIMENSION=1536` override before live use.
- Initial BM25 builds from the user-scoped database corpus per request. This is correct for the current single-user scale but remains a performance risk; a cached index with explicit invalidation can be added when corpus size justifies it.

### Phase 3: Standards-Compliant MCP and Time Tool

- Use the official MCP SDK behind the existing MCP service boundary.
- Implement stdio and Streamable HTTP transports with `initialize`, session lifecycle, `tools/list`, and `tools/call`.
- Store stdio configuration as command, args, environment, and optional working directory.
- Support the Time server using `uvx mcp-server-time --local-timezone=Asia/Shanghai` in local development.
- Replace heuristic argument generation with LLM tool calls validated against each tool input schema.
- Keep risk inference, approval, audit records, timeout handling, and exactly-once execution protections.

Acceptance: the LLM recognizes a time request, selects the Time tool, provides a valid IANA timezone, executes it, and presents the result; high-risk tools still require approval.

Implementation status (2026-06-28): completed in application code and automated coverage. The official stdio Time integration was live-verified. Credentialed DeepSeek tool selection, remote Streamable HTTP, and PostgreSQL migration 005 live execution remain pending.

#### Phase 3 verification and residual risks

- Replaced the handwritten JSON-RPC POST client with the official MCP Python SDK. Each operation performs transport connection, initialize, tools/list or tools/call, and deterministic session shutdown.
- Added stdio, Streamable HTTP, and legacy SSE support. Stdio persists command, ordered args, environment overrides, and optional working directory. Environment values are not returned by the API.
- Added MCP_STDIO_ALLOWED_COMMANDS (default uvx) and MCP_TIMEOUT_SECONDS. Arbitrary stdio commands are rejected.
- The life agent now uses provider tool calling. Tool aliases come from internal ids; returned arguments are validated locally with JSON Schema before approval or execution.
- High/medium-risk tools still require approval. Approval uses a row lock and executing state so concurrent approval attempts cannot execute one request twice. Failed approved calls remain auditable.
- Added migration 005_phase3_mcp_stdio.sql for existing volumes and mounted it for new Compose volumes.
- Offline automation uses FakeLLM, fake transport, and a local fake MCP stdio subprocess. A monkeypatched contract test verifies the DeepSeek tools/tool_calls shape; no model quota was consumed.
- Live verification completed: uvx mcp-server-time --local-timezone=Asia/Shanghai exposed get_current_time and convert_time, and both calls succeeded with IANA timezones.
- Live verification not completed: no credentialed DeepSeek tool-selection request was sent; no remote Streamable HTTP server was available; Docker Desktop was not running, so migration 005 and the pending Phase 2 PostgreSQL migrations were not run against live PostgreSQL. Compose configuration was validated statically.
- The schema recovery incident and prevention rules are recorded in docs/INCIDENT_2026-06-28_SCHEMA_RECOVERY.md.
- Detailed Phase 3 purpose, verification rationale, optimization triggers, and live acceptance runbooks are recorded in docs/PHASE3_IMPLEMENTATION_AND_OPERATIONS.md.


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
