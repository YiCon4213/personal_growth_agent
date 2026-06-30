# Roadmap

本文面向项目使用者和贡献者，说明当前版本已经提供的能力、已知限制和后续方向。它不记录单次开发会话、历史验收过程或内部工作指令。

## 当前状态

当前版本为 **单用户 Beta**，使用固定用户 ID `default_user`。主要链路已经实现：

- FastAPI + SSE 聊天接口与 Next.js 工作台；
- LangGraph Supervisor 及 learning、fitness、life、general Agent；
- DeepSeek/OpenAI-compatible LLM 接入；
- DashScope `text-embedding-v3`（1024 维）与 dense/BM25/RRF 混合检索；
- RAG 文档导入、索引重建与来源引用；
- MCP stdio、Streamable HTTP、legacy SSE 客户端边界；
- MCP 参数校验、风险分级、审批和调用审计；
- 对话、画像、Skill、RAG、MCP 与审批数据持久化；
- PostgreSQL 16 + pgvector 的版本化迁移；
- 本地 Compose 一键启动和带 Caddy 的公网部署模板；
- 单元、API、安全和端到端回归测试。

## 已知限制

- **身份与隔离**：没有注册、登录、权限或多用户数据隔离；Basic Auth 仅是部署外围保护。
- **Agent 路由**：Supervisor 目前主要使用确定性关键词路由，不是完整的语义意图分类。
- **Skill 形态**：Skill 是经过批准的文本模板，不是可执行插件。
- **限流**：后端限流器是单进程内存实现，不适合直接横向扩容。
- **远程 MCP**：stdio Time MCP 已覆盖，远程 Streamable HTTP 仍需要针对明确服务完成真实环境验证。
- **外部依赖**：真实回答与 RAG 依赖 DeepSeek、DashScope 及其可用性和额度。
- **部署验收**：生产使用者仍需在自己的主机上完成 DNS、ACME、防火墙、监控、离机备份和恢复演练。

## 下一步计划

优先级会根据使用反馈调整，当前建议顺序为：

1. 增加应用级身份认证、授权和多用户数据隔离。
2. 引入可评估的语义路由，同时保留可解释的回退策略。
3. 扩充 learning、fitness 与工具调用的质量评估集和回归指标。
4. 对明确允许的远程 Streamable HTTP MCP 服务完成认证、超时和故障场景验证。
5. 增加共享限流、指标、追踪和告警，为多实例部署做准备。
6. 完善备份自动化、版本发布说明和升级兼容策略。

## 不在当前范围内

- 医疗诊断或替代专业医疗意见；
- 默认允许任意本地命令或任意远程 MCP 主机；
- 未经批准自动执行高风险工具；
- 将用户生成的 Skill 当作可执行代码运行。
