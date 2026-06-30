# Personal Growth Agent

个人成长型 LangGraph 多 Agent 平台的新项目目录。所有新后端、前端、基础设施、测试和运行文档都放在 `personal_growth_agent/` 内；旧 `app/` 只作为历史参考，不在本项目中原地修改。

## 项目边界

- 新代码只能写入 `personal_growth_agent/`。
- 不修改旧 `app/`、根目录旧 `main.py`、根目录旧 `langgraph.json`、根目录旧 `pyproject.toml`。
- 当前后端数据库使用 Docker Postgres + pgvector，默认端口是 `localhost:5433`，不是 `5432`。
- Phase 1-4 implementations are present. RAG uses DashScope text-embedding-v3 at 1024 dimensions; MCP uses the official SDK; the three-service Compose stack has completed live acceptance.

## 产品策略与改造路线

- 当前固定使用本地单用户 `default_user`，暂不实现注册、登录和用户管理。
- 核心场景是学习计划、基于专业知识库的健身健康问答，以及由 LLM 判断并调用 MCP 工具的生活助手。
- Phase 1-4 已实现；后续重点是尚未完成的外部集成验收与 Phase 5 公网部署安全加固。
- 当前实现能力、目标架构、阶段顺序和验收标准见 `docs/CURRENT_STATE_AND_ROADMAP.md`。
- 开始新的开发会话时，可直接使用 `docs/NEW_SESSION_CONTEXT.md` 中的上下文指令。

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
    migrations/001_init_pgvector.sql ... 006_phase4_normalize_legacy_titles.sql
  docs/
```

## Docker Compose 一键启动

从仓库根目录复制 `backend/.env.example` 为不提交的 `backend/.env`，按需填写 DeepSeek 和 DashScope 密钥，然后运行：

```powershell
docker compose -f infra/docker-compose.yml up --build -d --wait
```

服务地址：

- 前端：`http://localhost:3000`
- 后端健康检查：`http://localhost:8000/api/v1/health`
- 宿主机 PostgreSQL：`localhost:5433`

Compose 会先等待 PostgreSQL 健康，再运行带校验和账本的版本化迁移；迁移成功后启动后端，最后启动前端。`docker compose down` 默认保留数据库命名卷。完整配置、旧卷升级语义和当前 live verification 见 `infra/README.md`。
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
docker compose -f infra/docker-compose.yml up -d postgres --wait
```

默认连接：

```text
DATABASE_URL=postgresql+psycopg://personal_growth_agent:personal_growth_agent_dev@localhost:5433/personal_growth_agent
```

初始化 SQL：

```text
The one-shot `migrate` service applies every numbered file in `infra/migrations/` and records it in `schema_migrations`.
```

## 主要 API

聊天：

- `POST /api/v1/chat/stream`

RAG：

- `POST /api/v1/rag/documents`
- `POST /api/v1/rag/documents/upload` (multipart Markdown/TXT/text-based PDF)
- `GET /api/v1/rag/documents`
- `POST /api/v1/rag/search`
- `POST /api/v1/rag/documents/rebuild-index`

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

## Phase 1 配置与迁移

真实聊天使用 `backend/.env` 中的 `DEEPSEEK_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL`。OpenAI-compatible 客户端的 base URL 应为 `https://api.deepseek.com`，不要使用 Anthropic 路径。

已有 PostgreSQL 数据卷升级时执行版本化迁移：

```powershell
Get-Content infra/migrations/002_phase1_conversations.sql | docker compose -f infra/docker-compose.yml exec -T postgres psql -U personal_growth_agent -d personal_growth_agent
```

迁移会把历史上为空的 thread 用户统一为固定单用户 `default_user`，并补齐空标题；本阶段没有新增表或列。

## Phase 2 DashScope RAG configuration and migration

Production document and query vectors use the official DashScope Python SDK with `text-embedding-v3`, explicit `dimension=1024`, `output_type="dense"`, and distinct `text_type="document"` / `text_type="query"` values. Final evidence order comes directly from RRF; no independent Rerank API is configured or called.

Configure these values in `backend/.env`:

```env
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/api/v1
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_MODEL_VERSION=v3-1024-dense
EMBEDDING_DIMENSION=1024
```

If the private `.env` still contains the old `EMBEDDING_DIMENSION=1536`, change it to `1024` or remove that override. Native `/api/v1` and an existing `/compatible-mode/v1` Base URL are both accepted; the provider normalizes the latter for the SDK. Never commit `.env`.

Existing PostgreSQL volumes must apply migrations 003 and 004 in order if they have not already done so:

```powershell
Get-Content infra/migrations/003_phase2_advanced_rag.sql | docker compose -f infra/docker-compose.yml exec -T postgres psql -U personal_growth_agent -d personal_growth_agent
Get-Content infra/migrations/004_dashscope_embedding_1024.sql | docker compose -f infra/docker-compose.yml exec -T postgres psql -U personal_growth_agent -d personal_growth_agent
```

Migration 004 marks documents stale, clears incompatible vectors, changes the column to `vector(1024)`, and recreates the cosine index. Rebuild after configuring DashScope:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/rag/documents/rebuild-index
```

Rebuild sends stored chunks to DashScope and can consume quota. Automated tests monkeypatch the SDK and do not use `DASHSCOPE_API_KEY`. Credentialed DashScope calls and index rebuild were user-confirmed live; migrations and `vector(1024)` were verified during Phase 4.

## Phase 3 MCP and Time configuration

Production MCP clients use the official Python SDK. Supported transports are stdio, streamable_http, and legacy sse. Local stdio commands must appear in MCP_STDIO_ALLOWED_COMMANDS; the default is uvx.

Create a local Time server by POSTing this shape to /api/v1/mcp/servers:

- user_id: default_user
- name: Time
- endpoint_url: empty string
- transport: stdio
- command: uvx
- args: ["mcp-server-time", "--local-timezone=Asia/Shanghai"]
- env: {}
- enabled: true

Then call POST /api/v1/mcp/servers/{id}/refresh-tools?user_id=default_user and enable that server id in chat requests. The life agent sends MCP definitions through provider tool calling and validates returned arguments against the advertised JSON Schema before execution or approval.

Existing PostgreSQL volumes must apply infra/migrations/005_phase3_mcp_stdio.sql. The Time stdio server was live-verified locally for both get_current_time and convert_time, and credentialed DeepSeek tool selection was user-confirmed live. Remote Streamable HTTP remains unverified.
