import type {
  ApprovalRequest,
  ChatStreamRequest,
  MCPServer,
  MCPTool,
  ProfileCandidate,
  RagDocument,
  SkillCandidate,
  StreamEvent,
  UserProfileItem,
  UserSkill
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      detail = await response.text();
    }
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function url(path: string, params?: Record<string, string | number | boolean | undefined | null>) {
  const query = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  });
  return `${API_BASE}${path}${query.size ? `?${query.toString()}` : ""}`;
}

export async function getJson<T>(path: string, params?: Record<string, string | number | boolean | undefined | null>) {
  return parseJsonResponse<T>(await fetch(url(path, params), { cache: "no-store" }));
}

export async function postJson<T>(path: string, body: unknown, params?: Record<string, string | number | boolean | undefined | null>) {
  return parseJsonResponse<T>(
    await fetch(url(path, params), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    })
  );
}

export async function deleteJson<T>(path: string, params?: Record<string, string | number | boolean | undefined | null>) {
  return parseJsonResponse<T>(await fetch(url(path, params), { method: "DELETE" }));
}

function parseSseChunk(buffer: string): { events: StreamEvent[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events = blocks
    .map((block) => {
      const dataLines = block
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart());
      if (!dataLines.length) return null;
      return JSON.parse(dataLines.join("\n")) as StreamEvent;
    })
    .filter((event): event is StreamEvent => event !== null);
  return { events, rest };
}

export async function streamChat(request: ChatStreamRequest, onEvent: (event: StreamEvent) => void) {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request)
  });

  if (!response.ok || !response.body) {
    throw new Error(`Chat stream failed with ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseChunk(buffer);
    buffer = parsed.rest;
    parsed.events.forEach(onEvent);
  }

  buffer += decoder.decode();
  const parsed = parseSseChunk(`${buffer}\n\n`);
  parsed.events.forEach(onEvent);
}

export const api = {
  listApprovals: (userId: string) => getJson<ApprovalRequest[]>("/approvals", { user_id: userId }),
  approveApproval: (id: string, userId: string) => postJson(`/approvals/${id}/approve`, { user_id: userId, approver_id: userId }),
  rejectApproval: (id: string, userId: string) => postJson(`/approvals/${id}/reject`, { user_id: userId, reason: "Rejected in frontend" }),

  listProfile: (userId: string) => getJson<UserProfileItem[]>("/profile", { user_id: userId }),
  listProfileCandidates: (userId: string) => getJson<ProfileCandidate[]>("/profile/candidates", { user_id: userId }),
  approveProfileCandidate: (id: string, userId: string) => postJson(`/profile/candidates/${id}/approve`, { user_id: userId }),
  rejectProfileCandidate: (id: string, userId: string) => postJson(`/profile/candidates/${id}/reject`, { user_id: userId, reason: "Rejected in frontend" }),
  disableProfileItem: (id: string, userId: string) => postJson<UserProfileItem>(`/profile/${id}/disable`, null, { user_id: userId }),

  listSkills: (userId: string) => getJson<UserSkill[]>("/skills", { user_id: userId }),
  listSkillCandidates: (userId: string) => getJson<SkillCandidate[]>("/skills/candidates", { user_id: userId }),
  approveSkillCandidate: (id: string, userId: string) => postJson(`/skills/candidates/${id}/approve`, { user_id: userId }),
  rejectSkillCandidate: (id: string, userId: string) => postJson(`/skills/candidates/${id}/reject`, { user_id: userId, reason: "Rejected in frontend" }),
  disableSkill: (id: string, userId: string) => postJson<UserSkill>(`/skills/${id}/disable`, null, { user_id: userId }),

  listRagDocuments: (userId: string) => getJson<RagDocument[]>("/rag/documents", { user_id: userId }),
  importRagDocument: (body: { user_id: string; title: string; content: string; source_uri?: string; source_type?: string }) =>
    postJson<RagDocument>("/rag/documents", body),

  listMcpServers: (userId: string) => getJson<MCPServer[]>("/mcp/servers", { user_id: userId }),
  createMcpServer: (body: { user_id: string; name: string; endpoint_url: string; transport: MCPServer["transport"]; enabled: boolean }) =>
    postJson<MCPServer>("/mcp/servers", body),
  refreshMcpTools: (serverId: string, userId: string) => postJson(`/mcp/servers/${serverId}/refresh-tools`, null, { user_id: userId }),
  listMcpTools: (userId: string) => getJson<MCPTool[]>("/mcp/tools", { user_id: userId, enabled_only: false })
};
