BEGIN;

ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS embedding_provider varchar(80) NOT NULL DEFAULT 'unknown';
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS embedding_version varchar(80) NOT NULL DEFAULT '1';
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS content_hash varchar(64) NOT NULL DEFAULT '';
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS index_status varchar(20) NOT NULL DEFAULT 'stale';

ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS embedding_provider varchar(80) NOT NULL DEFAULT 'unknown';
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS embedding_version varchar(80) NOT NULL DEFAULT '1';
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS embedding_dimension integer NOT NULL DEFAULT 1536;
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS content_hash varchar(64) NOT NULL DEFAULT '';

-- Existing hash vectors must never be mixed with semantic vectors. The rebuild endpoint
-- repopulates them through the configured external provider after this migration.
UPDATE rag_documents SET index_status = 'stale' WHERE embedding_provider = 'unknown';
UPDATE rag_chunks SET embedding = NULL WHERE embedding_provider = 'unknown';

CREATE INDEX IF NOT EXISTS ix_rag_documents_active_index
  ON rag_documents(user_id, index_status, embedding_provider, embedding_model, embedding_version);

COMMIT;
