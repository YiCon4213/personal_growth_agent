# Personal Growth Agent

一个面向个人学习、健身与日常事务的本地优先 AI 助手。项目使用 LangGraph 编排多个专业 Agent，通过 DeepSeek 生成回答、DashScope 构建 RAG 知识库，并可通过 MCP 连接外部工具。

> 当前版本为单用户 Beta：所有数据使用固定用户 `default_user`。项目尚未提供应用级登录与多用户隔离，请勿在没有额外访问控制的情况下直接暴露到公网。

## 能做什么

- **学习规划**：把学习目标整理为结构化、可调整的行动计划。
- **健身问答**：从用户导入的知识库中检索依据，生成带引用与安全提示的回答。
- **生活助手**：发现并调用 MCP 工具；高风险操作需要用户批准后才会执行。
- **长期上下文**：保存对话、用户画像候选项和可复用 Skill 候选项，由用户决定是否采纳。
- **可视化工作台**：在同一界面管理聊天、RAG 文档、MCP 服务、审批、画像和 Skill。

## 技术架构

```text
Next.js / React
       │ SSE + REST
       ▼
FastAPI ── LangGraph Supervisor
       │       ├── Learning Agent
       │       ├── Fitness Agent ── RAG / DashScope Embedding
       │       ├── Life Agent ───── MCP Tools / Approval
       │       └── General Agent
       ▼
PostgreSQL 16 + pgvector
```

主要技术栈：Python 3.12、FastAPI、LangGraph、Next.js 16、React 19、PostgreSQL、pgvector、Docker Compose。

## 快速开始（推荐）

### 前置条件

- Docker Engine 或 Docker Desktop，并支持 Compose v2
- DeepSeek API Key
- DashScope API Key（用于知识库向量化与检索）

### 1. 克隆并配置

```bash
git clone https://github.com/YiCon4213/personal_growth_agent.git
cd personal_growth_agent
cp backend/.env.example backend/.env
```

Windows PowerShell 可将最后一行替换为：

```powershell
Copy-Item backend/.env.example backend/.env
```

编辑 `backend/.env`，至少填写：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DASHSCOPE_API_KEY=your_dashscope_api_key
```

不要提交包含真实密钥的 `.env` 文件。

### 2. 启动完整服务

```bash
docker compose -f infra/docker-compose.yml up --build -d --wait
```

启动完成后访问：

- Web 界面：<http://127.0.0.1:3000>
- 后端健康检查：<http://127.0.0.1:8000/api/v1/health>
- PostgreSQL：`127.0.0.1:5433`

查看状态或停止服务：

```bash
docker compose -f infra/docker-compose.yml ps
docker compose -f infra/docker-compose.yml down
```

`down` 默认保留 PostgreSQL 命名卷中的数据。除非确定要永久删除数据，否则不要使用 `--volumes`。

## 首次使用

1. 打开 Web 界面并发送学习、健身或生活类问题。
2. 健身 RAG 问答前，在知识库面板导入 Markdown、TXT 或文本型 PDF。
3. 如需工具调用，在 MCP 面板添加服务并刷新工具列表。
4. 在审批、画像和 Skill 面板中检查待确认项目。

应用默认不自动配置 MCP 服务。若要使用 Time MCP，需要主机已安装 `uvx`，然后在 MCP 面板/API 中创建 stdio 服务：命令为 `uvx`，参数为 `mcp-server-time --local-timezone=Asia/Shanghai`。

## 本地开发

### 后端

后端使用 [uv](https://docs.astral.sh/uv/) 管理依赖：

```bash
cd backend
uv sync --group dev
uv run uvicorn app.main:app --reload
```

仅启动开发数据库：

```bash
docker compose -f infra/docker-compose.yml up -d postgres --wait
```

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认将 `/api/v1/*` 转发到 `http://127.0.0.1:8000`。

## 测试与质量检查

```bash
cd backend
uv run pytest -q
```

```bash
cd frontend
npm run lint
npm run typecheck
npm run build
```

自动化测试使用 fake LLM、embedding 和 MCP 客户端，不会消耗真实服务额度。真实 RAG 评估方法见 [`backend/evaluation/README.md`](backend/evaluation/README.md)。

## 配置说明

完整配置及默认值见 [`backend/.env.example`](backend/.env.example)。常用配置包括：

| 配置 | 用途 |
| --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek/OpenAI-compatible 聊天模型凭据 |
| `DASHSCOPE_API_KEY` | DashScope `text-embedding-v3` 凭据 |
| `DATABASE_URL` | 后端数据库连接；Compose 会自动覆盖为容器地址 |
| `ALLOWED_HOSTS` | 后端允许的 Host 列表 |
| `MCP_STDIO_ALLOWED_COMMANDS` | 允许启动的 stdio MCP 命令 |
| `MCP_STDIO_ALLOWED_TARGETS` | 允许的 stdio MCP 包/目标 |
| `MCP_REMOTE_ALLOWED_HOSTS` | 生产环境允许连接的远程 HTTPS MCP 主机 |

## 项目结构

```text
backend/                 FastAPI、LangGraph、数据模型、服务与测试
backend/evaluation/      真实模型 RAG 评估脚本与语料
frontend/                Next.js 用户界面
infra/                   Compose、Caddy、迁移和备份脚本
docs/ROADMAP.md          当前能力、已知限制与公开路线图
```

## 公网部署

[`infra/docker-compose.public.yml`](infra/docker-compose.public.yml) 提供 Caddy HTTPS 和强制 Basic Auth 的部署模板。完整的 DNS、证书、防火墙、备份与恢复步骤见 [`infra/README.md`](infra/README.md)。

公网部署前请特别注意：

- 当前没有应用级身份认证或多用户数据隔离；
- Basic Auth 只是临时外围保护，不能替代正式账号系统；
- PostgreSQL、后端和前端诊断端口应保持仅绑定 `127.0.0.1`；
- 当前限流器为单进程内存实现，横向扩容前需要共享限流层；
- 请先完成离机备份和隔离恢复演练。

## 当前限制与路线图

项目的实现状态、已知限制和下一步计划见 [`docs/ROADMAP.md`](docs/ROADMAP.md)。主要限制包括固定单用户、关键词式 Supervisor 路由、远程 Streamable HTTP MCP 尚未完成真实环境验证，以及应用级认证尚未实现。

## 许可证

仓库目前尚未添加开源许可证。在许可证明确之前，源代码仅可按 GitHub 服务条款查看和分叉，不代表已授予复制、修改或分发权利。
