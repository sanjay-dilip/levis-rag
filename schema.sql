-- Enable pgvector extension (already done manually, this is idempotent)
create extension if not exists vector;

-- Main chunks table
create table if not exists chunks (
    id bigint primary key,
    text text not null,
    source text not null,
    filing_type text not null,
    section text,
    word_count integer,
    is_table boolean default false,
    embedding vector(384)
);

-- Index for fast cosine similarity search
create index if not exists chunks_embedding_idx
    on chunks
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 50);

-- Similarity search function
create or replace function match_chunks(
    query_embedding vector(384),
    match_count int default 10
)
returns table (
    id bigint,
    text text,
    source text,
    filing_type text,
    section text,
    word_count integer,
    is_table boolean,
    similarity float
)
language sql stable
as $$
    select
        id,
        text,
        source,
        filing_type,
        section,
        word_count,
        is_table,
        1 - (embedding <=> query_embedding) as similarity
    from chunks
    order by embedding <=> query_embedding
    limit match_count;
$$;
