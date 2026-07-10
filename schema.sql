-- Enable pgvector extension (already done manually, this is idempotent)
CREATE EXTENSION IF NOT EXISTS vector;

-- Main chunks table
CREATE TABLE IF NOT EXISTS chunks (
    id               bigserial PRIMARY KEY,
    text             text NOT NULL,
    source           text,
    filing_type      text,
    section          text,
    word_count       integer,
    is_table         boolean DEFAULT false,
    fiscal_year      text,
    period_of_report text,
    embedding        vector(384)
);

-- Index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50);

-- Similarity search function
-- Sets ivfflat.probes=30 per-query (raised from 10 during the residual-miss
-- triage session below) so the index scans more of the 50 list partitions.
-- Raised because a freshly-updated chunk's own true nearest match (cosine
-- 0.65, rank 1 of the full corpus) was found to be completely absent from
-- a probes=10 scan requesting the normal 500-candidate pool -- confirmed via
-- direct comparison (present when requesting a near-exhaustive scan, absent
-- at normal candidate budgets, and inconsistent rank on repeated identical
-- queries), i.e. a real approximate-index coverage gap, not an embedding
-- defect. Returning fiscal_year and period_of_report enables metadata
-- filtering in the retriever without a separate lookup.
CREATE OR REPLACE FUNCTION match_chunks(
    query_embedding  vector(384),
    match_count      int DEFAULT 10
)
RETURNS TABLE (
    id               bigint,
    text             text,
    source           text,
    filing_type      text,
    section          text,
    word_count       integer,
    is_table         boolean,
    fiscal_year      text,
    period_of_report text,
    similarity       float
)
LANGUAGE plpgsql STABLE AS $$
BEGIN
  PERFORM set_config('ivfflat.probes', '30', true);
  RETURN QUERY
    SELECT c.id, c.text, c.source, c.filing_type, c.section,
           c.word_count, c.is_table, c.fiscal_year,
           c.period_of_report,
           1 - (c.embedding <=> query_embedding) AS similarity
    FROM chunks c
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
