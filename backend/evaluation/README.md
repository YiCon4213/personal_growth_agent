# 真实模型健身 RAG 评估

该目录是现有 `FitnessRagService` 的独立质量实验，不调用聊天 API、会话持久化或 supervisor 业务流程。

## 评估对象

- 语料：12 份中文 Markdown，覆盖身体活动、力量训练、动作技术、跑步、恢复、饮食、疼痛边界、老年人和平衡训练。
- 用例：`rag_eval_cases.json` 中 30 条事实、改写、计划、排错、误区、实体/数字和安全警示问题。
- 被测系统：真实 PostgreSQL/pgvector、DashScope `text-embedding-v3`、dense + BM25 + RRF 和 DeepSeek 证据回答。
- RAGAS 裁判：通过 OpenAI-compatible API 连接 DeepSeek。
- AnswerRelevancy 向量：通过 OpenAI-compatible API 连接 DashScope `text-embedding-v3`。

六个指标为 `Faithfulness`、`AnswerRelevancy`、`ContextPrecision`、`ContextEntityRecall`、`NoiseSensitivity(mode="irrelevant")` 和 `ContextRecall`。除 NoiseSensitivity 越低越好外，其余均越高越好。

## 准备

从 `backend/` 运行：

```powershell
uv sync --group dev --group eval
docker compose -f ..\infra\docker-compose.yml up -d postgres --wait
```

真实密钥只放在未提交的 `backend/.env`。程序要求 `DATABASE_URL`、`DEEPSEEK_API_KEY` 和 `DASHSCOPE_API_KEY`，并复用当前模型、维度和检索参数。

## 使用

删除 `default_user` 原有 RAG 文档并导入本语料。删除与导入位于同一事务，嵌入失败会整体回滚：

```powershell
uv run --group eval python -m evaluation.ragas_experiment prepare --replace
```

先用两条真实用例检查密钥和额度：

```powershell
uv run --group eval python -m evaluation.ragas_experiment collect --limit 2 --request-delay 1
uv run --group eval python -m evaluation.ragas_experiment evaluate --concurrency 1
```

完整运行 30 条：

```powershell
uv run --group eval python -m evaluation.ragas_experiment run --replace --request-delay 1 --concurrency 1
```

生成的 RAGAS CSV 数据集、逐行实验结果和 JSON 汇总位于 `evaluation/artifacts/`，不会提交到 Git。每条样本会触发多次裁判调用，未知限流条件下应保持并发为 1。
