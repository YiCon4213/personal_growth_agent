BEGIN;

-- text-embedding-v3 defaults to 1024 dimensions. Existing vectors belong to a
-- different vector space and must not survive the schema change.
UPDATE rag_documents SET index_status = 'stale';
UPDATE rag_chunks SET embedding = NULL;

DROP INDEX IF EXISTS ix_rag_chunks_embedding;

ALTER TABLE rag_chunks
  ALTER COLUMN embedding TYPE vector(1024)
  USING NULL::vector(1024);

ALTER TABLE rag_chunks
  ALTER COLUMN embedding_dimension SET DEFAULT 1024;

CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding
  ON rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

COMMIT;
