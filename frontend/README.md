# Frontend

Personal Growth Agent 的 Next.js/React 用户界面。完整安装和 Docker 启动方式见仓库根目录 [`README.md`](../README.md)。

## 本地开发

先在另一个终端启动后端，然后运行：

```bash
npm ci
npm run dev
```

打开 <http://127.0.0.1:3000>。前端会把 `/api/v1/*` 转发到 `http://127.0.0.1:8000`；可通过 `BACKEND_URL` 覆盖目标地址。

## 检查

```bash
npm run lint
npm run typecheck
npm run build
```

界面包含聊天流、Agent 状态、RAG 来源、MCP 调用与审批，以及画像、Skill、MCP 服务和知识库管理面板。
