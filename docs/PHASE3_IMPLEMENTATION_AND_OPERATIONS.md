# Phase 3 Implementation, Verification, and Operations

Date: 2026-06-28
Status: implementation complete; selected live acceptance remains pending

## Purpose

Phase 3 replaces the simplified MCP JSON-RPC integration with a standards-oriented client boundary. Its purpose is to let the life assistant discover and call external tools without allowing the language model to bypass input validation, risk classification, approval, or audit records.

The Time MCP server is the reference integration because it is useful, read-only, low risk, and exercises both tool discovery and schema-valid argument generation with IANA timezones.

## Delivered Capabilities

- Official MCP Python SDK client lifecycle.
- stdio and Streamable HTTP transports, plus legacy SSE compatibility.
- initialize, tools/list, tools/call, pagination, timeouts, and session cleanup.
- Persisted stdio command, ordered arguments, environment overrides, and optional working directory.
- Explicit stdio command allowlist. The default allows uvx only.
- Provider tools and tool_calls support in the DeepSeek-compatible LLM service.
- Internal tool aliases so arbitrary MCP names are not sent directly as provider function names.
- Local JSON Schema validation before approval and again before execution.
- Time request routing for narrow phrases such as current time, timezone, and what time is it.
- Risk inference, approval requests, call audit records, and failed-call persistence.
- Row locking plus an executing state to prevent duplicate execution when an approval is submitted concurrently.
- Migration 005 for existing PostgreSQL volumes.
- Frontend fields for stdio and Streamable HTTP server configuration.
- Offline FakeLLM, fake transport, provider contract, and real local fake-stdio process tests.

## Product and Safety Effect

The LLM may choose a tool and propose arguments, but it is not trusted to authorize execution. The application still owns all important decisions:

1. Only enabled tools from enabled servers are offered.
2. The selected alias must map to one offered tool.
3. Arguments must pass the advertised JSON Schema.
4. Medium- and high-risk tools stop at approval.
5. An approved request can execute only once.
6. Every success or failure is recorded.
7. Stdio commands must be allowlisted.
8. Environment values are stored for process launch but are not returned by the API.

These boundaries must remain in later refactors.

## Verification Performed

The following checks were necessary because they protect different failure surfaces:

- Complete backend suite: verifies Phase 1 conversations, Phase 2 RAG, Phase 3 MCP, approval, API, and end-to-end compatibility.
- Frontend lint: catches invalid React and project lint rules.
- TypeScript check: verifies API and component types without relying on the production bundler.
- Production build: verifies the actual Next.js production compilation path.
- Fake MCP stdio subprocess: proves the official SDK performs a real initialize, tools/list, tools/call, and shutdown lifecycle without network or paid services.
- DeepSeek contract test: proves the production request uses tools and parses tool_calls without consuming quota.
- Live Time stdio test: proves uvx mcp-server-time works in the current machine environment.

Final automated result at handoff:

- Backend: 75 passed.
- Frontend lint: passed.
- TypeScript: passed.
- Next.js production build: passed.
- Live Time: get_current_time and convert_time passed.

## Were All Tests Necessary?

The final verification categories were necessary and proportionate to the requested phase. In particular, the complete backend run was mandatory after recovering schemas.py because a narrower MCP-only test could not prove that Phase 1 and Phase 2 contracts had been reconstructed correctly.

Some repeated executions were not inherent Phase 3 cost. They were caused by the workspace-path editing failure and the accidental deletion/recovery incident. Repeating tests after recovery and after the final routing change was still necessary, but the failed patch attempts and several broad diff reads should not recur.

For future phases:

- Run targeted tests while iterating.
- Run the complete backend and frontend baseline once after the implementation stabilizes.
- Rerun a complete category only when a later change can affect it.
- Avoid printing whole large files or whole repository diffs when a scoped diff or search is sufficient.

## Main Time and Context Cost

The most expensive part was not the official MCP implementation. It was incident recovery:

1. Diagnosing inconsistent Windows sandbox behavior on a non-ASCII path.
2. Searching Git objects, bytecode, and IDE history for a lossless copy.
3. Reconstructing the uncommitted Phase 1/2 schema from callers and tests.
4. Repeating verification to prove equivalence.
5. Reviewing large diffs produced by the already-uncommitted multi-phase worktree.

The next largest cost was checking the current official SDK signatures and building the stdio lifecycle test. That work was justified because MCP SDK APIs are version-sensitive.

## Required Follow-up Rules

- Keep external LLM, embedding, and MCP integrations injectable.
- Automated tests must continue using fakes and must not consume paid quota.
- Never accept arbitrary stdio commands from a public request. Keep the allowlist restrictive.
- Never return stdio environment values through API responses or logs.
- Never weaken JSON Schema validation because the model appears reliable.
- Never bypass approval for medium- or high-risk tools.
- Keep the approval row lock or replace it with an equally strong idempotency design.
- Apply versioned migrations to existing volumes; Compose initialization scripts only handle empty volumes.
- Do not describe provider contract tests as credentialed live verification.
- Create a recoverable checkpoint before using fallback editing tools on a dirty worktree.
- Prefer a user-approved Git checkpoint after every accepted phase.

## When to Optimize

### Persistent MCP sessions

The current client opens and closes a standards-compliant session per list or call operation. This is simple and safe for current single-user traffic.

Optimize to managed persistent sessions only when measurements show connection startup is material or when a server requires long-lived state. Any pool must handle process death, HTTP session expiry, capability changes, tool-list change notifications, and clean shutdown.

### Approval execution architecture

The current PostgreSQL design keeps a row lock while the approved external call runs. This provides strong duplicate protection at current scale.

Move execution to an outbox or durable job worker before high concurrency, long-running tools, retries across process restarts, or horizontal backend replicas. Preserve an idempotency key and unique execution ownership.

### Tool discovery cache

Tools are persisted after refresh. Add automatic refresh or capability-change handling when servers change frequently. Do not refresh every chat request without latency and failure measurements.

### Stdio security

Before public deployment, replace the simple command-name allowlist with configured server profiles. A profile should fix command, allowed arguments, working directory roots, environment keys, resource limits, and ownership. Do not expose arbitrary filesystem paths.

### Streamable HTTP authentication

The current implementation covers the transport lifecycle but not a production credential-management UI. Before connecting to an authenticated remote server, add an injectable authentication provider and secret storage. Do not put bearer tokens in ordinary metadata or frontend-visible fields.

### Observability

Before public deployment, add structured MCP latency, transport, server id, tool id, result status, timeout, validation failure, and approval transition metrics. Do not log arguments or output blindly because they may contain sensitive data.

## Pending Live Acceptance

### 1. Credentialed DeepSeek tool selection

Who should run it: the user, or Codex after the user explicitly authorizes a quota-consuming request.

When: before declaring Phase 3 fully live-accepted, and before relying on tool selection in a real workflow.

Prerequisites:

- Put DEEPSEEK_API_KEY only in backend/.env.
- Confirm LLM_BASE_URL and LLM_MODEL.
- Configure the Time server and refresh its tools.
- Ensure the database migrations required by the current volume are applied.

Procedure:

1. Start PostgreSQL and the backend.
2. Create or select the Time MCP server.
3. Enable its server id in a chat request.
4. Ask: 请告诉我现在 Asia/Shanghai 是几点.
5. Confirm the SSE stream contains a tool_call event for get_current_time.
6. Confirm arguments contain timezone equal to Asia/Shanghai.
7. Confirm the final assistant text presents the returned time.
8. Confirm mcp_tool_calls contains one succeeded audit row.
9. Ask a non-tool life question and confirm the model may return no tool call.
10. Test a high-risk fake or controlled tool and confirm it creates approval rather than executing.

Expected cost: a small number of chat-model requests. No embedding quota is needed.

### 2. Remote Streamable HTTP

Who should run it: whoever can provide a safe test endpoint and any required network access.

When: before adopting a real remote MCP server or before public deployment. It does not block local Time stdio use.

Procedure:

1. Use a non-production MCP server with a harmless read-only tool.
2. Create a server record with transport streamable_http and its absolute HTTP or HTTPS endpoint.
3. Refresh tools and confirm initialize plus tools/list succeeds.
4. Call the read-only tool with schema-valid arguments.
5. Confirm timeout and connection failures become controlled 502 responses.
6. Restart or expire the server session and confirm the next operation reconnects cleanly.
7. If authentication is required, implement the authentication-provider work described above before testing with secrets.

Do not test against an unknown public MCP endpoint.

### 3. PostgreSQL migration 005

Who should run it: Codex can perform it after the user starts Docker Desktop, or the user can run it manually.

When: before using the new backend against an existing PostgreSQL volume. A new empty volume receives migration 005 through Compose initialization.

Important dependency:

- If migrations 003 and 004 are still pending, apply them in order before 005.
- Migration 004 clears incompatible vectors and requires a later embedding rebuild. That rebuild consumes DashScope quota. Back up the database and plan the rebuild before running it.

Recommended procedure:

1. Start Docker Desktop.
2. Back up the database or volume.
3. Check which migration effects already exist.
4. Apply only missing migrations in numeric order.
5. Apply infra/migrations/005_phase3_mcp_stdio.sql.
6. Verify mcp_servers contains command, args, env, and working_directory.
7. Start the backend and create a stdio Time server.
8. Refresh tools and perform a Time call.
9. Record the live result in CURRENT_STATE_AND_ROADMAP.md.

If Docker Desktop is started, Codex can execute and document this verification in a follow-up task.

## Rollback and Git Checkpoints

This implementation should be committed as a checkpoint before Phase 4. Future phases should use separate commits so a rollback can distinguish conversation/RAG/MCP foundations from Docker and deployment work.

Do not use destructive rollback commands on a dirty worktree. Inspect status first and prefer reverting a known commit or restoring a specific file only after confirming scope.

## Related Documents

- docs/CURRENT_STATE_AND_ROADMAP.md
- docs/INCIDENT_2026-06-28_SCHEMA_RECOVERY.md
- docs/DEVELOPMENT_BOUNDARIES.md
- docs/NEW_SESSION_CONTEXT.md
- infra/README.md
