"use client";

import { FormEvent, KeyboardEvent, MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [rightView, setRightView] = useState<"activity" | "workbench" | "events">("activity");
  const [mobileLeftOpen, setMobileLeftOpen] = useState(false);
  const [mobileRightOpen, setMobileRightOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const selectedServers = useMemo(() => new Set(enabledServerIds), [enabledServerIds]);

  useEffect(() => {
    const viewport = messagesRef.current;
    if (viewport) viewport.scrollTo({ top: viewport.scrollHeight, behavior: busy ? "smooth" : "auto" });
  }, [messages, busy]);

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

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

  async function addMcpServer(body: { name: string; endpoint_url: string; transport: MCPServer["transport"]; enabled: boolean; command?: string; args?: string[]; working_directory?: string }) {
    setError(null);
    setNotice(null);
    try {
      const created = await api.createMcpServer({ user_id: userId, ...body });
      try {
        await api.refreshMcpTools(created.id, userId);
        setEnabledServerIds((current) => unique([...current.map((id) => ({ id })), { id: created.id }]).map((item) => item.id));
        const refreshed = await refreshAll(false);
        setNotice(refreshed ? "MCP server 已添加、工具已发现并启用" : "MCP server 和工具已就绪，但列表刷新失败");
      } catch (exc) {
        await refreshAll(false);
        const detail = exc instanceof Error ? exc.message : "未知错误";
        setError(`MCP server 已保存，但工具发现失败：${detail}`);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "添加 MCP server 失败");
    }
  }

  const currentConversation = conversations.find((item) => item.id === threadId);
  const pendingApprovals = approvals.filter((item) => item.status === "pending").length;

  return (
    <main className={`app-shell ${leftOpen ? "" : "left-collapsed"} ${rightOpen ? "" : "right-collapsed"} ${mobileLeftOpen ? "" : "mobile-left-closed"} ${mobileRightOpen ? "" : "mobile-right-closed"}`}>
      <aside className="conversation-sidebar" aria-label="会话导航">
        <div className="brand-row">
          <div className="brand-mark">P</div>
          <div className="brand-copy"><strong>Personal</strong><span>Growth Agent</span></div>
          <button className="ghost-button sidebar-close" onClick={() => { setLeftOpen(false); setMobileLeftOpen(false); }} aria-label="收起会话栏">‹</button>
        </div>
        <button className="new-chat-button" onClick={() => void newConversation()} disabled={busy}><span>＋</span> 新对话</button>
        <div className="sidebar-label"><span>最近对话</span><span>{conversations.length}</span></div>
        <nav className="conversation-list">
          {conversations.map((item) => (
            <div className={`conversation-item ${item.id === threadId ? "active" : ""}`} key={item.id}>
              <button className="conversation-select" onClick={() => void selectConversation(item.id)}>
                <span className="conversation-icon">◇</span>
                <span className="conversation-copy"><strong>{item.title}</strong><small>{item.message_count} 条消息</small></span>
              </button>
              <button className="conversation-delete" aria-label={`删除 ${item.title}`} onClick={(event) => void removeConversation(event, item.id)}>×</button>
            </div>
          ))}
        </nav>
        <div className="sidebar-footer"><span className="avatar">D</span><div><strong>本地用户</strong><small>default_user</small></div><span className="online-dot" title="本地模式" /></div>
      </aside>

      <section className="chat-column">
        <header className="chat-header">
          <div className="header-title">
            {!leftOpen && <button className="ghost-button desktop-only" onClick={() => setLeftOpen(true)} aria-label="展开会话栏">☰</button>}
            {!mobileLeftOpen && <button className="ghost-button mobile-only" onClick={() => setMobileLeftOpen(true)} aria-label="展开会话栏">☰</button>}
            <div><h1>{currentConversation?.title || "新对话"}</h1><p><span className={`live-dot ${busy ? "working" : ""}`} />{busy ? "正在思考与生成" : "随时可以开始"}</p></div>
          </div>
          <div className="header-actions">
            <button className="ghost-button" onClick={() => void Promise.all([refreshAll(), api.listConversations().then(setConversations)])} title="刷新数据" aria-label="刷新数据">↻</button>
            <button className={`ghost-button desktop-only ${rightOpen ? "active" : ""}`} onClick={() => setRightOpen((value) => !value)} title="上下文与工具" aria-label="切换上下文与工具栏">◫</button>
            <button className={`ghost-button mobile-only ${mobileRightOpen ? "active" : ""}`} onClick={() => setMobileRightOpen((value) => !value)} title="上下文与工具" aria-label="切换上下文与工具栏">◫</button>
          </div>
        </header>

        <div className="messages" ref={messagesRef} aria-live="polite">
          <div className="message-flow">
            {messages.length ? messages.map((item) => (
              <article className={`message ${item.role}`} key={item.id}>
                <div className="message-avatar">{item.role === "user" ? "你" : "P"}</div>
                <div className="message-content"><span>{item.role === "user" ? "你" : "成长助手"}</span><p>{item.content || "正在组织回答…"}</p></div>
              </article>
            )) : (
              <div className="welcome-panel">
                <div className="welcome-mark">✦</div>
                <h2>今天想往哪里生长？</h2>
                <p>聊学习计划、训练与健康，或让生活助手调用工具。过程与依据都可以在右侧查看。</p>
                <div className="prompt-chips">
                  {["帮我制定一周学习计划", "设计一套居家训练", "记住我的工作习惯"].map((prompt) => <button key={prompt} onClick={() => setDraft(prompt)}>{prompt}<span>↗</span></button>)}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="composer-wrap">
          {(notice || error) && <div className={`status ${error ? "error" : "ok"}`}><span>{error ? "!" : "✓"}</span>{error || notice}<button onClick={() => { setError(null); setNotice(null); }} aria-label="关闭提示">×</button></div>}
          {statuses[0] && busy && <div className="thinking-line"><span className="thinking-pulse" />{statuses[0].message || `${statuses[0].agent} · ${statuses[0].status}`}</div>}
          <form className="composer" onSubmit={sendMessage}>
            <textarea rows={2} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={handleComposerKeyDown} placeholder="输入消息，Enter 发送，Shift + Enter 换行" aria-label="消息内容" />
            <div className="composer-footer"><span>Personal Growth Agent</span><button className="send-button" disabled={busy || !threadId || !draft.trim()} aria-label="发送消息">{busy ? "···" : "↑"}</button></div>
          </form>
        </div>
      </section>

      <aside className="context-sidebar" aria-label="上下文与工具">
        <div className="context-header"><div><span className="eyebrow">Context</span><h2>工作台</h2></div><button className="ghost-button" onClick={() => { setRightOpen(false); setMobileRightOpen(false); }} aria-label="收起工作台">›</button></div>
        <nav className="context-nav">
          <button className={rightView === "activity" ? "active" : ""} onClick={() => setRightView("activity")}><span>◉</span>运行</button>
          <button className={rightView === "workbench" ? "active" : ""} onClick={() => setRightView("workbench")}><span>⌘</span>功能{pendingApprovals > 0 && <b>{pendingApprovals}</b>}</button>
          <button className={rightView === "events" ? "active" : ""} onClick={() => setRightView("events")}><span>⌁</span>事件</button>
        </nav>

        <div className="context-scroll">
          {rightView === "activity" && <div className="activity-view">
            <section className="context-section"><div className="section-heading"><h3>Agent 状态</h3><span>{statuses.length}</span></div>{statuses.length ? statuses.map((status, index) => <div className="status-line" key={`${status.agent}-${index}`}><span className="status-symbol">{index === 0 ? "●" : "○"}</span><div><strong>{status.agent}</strong><small>{status.status}</small><p>{status.message}</p></div></div>) : <Empty text="发送消息后，运行轨迹会显示在这里。" />}</section>
            <section className="context-section"><div className="section-heading"><h3>RAG 来源</h3><span>{rag.sources.length}</span></div>{rag.sources.length ? rag.sources.map((source) => <article className="source" key={source.chunk_id}><div><strong>{source.title}</strong><span>{source.relevance_score?.toFixed(2) ?? "-"}</span></div><p>{source.excerpt}</p></article>) : <Empty text={rag.no_match_reason || "本轮暂无知识库引用。"} />}</section>
            <section className="context-section"><div className="section-heading"><h3>工具调用</h3><span>{toolCalls.length}</span></div>{toolCalls.length ? toolCalls.map((call, index) => <details className="tool-call" key={`${call.tool_id}-${index}`}><summary><span>{call.tool_name}</span><small>{call.status} · {call.risk_level}</small></summary><JsonBlock value={call.arguments} /></details>) : <Empty text="本轮暂无工具调用。" />}</section>
          </div>}

          {rightView === "workbench" && <div className="workbench">
            <nav className="tabs">{(["approvals", "memory", "rag", "mcp"] as const).map((key) => <button className={tab === key ? "active" : ""} key={key} onClick={() => setTab(key)}>{key === "approvals" ? "审批" : key === "memory" ? "记忆" : key.toUpperCase()}{key === "approvals" && pendingApprovals > 0 && <b>{pendingApprovals}</b>}</button>)}</nav>
            {tab === "approvals" && <div className="grid-list">{approvals.length ? approvals.map((approval) => <article className="card" key={approval.id}><div className="card-head"><strong>{approval.tool_name}</strong><span>{approval.status} · {approval.risk_level}</span></div><p>{approval.expected_impact}</p><JsonBlock value={approval.arguments} /><div className="actions"><button onClick={() => run(() => api.approveApproval(approval.id, userId), "审批已批准")}>批准</button><button className="secondary" onClick={() => run(() => api.rejectApproval(approval.id, userId), "审批已拒绝")}>拒绝</button></div></article>) : <Empty text="暂无待审批任务。" />}</div>}
            {tab === "memory" && <div className="stack-list"><MemoryPanel title="画像候选" items={profileCandidates} approve={(id) => run(() => api.approveProfileCandidate(id, userId), "画像候选已批准")} reject={(id) => run(() => api.rejectProfileCandidate(id, userId), "画像候选已拒绝")} /><MemoryPanel title="Skill 候选" items={skillCandidates} approve={(id) => run(() => api.approveSkillCandidate(id, userId), "Skill 候选已批准")} reject={(id) => run(() => api.rejectSkillCandidate(id, userId), "Skill 候选已拒绝")} /><ReadOnly title="已确认画像" items={profileItems} action={(id) => run(() => api.disableProfileItem(id, userId), "画像已禁用")} /><ReadOnly title="已启用 Skill" items={skills} action={(id) => run(() => api.disableSkill(id, userId), "Skill 已禁用")} /></div>}
            {tab === "rag" && <div className="stack-list"><RagForm onSubmit={(title, content, file) => run(() => file ? api.uploadRagDocument(file, title) : api.importRagDocument({ user_id: userId, title, content, source_type: "markdown", source_uri: title }), "RAG 文档已导入")} /><section><h2>文档列表</h2>{ragDocs.length ? ragDocs.map((document) => <article className="card" key={document.id}><div className="card-head"><strong>{document.title}</strong><span>{document.chunk_count} chunks</span></div><p>{document.source_uri || document.embedding_model}</p></article>) : <Empty text="暂无 RAG 文档。" />}</section></div>}
            {tab === "mcp" && <div className="stack-list"><McpForm onSubmit={(body) => void addMcpServer(body)} /><section><h2>Servers</h2>{servers.length ? servers.map((server) => <article className="card" key={server.id}><div className="card-head"><strong>{server.name}</strong><span>{server.transport}</span></div><p>{server.transport === "stdio" ? `${server.command} ${(server.args || []).join(" ")}` : server.endpoint_url}</p><label className="check-row"><input type="checkbox" checked={selectedServers.has(server.id)} onChange={(event) => setEnabledServerIds((current) => event.target.checked ? [...current, server.id] : current.filter((id) => id !== server.id))} />启用于下一次聊天</label><button className="secondary" onClick={() => run(() => api.refreshMcpTools(server.id, userId), "工具列表已刷新")}>刷新工具</button></article>) : <Empty text="暂无 MCP server。" />}<h2>Tools</h2>{tools.length ? tools.map((tool) => <article className="card" key={tool.id}><div className="card-head"><strong>{tool.name}</strong><span>{tool.risk_level}</span></div><p>{tool.description || tool.server_id}</p></article>) : <Empty text="暂无 MCP tools。" />}</section></div>}
          </div>}

          {rightView === "events" && <section className="event-log"><div className="section-heading"><h3>SSE 事件</h3><span>{events.length}</span></div>{events.length ? events.map((event, index) => <details key={`${event.run_id}-${index}`}><summary>{event.event}<span>{new Date(event.timestamp).toLocaleTimeString()}</span></summary><JsonBlock value={event.payload} /></details>) : <Empty text="开始对话后，这里会记录最近 30 个事件。" />}</section>}
        </div>
      </aside>
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
