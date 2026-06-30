# Personal Growth Agent Frontend

Next.js/React frontend for the new `personal_growth_agent` project.

## Start

Install dependencies:

```powershell
cd personal_growth_agent/frontend
npm install
```

Start the backend in another terminal:

```powershell
cd personal_growth_agent/backend
uv run uvicorn app.main:app --reload
```

Start the frontend:

```powershell
cd personal_growth_agent/frontend
npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

The frontend calls `/api/v1/*`. `next.config.mjs` rewrites those requests to `http://127.0.0.1:8000/api/v1/*` by default. Override with:

```powershell
$env:BACKEND_URL="http://127.0.0.1:8000"
```

## What Is Implemented

- Responsive, collapsible three-column chat workspace with SSE streaming and an independently scrolling message viewport.
- Agent status, RAG sources, MCP tool calls, approval requests, profile candidates, and skill candidates.
- Centralized API client in `src/lib/api-client.ts`.
- Basic panels for approvals, profile candidates/items, skill candidates/items, MCP servers/tools, and RAG documents.

## Manual Verification

1. Start Postgres from `personal_growth_agent/infra` if using database-backed flows.
2. Start the FastAPI backend.
3. Start this frontend.
4. Send a chat message such as `我每天晚上 9 点后学习效率高，请记住。`.
5. Confirm the streamed reply appears and a profile candidate can be approved or rejected.
6. Add a RAG document, then send a fitness query such as `我想做减脂训练`.
