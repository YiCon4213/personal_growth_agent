# New Session Context

Copy the instruction below into a new development session and replace the final task placeholder.

```text
请先阅读并遵守以下项目文档：

- README.md
- docs/DEVELOPMENT_BOUNDARIES.md
- docs/CURRENT_STATE_AND_ROADMAP.md
- backend/.env.example
- infra/docker-compose.yml
- 与本次任务直接相关的现有代码和测试

项目根目录就是 personal_growth_agent/，它是独立 Git 仓库。所有修改只能发生在这个仓库内，不要依赖或修改父目录中的历史项目。

产品策略：

1. 当前是固定单用户本地应用，统一使用 default_user；暂不实现注册、登录、认证和多用户管理。
2. 核心场景只有三条主线：
   - 学习问题：分析用户目标和约束，生成可执行、可调整的学习计划。
   - 健身健康问题：健身 Agent 必须优先使用 RAG 专业知识，并返回来源和安全边界。
   - 生活问题：由 LLM 判断是否适合调用已启用的 MCP 工具，生成符合工具 schema 的参数，并遵守风险审批流程。
3. 项目后续会部署到公网，因此当前实现也要注意密钥、输入验证、命令执行边界、迁移和可观测性。
4. 最终需要 frontend、backend、PostgreSQL/pgvector 三服务 Docker Compose 一键启动。

当前真实状态：

- FastAPI、Next.js、LangGraph、PostgreSQL/pgvector、SSE、RAG、MCP 元数据/审批、画像和 Skill 的基础闭环已经存在。
- Agent 回复和 Supervisor 路由仍主要是确定性规则，不是真实 LLM 推理。
- SSE 当前是把完整模拟回复切分成 token，不是真实模型流式输出。
- EMBEDDING_MODEL 当前只是元数据；实际 embedding 是 1536 维本地哈希测试向量，不是语义模型。
- MCP 当前只实现简化 HTTP JSON-RPC POST；stdio_bridge 未实现，SSE/Streamable HTTP 也没有完整 MCP 生命周期。
- uvx mcp-server-time 属于 stdio MCP，当前不能直接填写到前端 endpoint_url 使用。
- threads/messages 已落库，但缺少会话 CRUD API、前端会话列表和将历史消息传入 Agent 的能力。
- Skill 当前每 10 条用户消息用规则整理一次偏好/模板/决策规则，批准后作为文字上下文使用，不是可执行代码。
- Docker Compose 当前只包含 PostgreSQL。宿主机数据库端口是 localhost:5433；未来后端容器应访问 postgres:5432。

目标改造顺序：

1. 会话 CRUD、历史上下文、真实 DeepSeek LLM 服务和真实 SSE 流式输出。
2. 真实多语言 embedding、RAG 重建索引、文件上传和基于证据的健身回答。
3. 官方 MCP SDK、stdio/Streamable HTTP、Time MCP、LLM 工具选择和 schema 参数校验。
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

本次具体任务：
[在这里填写，例如：执行 Phase 1，会话管理与 DeepSeek LLM 接入。]
```