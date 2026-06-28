export type StreamEventName =
  | "token"
  | "agent_status"
  | "tool_call"
  | "approval_required"
  | "rag_sources"
  | "profile_candidate"
  | "skill_candidate"
  | "final"
  | "error";

export type RiskLevel = "low" | "medium" | "high";
export type CandidateStatus = "pending" | "approved" | "rejected";
export type ApprovalStatus = "pending" | "approved" | "executing" | "rejected" | "executed" | "failed";

export interface StreamEvent<TPayload = Record<string, unknown>> {
  event: StreamEventName;
  thread_id: string;
  run_id: string;
  timestamp: string;
  payload: TPayload;
}

export interface ChatStreamRequest {
  message: string;
  thread_id: string;
  user_id?: string;
  enabled_mcp_server_ids?: string[];
  rag_collection_ids?: string[];
  attachments?: unknown[];
  metadata?: Record<string, unknown>;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  created_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessage[];
}

export interface AgentStatusPayload {
  agent: string;
  status: string;
  message?: string | null;
  details?: Record<string, unknown>;
}

export interface TokenPayload {
  text: string;
}

export interface RagSource {
  document_id: string;
  chunk_id: string;
  title: string;
  source_uri?: string | null;
  relevance_score?: number | null;
  excerpt: string;
  metadata?: Record<string, unknown>;
}

export interface RagSourcesPayload {
  sources: RagSource[];
  no_match_reason?: string | null;
}

export interface ToolCallPayload {
  tool_id: string;
  tool_name: string;
  server_id?: string | null;
  arguments: Record<string, unknown>;
  risk_level: RiskLevel;
  status: string;
  output?: Record<string, unknown>;
  call_id?: string;
  error?: unknown;
}

export interface ApprovalRequest {
  id: string;
  user_id?: string | null;
  thread_id: string;
  tool_id?: string | null;
  server_id?: string | null;
  tool_name: string;
  arguments: Record<string, unknown>;
  risk_level: RiskLevel;
  expected_impact: string;
  status: ApprovalStatus;
  created_at?: string | null;
  decided_at?: string | null;
  executed_at?: string | null;
  execution_result?: Record<string, unknown>;
  error_message?: string | null;
}

export interface ApprovalRequiredPayload {
  approval: ApprovalRequest;
}

export interface ProfileCandidate {
  id: string;
  user_id?: string | null;
  category: string;
  content: string;
  confidence?: number | null;
  source_summary: string;
  source_thread_id?: string | null;
  status: CandidateStatus;
  created_at?: string | null;
}

export interface ProfileCandidatePayload {
  candidate: ProfileCandidate;
}

export interface UserProfileItem {
  id: string;
  user_id?: string | null;
  category: string;
  content: string;
  source_summary: string;
  source_thread_id?: string | null;
  enabled: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface SkillCandidate {
  id: string;
  user_id?: string | null;
  title: string;
  content: string;
  applicable_scenarios: string[];
  source_thread_id: string;
  status: CandidateStatus;
  created_at?: string | null;
}

export interface SkillCandidatePayload {
  candidate: SkillCandidate;
}

export interface UserSkill {
  id: string;
  user_id?: string | null;
  title: string;
  content: string;
  applicable_scenarios: string[];
  status: "candidate" | "enabled" | "disabled";
  source_thread_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface FinalPayload {
  message: string;
  sources: RagSource[];
  metadata: Record<string, unknown>;
}

export interface ErrorPayload {
  code?: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface RagDocument {
  id: string;
  user_id: string;
  title: string;
  source_uri?: string | null;
  source_type?: string | null;
  embedding_provider: string;
  embedding_model: string;
  embedding_version: string;
  embedding_dimension: number;
  content_hash: string;
  index_status: string;
  chunk_count: number;
  created_at?: string | null;
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface MCPServer {
  id: string;
  user_id: string;
  name: string;
  endpoint_url: string;
  transport: "http" | "sse" | "streamable_http" | "stdio" | "stdio_bridge";
  enabled: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
  command?: string | null;
  args: string[];
  env_keys: string[];
  working_directory?: string | null;
}

export interface MCPTool {
  id: string;
  server_id: string;
  name: string;
  description?: string | null;
  transport: MCPServer["transport"];
  input_schema: Record<string, unknown>;
  risk_level: RiskLevel;
  enabled: boolean;
  metadata?: Record<string, unknown>;
}
