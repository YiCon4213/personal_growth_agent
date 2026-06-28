"use client";

import { FormEvent, MouseEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api, streamChat } from "@/lib/api-client";
import type { AgentStatusPayload, ApprovalRequest, ChatMessage, ConversationSummary, MCPServer, MCPTool, ProfileCandidate, RagDocument, RagSourcesPayload, SkillCandidate, StreamEvent, ToolCallPayload, UserProfileItem, UserSkill } from "@/lib/types";

const defaultUserId = "default_user";
const newId = (prefix: string) => `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
const unique = <T extends { id: string }>(items: T[]) => Array.from(new Map(items.map((item) => [item.id, item])).values());

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>;
}

function Empty({ text }: { text: string }) {
  return <p className="empty">{text}</p>;
}

export default function Home() {
  const userId = defaultUserId;
  const [threadId, setThreadId] = useState("");
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [draft, setDraft] = useState("我每天晚上 9 点后学习效率高，请记住。帮我规划 Python 学习。");
  const [enabledServerIds, setEnabledServerIds] = useState<string[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [statuses, setStatuses] = useState<AgentStatusPayload[]>([]);
  const [rag, setRag] = useState<RagSourcesPayload>({ sources: [] });
  const [toolCalls, setToolCalls] = useState<ToolCallPayload[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [profileCandidates, setProfileCandidates] = useState<ProfileCandidate[]>([]);
  const [skillCandidates, setSkillCandidates] = useState<SkillCandidate[]>([]);
  const [profileItems, setProfileItems] = useState<UserProfileItem[]>([]);
  const [skills, setSkills] = useState<UserSkill[]>([]);
  const [ragDocs, setRagDocs] = useState<RagDocument[]>([]);
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [tab, setTab] = useState<"approvals" | "memory" | "rag" | "mcp">("approvals");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedServers = useMemo(() => new Set(enabledServerIds), [enabledServerIds]);

  async function selectConversation(id: string) {
    if (busy || id === threadId) return;
    try {
      setError(null);
      const detail = await api.getConversation(id);
      setThreadId(id);
      setMessages(detail.messages);
      setEvents([]);
      setStatuses([]);
      setToolCalls([]);
      setRag({ sources: [] });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载会话失败");
    }
  }

  async function newConversation() {
    if (busy) return;
    try {
      const created = await api.createConversation();
      setConversations((current) => [created, ...current]);
      setThreadId(created.id);
      setMessages([]);
      setEvents([]);
      setNotice("已新建会话");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "新建会话失败");
    }
  }

  async function removeConversation(event: MouseEvent, id: string) {
    event.stopPropagation();
    if (busy || !window.confirm("删除这个会话及其历史消息？")) return;
    try {
      await api.deleteConversation(id);
      const remaining = conversations.filter((item) => item.id !== id);
      setConversations(remaining);
      if (id === threadId) {
        if (remaining[0]) await selectConversation(remaining[0].id);
        else {
          const created = await api.createConversation();
          setConversations([created]);
          setThreadId(created.id);
          setMessages([]);
        }
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "删除会话失败");
    }
  }

  useEffect(() => {
    let active = true;
    void api.listConversations().then(async (items) => {
      if (!active) return;
      if (items.length) {
        const detail = await api.getConversation(items[0].id);
        if (!active) return;
        setConversations(items);
        setThreadId(detail.id);
        setMessages(detail.messages);
      } else {
        const created = await api.createConversation();
        if (!active) return;
        setConversations([created]);
        setThreadId(created.id);
      }
    }).catch((exc) => {
      if (active) setError(exc instanceof Error ? exc.message : "初始化会话失败");
    });
    return () => { active = false; };
  }, []);

  const refreshAll = useCallback(async (reportError = true): Promise<boolean> => {
    if (reportError) setError(null);
    try {
      const [a, pc, pi, sc, sk, rd, sv, tl] = await Promise.all([
        api.listApprovals(userId), api.listProfileCandidates(userId), api.listProfile(userId), api.listSkillCandidates(userId),
        api.listSkills(userId), api.listRagDocuments(userId), api.listMcpServers(userId), api.listMcpTools(userId)
      ]);
      setApprovals(a); setProfileCandidates(pc); setProfileItems(pi); setSkillCandidates(sc); setSkills(sk); setRagDocs(rd); setServers(sv); setTools(tl);
      return true;
    } catch (exc) {
      if (reportError) setError(exc instanceof Error ? exc.message : "刷新失败");
      return false;
    }
  }, [userId]);

  function onStreamEvent(event: StreamEvent) {
    setEvents((current) => [event, ...current].slice(0, 30));
    if (event.event === "agent_status") setStatuses((current) => [event.payload as unknown as AgentStatusPayload, ...current].slice(0, 8));
    if (event.event === "tool_call") setToolCalls((current) => [event.payload as unknown as ToolCallPayload, ...current].slice(0, 8));
    if (event.event === "rag_sources") setRag(event.payload as unknown as RagSourcesPayload);
    if (event.event === "approval_required") setApprovals((current) => unique([(event.payload as any).approval, ...current]));
    if (event.event === "profile_candidate") setProfileCandidates((current) => unique([(event.payload as any).candidate, ...current]));
    if (event.event === "skill_candidate") setSkillCandidates((current) => unique([(event.payload as any).candidate, ...current]));
    if (event.event === "token") {
      setMessages((current) => {
        const next = [...current];
        const last = next.at(-1);
        if (last?.role === "assistant") next[next.length - 1] = { ...last, content: last.content + String((event.payload as any).text ?? "") };
        return next;
      });
    }
    if (event.event === "final") {
      setMessages((current) => {
        const next = [...current];
        const last = next.at(-1);
        if (last?.role === "assistant" && !last.content.trim()) next[next.length - 1] = { ...last, content: String((event.payload as any).message ?? "") };
        return next;
      });
    }
    if (event.event === "error") setError(String((event.payload as any).message ?? "聊天流返回错误"));
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || busy || !threadId) return;
    setBusy(true); setError(null); setNotice(null); setStatuses([]); setToolCalls([]); setRag({ sources: [] }); setDraft("");
    setMessages((current) => [...current, { id: newId("user"), role: "user", content: message }, { id: newId("assistant"), role: "assistant", content: "" }]);
    try {
      await streamChat({ message, thread_id: threadId, enabled_mcp_server_ids: enabledServerIds }, onStreamEvent);
      setConversations(await api.listConversations());
      setNotice("聊天流已完成");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "发送失败");
    } finally {
      setBusy(false);
    }
  }

  async function run(action: () => Promise<unknown>, success: string) {
    try {
      setError(null);
      await action();
      const refreshed = await refreshAll(false);
      setNotice(refreshed ? success : `${success}，但列表刷新失败，请手动刷新`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "操作失败");
    }
  }

  return (
    <main className="app-shell">
      <section className="chat-column">
        <div className="topbar"><div><p className="eyebrow">Personal Growth Agent</p><h1>统一成长助手</h1></div><button className="icon-button" onClick={() => void Promise.all([refreshAll(), api.listConversations().then(setConversations)])} title="刷新">↻</button></div>
        <div className="conversation-bar">
          <div className="conversation-heading"><strong>会话</strong><span>固定用户：default_user</span><button onClick={() => void newConversation()}>新建会话</button></div>
          <div className="conversation-list">
            {conversations.map((item) => <div className={`conversation-item ${item.id === threadId ? "active" : ""}`} key={item.id}><button className="conversation-select" onClick={() => void selectConversation(item.id)}><strong>{item.title}</strong><span>{item.message_count} 条消息</span></button><button className="conversation-delete" aria-label={`删除 ${item.title}`} onClick={(event) => void removeConversation(event, item.id)}>×</button></div>)}
          </div>
        </div>
        <div className="messages" aria-live="polite">
          {messages.length ? messages.map((item) => <article className={`message ${item.role}`} key={item.id}><span>{item.role === "user" ? "你" : "助手"}</span><p>{item.content || "..."}</p></article>) : <div className="welcome-panel"><h2>开始一次可验证的对话</h2><p>流式回复、Agent 状态、RAG 来源、工具调用、审批和候选项会同步展示。</p></div>}
        </div>
        <form className="composer" onSubmit={sendMessage}><textarea rows={4} value={draft} onChange={(e) => setDraft(e.target.value)} /><button disabled={busy || !threadId}>{busy ? "发送中" : "发送"}</button></form>
        {(notice || error) && <p className={error ? "status error" : "status ok"}>{error || notice}</p>}
      </section>

      <aside className="inspector">
        <section className="panel compact"><h2>Agent 状态</h2>{statuses.length ? statuses.map((s, i) => <div className="status-line" key={`${s.agent}-${i}`}><strong>{s.agent}</strong><span>{s.status}</span><p>{s.message}</p></div>) : <Empty text="发送消息后显示。" />}</section>
        <section className="panel compact"><h2>RAG 来源</h2>{rag.sources.length ? rag.sources.map((s) => <article className="source" key={s.chunk_id}><strong>{s.title}</strong><span>{s.relevance_score?.toFixed(2) ?? "-"}</span><p>{s.excerpt}</p></article>) : <Empty text={rag.no_match_reason || "暂无引用。"} />}</section>
        <section className="panel compact"><h2>工具调用</h2>{toolCalls.length ? toolCalls.map((c, i) => <article className="source" key={`${c.tool_id}-${i}`}><strong>{c.tool_name}</strong><span>{c.status} · {c.risk_level}</span><JsonBlock value={c.arguments} /></article>) : <Empty text="暂无工具调用。" />}</section>
      </aside>

      <section className="workbench">
        <nav className="tabs">{(["approvals", "memory", "rag", "mcp"] as const).map((key) => <button className={tab === key ? "active" : ""} key={key} onClick={() => setTab(key)}>{key === "approvals" ? "审批" : key === "memory" ? "画像 / Skill" : key.toUpperCase()}</button>)}</nav>
        {tab === "approvals" && <div className="grid-list">{approvals.length ? approvals.map((a) => <article className="card" key={a.id}><div className="card-head"><strong>{a.tool_name}</strong><span>{a.status} · {a.risk_level}</span></div><p>{a.expected_impact}</p><JsonBlock value={a.arguments} /><div className="actions"><button onClick={() => run(() => api.approveApproval(a.id, userId), "审批已批准")}>批准</button><button className="secondary" onClick={() => run(() => api.rejectApproval(a.id, userId), "审批已拒绝")}>拒绝</button></div></article>) : <Empty text="暂无待审批任务。" />}</div>}
        {tab === "memory" && <div className="two-column"><MemoryPanel title="画像候选" items={profileCandidates} approve={(id) => run(() => api.approveProfileCandidate(id, userId), "画像候选已批准")} reject={(id) => run(() => api.rejectProfileCandidate(id, userId), "画像候选已拒绝")} /><MemoryPanel title="Skill 候选" items={skillCandidates} approve={(id) => run(() => api.approveSkillCandidate(id, userId), "Skill 候选已批准")} reject={(id) => run(() => api.rejectSkillCandidate(id, userId), "Skill 候选已拒绝")} /><ReadOnly title="已确认画像" items={profileItems} action={(id) => run(() => api.disableProfileItem(id, userId), "画像已禁用")} /><ReadOnly title="已启用 Skill" items={skills} action={(id) => run(() => api.disableSkill(id, userId), "Skill 已禁用")} /></div>}
        {tab === "rag" && <div className="two-column"><RagForm onSubmit={(title, content, file) => run(() => file ? api.uploadRagDocument(file, title) : api.importRagDocument({ user_id: userId, title, content, source_type: "markdown", source_uri: title }), "RAG 文档已导入")} /><section><h2>文档列表</h2>{ragDocs.length ? ragDocs.map((d) => <article className="card" key={d.id}><div className="card-head"><strong>{d.title}</strong><span>{d.chunk_count} chunks</span></div><p>{d.source_uri || d.embedding_model}</p></article>) : <Empty text="暂无 RAG 文档。" />}</section></div>}
        {tab === "mcp" && <div className="two-column"><McpForm onSubmit={(body) => run(() => api.createMcpServer({ user_id: userId, ...body }), "MCP server 已添加")} /><section><h2>Servers</h2>{servers.length ? servers.map((s) => <article className="card" key={s.id}><div className="card-head"><strong>{s.name}</strong><span>{s.transport}</span></div><p>{s.transport === "stdio" ? `${s.command} ${(s.args || []).join(" ")}` : s.endpoint_url}</p><label className="check-row"><input type="checkbox" checked={selectedServers.has(s.id)} onChange={(e) => setEnabledServerIds((cur) => e.target.checked ? [...cur, s.id] : cur.filter((id) => id !== s.id))} />启用于下一次聊天</label><button className="secondary" onClick={() => run(() => api.refreshMcpTools(s.id, userId), "工具列表已刷新")}>刷新工具</button></article>) : <Empty text="暂无 MCP server。" />}<h2>Tools</h2>{tools.length ? tools.map((t) => <article className="card" key={t.id}><div className="card-head"><strong>{t.name}</strong><span>{t.risk_level}</span></div><p>{t.description || t.server_id}</p></article>) : <Empty text="暂无 MCP tools。" />}</section></div>}
      </section>

      <section className="event-log"><h2>SSE 事件</h2>{events.length ? events.map((e, i) => <details key={`${e.run_id}-${i}`}><summary>{e.event} · {new Date(e.timestamp).toLocaleTimeString()}</summary><JsonBlock value={e.payload} /></details>) : <Empty text="暂无事件。" />}</section>
    </main>
  );
}

function MemoryPanel({ title, items, approve, reject }: { title: string; items: Array<ProfileCandidate | SkillCandidate>; approve: (id: string) => void; reject: (id: string) => void }) {
  return <section><h2>{title}</h2>{items.length ? items.map((item) => <article className="card" key={item.id}><div className="card-head"><strong>{"title" in item ? item.title : item.category}</strong><span>{item.status}</span></div><p>{item.content}</p><small>{"source_summary" in item ? item.source_summary : item.applicable_scenarios.join(" / ")}</small><div className="actions"><button onClick={() => approve(item.id)}>批准</button><button className="secondary" onClick={() => reject(item.id)}>拒绝</button></div></article>) : <Empty text={`暂无${title}。`} />}</section>;
}

function ReadOnly({ title, items, action }: { title: string; items: Array<UserProfileItem | UserSkill>; action: (id: string) => void }) {
  return <section><h2>{title}</h2>{items.length ? items.map((item) => <article className="card" key={item.id}><div className="card-head"><strong>{"title" in item ? item.title : item.category}</strong><span>{"enabled" in item ? (item.enabled ? "enabled" : "disabled") : item.status}</span></div><p>{item.content}</p><button className="secondary" onClick={() => action(item.id)}>禁用</button></article>) : <Empty text={`暂无${title}。`} />}</section>;
}

function RagForm({ onSubmit }: { onSubmit: (title: string, content: string, file: File | null) => void }) {
  return <form className="stack-form" onSubmit={(e) => { e.preventDefault(); const data = new FormData(e.currentTarget); const value = data.get("file"); onSubmit(String(data.get("title") || ""), String(data.get("content") || ""), value instanceof File && value.size ? value : null); }}><h2>导入文档</h2><input name="title" placeholder="标题（可选）" /><input name="file" type="file" accept=".md,.markdown,.txt,.pdf,text/plain,text/markdown,application/pdf" /><textarea name="content" rows={8} placeholder="或直接粘贴 Markdown / TXT 内容" /><button>导入</button></form>;
}

function McpForm({ onSubmit }: { onSubmit: (body: { name: string; endpoint_url: string; transport: MCPServer["transport"]; enabled: boolean; command?: string; args?: string[]; working_directory?: string }) => void }) {
  return <form className="stack-form" onSubmit={(e) => {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const transport = String(data.get("transport") || "streamable_http") as MCPServer["transport"];
    const args = String(data.get("args") || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
    onSubmit({
      name: String(data.get("name") || ""),
      endpoint_url: String(data.get("endpoint_url") || ""),
      transport,
      enabled: true,
      command: String(data.get("command") || "") || undefined,
      args,
      working_directory: String(data.get("working_directory") || "") || undefined,
    });
  }}>
    <h2>添加 Server</h2>
    <input name="name" placeholder="名称（例如 Time）" required />
    <select name="transport" defaultValue="streamable_http">
      <option value="streamable_http">Streamable HTTP</option>
      <option value="stdio">stdio</option>
      <option value="sse">SSE（legacy）</option>
    </select>
    <input name="endpoint_url" placeholder="HTTP: http://127.0.0.1:9000/mcp" />
    <input name="command" placeholder="stdio command（例如 uvx）" />
    <textarea name="args" placeholder={"stdio 参数，每行一个\nmcp-server-time\n--local-timezone=Asia/Shanghai"} />
    <input name="working_directory" placeholder="可选工作目录" />
    <button>添加</button>
  </form>;
}
