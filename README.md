# Personal Growth Agent

个人成长型 LangGraph 多 Agent 平台的新项目目录。所有新后端、前端、基础设施、测试和运行文档都放在 `personal_growth_agent/` 内；旧 `app/` 只作为历史参考，不在本项目中原地修改。

## 项目边界

- 新代码只能写入 `personal_growth_agent/`。
- 不修改旧 `app/`、根目录旧 `main.py`、根目录旧 `langgraph.json`、根目录旧 `pyproject.toml`。
- 当前后端数据库使用 Docker Postgres + pgvector，默认端口是 `localhost:5433`，不是 `5432`。
- 当前实现仍是第一阶段学习项目闭环：Agent 回复、RAG embedding、MCP transport 都使用可测试的确定性/本地实现，不依赖真实 LLM。

## 当前结构

```text
personal_growth_agent/
  backend/
    app/
      agents/          # LangGraph supervisor 与学习/健身/生活/通用 Agent
      api/v1/          # chat、rag、mcp、approvals、profile、skills 等 API
      core/            # 配置与数据库连接
      db/              # SQLAlchemy 模型与初始化
      models/          # Pydantic API/SSE schema
      services/        # RAG、MCP、审批、画像、Skill、数据访问
    tests/             # 单元、API 与端到端回归测试
    .env.example
    langgraph.json
    pyproject.toml
  frontend/
    src/               # Next.js/React/TypeScript 前端源码
  infra/
    docker-compose.yml
    migrations/001_init_pgvector.sql
  docs/
```

## 后端启动

```powershell
cd personal_growth_agent/backend
uv sync --group dev
uv run uvicorn app.main:app --reload
```

健康检查：

```powershell
curl http://127.0.0.1:8000/api/v1/health
```

聊天 SSE：

```powershell
curl -N -X POST http://127.0.0.1:8000/api/v1/chat/stream `
  -H "Content-Type: application/json" `
  -d "{\"message\":\"我想 3 个月学完 Python 后端，每天 2 小时\",\"thread_id\":\"thread_demo\",\"user_id\":\"default_user\"}"
```

## 数据库

启动本地 Postgres + pgvector：

```powershell
cd personal_growth_agent/infra
docker compose up -d
```

默认连接：

```text
DATABASE_URL=postgresql+psycopg://personal_growth_agent:personal_growth_agent_dev@localhost:5433/personal_growth_agent
```

初始化 SQL：

```text
personal_growth_agent/infra/migrations/001_init_pgvector.sql
```

## 主要 API

聊天：

- `POST /api/v1/chat/stream`

RAG：

- `POST /api/v1/rag/documents`
- `POST /api/v1/rag/documents/import-file`
- `GET /api/v1/rag/documents?user_id=default_user`
- `POST /api/v1/rag/search`

MCP：

- `POST /api/v1/mcp/servers`
- `GET /api/v1/mcp/servers?user_id=default_user`
- `POST /api/v1/mcp/servers/{id}/refresh-tools?user_id=default_user`
- `GET /api/v1/mcp/tools?user_id=default_user`
- `POST /api/v1/mcp/tools/{id}/test`

审批：

- `GET /api/v1/approvals?user_id=default_user`
- `POST /api/v1/approvals/{id}/approve`
- `POST /api/v1/approvals/{id}/reject`

画像：

- `GET /api/v1/profile?user_id=default_user`
- `GET /api/v1/profile/candidates?user_id=default_user`
- `POST /api/v1/profile/candidates/{id}/approve`
- `POST /api/v1/profile/candidates/{id}/reject`
- `POST /api/v1/profile/{id}/disable?user_id=default_user`
- `DELETE /api/v1/profile/{id}?user_id=default_user`

Skill：

- `GET /api/v1/skills?user_id=default_user`
- `GET /api/v1/skills/candidates?user_id=default_user`
- `POST /api/v1/skills/candidates/{id}/approve`
- `POST /api/v1/skills/candidates/{id}/reject`
- `POST /api/v1/skills/{id}/disable?user_id=default_user`

## 前端启动

```powershell
cd personal_growth_agent/frontend
npm install
npm run dev
```

默认通过 `next.config.mjs` rewrite 到后端 `http://127.0.0.1:8000`。

前端验证：

```powershell
cd personal_growth_agent/frontend
npm.cmd run lint
npx.cmd tsc --noEmit --incremental false
```

说明：在当前 Windows PowerShell 环境中，`npm run typecheck` 可能因为执行策略或 `tsconfig.tsbuildinfo` 写入权限失败；上面的 `npx.cmd tsc --noEmit --incremental false` 用于验证类型本身。

## 自动化验证

后端完整测试：

```powershell
cd personal_growth_agent/backend
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

当前端到端回归测试位于：

```text
personal_growth_agent/backend/tests/test_e2e_integration.py
```

它使用 SQLite 内存数据库和 fake MCP transport，不依赖真实 LLM、真实 MCP server 或 Docker Postgres，覆盖：

- 学习规划聊天完成并返回 `learning_plan`。
- 导入健身 RAG 文档后，健身聊天返回 `rag_sources` 引用。
- 低风险 MCP 工具通过生活 Agent 被调用。
- 高风险 MCP 工具触发 `approval_required`，批准后才执行。
- 画像候选生成、批准，并在后续聊天中作为 `profile_context` 使用。
- 同一 thread 累计 10 轮后生成 Skill 候选，批准后在后续聊天中作为 `skill_context` 使用。

## 手动端到端验收建议

1. 启动 Docker Postgres + pgvector，并确认 `.env` 使用 `localhost:5433`。
2. 启动后端 `uv run uvicorn app.main:app --reload`。
3. 启动前端 `npm run dev`。
4. 在前端依次验证学习规划、导入 RAG 文档后的健身问答、MCP server 管理、审批、画像候选批准、10 轮 Skill 候选批准。
5. 如未配置真实 MCP server，可先依赖自动化端到端测试验证 MCP/审批契约。
