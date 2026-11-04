-- New raa-p4-demo cluster/database only. No historical database is referenced.
CREATE EXTENSION vector VERSION '0.8.7';
CREATE SCHEMA p4;
CREATE TABLE p4.chunks (
  chunk_id text PRIMARY KEY,
  source_id text NOT NULL,
  source_path text NOT NULL,
  document_sha256 text NOT NULL CHECK (document_sha256 ~ '^[0-9a-f]{64}$'),
  text text NOT NULL CHECK (length(text) BETWEEN 1 AND 450),
  embedding_model text NOT NULL CHECK (embedding_model = 'all-minilm:22m'),
  embedding vector(384) NOT NULL
);
REVOKE ALL ON DATABASE raa_p4_rag FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA p4 FROM PUBLIC;
GRANT CONNECT ON DATABASE raa_p4_rag TO raa_p4_ingest, raa_p4_read;
GRANT USAGE ON SCHEMA public,p4 TO raa_p4_ingest, raa_p4_read;
GRANT SELECT,INSERT ON p4.chunks TO raa_p4_ingest;
GRANT SELECT ON p4.chunks TO raa_p4_read;
ALTER ROLE raa_p4_read SET default_transaction_read_only = on;
