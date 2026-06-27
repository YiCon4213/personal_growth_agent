# Development Boundaries

This directory is the only writable project area for the new Personal Growth Agent implementation.

Allowed for new code:

- `personal_growth_agent/backend/`
- `personal_growth_agent/frontend/`
- `personal_growth_agent/infra/`
- `personal_growth_agent/docs/`

Read-only historical reference:

- root `app/`
- root `main.py`
- root `langgraph.json`
- root `pyproject.toml`

Current subtask scope:

- project skeleton
- minimal FastAPI health check
- independent backend dependency file
- environment variable example
- README startup and validation instructions

Out of scope for subtask 0:

- LangGraph agents
- chat SSE
- database and migrations
- RAG
- MCP
- approvals
- user profile
- user Skill generation
- Next.js implementation
