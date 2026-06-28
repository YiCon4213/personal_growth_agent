# New Session Context

This is a living handoff template, not a permanent snapshot. After every completed phase, update `CURRENT_STATE_AND_ROADMAP.md` and this file before copying the instruction into a new development session. Replace the final task placeholder each time.

```text
请先阅读并遵守以下项目文档：

- README.md
- docs/DEVELOPMENT_BOUNDARIES.md
- docs/CURRENT_STATE_AND_ROADMAP.md
- backend/.env.example
- infra/docker-compose.yml
- 与本次任务直接相关的现有代码和测试

`docs/CURRENT_STATE_AND_ROADMAP.md` 是持续更新的项目事实源。开始任务前必须将文档描述与当前代码、数据库迁移和测试进行核对；如果旧会话内容与最新代码或路线图冲突，以已验证的代码和最新路线图为准。

项目根目录就是 personal_growth_agent/，它是独立 Git 仓库。所有修改只能发生在这个仓库内，不要依赖或修改父目录中的历史项目。

产品策略：

1. 当前是固定单用户本地应用，统一使用 default_user；暂不实现注册、登录、认证和多用户管理。
2. 核心场景只有三条主线：
   - 学习问题：分析用户目标和约束，生成可执行、可调整的学习计划。
   - 健身健康问题：健身 Agent 必须优先使用 RAG 专业知识，并返回来源和安全边界。
   - 生活问题：由 LLM 判断是否适合调用已启用的 MCP 工具，生成符合工具 schema 的参数，并遵守风险审批流程。
3. 项目后续会部署到公网，因此当前实现也要注意密钥、输入验证、命令执行边界、迁移和可观测性。
4. 最终需要 frontend、backend、PostgreSQL/pgvector 三服务 Docker Compose 一键启动。

Current verified state:

- Phase 1 conversation CRUD/history and injectable DeepSeek streaming are implemented. FakeLLM automation passes; a prior separate DeepSeek live check was recorded.
- Phase 2 production embedding uses the official DashScope SDK with `text-embedding-v3`, explicit 1024-dimensional dense output, and separate document/query text types. Automated tests inject FakeEmbedding and monkeypatch DashScope; no real quota is used.
- The RAG subgraph exposes history rewrite, optional decomposition/HyDE, dense retrieval, real Okapi BM25, deduplication, direct RRF final ordering, a dense/BM25 relevance gate, final Top 3 evidence, and grounded fitness streaming. Independent Rerank was intentionally removed.
- RAG documents/chunks store provider/model/version/dimension/content hashes and index status. Migration 003 adds metadata; migration `004_dashscope_embedding_1024.sql` clears incompatible vectors and changes pgvector to 1024 dimensions before rebuild.
- Browser multipart upload supports Markdown, TXT, and text-based PDF with a 10 MiB limit.
- Credentialed DashScope calls were not verified and no real quota was consumed. Migrations 003/004 and pgvector SQL still require live PostgreSQL verification. A private `.env` must use `EMBEDDING_DIMENSION=1024`, not the old 1536 override.
- Phase 3 uses the official MCP Python SDK with stdio, Streamable HTTP, and legacy SSE. Provider tool_calls are schema-validated; risky tools retain approval and row-lock exactly-once protection.
- Time MCP was live-verified through uvx stdio for get_current_time and convert_time. Credentialed DeepSeek tool selection, remote Streamable HTTP, and PostgreSQL migration 005 live execution remain pending.
- Skill remains a deterministic approved text template, not executable code. Docker Compose still contains PostgreSQL only.

目标改造顺序：

1. Completed: conversation CRUD, bounded history, injectable DeepSeek, and real provider SSE.
2. Implemented, live acceptance pending: external Embedding API and advanced RAG.
3. Completed in code: 官方 MCP SDK、stdio/Streamable HTTP、Time MCP、LLM 工具选择和 schema 参数校验；部分 live acceptance 见路线图。
4. 前后端 Dockerfile、三服务 Compose、一键启动和迁移机制。
5. 公网部署安全加固；登录和多用户仍放到更后面的独立阶段。

工程要求：

- 开始修改前先阅读代码并说明发现的现状。
- 保持外部服务可注入，自动测试使用 fake LLM、fake embedding 和 fake MCP，不能消耗真实额度。
- 接入真实服务后，必须额外说明是否完成 live integration 验证。
- 不得把 API Key、.env、虚拟环境、node_modules、.next 或本地数据提交到 Git。
- 数据库结构变化必须提供已有数据卷可执行的版本化迁移，不能只修改初始化 SQL。
- MCP 高风险工具必须继续经过审批，不允许因为引入 LLM tool calling 而绕过。
- 本次只实现明确指定的阶段或垂直功能，不顺手实现登录、多用户或其他后续阶段。
- 完成后运行相关后端测试、前端 lint、TypeScript 检查和生产构建，并说明改动文件、验证方式、未验证项和剩余风险。
- 每个 Phase 完成后，必须更新 docs/CURRENT_STATE_AND_ROADMAP.md 的当前状态、已完成项、真实验证情况、遗留风险和下一阶段前置条件，并同步更新本文件，避免下一会话使用过期上下文。

本次具体任务：
[Current task: execute Phase 4 frontend/backend/PostgreSQL three-service Docker Compose one-command startup.]
```
