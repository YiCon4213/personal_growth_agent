CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS threads (
  id varchar(80) PRIMARY KEY,
  user_id varchar(80),
  title varchar(200),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_threads_user_id ON threads(user_id);

CREATE TABLE IF NOT EXISTS messages (
  id varchar(36) PRIMARY KEY,
  thread_id varchar(80) NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  role varchar(20) NOT NULL,
  content text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_messages_thread_id ON messages(thread_id);

CREATE TABLE IF NOT EXISTS user_profile_items (
  id varchar(36) PRIMARY KEY,
  user_id varchar(80) NOT NULL,
  category varchar(40) NOT NULL,
  content text NOT NULL,
  source_summary text NOT NULL,
  source_thread_id varchar(80),
  enabled boolean NOT NULL DEFAULT true,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_user_profile_items_user_id ON user_profile_items(user_id);
CREATE INDEX IF NOT EXISTS ix_user_profile_items_source_thread_id ON user_profile_items(source_thread_id);

CREATE TABLE IF NOT EXISTS profile_candidates (
  id varchar(36) PRIMARY KEY,
  user_id varchar(80) NOT NULL,
  category varchar(40) NOT NULL,
  content text NOT NULL,
  confidence integer,
  source_summary text NOT NULL,
  source_thread_id varchar(80),
  status varchar(20) NOT NULL DEFAULT 'pending',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_profile_candidates_user_id ON profile_candidates(user_id);
CREATE INDEX IF NOT EXISTS ix_profile_candidates_source_thread_id ON profile_candidates(source_thread_id);

CREATE TABLE IF NOT EXISTS user_skills (
  id varchar(36) PRIMARY KEY,
  user_id varchar(80) NOT NULL,
  title varchar(160) NOT NULL,
  content text NOT NULL,
  applicable_scenarios jsonb NOT NULL DEFAULT '[]'::jsonb,
  status varchar(20) NOT NULL DEFAULT 'enabled',
  source_thread_id varchar(80),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_user_skills_user_id ON user_skills(user_id);
CREATE INDEX IF NOT EXISTS ix_user_skills_source_thread_id ON user_skills(source_thread_id);

CREATE TABLE IF NOT EXISTS skill_candidates (
  id varchar(36) PRIMARY KEY,
  user_id varchar(80) NOT NULL,
  title varchar(160) NOT NULL,
  content text NOT NULL,
  applicable_scenarios jsonb NOT NULL DEFAULT '[]'::jsonb,
  source_thread_id varchar(80) NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'pending',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_skill_candidates_user_id ON skill_candidates(user_id);
CREATE INDEX IF NOT EXISTS ix_skill_candidates_source_thread_id ON skill_candidates(source_thread_id);

CREATE TABLE IF NOT EXISTS mcp_servers (
  id varchar(36) PRIMARY KEY,
  user_id varchar(80) NOT NULL,
  name varchar(160) NOT NULL,
  endpoint_url text NOT NULL,
  transport varchar(40) NOT NULL DEFAULT 'http',
  enabled boolean NOT NULL DEFAULT true,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_mcp_servers_user_name UNIQUE (user_id, name)
);

CREATE INDEX IF NOT EXISTS ix_mcp_servers_user_id ON mcp_servers(user_id);

CREATE TABLE IF NOT EXISTS mcp_tools (
  id varchar(36) PRIMARY KEY,
  server_id varchar(36) NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
  name varchar(200) NOT NULL,
  description text,
  input_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
  risk_level varchar(20) NOT NULL DEFAULT 'low',
  enabled boolean NOT NULL DEFAULT true,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_mcp_tools_server_name UNIQUE (server_id, name)
);

CREATE INDEX IF NOT EXISTS ix_mcp_tools_server_id ON mcp_tools(server_id);

CREATE TABLE IF NOT EXISTS mcp_tool_calls (
  id varchar(36) PRIMARY KEY,
  user_id varchar(80) NOT NULL,
  thread_id varchar(80),
  server_id varchar(36) NOT NULL,
  tool_id varchar(36),
  tool_name varchar(200) NOT NULL,
  arguments jsonb NOT NULL DEFAULT '{}'::jsonb,
  output jsonb NOT NULL DEFAULT '{}'::jsonb,
  risk_level varchar(20) NOT NULL DEFAULT 'low',
  status varchar(40) NOT NULL,
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_mcp_tool_calls_user_id ON mcp_tool_calls(user_id);
CREATE INDEX IF NOT EXISTS ix_mcp_tool_calls_thread_id ON mcp_tool_calls(thread_id);
CREATE INDEX IF NOT EXISTS ix_mcp_tool_calls_server_id ON mcp_tool_calls(server_id);
CREATE INDEX IF NOT EXISTS ix_mcp_tool_calls_tool_id ON mcp_tool_calls(tool_id);

CREATE TABLE IF NOT EXISTS approval_requests (
  id varchar(36) PRIMARY KEY,
  user_id varchar(80) NOT NULL,
  thread_id varchar(80) NOT NULL,
  server_id varchar(36) NOT NULL,
  tool_id varchar(36) NOT NULL,
  tool_name varchar(200) NOT NULL,
  arguments jsonb NOT NULL DEFAULT '{}'::jsonb,
  risk_level varchar(20) NOT NULL DEFAULT 'high',
  expected_impact text NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'pending',
  approved_by varchar(80),
  rejected_by varchar(80),
  decision_reason text,
  tool_call_id varchar(36),
  execution_result jsonb NOT NULL DEFAULT '{}'::jsonb,
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now(),
  decided_at timestamptz,
  executed_at timestamptz
);

CREATE INDEX IF NOT EXISTS ix_approval_requests_user_id ON approval_requests(user_id);
CREATE INDEX IF NOT EXISTS ix_approval_requests_thread_id ON approval_requests(thread_id);
CREATE INDEX IF NOT EXISTS ix_approval_requests_server_id ON approval_requests(server_id);
CREATE INDEX IF NOT EXISTS ix_approval_requests_tool_id ON approval_requests(tool_id);
CREATE INDEX IF NOT EXISTS ix_approval_requests_tool_call_id ON approval_requests(tool_call_id);
CREATE TABLE IF NOT EXISTS rag_documents (
  id varchar(36) PRIMARY KEY,
  user_id varchar(80) NOT NULL,
  title varchar(240) NOT NULL,
  source_uri text,
  source_type varchar(60),
  embedding_model varchar(120) NOT NULL,
  embedding_dimension integer NOT NULL,
  chunk_count integer NOT NULL DEFAULT 0,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_rag_documents_user_id ON rag_documents(user_id);

CREATE TABLE IF NOT EXISTS rag_chunks (
  id varchar(36) PRIMARY KEY,
  document_id varchar(36) NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
  chunk_index integer NOT NULL,
  content text NOT NULL,
  embedding vector(1536),
  embedding_model varchar(120) NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_rag_chunks_document_index UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS ix_rag_chunks_document_id ON rag_chunks(document_id);
CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding ON rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
